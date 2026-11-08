# NightShift oilfield digital twin

The existing Next.js frontend now renders a procedural, navigable WebGL digital twin. The Python API, optimizer and official datasets are unchanged.

## Start in PowerShell

From the repository root:

```powershell
$env:Path = 'C:\Program Files\nodejs;' + $env:Path
Set-Location frontend
npm install
npm run dev
```

Open **http://localhost:3000**. The existing backend must already be running on port 8000. To start it in another terminal from the repository root:

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

The existing Next proxy is preserved. `BACKEND_URL` can point to a different backend when starting Next. NVIDIA credentials belong exclusively in the backend process environment.

## Navigate

- Drag to orbit, scroll to zoom, right-drag to pan. On touch screens, use one finger to orbit and two fingers to zoom/pan.
- Select a system label or use the system dropdown. Select a facility label or its dropdown to frame the entire facility.
- Click equipment to open its inspector. Double-click it or press **Focus equipment** to move closer.
- Choose equipment from the dropdown for keyboard-accessible inspection.
- Click a sensor marker or measurement row to see real telemetry, units and its recent history.
- Use breadcrumbs and Back to move up; Reset restores the current navigation level.
- Click an incident to focus the affected pump or pipeline.
- Scrub the replay timeline to refresh the recorded equipment state. Requests wait for a 350 ms pause. Selection and camera are preserved across replay updates.

The default dataset is `history/snapshot_2026-10-08T1200` when available, otherwise the first dataset returned by the API. No fault locations or readings are hardcoded.

## Connected endpoints

| Endpoint                                         | Use                                                               |
| ------------------------------------------------ | ----------------------------------------------------------------- |
| `GET /api/datasets`                              | Available recordings and default fallback                         |
| `GET /api/dashboard?dataset=…&at=…`              | Topology, equipment state, incidents, limits and calculated plans |
| `GET /api/trend?dataset=…&asset=…&metric=…&at=…` | Actual per-asset sensor readings                                  |
| `POST /api/investigate`                          | Real Nemotron investigation, actual tool names and errors         |
| `GET /api/events?dataset=…&at=…`                 | Current-incident JSON export                                      |

## Implementation

- `lib/types.ts`: existing API shapes, asset identity, navigation and camera intent.
- `lib/scene-layout.ts`: deterministic system/facility layout and asset-to-world mapping.
- `lib/operational-status.ts`: status colors, thresholds, metric names and units.
- `lib/api.ts`: requests and backend errors with cancellation.
- `components/digital-twin/`: scene, systems, facilities, reusable equipment, projected labels and camera controls.
- `components/control-room/`: toolbar, incidents, asset inspector, replay and Nemotron.
- `components/charts/SensorTrend.tsx`: recorded readings and clearly labeled backend projections.

Models use generated meshes and procedural lighting. No external model assets, paid services, texture downloads, external font requests or postprocessing are required. Pixel density is capped at 1.5. Camera navigation is driven by one typed intent interface so future alternative input controls can share it.

## Exact file inventory

Modified:

```text
frontend/app/page.tsx
frontend/app/layout.tsx
frontend/app/globals.css
frontend/package.json
frontend/package-lock.json
```

Created:

```text
frontend/README.md
frontend/lib/api.ts
frontend/lib/types.ts
frontend/lib/scene-layout.ts
frontend/lib/operational-status.ts
frontend/components/charts/SensorTrend.tsx
frontend/components/control-room/TopBar.tsx
frontend/components/control-room/IncidentRail.tsx
frontend/components/control-room/AssetInspector.tsx
frontend/components/control-room/ReplayTimeline.tsx
frontend/components/control-room/NemotronInvestigation.tsx
frontend/components/digital-twin/AssetLabel.tsx
frontend/components/digital-twin/CameraController.tsx
frontend/components/digital-twin/DigitalTwinScene.tsx
frontend/components/digital-twin/Equipment.tsx
frontend/components/digital-twin/FacilityScene.tsx
frontend/components/digital-twin/SystemScene.tsx
```

## Existing API limits

- Layout and sensor-marker positions are schematic, not surveyed coordinates. A leak is associated with its pipeline asset; no exact leak location is claimed.
- Fleet sizes, availability, truck IDs and actual dispatch history are absent from the dashboard API. One stationary tanker represents a resource area, not an available truck count or dispatch.
- Well oil/gas rates and disposal pressure are labeled as configuration values. Disposal sites have no sensor series. Missing telemetry is unavailable, never substituted with zero.
- Countdown and plans come directly from the backend. Its conservative search limits are displayed. Alternatives have costs but no independent trajectory, so the inspector projects only the backend-recommended trace.
- Nemotron needs backend credentials. Missing credentials and upstream errors are shown verbatim from the API; no successful tool execution is simulated.
- No equipment controls, dispatches, persistent approvals, new endpoints, authentication, webcam controls or deployment infrastructure are added.

Use `npm run build` for a production build or `npm run typecheck` for TypeScript verification. No new test suites or testing infrastructure are included.
