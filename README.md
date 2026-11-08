# NightShift AI

Night-shift operations console for the EOG "Beat the Shutdown" challenge. It loads a
dataset folder, works out what is going wrong from the sensor readings alone, and
says what to do about it at the lowest cost. Everything is advisory: nothing here
controls real equipment.

## Run locally

Requires Python 3.10+ and Node.js 20.9+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn backend.main:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:3000. API docs at http://localhost:8000/docs.

On Windows use `.venv/Scripts/python.exe` in place of `.venv/bin/python`.

## Switching datasets

The app reads only `network.json`, `ops.json` and `telemetry.csv`. Any folder under
`data/eog` containing those three files shows up in the dataset picker, so the
judging `test/` folder works by dropping it in — no code change. `answer_key.json`
is never opened by the running app; only `scripts/validate_history.py` and the
tests read it.

## How it works

### Detecting the problems

Every healthy reading in this network is predicted by physics that `network.json`
already states: water arriving at the disposal site equals water the pump sent, a
healthy pump moves its rated flow, and both pressures sit a fixed offset above the
disposal site's. So instead of thresholding raw values, the backend subtracts the
prediction and watches the **residual**, which is zero-mean noise when the
equipment is healthy. Those offsets and the noise width are *learned* from the
dataset with robust statistics, never hardcoded, so an unseen network calibrates
itself.

Each fault moves its own residuals and leaves the others alone:

| Fault | Channels it moves |
|---|---|
| `pipeline_leak` | disposal-site arrivals, pipeline pressure |
| `pump_degradation` | pump flow, discharge pressure |
| `pump_failure` | pump fault status, flow to zero, discharge pressure collapses |

Leaks and worn pumps **ramp from zero**, so any fixed threshold is late by
construction. A **CUSUM** chart accumulates evidence instead, catching a
half-sigma drift that no single reading would reveal. It also yields the two
things a threshold cannot: a maximum-likelihood **change point**, so an event
reports when it *started* rather than when it was noticed, and a drain-back that
**closes** the event when the repair lands, so resolved problems leave the board.

Detection is causal — the statistic at time *t* uses only data up to *t* — so
dragging the replay slider shows exactly what an operator would have known then.

### Deciding what to do

A pump failure gets a costed plan. The planner replays candidate responses against
an event-driven tank simulation and keeps the cheapest one that never reaches the
shutdown limit. It searches every truck count and trip count, every subset of wells
to shut in, and the latest moment each shut-in can start — because a shut-in only
costs money while the well is off.

A system's trucks are shared, so concurrent failures are solved **together**: plan
combinations are searched against a truck timeline, and a truck committed to one
tank is gone from the others until it is back. Leaks and worn pumps still move
water, so they get an inspector and no countdown.

The countdown itself is reported as a band (`p10`/`p50`/`p90`): tank headroom is
exact geometry, but the fill rate is a noisy sensor sum, so its spread is carried
through.

## Measured against the answer keys

Run `.venv/bin/python -m scripts.validate_history`.

| Folder | Events found | Invented | Plan cost vs reference |
|---|---|---|---|
| `full_week` | 23 / 23 | 0 | — |
| `snapshot_2026-10-08T1200` | 13 / 13 | 0 | $3,106 vs $3,108 |
| `snapshot_2026-10-09T0330` | 15 / 15 | 0 | $1,810 vs $1,810 |
| `snapshot_2026-10-10T0900` | 21 / 21 | 0 | $3,022 vs $3,095 |

Alert ordering matches the key at every snapshot. Sampling the live alert board
every 30 minutes across the week gives precision 0.984 and recall 0.935; the
residual misses are the first hour or two of slow-ramping faults, and the residual
false positives are repaired leaks whose pipeline has not pumped since the repair,
so there is no flow to confirm it with.

## API

| Endpoint | What it returns |
|---|---|
| `GET /api/datasets` | Every loadable dataset folder |
| `GET /api/dashboard?dataset=&at=` | Alerts, plans, facility state at a replay timestamp |
| `GET /api/trend?dataset=&asset=&metric=` | One sensor channel's history |
| `GET /api/events?dataset=&at=` | Event export in the `SPEC.md` shape, resolved history included |
| `GET /api/handoff?dataset=&at=` | Plain-English shift brief |
| `GET /api/fleet-study?dataset=&at=` | Cost of the live incidents at each hypothetical fleet size |
| `POST /api/investigate` | Optional LLM narration of an already-computed result |

## Verification

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m scripts.validate_history
cd frontend && npm run typecheck && npm run build
```

## Nemotron (optional)

`POST /api/investigate` narrates a result through a tool-calling model. The model
never does the maths and never sees the raw files — detection and planning happen
in the backend, and the tools hand it only numbers already derived and verified
here. Set `NVIDIA_API_KEY` in the backend's terminal, and optionally `NVIDIA_MODEL`.
Without a key the endpoint returns an explicit 503 rather than pretending. The
server does not load `.env` automatically; `.env.example` documents the variables.

## Limits

This is a local decision-support MVP, not a certified control system.

- The planner searches simultaneous truck dispatches with equal trip counts per
  truck and a common shut-in time per well subset. It does not search independently
  timed shut-ins within one subset. Within a system it is exhaustive over each
  facility's non-dominated plans; the truck scheduler places jobs
  earliest-deadline-first, which is exact when each dispatch uses one truck.
- The cheapest plan can graze the shutdown limit exactly as the repair completes.
  That is genuinely optimal and genuinely zero-margin; an operator may prefer to
  act earlier than the recommendation.
- Simulation holds each well's currently measured water rate constant and uses the
  fixed repair duration from `ops.json`. A tank that has already tripped stays shut
  until the repair even if a truck drains it, as the rules require.
- Confidence is a one-sided Gaussian tail probability on the accumulated residual.
  It answers "is this really a fault", not "how bad will it get".
- A repaired leak stays flagged until its pipeline pumps again, because there is no
  reading that can clear it sooner.
- Inspection costs are not modelled. No authentication, dispatch ledger or hosted
  deployment is included.

The included EOG data README asks for Comic Sans typography and an Avon Corps
copyright footer; both are reflected in the dashboard.

© 2026 Avon Corps.
