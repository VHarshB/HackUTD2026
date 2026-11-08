import type {
  Asset,
  Dashboard,
  Facility,
  Navigation,
  System,
  Vec3,
} from "./types";

export type FacilityLayout = {
  facility: Facility;
  position: Vec3;
  width: number;
  depth: number;
  wellPositions: Vec3[];
};
export type SystemLayout = {
  system: System;
  position: Vec3;
  width: number;
  depth: number;
  facilities: FacilityLayout[];
  disposal: Vec3;
  yard: Vec3;
};
export type SceneGraph = {
  systems: SystemLayout[];
  assets: Record<string, Asset>;
  radius: number;
  center: Vec3;
};
export const add = (a: Vec3, b: Vec3): Vec3 => [
  a[0] + b[0],
  a[1] + b[1],
  a[2] + b[2],
];

/** All coordinates are a process schematic, never surveyed equipment locations. */
export function buildScene(data: Dashboard): SceneGraph {
  const systems: SystemLayout[] = data.systems.map((system) => {
    const facilities = data.facilities.filter((f) => f.system_id === system.id);
    const columns = Math.max(1, Math.ceil(Math.sqrt(facilities.length)));
    const rows = Math.ceil(facilities.length / columns);
    const cellDepth = Math.max(
      17,
      ...facilities.map((f) => f.wells.length * 2.8 + 5),
    );
    const width = columns * 26 + 10;
    const depth = rows * cellDepth + 21;
    return {
      system,
      position: [0, 0, 0],
      width,
      depth,
      disposal: [width / 2 - 8, 0, -depth / 2 + 6],
      yard: [-width / 2 + 8, 0, -depth / 2 + 6],
      facilities: facilities.map((facility, i) => ({
        facility,
        position: [
          ((i % columns) - (columns - 1) / 2) * 26,
          0,
          Math.floor(i / columns) * cellDepth -
            ((rows - 1) * cellDepth) / 2 +
            6,
        ],
        width: 23,
        depth: cellDepth - 3,
        wellPositions: facility.wells.map(
          (_, j) =>
            [-7.5, 0, (j - (facility.wells.length - 1) / 2) * 2.8] as Vec3,
        ),
      })),
    };
  });
  const columns = Math.max(1, Math.ceil(Math.sqrt(systems.length)));
  const rows = Math.ceil(systems.length / columns);
  const cellWidth = Math.max(40, ...systems.map((s) => s.width)) + 16;
  const cellDepth = Math.max(40, ...systems.map((s) => s.depth)) + 18;
  const assets: Record<string, Asset> = {};
  systems.forEach((s, i) => {
    s.position = [
      ((i % columns) - (columns - 1) / 2) * cellWidth,
      0,
      (Math.floor(i / columns) - (rows - 1) / 2) * cellDepth,
    ];
    const register = (
      id: string,
      kind: Asset["kind"],
      position: Vec3,
      metrics: string[],
      radius: number,
      facilityId?: string,
    ) => {
      assets[id] = {
        id,
        kind,
        systemId: s.system.id,
        facilityId,
        position: add(s.position, position),
        metrics,
        radius,
      };
    };
    register(s.system.disposal_site.id, "disposal", s.disposal, [], 7);
    register(`${s.system.id}:truck-yard`, "yard", s.yard, [], 6);
    s.facilities.forEach((f) => {
      register(
        f.facility.tank.id,
        "tank",
        add(f.position, [0, 1.6, 0]),
        ["level_pct"],
        4.5,
        f.facility.id,
      );
      register(
        f.facility.pump.id,
        "pump",
        add(f.position, [4.5, 0.7, 0]),
        ["status", "flow_bpd", "discharge_psi"],
        4,
        f.facility.id,
      );
      register(
        f.facility.pipeline.id,
        "pipeline",
        add(f.position, [8.1, 0.7, 0]),
        ["receive_flow_bpd", "pressure_psi"],
        5,
        f.facility.id,
      );
      f.facility.wells.forEach((w, j) =>
        register(
          w.id,
          "well",
          add(f.position, add(f.wellPositions[j], [0, 0.8, 0])),
          ["water_bpd", "status"],
          3.5,
          f.facility.id,
        ),
      );
    });
  });
  return {
    systems,
    assets,
    center: [0, 0, 0],
    radius: Math.max(columns * cellWidth, rows * cellDepth) * 0.44,
  };
}

export function navigationFrame(
  graph: SceneGraph,
  nav: Navigation,
): { target: Vec3; radius: number } {
  const system = graph.systems.find((s) => s.system.id === nav.systemId);
  const facility = system?.facilities.find(
    (f) => f.facility.id === nav.facilityId,
  );
  if (system && facility)
    return {
      target: add(system.position, add(facility.position, [0, 1, 0])),
      radius: Math.max(facility.width, facility.depth) * 0.65,
    };
  if (system)
    return {
      target: add(system.position, [0, 1, 0]),
      radius: Math.max(system.width, system.depth) * 0.66,
    };
  return { target: graph.center, radius: graph.radius };
}
