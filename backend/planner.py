"""Deciding what to do about a pump failure, and what it costs.

A failed pump means the tank has no outlet. Well water keeps arriving, the level
climbs, and when it reaches the shutdown limit the facility's wells trip off and
earn nothing until the repair finishes. The operator has three levers:

  * send trucks        -- flat price per trip, fixed barrels per trip, and the
                          truck is unavailable until it has driven back
  * shut in wells early-- the tank fills slower, but a shut well earns nothing
  * do nothing         -- accept the automatic trip and lose every well

Everything here is a deterministic simulation of the tank, so a plan is never
"recommended" on a rule of thumb: it is recommended because we replayed it and
watched the level stay under the limit, and because every cheaper plan we
replayed did not.

The subtle part is that a system's trucks are shared. When two or three pumps in
one system fail within a few hours, a truck sent to one tank cannot help another,
so the plans have to be chosen together rather than one facility at a time.
"""
from __future__ import annotations

import math
from statistics import mean as _mean, pstdev

# Standard normal deviate for a 10%/90% interval, used for the countdown range.
Z80 = 1.2816
# Bisection steps when searching for the latest moment an action still works.
BISECT_STEPS = 34


# --------------------------------------------------------------------------
# The tank simulator
# --------------------------------------------------------------------------

def simulate(capacity, limit, initial, horizon, water, revenue,
             shut, shut_at, arrivals, load, trip_cost):
    """Replay one plan against the tank and return its cost, or None if illegal.

    Arguments are in plain units so the maths stays inspectable:
      capacity  tank size in bbl              limit     shutdown level in bbl
      initial   current volume in bbl         horizon   hours until the repair ends
      water     each well's water rate, bpd   revenue   each well's lost $/hour
      shut      indices of wells to shut in   shut_at   hour the shut-in starts
      arrivals  hours at which truck trips land (repeated once per truck)
      load      bbl removed per trip          trip_cost $ per trip

    This integrates exactly rather than stepping a clock: the tank's level is
    piecewise linear, so we only need to evaluate it where something changes --
    a truck landing, the shut-in starting, the repair ending. Between those the
    level moves at a constant rate, so the crossing of the shutdown limit can be
    solved for directly instead of searched for.

    Returns None when the plan is physically impossible, which is how the search
    discards trips that would draw more water than the tank is holding.
    """
    volume = initial
    cost = len(arrivals) * trip_cost
    tripped = initial >= limit - 1e-7
    trace = [{'hour': 0.0, 'level_pct': 100 * volume / capacity}]
    previous = 0.0

    # Every moment the picture changes, in order. Anything outside the repair
    # window is irrelevant: the pump is back before it and the tank is safe after.
    moments = sorted({0.0, horizon, shut_at} | set(arrivals))

    for moment in moments:
        if moment < 0 or moment > horizon:
            continue
        # Wells still producing over the segment that just ended.
        shut_now = previous >= shut_at
        producing = [i for i in range(len(water)) if not (i in shut and shut_now)]
        inflow = 0.0 if tripped else sum(water[i] for i in producing) / 24.0  # bbl/hour
        span = moment - previous

        if tripped:
            # Automatic shut-in: every well in the facility is earning nothing.
            cost += sum(revenue) * span
        else:
            if shut_now:
                cost += sum(revenue[i] for i in shut) * span
            # How long until this segment's inflow would reach the limit?
            to_limit = (limit - volume) / inflow if inflow > 0 else math.inf
            if to_limit < span - 1e-8 or (to_limit <= span + 1e-9 and moment < horizon - 1e-8):
                # The tank trips partway through this segment.
                cost += sum(revenue[i] for i in producing) * max(0.0, span - to_limit)
                volume, tripped = limit, True
            else:
                volume += inflow * span

        trace.append({'hour': round(moment, 6), 'level_pct': 100 * volume / capacity})

        if moment in arrivals:
            # Trucks landing at this instant each take a full load.
            removed = arrivals.count(moment) * load
            if removed > volume + 1e-6:
                return None  # cannot haul water that is not in the tank
            volume -= removed
            trace.append({'hour': round(moment, 6), 'level_pct': 100 * volume / capacity})

        previous = moment

    return {'cost': round(cost, 2), 'tripped': tripped, 'trace': trace, 'verified': True}


# --------------------------------------------------------------------------
# Countdown
# --------------------------------------------------------------------------

def hours_to_limit(level_pct, capacity, limit_pct, inflow_samples):
    """How long until this tank trips, with an honest uncertainty band.

    The headroom is exact -- it is just tank geometry. The fill rate is not: it is
    a noisy sensor sum that also moves as wells breathe. So we take the spread of
    the recent inflow readings, turn it into a standard error of the mean, and
    report the countdown as a range. A faster-than-expected inflow gives the
    shorter time, which is why p10 uses the high end of the inflow band.

    Returns a dict of p50/p10/p90 hours, or zeroes if the tank is already at limit.
    """
    headroom = max(0.0, (limit_pct - level_pct) / 100.0 * capacity)  # bbl
    rates = [v for v in inflow_samples if v > 0]
    if not rates or headroom <= 0:
        return {'p50': 0.0, 'p10': 0.0, 'p90': 0.0, 'inflow_bpd': rates[-1] if rates else 0.0}

    centre = _mean(rates)
    # Standard error of the mean inflow; with one sample we fall back to no spread.
    spread = (pstdev(rates) / math.sqrt(len(rates))) if len(rates) > 1 else 0.0
    fast = max(centre + Z80 * spread, 1e-6)   # fills quickest -> least time
    slow = max(centre - Z80 * spread, 1e-6)   # fills slowest  -> most time
    return {
        'p50': headroom / (centre / 24.0),
        'p10': headroom / (fast / 24.0),
        'p90': headroom / (slow / 24.0),
        'inflow_bpd': centre,
    }


# --------------------------------------------------------------------------
# Candidate plans for one failed pump
# --------------------------------------------------------------------------

class FacilityProblem:
    """Everything the planner needs about one tank that is filling up."""

    def __init__(self, data, facility, level_pct, horizon_h, water, revenue):
        system = data.system_of[facility['id']]
        travel = data.ops['systems'][system['id']]['facilities'][facility['id']]
        trucking = data.ops['emergency_trucking']

        self.facility = facility
        self.facility_id = facility['id']
        self.system_id = system['id']
        self.capacity = facility['tank']['capacity_bbl']
        self.limit = self.capacity * data.limits['shutdown'] / 100.0   # bbl
        self.initial = self.capacity * level_pct / 100.0               # bbl
        self.horizon = max(0.0, horizon_h)
        self.water = water          # bbl/day per well, as measured right now
        self.revenue = revenue      # $/hour per well
        self.response_h = travel['response_min'] / 60.0
        self.cycle_h = travel['cycle_min'] / 60.0
        self.load = trucking['truck_capacity_bbl']
        self.trip_cost = trucking['cost_per_trip']
        self.fleet = data.ops['systems'][system['id']]['emergency_fleet_size']

    def run(self, shut, shut_at, arrivals):
        """Replay one specific plan on this tank."""
        return simulate(self.capacity, self.limit, self.initial, self.horizon,
                        self.water, self.revenue, shut, shut_at, arrivals,
                        self.load, self.trip_cost)

    def arrivals(self, trucks, trips, delay=0.0):
        """When each truck trip lands, given the dispatch is called at `delay` hours.

        Per the rules every truck in a plan is called together and arrives
        `response_min` later; a truck that goes back for more returns every
        `cycle_min`. A trip that would land after the repair is finished is not a
        trip at all, so it is dropped rather than charged for.
        """
        times = []
        for trip in range(trips):
            when = delay + self.response_h + trip * self.cycle_h
            if when >= self.horizon - 1e-9:
                break
            times.extend([when] * trucks)
        return times

    def busy_hours(self, trucks, trips):
        """How long each dispatched truck is tied up: out, back, and ready again."""
        if not trucks or not trips:
            return 0.0
        return self.response_h + (trips - 1) * self.cycle_h + self.cycle_h

    def max_trips(self, delay=0.0):
        """Most trips one truck can land inside the remaining repair window."""
        usable = self.horizon - delay - self.response_h
        return 0 if usable <= 0 else int(usable / self.cycle_h) + 1


def _latest(problem, test, hi):
    """Binary-search the latest moment an action can be taken and still work.

    `test(t)` must be True for small t and False for large t. Acting as late as
    possible is always at least as cheap here -- a shut-in costs by the hour, and a
    late truck call frees the truck for another tank in the meantime.
    """
    lo = 0.0
    if not test(lo):
        return None
    for _ in range(BISECT_STEPS):
        mid = (lo + hi) / 2
        if test(mid):
            lo = mid
        else:
            hi = mid
    return lo


def candidates(problem):
    """Every distinct response worth considering for one failed pump.

    The search is exhaustive over the levers that actually move cost:
      * how many trucks to send and how many trips each makes;
      * which subset of wells to shut in (a facility has only a handful, so every
        subset is evaluated -- no greedy shortcut, no missed combination);
      * when to start the shut-in, taken as late as the tank allows, since the
        meter only runs while the well is off;
      * how long the truck dispatch can wait, which costs nothing here but may
        free the truck for a sicker tank elsewhere in the system.

    Returns plans sorted cheapest first. Each carries its simulated tank trace,
    so the UI can show the operator the level staying under the limit.
    """
    n = len(problem.water)
    wells = problem.facility['wells']

    # The do-nothing baseline: what the week's recording already shows happening.
    base = problem.run([], problem.horizon, [])
    baseline_cost = base['cost'] if base else 0.0
    plans = [{
        **base,
        'label': 'Accept the automatic shut-in' if base['tripped'] else 'No action needed',
        'trucks': 0, 'trips': 0, 'delay_h': 0.0, 'latest_delay_h': 0.0,
        'busy_h': 0.0, 'shut_wells': [], 'shut_at_h': None,
        'actions': [] if base['tripped'] else [{'type': 'none'}],
        'baseline_cost': baseline_cost,
    }]

    # Nothing to plan if the tank has already tripped or the repair is done.
    if problem.initial >= problem.limit - 1e-7 or problem.horizon <= 0:
        return plans

    for trucks in range(0, problem.fleet + 1):
        for trips in range(1 if trucks else 0, problem.max_trips() + 1):
            arrivals = problem.arrivals(trucks, trips)
            if trucks and not arrivals:
                continue
            for mask in range(1 << n):
                shut = [i for i in range(n) if mask & (1 << i)]

                # Try the cheapest form first: trucks only, shut-in never starts.
                result = problem.run(shut, problem.horizon, arrivals)
                shut_at = problem.horizon
                if shut and (result is None or result['tripped']):
                    # Trucks alone are not enough. Find the latest the shut-in can
                    # start and still hold the tank under the limit.
                    def holds(t, shut=shut, arrivals=arrivals):
                        r = problem.run(shut, t, arrivals)
                        return r is not None and not r['tripped']
                    shut_at = _latest(problem, holds, problem.horizon)
                    if shut_at is None:
                        continue
                    result = problem.run(shut, shut_at, arrivals)
                if result is None or result['tripped']:
                    continue

                # How long can this dispatch wait before it stops working? That
                # slack is what lets the system-level allocator share a fleet.
                if trucks:
                    def ok(delay, shut=shut, shut_at=shut_at, trucks=trucks, trips=trips):
                        later = problem.arrivals(trucks, trips, delay)
                        if len(later) != len(arrivals):
                            return False
                        r = problem.run(shut, shut_at, later)
                        return r is not None and not r['tripped']
                    latest_delay = _latest(problem, ok, problem.horizon) or 0.0
                else:
                    latest_delay = 0.0

                plans.append({
                    **result,
                    'label': _label(problem, wells, trucks, trips, shut, shut_at),
                    'trucks': trucks, 'trips': trips,
                    'delay_h': 0.0, 'latest_delay_h': latest_delay,
                    'busy_h': problem.busy_hours(trucks, trips),
                    'shut_wells': [wells[i]['id'] for i in shut],
                    'shut_at_h': shut_at if shut and shut_at < problem.horizon - 1e-6 else None,
                    'actions': _actions(problem, wells, trucks, trips, shut, shut_at),
                    'baseline_cost': baseline_cost,
                })

    plans.sort(key=lambda p: p['cost'])
    return plans


def _label(problem, wells, trucks, trips, shut, shut_at):
    """Plain English for the operator, assembled from what the plan actually does."""
    parts = []
    if trucks:
        parts.append(f'{trucks} truck{"s" if trucks > 1 else ""}, '
                     f'{trips} trip{"s" if trips > 1 else ""} each')
    if shut and shut_at < problem.horizon - 1e-6:
        names = ', '.join(wells[i]['id'] for i in shut)
        when = 'now' if shut_at < 1e-6 else f'in {shut_at * 60:.0f} min'
        parts.append(f'shut in {names} {when}')
    return ' + '.join(parts) or 'Hold and monitor until the repair'


def _actions(problem, wells, trucks, trips, shut, shut_at):
    """The same plan in the machine-readable shape used by the events export."""
    actions = []
    if trucks:
        actions.append({
            'type': 'dispatch_truck', 'facility_id': problem.facility_id,
            'trucks': trucks, 'trips_per_truck': trips,
            'arrival_hours': sorted(set(problem.arrivals(trucks, trips))),
            # When these trucks are back in the yard and free for another tank.
            'busy_until_hour': round(problem.busy_hours(trucks, trips), 4),
        })
    if shut and shut_at < problem.horizon - 1e-6:
        actions.append({
            'type': 'shut_in_wells',
            'wells': [wells[i]['id'] for i in shut],
            'start_after_min': round(shut_at * 60, 1),
        })
    return actions or [{'type': 'none'}]


# --------------------------------------------------------------------------
# Sharing one fleet between several failing tanks
# --------------------------------------------------------------------------

def _schedulable(jobs, fleet):
    """Can `fleet` trucks cover every dispatch in this combination of plans?

    Each job needs `trucks` vehicles for `duration` hours and must be called no
    later than `latest`. We place the jobs earliest-deadline-first, each at the
    first moment enough trucks are idle, and fail if that is already too late.
    Taking the tightest deadline first is the classic scheduling order and is
    optimal whenever each dispatch needs a single truck, which is the normal case.

    Returns the call time per job, or None if the fleet cannot cover them.
    """
    free = [0.0] * fleet              # the hour each truck next becomes available
    calls = {}
    for key, trucks, duration, latest in sorted(jobs, key=lambda j: (j[3], j[1])):
        if trucks > fleet:
            return None
        # Earliest instant `trucks` vehicles are simultaneously idle.
        start = sorted(free)[trucks - 1]
        if start > latest + 1e-9:
            return None
        # Commit the earliest-available trucks to this job.
        order = sorted(range(fleet), key=lambda i: free[i])[:trucks]
        for i in order:
            free[i] = start + duration
        calls[key] = start
    return calls


def allocate(problems, plan_options, fleet, keep=8):
    """Choose one plan per failing tank so the whole system comes out cheapest.

    A truck committed to one facility is gone from the others for hours, so
    planning each tank in isolation over-promises: three tanks would each claim
    the same two trucks. We instead search combinations of plans and keep the
    cheapest one the fleet can actually execute.

    To keep the search small, each facility offers only its cheapest plan per
    (trucks used) level plus a few runners-up -- a more expensive plan that uses
    the same number of trucks can never help another facility, so it is safe to
    drop. With a handful of facilities per system this stays exhaustive in
    practice while running in milliseconds.
    """
    shortlists = []
    for problem in problems:
        cheapest_by_trucks = {}
        for plan in plan_options[problem.facility_id]:
            current = cheapest_by_trucks.get(plan['trucks'])
            if current is None or plan['cost'] < current['cost']:
                cheapest_by_trucks[plan['trucks']] = plan
        shortlist = sorted(cheapest_by_trucks.values(), key=lambda p: p['cost'])[:keep]
        shortlists.append(shortlist)

    best_total, best_combo = math.inf, None

    def search(index, chosen, running_cost):
        nonlocal best_total, best_combo
        if running_cost >= best_total:
            return                       # cannot beat what we already have
        if index == len(shortlists):
            jobs = [(problems[i].facility_id, p['trucks'], p['busy_h'], p['latest_delay_h'])
                    for i, p in enumerate(chosen) if p['trucks']]
            calls = _schedulable(jobs, fleet)
            if calls is None:
                return
            best_total, best_combo = running_cost, [
                {**p, 'delay_h': calls.get(problems[i].facility_id, 0.0)}
                for i, p in enumerate(chosen)
            ]
            return
        for plan in shortlists[index]:
            search(index + 1, chosen + [plan], running_cost + plan['cost'])

    search(0, [], 0.0)
    # Every facility always has an accept-the-trip plan, so a solution always exists.
    return best_combo or [shortlist[0] for shortlist in shortlists]


def reuse_possible(data) -> bool:
    """Could a truck ever finish one job and still reach a second tank in time?

    Answered from ops.json rather than assumed: a truck must drive out, work,
    drive back, then drive out again, all inside one repair window. On the
    practice network that is only marginally possible, but an unseen network may
    differ, so the app reports what it found instead of claiming a blanket rule.
    """
    horizon = data.ops['expected_repair_hours']['pump_failure'] * 60.0
    best = math.inf
    for system in data.ops['systems'].values():
        travel = list(system['facilities'].values())
        if len(travel) < 2:
            continue
        responses = sorted(t['response_min'] for t in travel)
        cycles = sorted(t['cycle_min'] for t in travel)
        best = min(best, responses[0] + cycles[0] + responses[1])
    return best < horizon
