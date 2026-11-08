"use client";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Box,
  Crosshair,
  HelpCircle,
  Layers3,
  LoaderCircle,
  MousePointer2,
  RotateCcw,
  X,
} from "lucide-react";
import type {
  Asset,
  CameraIntent,
  Dashboard,
  Incident,
  Navigation,
  Selection,
} from "../lib/types";
import { api } from "../lib/api";
import { buildScene, navigationFrame } from "../lib/scene-layout";
import { humanize } from "../lib/operational-status";
import TopBar from "../components/control-room/TopBar";
import IncidentRail from "../components/control-room/IncidentRail";
import AssetInspector from "../components/control-room/AssetInspector";
import ReplayTimeline from "../components/control-room/ReplayTimeline";

const DigitalTwinScene = dynamic(
  () => import("../components/digital-twin/DigitalTwinScene"),
  {
    ssr: false,
    loading: () => (
      <div className="scene-loading">
        <LoaderCircle className="spin" size={24} />
        <span>INITIALIZING 3D ENGINE</span>
      </div>
    ),
  },
);
const DEFAULT_DATASET = "history/snapshot_2026-10-08T1200";

export default function ControlRoom() {
  const [datasets, setDatasets] = useState<string[]>([]),
    [dataset, setDataset] = useState("");
  const [data, setData] = useState<Dashboard | null>(null),
    [at, setAt] = useState<number | null>(null);
  const [navigation, setNavigation] = useState<Navigation>({}),
    [selection, setSelection] = useState<Selection | null>(null);
  const [intent, setIntent] = useState<CameraIntent>({
    target: [0, 0, 0],
    radius: 100,
    revision: 0,
  });
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [retry, setRetry] = useState(0);
  const [railOpen, setRailOpen] = useState(false),
    [helpOpen, setHelpOpen] = useState(false);
  const initializedDataset = useRef("");
  // Playback issues one request per frame. Those are not user-visible loads, so
  // they must not strobe the spinner or disable the scene while it animates.
  const playing = useRef(false);
  const replayPlaying = useCallback((value: boolean) => {
    playing.current = value;
  }, []);
  const graph = useMemo(() => (data ? buildScene(data) : null), [data]);
  const selectedAsset =
    selection && graph ? graph.assets[selection.assetId] : undefined;
  useEffect(() => {
    setRailOpen(window.matchMedia("(min-width: 900px)").matches);
  }, []);
  useEffect(() => {
    if (dataset) return;
    const controller = new AbortController();
    setBusy(true);
    setError("");
    api
      .datasets(controller.signal)
      .then((names) => {
        if (controller.signal.aborted) return;
        setDatasets(names);
        if (!names.length)
          throw Error(
            "No datasets found. Add a dataset containing the three EOG input files to the backend.",
          );
        setDataset(
          names.includes(DEFAULT_DATASET) ? DEFAULT_DATASET : names[0],
        );
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError((e as Error).message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [dataset, retry]);
  useEffect(() => {
    if (!dataset) return;
    const controller = new AbortController();
    if (!playing.current) setBusy(true);
    setError("");
    api
      .dashboard(dataset, at, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError((e as Error).message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [dataset, at, retry]);
  useEffect(() => {
    if (!graph || initializedDataset.current === dataset) return;
    initializedDataset.current = dataset;
    setIntent((old) => ({
      ...navigationFrame(graph, {}),
      revision: old.revision + 1,
    }));
  }, [graph, dataset]);
  const changeDataset = useCallback((name: string) => {
    initializedDataset.current = "";
    setData(null);
    setSelection(null);
    setNavigation({});
    setAt(null);
    setDataset(name);
  }, []);
  const navigate = useCallback(
    (next: Navigation) => {
      if (!graph) return;
      setNavigation(next);
      setSelection((previous) => {
        const a = previous && graph.assets[previous.assetId];
        return a &&
          (next.facilityId
            ? a.facilityId === next.facilityId
            : next.systemId
              ? a.systemId === next.systemId
              : false)
          ? previous
          : null;
      });
      setIntent((old) => ({
        ...navigationFrame(graph, next),
        revision: old.revision + 1,
      }));
    },
    [graph],
  );
  const select = useCallback(
    (next: Selection) => {
      if (!graph || busy) return;
      const asset = graph.assets[next.assetId];
      if (!asset) return;
      setSelection(next);
      const nav = { systemId: asset.systemId, facilityId: asset.facilityId };
      if (
        navigation.systemId !== nav.systemId ||
        navigation.facilityId !== nav.facilityId
      ) {
        setNavigation(nav);
        setIntent((old) => ({
          ...navigationFrame(graph, nav),
          revision: old.revision + 1,
        }));
      }
    },
    [graph, navigation, busy],
  );
  const focus = useCallback(
    (asset: Asset) => {
      if (busy) return;
      setNavigation({ systemId: asset.systemId, facilityId: asset.facilityId });
      setSelection((previous) =>
        previous?.assetId === asset.id ? previous : { assetId: asset.id },
      );
      setIntent((old) => ({
        target: asset.position,
        radius: asset.radius,
        revision: old.revision + 1,
      }));
    },
    [busy],
  );
  const focusIncident = useCallback(
    (incident: Incident) => {
      const facility = data?.facilities.find(
        (f) => f.id === incident.facility_id,
      );
      const id =
        incident.category === "pipeline_leak"
          ? facility?.pipeline.id
          : facility?.pump.id;
      if (id && graph?.assets[id]) focus(graph.assets[id]);
      if (window.innerWidth < 900) setRailOpen(false);
    },
    [data, graph, focus],
  );
  const reset = useCallback(() => {
    if (graph)
      setIntent((old) => ({
        ...navigationFrame(graph, navigation),
        revision: old.revision + 1,
      }));
  }, [graph, navigation]);
  const replay = useCallback((time: number | null) => setAt(time), []);
  const interactions = useMemo(
    () => ({ onSelect: select, onFocus: focus, onNavigate: navigate }),
    [select, focus, navigate],
  );
  const scopeFacilities =
    data?.facilities.filter(
      (f) => !navigation.systemId || f.system_id === navigation.systemId,
    ) || [];
  const assetOptions = graph
    ? Object.values(graph.assets).filter((a) =>
        navigation.facilityId
          ? a.facilityId === navigation.facilityId
          : navigation.systemId
            ? a.systemId === navigation.systemId
            : true,
      )
    : [];
  return (
    <main className={"control-room " + (selectedAsset ? "inspector-open" : "")}>
      <div className="scene-stage">
        {data && graph ? (
          <DigitalTwinScene
            graph={graph}
            data={data}
            navigation={navigation}
            selection={selection}
            intent={intent}
            interactions={interactions}
          />
        ) : (
          <div className="scene-placeholder">
            <div className="placeholder-grid" />
            {!error && (
              <div className="scene-loading">
                <LoaderCircle size={24} className="spin" />
                <span>LOADING OILFIELD TOPOLOGY</span>
                <p>Reading the recorded network and telemetry.</p>
              </div>
            )}
          </div>
        )}
      </div>
      <TopBar
        datasets={datasets}
        dataset={dataset}
        data={data}
        navigation={navigation}
        busy={busy}
        onDataset={changeDataset}
        onNavigate={navigate}
        onReset={reset}
        onBack={() =>
          navigate(
            navigation.facilityId ? { systemId: navigation.systemId } : {},
          )
        }
      />
      {error && (
        <div
          className={"connection-error glass " + (!data ? "centered" : "")}
          role="alert"
        >
          <AlertTriangle size={21} />
          <div>
            <h2>
              {data
                ? "Replay update failed"
                : "Unable to load recorded operations"}
            </h2>
            <p>{error}</p>
            <small>
              {data
                ? "Showing the last successfully loaded timestamp."
                : "The frontend uses the existing Python API at 127.0.0.1:8000. Start it to load your network."}
            </small>
            <button
              className="ui-button"
              onClick={() => setRetry((n) => n + 1)}
            >
              <RotateCcw size={13} />
              Retry connection
            </button>
          </div>
        </div>
      )}
      {data && (
        <>
          <div className="scene-title">
            <span className="technical-label">
              <span className="status-dot cyan" />
              OILFIELD WATER OPERATIONS
            </span>
            <h2>
              {navigation.facilityId
                ? humanize(navigation.facilityId).toLowerCase()
                : navigation.systemId
                  ? `System ${navigation.systemId}`
                  : "The whole field. One clear view."}
            </h2>
            <p>
              {navigation.facilityId
                ? "Wells → tank → pump → pipeline → disposal"
                : `${navigation.systemId ? scopeFacilities.length : data.facilities.length} facilities · ${navigation.systemId ? "shared disposal destination" : `${data.systems.length} connected systems`}`}
            </p>
          </div>
          <div className="scene-navigator glass">
            <Layers3 size={14} />
            <select
              aria-label="Navigate to system"
              value={navigation.systemId || ""}
              onChange={(e) =>
                navigate(e.target.value ? { systemId: e.target.value } : {})
              }
            >
              <option value="">All systems</option>
              {data.systems.map((s) => (
                <option key={s.id} value={s.id}>
                  System {s.id}
                </option>
              ))}
            </select>
            {navigation.systemId && (
              <select
                aria-label="Navigate to facility"
                value={navigation.facilityId || ""}
                onChange={(e) =>
                  navigate({
                    systemId: navigation.systemId,
                    facilityId: e.target.value || undefined,
                  })
                }
              >
                <option value="">All facilities</option>
                {scopeFacilities.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.id.replace(
                      `${navigation.systemId}_FACILITY_`,
                      "Facility ",
                    )}
                  </option>
                ))}
              </select>
            )}
            <label className="asset-picker">
              <MousePointer2 size={13} />
              <select
                aria-label="Inspect equipment"
                value={selection?.assetId || ""}
                onChange={(e) => {
                  if (e.target.value) select({ assetId: e.target.value });
                }}
              >
                <option value="">Inspect equipment…</option>
                {assetOptions.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.id}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <IncidentRail
            incidents={data.alerts}
            open={railOpen}
            onToggle={() => setRailOpen((v) => !v)}
            onSelect={focusIncident}
            selectedFacility={selectedAsset?.facilityId}
            disabled={busy}
          />
          {selectedAsset && selection && (
            <AssetInspector
              key={`${dataset}:${selectedAsset.id}`}
              asset={selectedAsset}
              selection={selection}
              data={data}
              dataset={dataset}
              disabled={busy}
              onClose={() => setSelection(null)}
              onFocus={() => focus(selectedAsset)}
              onSelect={select}
            />
          )}
          <div className="scene-legend glass">
            <span>
              <i className="status-dot healthy" />
              Healthy
            </span>
            <span>
              <i className="status-dot idle" />
              Normal stop
            </span>
            <span>
              <i className="status-dot warning" />
              Warning
            </span>
            <span>
              <i className="status-dot fault" />
              Fault
            </span>
            <span>
              <i className="selection-swatch" />
              Selected
            </span>
          </div>
          <div className="scene-tools">
            {selectedAsset && (
              <button
                className="tool-button glass"
                onClick={() => focus(selectedAsset)}
                title="Focus selected equipment"
              >
                <Crosshair size={16} />
                <span>Focus</span>
              </button>
            )}
            <button
              className="tool-button glass"
              onClick={reset}
              title="Reset current camera view"
            >
              <Box size={16} />
              <span>Reset view</span>
            </button>
            <button
              className={"tool-button glass " + (helpOpen ? "active" : "")}
              aria-expanded={helpOpen}
              onClick={() => setHelpOpen((v) => !v)}
              title="Navigation guide"
            >
              <HelpCircle size={16} />
              <span>Controls</span>
            </button>
          </div>
          {helpOpen && (
            <div className="navigation-help glass">
              <div>
                <h2>Navigate the twin</h2>
                <button
                  className="icon-button"
                  onClick={() => setHelpOpen(false)}
                  aria-label="Close navigation guide"
                >
                  <X size={15} />
                </button>
              </div>
              <dl>
                <dt>Rotate</dt>
                <dd>Left-drag / one finger</dd>
                <dt>Zoom</dt>
                <dd>Scroll / pinch</dd>
                <dt>Pan</dt>
                <dd>Right-drag / two fingers</dd>
                <dt>Inspect</dt>
                <dd>Click equipment or a sensor</dd>
                <dt>Focus</dt>
                <dd>Double-click / Focus button</dd>
              </dl>
              <p>
                Use breadcrumbs to move back through the network. Equipment is
                laid out schematically.
              </p>
            </div>
          )}
          <ReplayTimeline
            key={dataset}
            data={data}
            onChange={replay}
            onPlayingChange={replayPlaying}
            busy={busy}
          />
          {busy && (
            <div className="updating-pill" role="status">
              <LoaderCircle size={12} className="spin" />
              Updating recorded state
            </div>
          )}
        </>
      )}
      <footer className="scene-footer">
        <span>
          <ArrowUpRight size={10} />
          SCHEMATIC LAYOUT · NOT GEOGRAPHIC SCALE
        </span>
        <span>
          Decision support & simulation only <i>·</i> © 2026 Avon Corps
        </span>
      </footer>
    </main>
  );
}
