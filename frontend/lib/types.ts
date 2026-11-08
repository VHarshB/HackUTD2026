export type Vec3 = [number, number, number];
export type IncidentCategory =
  "pump_failure" | "pump_degradation" | "pipeline_leak";
export type Well = {
  id: string;
  baseline_water_bpd: number;
  oil_bpd: number;
  gas_mcfd: number;
};
export type Facility = {
  id: string;
  system_id: string;
  lat: number;
  lon: number;
  wells: Well[];
  tank: { id: string; capacity_bbl: number };
  pump: {
    id: string;
    max_flow_bpd: number;
    start_level_pct: number;
    stop_level_pct: number;
  };
  pipeline: { id: string; max_bpd: number; max_pressure_psi: number };
  level_pct: number | null;
  pump_status: number | null;
  flow_bpd: number | null;
  category: IncidentCategory | null;
};
export type System = {
  id: string;
  center: [number, number];
  truck_yard: [number, number];
  disposal_site: { id: string; lat: number; lon: number; pressure_psi: number };
  facilities: Facility[];
};
export type Action = {
  type: string;
  facility_id?: string;
  asset_id?: string;
  trucks?: number;
  trips_per_truck?: number;
  arrival_hours?: number[];
  busy_until_hour?: number;
  wells?: string[];
  start_after_min?: number;
};
export type Plan = {
  label: string;
  cost: number;
  baseline_cost?: number;
  verified?: boolean;
  tripped?: boolean;
  trucks?: number;
  actions: Action[];
  trace?: { hour: number; level_pct: number }[];
  alternatives?: { label: string; cost: number; tripped: boolean }[];
};
export type Incident = {
  facility_id: string;
  system_id: string;
  category: IncidentCategory;
  onset_unix: number;
  evidence: string[];
  hours_to_limit: number | null;
  confidence: number;
  recommendation: Plan;
};
export type Dashboard = {
  now: number;
  start: number;
  end: number;
  /** Seconds between recorded readings, inferred by the backend. */
  step: number;
  systems: System[];
  facilities: Facility[];
  alerts: Incident[];
  limits: { warning: number; shutdown: number };
  planning_scope: string;
};
export type AssetKind =
  "well" | "tank" | "pump" | "pipeline" | "disposal" | "yard";
export type Asset = {
  id: string;
  kind: AssetKind;
  systemId: string;
  facilityId?: string;
  position: Vec3;
  radius: number;
  metrics: string[];
};
export type Selection = { assetId: string; metric?: string };
export type Navigation = { systemId?: string; facilityId?: string };
export type CameraIntent = { target: Vec3; radius: number; revision: number };
export type TrendPoint = { ts: number; value: number };
export type Investigation = {
  answer: string;
  tools_executed: string[];
  model: string;
};
