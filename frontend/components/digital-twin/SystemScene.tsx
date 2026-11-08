"use client";
import { AssetLabel as Html } from "./AssetLabel";
import { useMemo } from "react";
import type { Dashboard, Navigation, Selection, Vec3 } from "../../lib/types";
import type { SceneGraph, SystemLayout } from "../../lib/scene-layout";
import FacilityScene, { type SceneInteractions } from "./FacilityScene";
import {
  AssetAssembly,
  Box,
  DisposalModel,
  PipelineModel,
  TruckModel,
} from "./Equipment";
import { colors } from "../../lib/operational-status";

export default function SystemScene({
  layout,
  graph,
  data,
  navigation,
  selection,
  interactions,
}: {
  layout: SystemLayout;
  graph: SceneGraph;
  data: Dashboard;
  navigation: Navigation;
  selection: Selection | null;
  interactions: SceneInteractions;
}) {
  const incidents = data.alerts.filter((a) => a.system_id === layout.system.id);
  const affected = new Set(incidents.map((a) => a.facility_id)).size;
  const routes = useMemo(
    () =>
      layout.facilities.map((f) => {
        const [x, , z] = f.position;
        const channel = layout.width / 2 - 2;
        return [
          [x + 9.5, 0.65, z],
          [x + 11, 0.65, z],
          [x + 11, 0.65, z - f.depth / 2 - 1],
          [channel, 0.65, z - f.depth / 2 - 1],
          [channel, 0.65, layout.disposal[2] + 1.7],
          [layout.disposal[0] - 3.5, 0.65, layout.disposal[2] + 1.7],
        ] as Vec3[];
      }),
    [layout],
  );
  return (
    <group position={layout.position}>
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, -0.23, 0]}
        receiveShadow
      >
        <planeGeometry args={[layout.width, layout.depth]} />
        <meshStandardMaterial
          color="#101d28"
          roughness={0.95}
          metalness={0.12}
        />
      </mesh>
      {[-1, 1].map((side) => (
        <Box
          key={side}
          position={[(side * layout.width) / 2, -0.16, 0]}
          size={[0.07, 0.06, layout.depth]}
        />
      ))}
      {[-1, 1].map((side) => (
        <Box
          key={side}
          position={[0, -0.16, (side * layout.depth) / 2]}
          size={[layout.width, 0.06, 0.07]}
        />
      ))}
      <Html
        center
        position={[0, 0.5, layout.depth / 2 + 1.5]}
        zIndexRange={[10, 0]}
      >
        <button
          className={
            "system-tag " +
            (navigation.systemId === layout.system.id ? "selected" : "")
          }
          onClick={() =>
            interactions.onNavigate({ systemId: layout.system.id })
          }
        >
          <span className="system-tag-icon">{layout.system.id}</span>
          <span>
            <b>SYSTEM {layout.system.id}</b>
            <small>
              {layout.facilities.length} facilities ·{" "}
              {affected ? `${affected} affected` : "No active incidents"}
            </small>
          </span>
          <i style={{ background: affected ? colors.fault : colors.healthy }} />
          <span className="tag-arrow">↗</span>
        </button>
      </Html>
      {layout.facilities.map((f, i) => {
        const pipe = graph.assets[f.facility.pipeline.id];
        return (
          <group key={f.facility.id}>
            <group
              onClick={(e) => {
                e.stopPropagation();
                if (e.delta <= 5) interactions.onSelect({ assetId: pipe.id });
              }}
              onDoubleClick={(e) => {
                e.stopPropagation();
                interactions.onFocus(pipe);
              }}
            >
              <PipelineModel
                points={routes[i]}
                active={
                  f.facility.pump_status === 1 && (f.facility.flow_bpd ?? 0) > 0
                }
                fault={f.facility.category === "pipeline_leak"}
              />
            </group>
            <FacilityScene
              layout={f}
              graph={graph}
              data={data}
              navigation={navigation}
              selection={selection}
              interactions={interactions}
            />
          </group>
        );
      })}
      <AssetAssembly
        asset={graph.assets[layout.system.disposal_site.id]}
        position={layout.disposal}
        selected={selection?.assetId === layout.system.disposal_site.id}
        onSelect={interactions.onSelect}
        onFocus={interactions.onFocus}
        label="SHARED DISPOSAL"
        showLabel={navigation.systemId === layout.system.id}
        ringRadius={4}
      >
        <DisposalModel />
      </AssetAssembly>
      <AssetAssembly
        asset={graph.assets[`${layout.system.id}:truck-yard`]}
        position={layout.yard}
        selected={selection?.assetId === `${layout.system.id}:truck-yard`}
        onSelect={interactions.onSelect}
        onFocus={interactions.onFocus}
        label="FLEET AREA · SYMBOLIC"
        showLabel={navigation.systemId === layout.system.id}
        ringRadius={4}
      >
        <Box position={[0, 0.04, 0]} size={[8, 0.08, 5]} />
        <TruckModel />
        {[-2, 2].map((z) => (
          <Box key={z} position={[0, 0.1, z]} size={[7.5, 0.02, 0.04]} />
        ))}
      </AssetAssembly>
    </group>
  );
}
