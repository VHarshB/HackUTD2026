import type { Asset, Dashboard, Facility, Incident } from "./types";

export const colors = {
  healthy: "#67bc9c",
  idle: "#7b8f9f",
  warning: "#e7b568",
  fault: "#f16c68",
  selected: "#7edfe9",
  steel: "#637888",
  darkSteel: "#273e4d",
};
export const metricInfo: Record<string, { label: string; unit: string }> = {
  level_pct: { label: "Tank level", unit: "%" },
  status: { label: "Equipment status", unit: "code" },
  flow_bpd: { label: "Discharge flow", unit: "bbl/day" },
  discharge_psi: { label: "Discharge pressure", unit: "psi" },
  receive_flow_bpd: { label: "Received flow", unit: "bbl/day" },
  pressure_psi: { label: "Pipeline pressure", unit: "psi" },
  water_bpd: { label: "Water production", unit: "bbl/day" },
  inflow_bpd: { label: "Facility inflow", unit: "bbl/day" },
};
export function equipmentState(
  asset: Asset,
  facility?: Facility,
  incident?: Incident,
  limits?: Dashboard["limits"],
) {
  if (asset.kind === "pump") {
    if (facility?.pump_status === 2 || incident?.category === "pump_failure")
      return { label: "Pump fault", color: colors.fault };
    if (incident?.category === "pump_degradation")
      return { label: "Degraded performance", color: colors.warning };
    if (facility?.pump_status === 0)
      return { label: "Stopped · normal cycle", color: colors.idle };
    if (facility?.pump_status === 1)
      return { label: "Running", color: colors.healthy };
  }
  if (asset.kind === "pipeline" && incident?.category === "pipeline_leak")
    return {
      label: "Leak detected · asset location only",
      color: colors.fault,
    };
  if (asset.kind === "tank" && facility?.level_pct != null && limits) {
    if (facility.level_pct >= limits.shutdown)
      return { label: "At shutdown threshold", color: colors.fault };
    if (facility.level_pct >= limits.warning)
      return { label: "Above warning threshold", color: colors.warning };
    return { label: "Below warning threshold", color: colors.healthy };
  }
  return {
    label:
      asset.kind === "well"
        ? "Select a sensor to read status"
        : asset.kind === "yard"
          ? "Symbolic resource area"
          : asset.kind === "disposal"
            ? "Shared disposal destination"
            : "No active fault detected",
    color:
      asset.kind === "well" || asset.kind === "yard"
        ? colors.idle
        : colors.healthy,
  };
}
export const formatValue = (v: number | null | undefined, digits = 1) =>
  v == null || !Number.isFinite(v)
    ? "Unavailable"
    : v.toLocaleString("en-US", { maximumFractionDigits: digits });
export const money = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(v);
export const timestamp = (ts: number) =>
  new Date(ts * 1000).toLocaleString("en-GB", {
    timeZone: "UTC",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }) + " UTC";
export const humanize = (id: string) => id.replaceAll("_", " ");
