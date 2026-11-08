"""Turning a dataset and a timestamp into the console an operator reads.

This is the layer that answers "what is happening right now, and what should I
do about it". It owns none of the hard maths: detection lives in detect.py and
the cost optimisation in planner.py. What it does own is the operator's view --
which events are still in progress, how long each tank has, which plans the
system's shared trucks can actually support, and the order to show them in.

Replay is free. The detectors are causal, so every event is found once per
dataset and then filtered by the requested timestamp: scrubbing the timeline
shows exactly what the console would have shown at that moment, with no
knowledge of what happened afterwards.
"""
from __future__ import annotations

from functools import lru_cache

from .dataset import Dataset, Series, ROOT
from .detect import Baselines, Event, detect_all
from .planner import (FacilityProblem, allocate, candidates, hours_to_limit,
                      reuse_possible, simulate)

# How many recent inflow readings feed the countdown's uncertainty band.
INFLOW_WINDOW = 12

__all__ = ['Dataset', 'Series', 'ROOT', 'Analysis', 'simulate', 'analyze']


class Analysis:
    """A dataset plus everything that can be computed once and reused.

    Detection sweeps the whole recording a single time; each request for a
    replay timestamp is then a cheap filter and a plan search over whatever is
    still in progress.
    """

    def __init__(self, name: str):
        self.data = Dataset(name)
        self.baselines = Baselines(self.data)
        self.events: list[Event] = detect_all(self.data)
        self.truck_reuse_possible = reuse_possible(self.data)
        self._cache: dict[int, dict] = {}

    # -- per-timestamp view ------------------------------------------------

    def at(self, now: int) -> dict:
        """The full console payload for one moment in the recording.

        Cached per timestamp, so dragging the replay slider back over ground it
        has already covered costs nothing.
        """
        now = self.data.clamp(now)
        if now in self._cache:
            return self._cache[now]
        view = self._build(now)
        self._cache[now] = view
        return view

    def _build(self, now: int) -> dict:
        data = self.data

        live = [e for e in self.events if e.visible_at(now)]
        ongoing = [e for e in live if e.status_at(now) == 'ongoing']

        facilities = [self._facility_snapshot(f_id, now, ongoing)
                      for f_id in data.facilities]

        alerts = [self._alert(event, now) for event in ongoing]
        self._share_trucks(alerts, now)
        alerts.sort(key=_alert_order)

        return {
            'now': now, 'start': data.start, 'end': data.end,
            'systems': data.network['systems'],
            'facilities': facilities,
            'alerts': alerts,
            'events': [self._event_record(e, now) for e in live],
            'limits': data.limits,
            'baselines': self.baselines.describe(),
            'planning_scope': self._scope(),
        }

    # -- pieces ------------------------------------------------------------

    def _facility_snapshot(self, facility_id: str, now: int, ongoing: list[Event]) -> dict:
        """Current sensor picture for one facility, for the map and detail pane."""
        data = self.data
        facility = data.facilities[facility_id]
        problem = next((e for e in ongoing if e.facility_id == facility_id), None)
        return {
            **facility,
            'system_id': data.system_of[facility_id]['id'],
            'level_pct': data.value(facility['tank']['id'], 'level_pct', now),
            'pump_status': data.value(facility['pump']['id'], 'status', now),
            'flow_bpd': data.value(facility['pump']['id'], 'flow_bpd', now),
            'inflow_bpd': data.value(facility_id, 'inflow_bpd', now),
            'pipeline_psi': data.value(facility['pipeline']['id'], 'pressure_psi', now),
            'category': problem.category if problem else None,
        }

    def well_rates(self, facility: dict, now: int) -> tuple[list[float], list[float]]:
        """Each well's water rate and lost revenue per hour, as of `now`.

        A well that is currently shut in reads zero water, which would make the
        tank look like it had stopped filling. For planning we want the rate the
        well will produce once it is allowed to, so a shut-in well falls back to
        its baseline from network.json.
        """
        data = self.data
        water, revenue = [], []
        for well in facility['wells']:
            producing = data.value(well['id'], 'status', now, 1) == 1
            measured = data.value(well['id'], 'water_bpd', now)
            water.append(max(0.0, measured) if producing and measured > 0
                         else well['baseline_water_bpd'])
            revenue.append(data.well_revenue_per_hour(well))
        return water, revenue

    def _alert(self, event: Event, now: int) -> dict:
        """One row of the alerts view: what is wrong, how long we have, what to do."""
        data = self.data
        facility = data.facilities[event.facility_id]
        level = data.value(facility['tank']['id'], 'level_pct', now)
        water, revenue = self.well_rates(facility, now)

        alert = {
            'event_id': _event_id(event),
            'facility_id': event.facility_id,
            'system_id': event.system_id,
            'asset_id': event.asset_id,
            'category': event.category,
            'status': 'ongoing',
            'onset_unix': event.onset_unix,
            'alarm_unix': event.alarm_unix,
            'end_unix': None,
            'confidence': round(event.confidence, 3),
            'evidence': list(event.evidence),
            'peak_sigma': round(event.peak_sigma, 2),
            'level_pct': round(level, 2),
            'revenue_per_hour': round(sum(revenue), 2),
            'hours_to_limit': None,
            'hours_to_limit_band': None,
        }

        if event.category != 'pump_failure':
            # A leak or a worn pump still pumps, so the tank is not filling and
            # there is no countdown. The action is to get eyes on the asset.
            urgent = event.category == 'pipeline_leak'
            alert['recommendation'] = {
                'label': 'Send an inspector now' if urgent else 'Schedule a pump inspection',
                'cost': 0.0, 'baseline_cost': 0.0, 'verified': True, 'tripped': False,
                'trucks': 0, 'trace': [],
                'actions': [{'type': 'field_inspection', 'asset_id': event.asset_id}],
                'alternatives': [],
            }
            return alert

        # --- pump failure: countdown and costed plan ------------------------
        inflow = [v for _ts, v in data.channel(event.facility_id, 'inflow_bpd')
                  .tail(now, INFLOW_WINDOW)]
        if not inflow:
            inflow = [sum(water)]
        band = hours_to_limit(level, facility['tank']['capacity_bbl'],
                              data.limits['shutdown'], inflow)
        alert['hours_to_limit'] = round(band['p50'], 3)
        alert['hours_to_limit_band'] = {k: round(band[k], 3) for k in ('p10', 'p50', 'p90')}
        alert['inflow_bpd'] = round(band['inflow_bpd'], 1)

        # Repairs run a fixed length from onset, so what is left is what we plan against.
        elapsed_h = (now - event.onset_unix) / 3600.0
        horizon = max(0.0, data.ops['expected_repair_hours']['pump_failure'] - elapsed_h)
        alert['repair_hours_remaining'] = round(horizon, 3)
        alert['_problem'] = FacilityProblem(data, facility, level, horizon, water, revenue)
        return alert

    def _share_trucks(self, alerts: list[dict], now: int) -> None:
        """Pick the plans, one system at a time, because each system's fleet is shared.

        Nothing has been dispatched yet in this recording, so at any replay moment
        every truck in a system is idle and available to every one of that
        system's filling tanks -- but only to one of them at a time.
        """
        failures = [a for a in alerts if a['category'] == 'pump_failure']
        by_system: dict[str, list[dict]] = {}
        for alert in failures:
            by_system.setdefault(alert['system_id'], []).append(alert)

        for system_id, group in by_system.items():
            problems = [a.pop('_problem') for a in group]
            options = {p.facility_id: candidates(p) for p in problems}
            fleet = self.data.ops['systems'][system_id]['emergency_fleet_size']
            chosen = allocate(problems, options, fleet)

            for alert, problem, plan in zip(group, problems, chosen):
                ranked = options[problem.facility_id]
                alert['recommendation'] = {
                    'label': plan['label'], 'cost': plan['cost'],
                    'baseline_cost': plan['baseline_cost'],
                    'verified': plan.get('verified', False), 'tripped': plan['tripped'],
                    'trucks': plan['trucks'], 'trips_per_truck': plan.get('trips', 0),
                    'dispatch_delay_min': round(plan.get('delay_h', 0.0) * 60, 1),
                    'trace': plan['trace'], 'actions': plan['actions'],
                    # What the operator gave up by taking this plan, for the UI.
                    'alternatives': [{'label': p['label'], 'cost': p['cost'],
                                      'tripped': p['tripped'], 'trucks': p['trucks']}
                                     for p in ranked[:6]],
                    'fleet_size': fleet,
                    'shared_with': [o['facility_id'] for o in group
                                    if o is not alert],
                }

    def _event_record(self, event: Event, now: int) -> dict:
        """One event in the export shape from SPEC.md, resolved ones included."""
        data = self.data
        status = event.status_at(now)
        record = {
            'event_id': _event_id(event),
            'system_id': event.system_id,
            'facility_id': event.facility_id,
            'asset_id': event.asset_id,
            'category': event.category,
            'status': status,
            'onset_ts': _iso(event.onset_unix),
            'onset_unix': event.onset_unix,
            'end_ts': _iso(event.end_unix) if status == 'resolved' else None,
            'end_unix': event.end_unix if status == 'resolved' else None,
            'confidence': round(event.confidence, 3),
            'evidence': list(event.evidence),
            'hours_to_limit': None,
            'recommended_actions': [],
        }
        if status == 'ongoing':
            record['level_pct'] = round(
                data.value(data.facilities[event.facility_id]['tank']['id'], 'level_pct', now), 2)
        return record

    def _scope(self) -> str:
        """An honest statement of what the optimiser did and did not search."""
        reuse = ('A truck could in principle finish one job and reach a second tank '
                 'inside a repair window on this network, so dispatches are scheduled '
                 'on a shared truck timeline.'
                 if self.truck_reuse_possible else
                 'On this network no truck can finish one job and reach a second tank '
                 'before the repair ends, so each dispatch holds its trucks for the '
                 'whole response.')
        return ('Plans are chosen by replaying every combination of truck dispatches and '
                'well shut-ins against the tank and keeping the cheapest that never '
                'reaches the shutdown limit. Shut-ins start as late as the tank allows. '
                'Concurrent failures in one system are solved together against that '
                "system's fleet. " + reuse)


def _alert_order(alert: dict) -> tuple:
    """The alerts view order from SPEC.md.

    Pump failures first, soonest to reach the shutdown limit at the top, ties
    broken by the facility with more revenue on the line. Leaks and worn pumps
    follow in any order -- they have no countdown.
    """
    is_failure = alert['category'] == 'pump_failure'
    return (
        0 if is_failure else 1,
        alert['hours_to_limit'] if alert['hours_to_limit'] is not None else float('inf'),
        -alert['revenue_per_hour'],
    )


def _event_id(event: Event) -> str:
    """A stable id so the same event keeps its identity across replay positions."""
    return f'{event.facility_id}-{event.category}-{event.onset_unix}'


def _iso(unix: int | None) -> str | None:
    from datetime import datetime, timezone
    if unix is None:
        return None
    return datetime.fromtimestamp(unix, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@lru_cache(maxsize=8)
def load(name: str) -> Analysis:
    """Load and fully analyse a dataset folder, cached between requests."""
    return Analysis(name)


def analyze(name: str, now: int | None = None) -> dict:
    """Console payload for a dataset at a replay timestamp (default: its latest reading)."""
    analysis = load(name)
    return analysis.at(analysis.data.clamp(now))
