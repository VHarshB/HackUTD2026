"""Event detection from sensor readings alone.

THE IDEA
--------
Every healthy reading in this network is predicted by physics that network.json
already tells us:

    pipeline receive_flow  == pump flow                (nothing escapes en route)
    pump flow              == pump.max_flow_bpd        (a healthy pump moves its rating)
    pipeline pressure_psi  == disposal pressure + A    (A constant across the network)
    pump discharge_psi     == disposal pressure + B    (B constant across the network)

So instead of thresholding raw sensor values, we subtract the physics prediction
and watch the *residual*, which is zero-mean noise when the equipment is healthy.
A, B and the noise width are LEARNED from the dataset with robust statistics
(median / MAD), never hardcoded -- so this works unchanged on the unseen network.

Each fault pushes its own residuals negative and leaves the others alone, which we
verified on the practice week:

    pipeline_leak     -> receive-flow residual and pipeline-pressure residual
    pump_degradation  -> pump-flow residual and discharge-pressure residual
    pump_failure      -> pump reports fault status, flow collapses to zero

WHY CUSUM
---------
Leaks and especially worn pumps start at zero deviation and *ramp*. Any fixed
threshold on the instantaneous value is therefore late by construction: you must
wait for the fault to grow past the noise. A CUSUM chart instead accumulates
evidence sample by sample, so a persistent half-sigma drift still trips it, and
it detects the ramp long before any single reading looks abnormal.

CUSUM also hands us two things a threshold cannot:
  * the onset -- the last time the accumulator sat at zero is the maximum
    likelihood change point, so we can say when the fault *started*, not just
    when we noticed it;
  * recovery -- when the residual returns to zero the accumulator drains, which
    is how an event gets an end time and stops being an alert.

Detection is causal: the statistic at time t uses only samples up to t, so the
replay slider shows exactly what an operator would have known at that moment.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from .dataset import Dataset

# --- CUSUM design constants (statistical choices, not data) -----------------
# Slack: drifts smaller than half a standard deviation are treated as noise.
CUSUM_SLACK_SIGMA = 0.5
# Alarm threshold on the accumulated statistic. h=8 with k=0.5 still catches a
# 1-sigma drift within a few samples, but the in-control run length grows to tens
# of thousands of samples. That headroom matters because we run two charts on
# every facility continuously, so a threshold tuned for a single chart would
# produce a steady trickle of noise alarms across a whole field.
CUSUM_ALARM = 8.0
# Window used to declare a repair finished. We ask the AVERAGE of this many
# recent samples to sit back inside the healthy band, not every one of them
# individually: healthy noise dips below the band roughly a third of the time, so
# demanding an unbroken clean run would keep a repaired asset on the alert board
# for hours. Averaging tests the same thing far more sharply -- six samples
# averaging above the band is a ~1 sigma statement, while a fault that is still
# running sits many sigma below it and cannot pass by accident.
RECOVERY_SAMPLES = 4
# Minimum residual samples before a learned baseline is trusted.
MIN_BASELINE_SAMPLES = 30
# Smallest average displacement, in noise widths, that counts as a real fault.
# A CUSUM watched long enough will eventually cross its threshold on noise alone,
# and over a long window that excursion can even be statistically significant --
# but a fault that never moves a reading by a full noise width is not something
# to wake an operator for. This separates practical from statistical significance
# and is what keeps the healthy facilities off the alert board. On the practice
# week this sits with a wide margin on both sides: noise excursions average under
# 1.2 noise widths, while every genuine fault averages more than 11.
MIN_SHIFT_SIGMA = 2.0


@dataclass
class Event:
    """One detected problem, with the full life cycle an operator cares about."""
    facility_id: str
    system_id: str
    asset_id: str              # the thing to send an inspector to
    category: str              # pipeline_leak | pump_degradation | pump_failure
    onset_unix: int            # estimated start of the fault (CUSUM change point)
    alarm_unix: int            # when our detector could first have raised it
    end_unix: int | None       # None while still in progress
    confidence: float          # 0-1, from the Gaussian tail of the evidence
    evidence: list[str] = field(default_factory=list)
    peak_sigma: float = 0.0    # worst standardized deviation seen so far

    def status_at(self, now: int) -> str:
        return 'resolved' if self.end_unix is not None and self.end_unix <= now else 'ongoing'

    def visible_at(self, now: int) -> bool:
        """True once our detector would have fired, which is what replay must show."""
        return self.alarm_unix <= now


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------

def _robust(values: list[float]) -> tuple[float, float]:
    """Learn "what healthy looks like" from a recording that already contains faults.

    The median tolerates up to 50% bad data, so it finds the healthy centre even
    though some of these samples come from leaking pipelines and worn pumps. The
    noise width needs more care: every fault in this network pushes its residual
    *downwards*, so the lower tail of the distribution is contaminated while the
    upper tail is pure noise. Measuring the spread from the upper half only, then
    trimming the fault tail and refitting, recovers the true healthy sigma instead
    of an inflated one -- and an inflated sigma is exactly what makes a detector
    both late on real faults and jumpy on noise.

    The 1.4826 factor rescales a median absolute deviation into a standard
    deviation for Gaussian noise.
    """
    if len(values) < 2:
        return (values[0] if values else 0.0), 0.0
    centre = median(values)
    # Spread measured only above the centre, where no fault can reach.
    upper = 1.4826 * median([abs(v - centre) for v in values if v >= centre])
    if upper <= 0:
        return centre, 0.0
    # Drop the fault tail, then refit centre and spread on what is left.
    kept = [v for v in values if v >= centre - 2.5 * upper]
    centre = median(kept)
    sigma = 1.4826 * median([abs(v - centre) for v in kept if v >= centre])
    return centre, sigma


class Baselines:
    """Healthy-state model learned from the dataset's own running samples.

    Pooled across every facility: the challenge states the pressure offsets are
    network constants, and pooling gives thousands of samples, so a few faulted
    facilities cannot move a robust estimate.
    """

    def __init__(self, data: Dataset):
        recv_ratio, pipe_off, flow_scale, disch_off = [], [], [], []
        for facility_id, facility in data.facilities.items():
            disposal = data.system_of[facility_id]['disposal_site']['pressure_psi']
            for _ts, flow, recv, pipe_psi, disch_psi in _running_samples(data, facility):
                recv_ratio.append(recv / flow)
                flow_scale.append(flow / facility['pump']['max_flow_bpd'])
                pipe_off.append(pipe_psi - disposal)
                disch_off.append(disch_psi - disposal)

        self.ok = len(recv_ratio) >= MIN_BASELINE_SAMPLES
        # Centre of each residual channel, plus the noise width used to standardize it.
        self.recv_ratio, self.recv_sigma = _robust(recv_ratio)
        self.flow_scale, self.flow_sigma = _robust(flow_scale)
        self.pipe_offset, self.pipe_sigma = _robust(pipe_off)
        self.disch_offset, self.disch_sigma = _robust(disch_off)
        # Guard against a degenerate dataset where MAD collapses to zero.
        self.recv_sigma = self.recv_sigma or 0.01
        self.flow_sigma = self.flow_sigma or 0.01
        self.pipe_sigma = self.pipe_sigma or 1.0
        self.disch_sigma = self.disch_sigma or 1.0

    def describe(self) -> dict:
        """What the app learned, so the UI can show its own calibration."""
        return {
            'learned_from_samples': self.ok,
            'pipeline_pressure_offset_psi': round(self.pipe_offset, 2),
            'pipeline_pressure_sigma_psi': round(self.pipe_sigma, 2),
            'discharge_pressure_offset_psi': round(self.disch_offset, 2),
            'discharge_pressure_sigma_psi': round(self.disch_sigma, 2),
            'receive_flow_ratio': round(self.recv_ratio, 4),
            'receive_flow_sigma': round(self.recv_sigma, 4),
            'pump_flow_scale': round(self.flow_scale, 4),
            'pump_flow_sigma': round(self.flow_sigma, 4),
        }


def _running_samples(data: Dataset, facility: dict):
    """Yield (ts, pump_flow, receive_flow, pipeline_psi, discharge_psi) while pumping.

    The leak and wear residuals only exist when water is actually moving, so every
    detector works on this filtered stream. Pump-off stretches are skipped, not
    treated as evidence either way -- which is why a normal sawtooth never alarms.
    """
    pump, pipeline = facility['pump']['id'], facility['pipeline']['id']
    status = data.channel(pump, 'status')
    flow = data.channel(pump, 'flow_bpd')
    recv = data.channel(pipeline, 'receive_flow_bpd')
    pipe_psi = data.channel(pipeline, 'pressure_psi')
    disch_psi = data.channel(pump, 'discharge_psi')
    for ts, state in zip(status.ts, status.val):
        if state != 1:
            continue
        f = flow.at(ts)
        if f is None or f <= 1.0:
            continue
        r, pp, dp = recv.at(ts), pipe_psi.at(ts), disch_psi.at(ts)
        if r is None or pp is None or dp is None:
            continue
        yield ts, f, r, pp, dp


# --------------------------------------------------------------------------
# The CUSUM chart
# --------------------------------------------------------------------------

def _normal_cdf(x: float) -> float:
    """Standard normal CDF, used to turn accumulated sigmas into a confidence."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _change_point(window: list[tuple[int, float]]) -> int:
    """Best estimate of when the drift actually began, within the alarm window.

    "The last time the chart sat at zero" is the usual CUSUM change point, but it
    is biased early: on a quiet stretch the accumulator can idle at zero for a
    while before the real drift starts, and a run of mild noise drags the anchor
    back further still. So we refine it.

    For each candidate split we score the hypothesis "healthy up to here, shifted
    after here" against "healthy throughout". With standardized residuals that
    log-likelihood ratio reduces to n * mean^2 over the post-split segment, so we
    simply take the split that maximizes it. In practice this moves a reported
    onset hours closer to the truth, which is what an operator reads as "this
    started at...".
    """
    best_ts, best_score = window[0][0], -1.0
    total, count = 0.0, 0
    # Walk backwards so each candidate split's post-segment is built incrementally.
    for ts, z in reversed(window):
        total += z
        count += 1
        mean = total / count
        if mean >= 0:
            continue  # a positive segment is not evidence of a downward fault
        score = count * mean * mean
        if score > best_score:
            best_score, best_ts = score, ts
    return best_ts


def _scan(samples: list[tuple[int, float]]) -> list[dict]:
    """Run a one-sided CUSUM over (timestamp, z-score) and return detected episodes.

    `z` is the standardized residual, negative when the equipment is unhealthy.
    We accumulate how far below the slack band the readings run:

        S = max(0, S_prev + (-z - k))

    S stays near zero on noise and climbs steadily once a real drift begins.
    Crossing CUSUM_ALARM raises the event; the last moment S was zero is the
    change point we report as the onset.
    """
    episodes: list[dict] = []
    stat = 0.0
    anchor_i = 0               # index of the last time the chart sat at zero
    live: dict | None = None
    recent: list[float] = []   # rolling window used to spot a completed repair

    for i, (ts, z) in enumerate(samples):
        stat = max(0.0, stat + (-z - CUSUM_SLACK_SIGMA))
        if stat == 0.0 and live is None:
            anchor_i = i

        if live is None:
            if stat >= CUSUM_ALARM:
                # Alarm. Refine the change point inside the window the chart covered,
                # then treat everything from there on as part of this event.
                span = samples[anchor_i:i + 1]
                onset = _change_point(span)
                window = [v for t, v in span if t >= onset]
                live = {
                    'onset_unix': onset,
                    'alarm_unix': ts,
                    'end_unix': None,
                    'samples': window,
                    'peak_sigma': -min(window),
                }
                recent = []
        else:
            live['samples'].append(z)
            live['peak_sigma'] = max(live['peak_sigma'], -z)
            # Recovery: has the residual, on average, returned to the healthy band?
            recent.append(z)
            if len(recent) > RECOVERY_SAMPLES:
                recent.pop(0)
            if (len(recent) == RECOVERY_SAMPLES
                    and sum(recent) / RECOVERY_SAMPLES > -CUSUM_SLACK_SIGMA):
                live['end_unix'] = samples[i - RECOVERY_SAMPLES + 1][0]
                live['samples'] = live['samples'][:-RECOVERY_SAMPLES]
                episodes.append(live)
                live, stat, anchor_i = None, 0.0, i
                recent = []

    if live is not None:
        episodes.append(live)
    # Keep only episodes that moved the reading by a meaningful amount, not just
    # for a statistically detectable length of time.
    return [e for e in episodes
            if e['samples'] and -sum(e['samples']) / len(e['samples']) >= MIN_SHIFT_SIGMA]


def _confidence(zs: list[float]) -> float:
    """How sure are we? The one-sided Gaussian tail probability of this evidence.

    Under "equipment is healthy" the residuals are standard normal, so the mean of
    n of them has standard error 1/sqrt(n) and -mean*sqrt(n) is a z statistic.
    A big steady deviation over many samples gives a confidence near 1; a single
    noisy reading does not. This is a real significance level, not a rule score.
    """
    if not zs:
        return 0.0
    mean = sum(zs) / len(zs)
    return min(0.999, max(0.0, _normal_cdf(-mean * math.sqrt(len(zs)))))


# --------------------------------------------------------------------------
# The three detectors
# --------------------------------------------------------------------------

def _fuse(a: float, b: float) -> float:
    """Combine two independent standardized channels into one.

    The sum of two independent standard normals has standard deviation sqrt(2),
    so dividing by sqrt(2) keeps the fused score on the same sigma scale. Two
    agreeing channels therefore read ~1.4x the sigma of either alone, which is
    what lets us alarm earlier without alarming on noise.
    """
    return (a + b) / math.sqrt(2.0)


def detect_pipeline_leak(data: Dataset, facility: dict, base: Baselines) -> list[dict]:
    """Water escaping between the pump and the disposal site.

    Two independent fingerprints, fused:
      * less water arrives at the disposal site than the pump sent (receive ratio);
      * the pipeline cannot hold its pressure because water is leaving it.

    The pressure channel is the early one: in this data it drops roughly five
    sigma within the first running sample of a leak, while the flow imbalance
    still looks like noise for hours. Fusing them is what buys the early warning.
    """
    disposal = data.system_of[facility['id']]['disposal_site']['pressure_psi']
    zs = []
    for ts, flow, recv, pipe_psi, _disch in _running_samples(data, facility):
        z_flow = (recv / flow - base.recv_ratio) / base.recv_sigma
        z_press = ((pipe_psi - disposal) - base.pipe_offset) / base.pipe_sigma
        zs.append((ts, _fuse(z_flow, z_press)))
    return _scan(zs)


def detect_pump_degradation(data: Dataset, facility: dict, base: Baselines) -> list[dict]:
    """A pump that moves a little less water every hour.

    Fingerprints: flow falling below the pump's rating, and discharge pressure
    sagging because the pump cannot push as hard. Both ramp from zero, which is
    exactly the case a fixed threshold handles worst and CUSUM handles best.
    """
    disposal = data.system_of[facility['id']]['disposal_site']['pressure_psi']
    rated = facility['pump']['max_flow_bpd']
    zs = []
    for ts, flow, _recv, _pipe, disch_psi in _running_samples(data, facility):
        z_flow = (flow / rated - base.flow_scale) / base.flow_sigma
        z_press = ((disch_psi - disposal) - base.disch_offset) / base.disch_sigma
        zs.append((ts, _fuse(z_flow, z_press)))
    return _scan(zs)


def detect_pump_failure(data: Dataset, facility: dict) -> list[dict]:
    """A pump that has stopped: the one fault with a countdown attached.

    A failure is not a slow drift, so there is nothing to accumulate -- it is a
    step change we can read directly. We take any contiguous run where the pump
    reports fault status, or claims to run while moving no water, and corroborate
    with the discharge pressure collapsing back to the bare disposal pressure.
    """
    disposal = data.system_of[facility['id']]['disposal_site']['pressure_psi']
    pump = facility['pump']['id']
    status = data.channel(pump, 'status')
    flow = data.channel(pump, 'flow_bpd')
    disch = data.channel(pump, 'discharge_psi')

    episodes, run_start = [], None
    for ts, state in zip(status.ts, status.val):
        f = flow.at(ts) or 0.0
        faulted = state == 2 or (state == 1 and f <= 1.0)
        if faulted and run_start is None:
            run_start = ts
        elif not faulted and run_start is not None:
            episodes.append({'onset_unix': run_start, 'alarm_unix': run_start, 'end_unix': ts})
            run_start = None
    if run_start is not None:
        episodes.append({'onset_unix': run_start, 'alarm_unix': run_start, 'end_unix': None})

    for ep in episodes:
        pressure = disch.last(ep['onset_unix'], disposal) - disposal
        ep['pressure_deficit'] = pressure
        ep['samples'] = []
    return episodes


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def detect_all(data: Dataset) -> list[Event]:
    """Sweep every facility once and return every event found in the recording.

    Called once per dataset and cached. Because the detectors are causal, a query
    at any replay timestamp just filters this list -- no need to re-scan.
    """
    base = Baselines(data)
    events: list[Event] = []

    for facility_id, facility in data.facilities.items():
        system = data.system_of[facility_id]
        pump, pipeline = facility['pump']['id'], facility['pipeline']['id']

        for ep in detect_pump_failure(data, facility):
            events.append(Event(
                facility_id=facility_id, system_id=system['id'], asset_id=pump,
                category='pump_failure', onset_unix=ep['onset_unix'],
                alarm_unix=ep['alarm_unix'], end_unix=ep['end_unix'],
                confidence=0.99, peak_sigma=0.0,
                evidence=[
                    'Pump reports a fault and is moving no water.',
                    f'Discharge pressure has fallen to the bare disposal pressure '
                    f'({ep["pressure_deficit"]:+.0f} psi above it, normally '
                    f'{base.disch_offset:+.0f} psi).',
                    'The tank has no outlet, so its level is now rising on well inflow alone.',
                ],
            ))

        for ep in detect_pipeline_leak(data, facility, base):
            events.append(Event(
                facility_id=facility_id, system_id=system['id'], asset_id=pipeline,
                category='pipeline_leak', onset_unix=ep['onset_unix'],
                alarm_unix=ep['alarm_unix'], end_unix=ep['end_unix'],
                confidence=_confidence(ep['samples']), peak_sigma=ep['peak_sigma'],
                evidence=[
                    f'Pipeline pressure and disposal-site arrivals are both short of '
                    f'what the pump is sending, by up to {ep["peak_sigma"]:.1f} sigma.',
                    f'Evidence accumulated across {len(ep["samples"])} pumping samples; '
                    f'the drift began around the onset shown.',
                    'Water is still leaving the tank, so there is no shutdown countdown.',
                ],
            ))

        for ep in detect_pump_degradation(data, facility, base):
            events.append(Event(
                facility_id=facility_id, system_id=system['id'], asset_id=pump,
                category='pump_degradation', onset_unix=ep['onset_unix'],
                alarm_unix=ep['alarm_unix'], end_unix=ep['end_unix'],
                confidence=_confidence(ep['samples']), peak_sigma=ep['peak_sigma'],
                evidence=[
                    f'Pump flow and discharge pressure are drifting below rating, by up '
                    f'to {ep["peak_sigma"]:.1f} sigma.',
                    f'Evidence accumulated across {len(ep["samples"])} pumping samples.',
                    'The pump is still moving water, so there is no shutdown countdown.',
                ],
            ))

    _supersede_degradation(events)
    events.sort(key=lambda e: (e.onset_unix, e.facility_id))
    return events


def _supersede_degradation(events: list[Event]) -> None:
    """Close a wear event when that same pump actually fails.

    A worn pump and a failed pump are two separate events, but the wear channels
    only exist while the pump is turning. Once it stops there are no readings to
    show the wear has been repaired, so the wear event would otherwise hang on the
    board for the whole repair. The failure at the same asset is itself the
    evidence that the wear episode is over, so we end it there.
    """
    failures = [e for e in events if e.category == 'pump_failure']
    for wear in events:
        if wear.category != 'pump_degradation':
            continue
        for failure in failures:
            if failure.asset_id != wear.asset_id:
                continue
            if wear.onset_unix <= failure.onset_unix and (
                    wear.end_unix is None or wear.end_unix > failure.onset_unix):
                wear.end_unix = failure.onset_unix
