import {
  ArrowLeft,
  ChevronRight,
  Crosshair,
  Download,
  Layers3,
  RotateCcw,
  Waves,
} from "lucide-react";
import type { Dashboard, Navigation } from "../../lib/types";
import { useState } from "react";
import { timestamp } from "../../lib/operational-status";

export default function TopBar({
  datasets,
  dataset,
  data,
  navigation,
  busy,
  onDataset,
  onNavigate,
  onReset,
  onBack,
}: {
  datasets: string[];
  dataset: string;
  data: Dashboard | null;
  navigation: Navigation;
  busy: boolean;
  onDataset: (name: string) => void;
  onNavigate: (nav: Navigation) => void;
  onReset: () => void;
  onBack: () => void;
}) {
  const [notice, setNotice] = useState("");
  function exportSnapshot() {
    if (!data) return;
    const blob = new Blob([JSON.stringify({ dataset, now: data.now, events: data.alerts, source: "Currently loaded recorded telemetry" }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const download = document.createElement("a");
    download.href = url;
    download.download = "nightshift-events.json";
    download.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice("Exported the currently loaded incidents. No backend connection needed.");
    window.setTimeout(() => setNotice(""), 4000);
  }
  return (
    <header className="topbar glass">
      <button type="button" onClick={() => onNavigate({})} className="brand" style={{ background: "none", border: 0, padding: 0, textAlign: "left" }}>
        <span className="brand-symbol">
          <Waves size={22} />
        </span>
        <span>
          NIGHTSHIFT <em>AI</em>
          <small>OPERATIONS DIGITAL TWIN</small>
        </span>
      </button>
      <span className="toolbar-divider" />
      <label className="dataset-control">
        <span className="technical-label">DATASET</span>
        <select
          value={dataset}
          aria-label="Select telemetry dataset"
          onChange={(e) => onDataset(e.target.value)}
          disabled={!datasets.length}
        >
          {!datasets.length && <option>Connecting…</option>}
          {datasets.map((d) => (
            <option value={d} key={d}>
              {d.replace("history/", "")}
            </option>
          ))}
        </select>
      </label>
      <div className="replay-status">
        <span>
          <i />
          {busy ? "LOADING RECORDING" : "RECORDED TELEMETRY"}
        </span>
        <time>{data ? timestamp(data.now) : "Awaiting dataset"}</time>
      </div>
      <div className="toolbar-actions">
        {data && (
          <button
            className="icon-button export-button"
            onClick={exportSnapshot}
            title="Export current incidents"
            aria-label="Export current incidents"
          >
            <Download size={16} />
          </button>
        )}
        <button
          className="icon-button"
          onClick={onReset}
          disabled={!data}
          title="Reset current view"
          aria-label="Reset current view"
        >
          <RotateCcw size={16} />
        </button>
      </div>
      <nav className="breadcrumbs" aria-label="Spatial navigation">
        <button
          className="back-button"
          onClick={onBack}
          disabled={!navigation.systemId}
          aria-label="Back one navigation level"
        >
          <ArrowLeft size={14} />
        </button>
        <button onClick={() => onNavigate({})}>
          <Layers3 size={13} /> All systems
        </button>
        {navigation.systemId && (
          <>
            <ChevronRight size={12} />
            <button
              onClick={() => onNavigate({ systemId: navigation.systemId })}
            >
              System {navigation.systemId}
            </button>
          </>
        )}
        {navigation.facilityId && (
          <>
            <ChevronRight size={12} />
            <span>
              {navigation.facilityId.replace(
                `${navigation.systemId}_FACILITY_`,
                "Facility ",
              )}
            </span>
          </>
        )}
        <span className="view-level">
          <Crosshair size={11} />
          {navigation.facilityId
            ? "FACILITY DETAIL"
            : navigation.systemId
              ? "SYSTEM OVERVIEW"
              : "NETWORK OVERVIEW"}
        </span>
      </nav>
      {notice && <div role="status" style={{ position: "absolute", right: 0, top: "calc(100% + 60px)", padding: "12px 16px", border: "1px solid #385969", borderRadius: 6, background: "#102330", color: "#b7dce6", fontSize: 11, maxWidth: 320 }}>{notice}</div>}
    </header>
  );
}
