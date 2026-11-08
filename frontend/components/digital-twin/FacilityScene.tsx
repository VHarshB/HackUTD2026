"use client";
import { AssetLabel as Html } from "./AssetLabel";
import { useMemo } from "react";
import type { Asset, Dashboard, Navigation, Selection } from "../../lib/types";
import type { FacilityLayout, SceneGraph } from "../../lib/scene-layout";
import {
  equipmentState,
  formatValue,
  colors,
} from "../../lib/operational-status";
import {
  AssetAssembly,
  PipelineModel,
  PumpModel,
  SensorMarker,
  TankModel,
  WellModel,
} from "./Equipment";

export type SceneInteractions = {
  onSelect: (s: Selection) => void;
  onFocus: (a: Asset) => void;
  onNavigate: (nav: Navigation) => void;
};

export default function FacilityScene({
  layout,
  graph,
  data,
  navigation,
  selection,
  interactions,
}: {
  layout: FacilityLayout;
  graph: SceneGraph;
  data: Dashboard;
  navigation: Navigation;
  selection: Selection | null;
  interactions: SceneInteractions;
}) {
  const f = layout.facility;
  const detailed = navigation.facilityId === f.id;
  const incident = data.alerts.find((a) => a.facility_id === f.id);
  const asset = (id: string) => graph.assets[id];
  const state = (id: string) =>
    equipmentState(asset(id), f, incident, data.limits);
  const active = f.pump_status === 1 && f.flow_bpd != null && f.flow_bpd > 0;
  const connectors = useMemo(
    () => ({
      tankPump: [
        [1.8, 0.65, 0],
        [2.5, 0.65, 0],
        [3, 0.85, 0],
      ] as [number, number, number][],
      pumpPipe: [
        [3.7, 1.72, 0],
        [3.7, 1.95, 0],
        [6.3, 1.95, 0],
        [6.8, 0.65, 0],
        [9.5, 0.65, 0],
      ] as [number, number, number][],
    }),
    [],
  );
  const assemblyProps = (id: string) => ({
    asset: asset(id),
    selected: selection?.assetId === id,
    onSelect: interactions.onSelect,
    onFocus: interactions.onFocus,
  });
  function sensors(id: string, positions: [number, number, number][]) {
    if (!detailed) return null;
    return asset(id).metrics.map((metric, i) => (
      <SensorMarker
        key={metric}
        assetId={id}
        metric={metric}
        position={positions[i] || [0, 2, 0]}
        selected={selection?.assetId === id && selection.metric === metric}
        onSelect={interactions.onSelect}
      />
    ));
  }
  return (
    <group position={layout.position}>
      <mesh position={[0, -0.1, 0]} receiveShadow>
        <boxGeometry args={[layout.width, 0.18, layout.depth]} />
        <meshStandardMaterial
          color={detailed ? "#192f3c" : "#15232e"}
          metalness={0.15}
          roughness={0.9}
        />
      </mesh>
      {navigation.systemId === f.system_id && (
        <Html
          center
          position={[0, 0.35, layout.depth / 2 - 0.5]}
          zIndexRange={[10, 0]}
        >
          <button
            className={"facility-tag " + (incident ? "has-incident" : "")}
            onClick={() =>
              interactions.onNavigate({
                systemId: f.system_id,
                facilityId: f.id,
              })
            }
          >
            <i
              style={{
                background: incident
                  ? incident.category === "pump_degradation"
                    ? colors.warning
                    : colors.fault
                  : colors.healthy,
              }}
            />
            {f.id.replace(`${f.system_id}_FACILITY_`, "FACILITY ")}
            <span>↗</span>
          </button>
        </Html>
      )}
      {layout.wellPositions.map((p, i) => {
        const well = f.wells[i];
        return (
          <group key={well.id}>
            <PipelineModel
              points={[
                [p[0] + 0.9, 0.4, p[2]],
                [-4.5, 0.4, p[2]],
                [-4, 0.65, 0],
                [-1.9, 0.65, 0],
              ]}
            />
            <AssetAssembly
              {...assemblyProps(well.id)}
              position={p}
              ringRadius={1}
              label="WELLHEAD"
              showLabel={false}
            >
              <WellModel />
              {sensors(well.id, [
                [0, 2.1, 0.35],
                [0, 2.65, 0.35],
              ])}
            </AssetAssembly>
          </group>
        );
      })}
      <AssetAssembly
        {...assemblyProps(f.tank.id)}
        position={[0, 0, 0]}
        ringRadius={2.2}
        label={`TANK · ${formatValue(f.level_pct)}%`}
      >
        <TankModel
          level={f.level_pct}
          warning={data.limits.warning}
          shutdown={data.limits.shutdown}
          color={state(f.tank.id).color}
        />
        {sensors(f.tank.id, [[0.4, 3.7, 1.6]])}
        {detailed && (
          <Html
            position={[2.85, 1.8, 0.5]}
            center
            zIndexRange={[10, 0]}
            style={{ pointerEvents: "none" }}
          >
            <div className="gauge-label">
              <b>{formatValue(f.level_pct)}%</b>
              <small>
                <i className="warning-dot" />
                {data.limits.warning}% WARN
              </small>
              <small>
                <i className="fault-dot" />
                {data.limits.shutdown}% STOP
              </small>
            </div>
          </Html>
        )}
      </AssetAssembly>
      <PipelineModel points={connectors.tankPump} active={active} />
      <AssetAssembly
        {...assemblyProps(f.pump.id)}
        position={[4.5, 0, 0]}
        ringRadius={1.8}
        label="PUMP"
      >
        <PumpModel
          color={state(f.pump.id).color}
          fault={incident?.category === "pump_failure"}
        />
        {sensors(f.pump.id, [
          [0.3, 2, 0.6],
          [0.3, 2.6, 0.6],
          [0.3, 3.2, 0.6],
        ])}
        {incident && incident.category !== "pipeline_leak" && (
          <Html position={[0, 2.05, -0.7]} center zIndexRange={[12, 0]}>
            <button
              className={
                "fault-marker " +
                (incident.category === "pump_degradation" ? "amber" : "")
              }
              onClick={() => interactions.onSelect({ assetId: f.pump.id })}
            >
              !{" "}
              <span>
                {incident.category === "pump_failure"
                  ? "PUMP FAULT"
                  : "DEGRADATION"}
              </span>
            </button>
          </Html>
        )}
      </AssetAssembly>
      <AssetAssembly
        {...assemblyProps(f.pipeline.id)}
        position={[0, 0, 0]}
        anchor={[8, 0, 0]}
        ringRadius={1.2}
        label="PIPELINE"
        showLabel={false}
      >
        <PipelineModel
          points={connectors.pumpPipe}
          active={active}
          fault={incident?.category === "pipeline_leak"}
        />
        {sensors(f.pipeline.id, [
          [8.5, 1.3, 0.5],
          [8.5, 1.9, 0.5],
        ])}
        {selection?.assetId === f.pipeline.id && (
          <group position={[8, 0, 0]}>
            <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.1, 0]}>
              <ringGeometry args={[1.1, 1.14, 48]} />
              <meshBasicMaterial color={colors.selected} />
            </mesh>
          </group>
        )}
        {incident?.category === "pipeline_leak" && (
          <Html position={[8, 1.5, -0.5]} center zIndexRange={[12, 0]}>
            <button
              className="fault-marker"
              onClick={() => interactions.onSelect({ assetId: f.pipeline.id })}
            >
              ! <span>PIPELINE LEAK</span>
            </button>
          </Html>
        )}
      </AssetAssembly>
    </group>
  );
}
