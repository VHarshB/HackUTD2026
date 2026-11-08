"use client";
import { useEffect, useState } from "react";
import { ChevronRight, Crosshair, Gauge, ShieldCheck, X } from "lucide-react";
import type { Asset, Dashboard, Selection, TrendPoint } from "../../lib/types";
import { api } from "../../lib/api";
import {
  equipmentState,
  formatValue,
  humanize,
  metricInfo,
  money,
} from "../../lib/operational-status";
import SensorTrend from "../charts/SensorTrend";
import NemotronInvestigation from "./NemotronInvestigation";

export default function AssetInspector({
  asset,
  selection,
  data,
  dataset,
  disabled,
  onClose,
  onFocus,
  onSelect,
}: {
  asset: Asset;
  selection: Selection;
  data: Dashboard;
  dataset: string;
  disabled: boolean;
  onClose: () => void;
  onFocus: () => void;
  onSelect: (s: Selection) => void;
}) {
  const facility = data.facilities.find((f) => f.id === asset.facilityId);
  const incident = data.alerts.find((a) => a.facility_id === asset.facilityId);
  const state = equipmentState(asset, facility, incident, data.limits);
  const [readings, setReadings] = useState<Record<string, TrendPoint[]>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const metric =
    selection.metric && asset.metrics.includes(selection.metric)
      ? selection.metric
      : asset.metrics[0];
  const metricsKey = asset.metrics.join(",");
  useEffect(() => {
    const controller = new AbortController();
    setReadings({});
    setErrors({});
    const metrics = metricsKey ? metricsKey.split(",") : [];
    setLoading(metrics.length > 0);
    void Promise.all(
      metrics.map(async (name) => {
        try {
          const points = await api.trend(
            dataset,
            asset.id,
            name,
            data.now,
            controller.signal,
          );
          if (!controller.signal.aborted)
            setReadings((prev) => ({ ...prev, [name]: points }));
        } catch (e) {
          if (!controller.signal.aborted)
            setErrors((prev) => ({ ...prev, [name]: (e as Error).message }));
        }
      }),
    ).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [dataset, asset.id, data.now, metricsKey]);
  const plan = incident?.recommendation;
  const well = facility?.wells.find((w) => w.id === asset.id);
  const disposal = data.systems.find(
    (s) => s.disposal_site.id === asset.id,
  )?.disposal_site;
  return (
    <aside
      className="asset-inspector glass"
      aria-label={`${asset.id} inspector`}
    >
      <div className="inspector-heading">
        <span className="technical-label">ASSET INSPECTOR</span>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close asset inspector"
        >
          <X size={17} />
        </button>
      </div>
      <div className="inspector-scroll">
        <div className="asset-title">
          <span className="asset-type">
            {asset.kind === "yard"
              ? "TRUCK YARD"
              : asset.kind === "disposal"
                ? "DISPOSAL SITE"
                : asset.kind.toUpperCase()}
          </span>
          <h1>{humanize(asset.id)}</h1>
          <p>
            <i style={{ background: state.color }} />
            {state.label}
          </p>
        </div>
        <button className="focus-button" onClick={onFocus}>
          <Crosshair size={14} />
          Focus equipment
          <ChevronRight size={13} />
        </button>
        {asset.metrics.length > 0 && (
          <section className="inspector-section">
            <div className="section-heading">
              <Gauge size={14} />
              <h2>Recorded measurements</h2>
            </div>
            <div className="measurement-list">
              {asset.metrics.map((name) => {
                const points = readings[name];
                const value = points?.[points.length - 1]?.value;
                const status =
                  name === "status" && value != null
                    ? asset.kind === "pump"
                      ? (
                          { 0: "Stopped", 1: "Running", 2: "Fault" } as Record<
                            number,
                            string
                          >
                        )[value]
                      : (
                          { 0: "Shut in", 1: "Producing" } as Record<
                            number,
                            string
                          >
                        )[value]
                    : null;
                return (
                  <button
                    key={name}
                    className={metric === name ? "selected" : ""}
                    onClick={() =>
                      onSelect({ assetId: asset.id, metric: name })
                    }
                  >
                    <span>{metricInfo[name]?.label || name}</span>
                    <b>
                      {value == null
                        ? loading
                          ? "Loading…"
                          : "Unavailable"
                        : status || formatValue(value)}
                      <small>
                        {value != null && !status ? metricInfo[name]?.unit : ""}
                      </small>
                    </b>
                  </button>
                );
              })}
            </div>
            {metric && (
              <>
                <div className="chart-heading">
                  <span>{metricInfo[metric]?.label || metric}</span>
                  <code>{metric}</code>
                </div>
                {errors[metric] ? (
                  <p className="inline-error" role="alert">
                    {errors[metric]}
                  </p>
                ) : loading && !readings[metric] ? (
                  <p className="fine-print">Loading actual sensor readings…</p>
                ) : (
                  <SensorTrend
                    points={readings[metric] || []}
                    metric={metric}
                    unit={metricInfo[metric]?.unit || ""}
                    thresholds={
                      metric === "level_pct" ? data.limits : undefined
                    }
                  />
                )}
              </>
            )}
            <p className="fine-print">
              Sensor markers identify measured assets and metrics. Mounting
              positions are schematic.
            </p>
          </section>
        )}
        {asset.kind === "tank" && facility && (
          <div className="spec-list">
            <span>
              Configured capacity{" "}
              <b>{formatValue(facility.tank.capacity_bbl, 0)} bbl</b>
            </span>
            <span>
              Warning / shutdown{" "}
              <b>
                {data.limits.warning}% / {data.limits.shutdown}%
              </b>
            </span>
          </div>
        )}
        {well && (
          <div className="spec-list">
            <span>
              Catalog oil production{" "}
              <b>{formatValue(well.oil_bpd, 0)} bbl/day</b>
            </span>
            <span>
              Catalog gas production{" "}
              <b>{formatValue(well.gas_mcfd, 0)} mcf/day</b>
            </span>
            <p className="fine-print">
              Configured production rates; these are not live oil/gas sensors.
            </p>
          </div>
        )}
        {disposal && (
          <section className="inspector-section">
            <h2>Shared disposal destination</h2>
            <p>
              Facility pipelines in system {asset.systemId} connect to this
              installation.
            </p>
            <div className="spec-list">
              <span>
                Configured pressure{" "}
                <b>{formatValue(disposal.pressure_psi, 0)} psi</b>
              </span>
            </div>
            <p className="fine-print">
              The dataset provides no disposal-site sensors. This is a network
              configuration value.
            </p>
          </section>
        )}
        {asset.kind === "yard" && (
          <section className="inspector-section">
            <h2>Fleet resource area</h2>
            <p>
              The tanker is a symbolic representation, not a truck count or
              dispatch. The current API does not expose fleet size, live
              availability, truck identities or movement.
            </p>
            <p className="fine-print">
              Truck recommendations are visible in the affected facility’s
              response panel. No trucks have been dispatched by this interface.
            </p>
          </section>
        )}
        {incident && (
          <section className="inspector-section incident-evidence">
            <div className="section-heading">
              <span
                className={
                  "status-dot " +
                  (incident.category === "pump_degradation"
                    ? "warning"
                    : "fault")
                }
              />
              <h2>{humanize(incident.category)}</h2>
              <span className="context-label">FACILITY CONTEXT</span>
            </div>
            {incident.category === "pump_failure" &&
              incident.hours_to_limit != null && (
                <div className="countdown">
                  <strong>
                    {incident.hours_to_limit.toFixed(2)}
                    <small>h</small>
                  </strong>
                  <span>
                    until automatic shutdown
                    <br />
                    <small>Backend estimate · no intervention</small>
                  </span>
                </div>
              )}
            {incident.category === "pipeline_leak" && (
              <p className="fine-print">
                The fault is associated with {facility?.pipeline.id}; the
                dataset does not locate the leak along the pipe.
              </p>
            )}
            <ul className="evidence-list">
              {incident.evidence.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
            <p className="fine-print">
              Rule confidence {Math.round(incident.confidence * 100)}% · not a
              calibrated probability
            </p>
          </section>
        )}
        {plan && (
          <section className="inspector-section response-section">
            <div className="section-heading">
              <ShieldCheck size={14} />
              <h2>
                {plan.verified
                  ? "Verified response candidate"
                  : "Recommended response"}
              </h2>
            </div>
            <h3>{plan.label}</h3>
            {incident?.category === "pump_failure" ? (
              <>
                <div className="response-cost">
                  <span>Estimated response cost</span>
                  <strong>{money(plan.cost)}</strong>
                </div>
                {plan.baseline_cost != null && (
                  <p className="saving">
                    {money(Math.max(0, plan.baseline_cost - plan.cost))} avoided
                    vs. no intervention
                  </p>
                )}
              </>
            ) : (
              <p className="fine-print">
                Inspection cost is not modeled by the backend.
              </p>
            )}
            {plan.actions.map((action, i) => (
              <p className="response-action" key={i}>
                {action.type === "dispatch_truck"
                  ? `${action.trucks} truck(s) × ${action.trips_per_truck} trip(s). First arrival: ${action.arrival_hours?.[0] != null ? "+" + formatValue(action.arrival_hours[0] * 60, 0) + " min" : "not provided"}.`
                  : action.type === "shut_in_wells"
                    ? `Shut in ${action.wells?.join(", ")} at +${formatValue(action.start_after_min, 0)} min.`
                    : `Inspect ${action.asset_id || "affected equipment"}.`}
              </p>
            ))}
            {plan.alternatives && (
              <details className="alternatives">
                <summary>
                  Calculated alternatives <ChevronRight size={13} />
                </summary>
                {plan.alternatives.map((p, i) => (
                  <div key={i}>
                    <span>
                      {p.label}
                      {p.tripped && <small>Includes automatic shut-in</small>}
                    </span>
                    <b>{money(p.cost)}</b>
                  </div>
                ))}
              </details>
            )}
            {plan.trace && (
              <details className="projection">
                <summary>
                  Projected tank response <ChevronRight size={13} />
                </summary>
                <SensorTrend
                  projected
                  points={plan.trace.map((p) => ({
                    ts: data.now + p.hour * 3600,
                    value: p.level_pct,
                  }))}
                  metric="level_pct"
                  unit="%"
                  thresholds={data.limits}
                />
                <p className="fine-print">
                  Backend simulation through repair. Not recorded telemetry.
                </p>
              </details>
            )}
            <details className="planning-limits">
              <summary>Verification & planning limits</summary>
              <p>{data.planning_scope}</p>
            </details>
            <p className="simulation-note">
              Recommendation only. No equipment commands or dispatches are sent.
            </p>
          </section>
        )}
        {facility && (
          <NemotronInvestigation
            dataset={dataset}
            facilityId={facility.id}
            at={data.now}
            disabled={disabled}
          />
        )}
      </div>
    </aside>
  );
}
