import {
  Activity,
  ChevronDown,
  ChevronUp,
  Clock3,
  Crosshair,
} from "lucide-react";
import type { Incident } from "../../lib/types";
import { humanize } from "../../lib/operational-status";

export default function IncidentRail({
  incidents,
  open,
  onToggle,
  onSelect,
  selectedFacility,
  disabled,
}: {
  incidents: Incident[];
  open: boolean;
  onToggle: () => void;
  onSelect: (a: Incident) => void;
  selectedFacility?: string;
  disabled: boolean;
}) {
  return (
    <aside
      className={"incident-rail glass " + (open ? "expanded" : "collapsed")}
      aria-label="Active incidents"
    >
      <button className="rail-heading" aria-expanded={open} onClick={onToggle}>
        <Activity size={16} />
        <b>Active incidents</b>
        <span
          className={
            incidents.length ? "incident-count" : "incident-count clear"
          }
        >
          {incidents.length}
        </span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {open && (
        <div className="incident-scroll">
          {!incidents.length && (
            <div className="no-incidents">
              <span className="status-dot healthy" />
              No active incidents detected.
              <small>Showing the recorded state.</small>
            </div>
          )}
          {incidents.map((a) => (
            <button
              key={`${a.facility_id}:${a.category}`}
              disabled={disabled}
              onClick={() => onSelect(a)}
              className={
                "incident-row " +
                (selectedFacility === a.facility_id ? "selected" : "")
              }
            >
              <div className="incident-row-top">
                <span
                  className={
                    "incident-severity " +
                    (a.category === "pump_degradation" ? "warning" : "fault")
                  }
                >
                  {a.category === "pump_failure" ? "CRITICAL" : "INSPECTION"}
                </span>
                <span>{a.system_id}</span>
              </div>
              <strong>{humanize(a.facility_id)}</strong>
              <p>{humanize(a.category)}</p>
              <div className="incident-row-bottom">
                {a.category === "pump_failure" && a.hours_to_limit != null ? (
                  <span>
                    <Clock3 size={11} />
                    {a.hours_to_limit.toFixed(1)}h to shutdown
                  </span>
                ) : (
                  <span>Field inspection required</span>
                )}
                <Crosshair size={14} />
              </div>
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}
