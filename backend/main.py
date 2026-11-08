"""HTTP API for the NightShift console.

Every endpoint is a thin wrapper around engine.analyze: the API does routing,
validation and shaping, never analysis. Datasets are addressed by their folder
name under data/eog, so switching between the practice week, a snapshot and the
judging `test/` folder is a query parameter and nothing else -- no code change,
no restart, no hardcoded paths.
"""
from __future__ import annotations

import json
import os

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .engine import ROOT, analyze, load
from .planner import FacilityProblem, allocate, candidates

app = FastAPI(title='NightShift AI', version='1.0.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:3000', 'http://127.0.0.1:3000'],
    allow_methods=['GET', 'POST'], allow_headers=['Content-Type'],
)

DEFAULT_MODEL = 'nvidia/llama-3.3-nemotron-super-49b-v1.5'


def _analysis(dataset: str):
    """Load a dataset or turn any loading problem into a clean 400."""
    try:
        return load(dataset)
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(400, f'Invalid dataset: {exc}') from exc


def _view(dataset: str, at: int | None):
    try:
        return analyze(dataset, at)
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(400, f'Invalid dataset: {exc}') from exc


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

@app.get('/api/health')
def health():
    return {'status': 'ok', 'nemotron_configured': bool(os.getenv('NVIDIA_API_KEY'))}


@app.get('/api/datasets')
def datasets():
    """Every folder under data/eog holding the three files the app can load.

    A new folder dropped in -- including the judging `test/` folder -- appears
    here automatically, which is how the UI switches networks.
    """
    found = []
    for path in sorted(ROOT.rglob('network.json')):
        folder = path.parent
        if (folder / 'ops.json').exists() and (folder / 'telemetry.csv').exists():
            found.append(str(folder.relative_to(ROOT)).replace('\\', '/'))
    return found


# --------------------------------------------------------------------------
# The console
# --------------------------------------------------------------------------

@app.get('/api/dashboard')
def dashboard(dataset: str = 'history/snapshot_2026-10-09T0330', at: int | None = None):
    """Everything the operator's screen needs for one moment in the recording.

    `at` is the replay timestamp; leaving it off means the latest reading, which
    is the dataset's "now".
    """
    return _view(dataset, at)


@app.get('/api/trend')
def trend(dataset: str, asset: str, metric: str, at: int | None = None,
          samples: int = Query(288, ge=1, le=20000)):
    """One sensor channel's recent history, for plotting any asset's readings."""
    analysis = _analysis(dataset)
    now = analysis.data.clamp(at)
    series = analysis.data.channel(asset, metric).tail(now, samples)
    return [{'ts': ts, 'value': value} for ts, value in series]


@app.get('/api/events')
def events(dataset: str, at: int | None = None, only_ongoing: bool = False):
    """Event export in the shape SPEC.md describes, resolved history included.

    This is the file a shift hands over: every problem the app found in the
    recording, when it started, when it ended, and what should have been done.
    """
    view = _view(dataset, at)
    actions = {a['event_id']: a for a in view['alerts']}
    records = []
    for record in view['events']:
        if only_ongoing and record['status'] != 'ongoing':
            continue
        alert = actions.get(record['event_id'])
        if alert:
            record = {**record,
                      'recommended_actions': alert['recommendation']['actions'],
                      'est_cost': alert['recommendation']['cost']}
            if alert['hours_to_limit_band']:
                record['hours_to_limit'] = alert['hours_to_limit_band']
        records.append(record)
    return {'generated_at_unix': view['now'], 'dataset': dataset, 'events': records}


@app.get('/api/handoff')
def handoff(dataset: str, at: int | None = None):
    """A plain-English shift brief the next operator can read in thirty seconds."""
    view = _view(dataset, at)
    failures = [a for a in view['alerts'] if a['category'] == 'pump_failure']
    inspections = [a for a in view['alerts'] if a['category'] != 'pump_failure']
    spend = sum(a['recommendation']['cost'] for a in failures)
    avoided = sum(max(0.0, a['recommendation']['baseline_cost'] - a['recommendation']['cost'])
                  for a in failures)

    lines = []
    if not view['alerts']:
        lines.append('Field is quiet. No problems detected in the current readings.')
    if failures:
        soonest = failures[0]
        lines.append(
            f'{len(failures)} pump failure(s) are filling tanks right now. The tightest is '
            f'{soonest["facility_id"]}, about {soonest["hours_to_limit"]:.1f} hours from an '
            f'automatic shut-in.')
    for alert in failures:
        rec = alert['recommendation']
        lines.append(
            f'{alert["facility_id"]}: {rec["label"]}. That costs about ${rec["cost"]:,.0f} '
            f'against ${rec["baseline_cost"]:,.0f} if nobody acts.')
    for alert in inspections:
        kind = 'leaking' if alert['category'] == 'pipeline_leak' else 'wearing out'
        lines.append(
            f'{alert["asset_id"]} is {kind} ({alert["confidence"] * 100:.0f}% confidence, '
            f'peak deviation {alert["peak_sigma"]:.1f} sigma). It still moves water, so there '
            f'is no countdown -- send an inspector.')
    if failures:
        lines.append(f'Total planned spend ${spend:,.0f}, avoiding about ${avoided:,.0f} '
                     f'in lost production.')

    return {'now': view['now'], 'summary': lines,
            'planned_cost': round(spend, 2), 'avoided_cost': round(avoided, 2),
            'scope': view['planning_scope']}


@app.get('/api/fleet-study')
def fleet_study(dataset: str, at: int | None = None,
                max_trucks: int = Query(8, ge=1, le=20)):
    """How many trucks would this field actually need right now?

    Re-solves each system's live pump failures against a hypothetical fleet size
    and reports what it would cost. The curve flattens once more trucks stop
    buying anything, which is the answer to "is our fleet the right size".
    """
    analysis = _analysis(dataset)
    view = _view(dataset, at)
    data = analysis.data
    failures = [a for a in view['alerts'] if a['category'] == 'pump_failure']

    by_system: dict[str, list[dict]] = {}
    for alert in failures:
        by_system.setdefault(alert['system_id'], []).append(alert)

    study = []
    for system_id, group in by_system.items():
        actual = data.ops['systems'][system_id]['emergency_fleet_size']
        curve = []
        for size in range(0, max_trucks + 1):
            # Rebuild the same problems against a hypothetical fleet and re-run the
            # real shared-fleet allocator, so the number on the curve is what the
            # system would genuinely cost with that many trucks -- not a per-tank
            # best case that quietly double-books one truck across three tanks.
            problems = []
            for alert in group:
                facility = data.facilities[alert['facility_id']]
                water, revenue = analysis.well_rates(facility, view['now'])
                problem = FacilityProblem(data, facility, alert['level_pct'],
                                          alert['repair_hours_remaining'], water, revenue)
                problem.fleet = size
                problems.append(problem)
            options = {p.facility_id: candidates(p) for p in problems}
            chosen = allocate(problems, options, size)
            total = sum(plan['cost'] for plan in chosen)
            trips = sum(plan['trucks'] * plan.get('trips', 0) for plan in chosen)
            curve.append({'fleet_size': size, 'system_cost': round(total, 2),
                          'truck_trips': trips,
                          'tanks_lost': sum(1 for p in chosen if p['tripped'])})
        # The smallest fleet that already buys everything a bigger one would.
        floor = min(point['system_cost'] for point in curve)
        enough = next(point['fleet_size'] for point in curve
                      if point['system_cost'] <= floor + 1e-6)
        study.append({'system_id': system_id, 'actual_fleet_size': actual,
                      'failures': len(group), 'trucks_worth_having': enough,
                      'curve': curve})

    return {'now': view['now'], 'systems': study,
            'note': 'Cost of this system\'s live pump failures if its fleet were this '
                    'size, solved with the same shared-fleet allocator. Where the curve '
                    'flattens, another truck buys nothing.'}


# --------------------------------------------------------------------------
# Optional LLM narration over the computed result
# --------------------------------------------------------------------------

class Investigation(BaseModel):
    dataset: str
    facility_id: str
    at: int | None = None
    question: str = Field(
        default='Explain the evidence, the verified plan, and the tradeoffs for this facility.',
        max_length=2000)


@app.post('/api/investigate')
async def investigate(request: Investigation):
    """Narrate an already-computed result through a tool-calling model.

    The model never does the maths and never sees the raw files: detection and
    planning happen here, and the tools only hand it numbers this backend has
    already derived and verified. That keeps the recommendation deterministic and
    reproducible while letting the explanation be conversational.
    """
    key = os.getenv('NVIDIA_API_KEY')
    if not key:
        raise HTTPException(503, 'Set NVIDIA_API_KEY on the backend to enable live '
                                 'Nemotron tool execution.')
    model = os.getenv('NVIDIA_MODEL', DEFAULT_MODEL)
    view = _view(request.dataset, request.at)
    facility = next((f for f in view['facilities'] if f['id'] == request.facility_id), None)
    if facility is None:
        raise HTTPException(404, 'Unknown facility')
    alert = next((a for a in view['alerts'] if a['facility_id'] == request.facility_id), None)

    tool_specs = [
        ('inspect_telemetry', 'Read the selected facility and its sensor evidence.'),
        ('get_verified_plan', 'Read the deterministic plan chosen against the shared fleet.'),
        ('verify_plan', 'Check the simulation result and the stated planning limits.'),
    ]
    tools = [{'type': 'function', 'function': {
        'name': name, 'description': description,
        'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}}
        for name, description in tool_specs]

    messages = [
        {'role': 'system', 'content':
            'You are NightShift, an oilfield investigation assistant. Use all three tools '
            'before explaining a plan. Only cite numbers returned by tools. Actions are '
            'simulations requiring operator review. State the optimization limits and never '
            'claim global optimality.'},
        {'role': 'user', 'content': request.question},
    ]
    required = {name for name, _ in tool_specs}
    executed: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            for _ in range(6):
                response = await client.post(
                    'https://integrate.api.nvidia.com/v1/chat/completions',
                    headers={'Authorization': f'Bearer {key}'},
                    json={'model': model, 'messages': messages, 'tools': tools,
                          'temperature': .1, 'max_tokens': 1600})
                response.raise_for_status()
                message = response.json()['choices'][0]['message']
                messages.append(message)

                if not message.get('tool_calls'):
                    if not required.issubset(executed):
                        messages.append({'role': 'user', 'content':
                                         'Call all three required tools before your final '
                                         'explanation.'})
                        continue
                    return {'answer': message.get('content', ''),
                            'tools_executed': executed, 'model': model}

                for call in message['tool_calls']:
                    name = call['function']['name']
                    if name == 'inspect_telemetry':
                        result = {'facility': facility,
                                  'evidence': alert['evidence'] if alert else [],
                                  'confidence': alert['confidence'] if alert else None,
                                  'now': view['now']}
                    elif name == 'get_verified_plan':
                        result = alert['recommendation'] if alert else {
                            'status': 'No detected incident at this facility'}
                    elif name == 'verify_plan':
                        result = {'verified': bool(alert and alert['recommendation'].get('verified')),
                                  'scope': view['planning_scope']}
                    else:
                        result = {'error': 'Unknown tool'}
                    executed.append(name)
                    messages.append({'role': 'tool', 'tool_call_id': call['id'],
                                     'content': json.dumps(result, default=str)})
        raise HTTPException(502, 'Nemotron did not complete the required investigation '
                                 'within six steps.')
    except httpx.HTTPError as exc:
        raise HTTPException(502, 'NVIDIA request failed. Check server credentials, model '
                                 'availability, and connectivity.') from exc
