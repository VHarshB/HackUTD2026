"""Dataset loading and indexed telemetry access.

An app-visible dataset is a folder holding exactly the three files the challenge
promises: network.json, ops.json and telemetry.csv. answer_key.json is never read
here -- it exists only for the offline scorer in scripts/.

The job of this module is to turn the long-format telemetry.csv (one row per
asset/metric/timestamp) into something the detectors can sweep quickly, and to
expose the network/ops documents with a few convenience lookups.
"""
from __future__ import annotations

import bisect
import csv
import json
from pathlib import Path

# Root that every dataset folder must live under. Keeps `?dataset=` from the API
# from walking out of the project.
ROOT = Path(__file__).resolve().parents[1] / 'data' / 'eog'


class Series:
    """One (asset, metric) sensor channel: parallel arrays of timestamp and value.

    Parallel arrays rather than dicts because the detectors sweep a whole channel
    in order, and bisect gives O(log n) "value as of time t" for the dashboard.
    """

    __slots__ = ('ts', 'val', '_index')

    def __init__(self, samples: list[tuple[int, float]]):
        samples.sort()
        self.ts = [t for t, _ in samples]
        self.val = [v for _, v in samples]
        self._index = {t: v for t, v in samples}  # exact-timestamp lookup

    def __len__(self) -> int:
        return len(self.ts)

    def at(self, ts: int):
        """Value sampled exactly at `ts`, or None if this channel has no sample there."""
        return self._index.get(ts)

    def last(self, ts: int, default: float = 0.0) -> float:
        """Most recent value at or before `ts` -- the reading an operator would see."""
        i = bisect.bisect_right(self.ts, ts)
        return self.val[i - 1] if i else default

    def window(self, lo: int, hi: int) -> list[tuple[int, float]]:
        """Samples with lo <= ts <= hi, in time order."""
        a = bisect.bisect_left(self.ts, lo)
        b = bisect.bisect_right(self.ts, hi)
        return list(zip(self.ts[a:b], self.val[a:b]))

    def tail(self, ts: int, count: int) -> list[tuple[int, float]]:
        """The last `count` samples at or before `ts`."""
        b = bisect.bisect_right(self.ts, ts)
        return list(zip(self.ts[max(0, b - count):b], self.val[max(0, b - count):b]))


class Dataset:
    """One dataset folder: the network description, the ops/price book, and telemetry.

    `start` and `end` come only from the telemetry, as the spec requires -- no file
    states the time range, and the last `ts_unix` in telemetry.csv is "now".
    """

    def __init__(self, name: str):
        folder = (ROOT / name).resolve()
        if not folder.is_relative_to(ROOT.resolve()):
            raise ValueError('Dataset must be inside data/eog')
        self.name = name
        self.network = json.loads((folder / 'network.json').read_text())
        self.ops = json.loads((folder / 'ops.json').read_text())

        # --- telemetry.csv -> {(asset_id, metric): Series} -------------------
        raw: dict[tuple[str, str], list[tuple[int, float]]] = {}
        with (folder / 'telemetry.csv').open(newline='') as handle:
            for row in csv.DictReader(handle):
                try:
                    sample = (int(row['ts_unix']), float(row['value']))
                except (TypeError, ValueError):
                    continue  # skip malformed rows rather than failing the whole load
                raw.setdefault((row['asset_id'], row['metric']), []).append(sample)
        if not raw:
            raise ValueError('Empty telemetry')
        self.series: dict[tuple[str, str], Series] = {k: Series(v) for k, v in raw.items()}

        self.start = min(s.ts[0] for s in self.series.values())
        self.end = max(s.ts[-1] for s in self.series.values())
        # Sampling interval, inferred rather than assumed to be 5 minutes.
        grid = sorted({t for s in self.series.values() for t in s.ts[:50]})
        gaps = [b - a for a, b in zip(grid, grid[1:]) if b > a]
        self.step = min(gaps) if gaps else 300

        # --- flattened views of network.json ---------------------------------
        # facility_id -> facility dict, and facility_id -> its system dict, so
        # detectors and planners never have to walk the nested structure again.
        self.facilities: dict[str, dict] = {}
        self.system_of: dict[str, dict] = {}
        for system in self.network['systems']:
            for facility in system['facilities']:
                self.facilities[facility['id']] = facility
                self.system_of[facility['id']] = system
        self.limits = self.network['defaults']['tank_limits_pct']

    # -- channel helpers ------------------------------------------------------

    def channel(self, asset: str, metric: str) -> Series:
        """A Series for this asset/metric, or an empty one if the sensor is absent."""
        return self.series.get((asset, metric)) or Series([])

    def value(self, asset: str, metric: str, now: int, default: float = 0.0) -> float:
        """Latest reading of asset/metric as of `now`."""
        return self.channel(asset, metric).last(now, default)

    def values(self, asset: str, metric: str, now: int) -> list[tuple[int, float]]:
        """Every sample of asset/metric up to and including `now`."""
        return self.channel(asset, metric).window(self.start, now)

    def clamp(self, now: int | None) -> int:
        """Snap a requested replay timestamp into the dataset's recorded range."""
        if now is None:
            return self.end
        return max(self.start, min(int(now), self.end))

    # -- economics ------------------------------------------------------------

    def well_revenue_per_hour(self, well: dict) -> float:
        """Dollars per hour a producing well earns: oil at $/bbl plus gas at $/mcf.

        This is exactly what is lost while the well is shut in, so it is both the
        cost of a voluntary shut-in and the cost of an automatic trip.
        """
        prices = self.ops['prices']
        daily = well['oil_bpd'] * prices['oil_per_bbl'] + well['gas_mcfd'] * prices['gas_per_mcf']
        return daily / 24.0
