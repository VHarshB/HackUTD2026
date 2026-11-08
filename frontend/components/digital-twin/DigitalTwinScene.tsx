"use client";
import { Component, useEffect, useRef, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { Environment, Grid, Lightformer } from "@react-three/drei";
import * as THREE from "three";
import type {
  CameraIntent,
  Dashboard,
  Navigation,
  Selection,
} from "../../lib/types";
import type { SceneGraph } from "../../lib/scene-layout";
import type { SceneInteractions } from "./FacilityScene";
import CameraController from "./CameraController";
import { LabelPortal } from "./AssetLabel";
import SystemScene from "./SystemScene";

function Unavailable({ message }: { message?: string }) {
  return (
    <div className="scene-unavailable">
      <span className="technical-label">RENDERER UNAVAILABLE</span>
      <h2>3D view needs WebGL.</h2>
      <p>
        {message ||
          "Enable hardware acceleration or use a WebGL-capable browser. Incident details, telemetry and replay remain available."}
      </p>
      <button className="ui-button" onClick={() => window.dispatchEvent(new Event("nightshift:retry-renderer"))}>
        Retry 3D view
      </button>
    </div>
  );
}
class SceneBoundary extends Component<
  { children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? <Unavailable /> : this.props.children;
  }
}
function ContextMonitor({
  onLost,
  topology,
}: {
  onLost: (lost: boolean) => void;
  topology: string;
}) {
  const gl = useThree((s) => s.gl);
  useEffect(() => {
    // Equipment is stationary: reuse its shadow map while flow markers animate.
    gl.shadowMap.autoUpdate = false;
    gl.shadowMap.needsUpdate = true;
  }, [gl, topology]);
  useEffect(() => {
    const lost = (event: Event) => {
      event.preventDefault();
      onLost(true);
    };
    const restored = () => onLost(false);
    gl.domElement.addEventListener("webglcontextlost", lost);
    gl.domElement.addEventListener("webglcontextrestored", restored);
    return () => {
      gl.domElement.removeEventListener("webglcontextlost", lost);
      gl.domElement.removeEventListener("webglcontextrestored", restored);
    };
  }, [gl, onLost]);
  return null;
}

export default function DigitalTwinScene({
  graph,
  data,
  navigation,
  selection,
  intent,
  interactions,
}: {
  graph: SceneGraph;
  data: Dashboard;
  navigation: Navigation;
  selection: Selection | null;
  intent: CameraIntent;
  interactions: SceneInteractions;
}) {
  const [contextLost, setContextLost] = useState(false);
  const [rendererKey, setRendererKey] = useState(0);
  useEffect(() => {
    const retry = () => { setContextLost(false); setRendererKey(key => key + 1); };
    window.addEventListener("nightshift:retry-renderer", retry);
    return () => window.removeEventListener("nightshift:retry-renderer", retry);
  }, []);
  const labelPortal = useRef<HTMLDivElement>(null!);
  return (
    <SceneBoundary key={rendererKey}>
      <div
        className="webgl-surface"
        aria-label="Interactive oilfield digital twin. Drag to orbit, scroll to zoom, right-drag to pan."
      >
        <Canvas
          shadows="percentage"
          dpr={[1, 1.5]}
          camera={{
            position: [110, 130, 110],
            fov: 42,
            near: 0.2,
            far: Math.max(2500, graph.radius * 15),
          }}
          gl={{
            antialias: true,
            alpha: false,
            powerPreference: "high-performance",
            toneMapping: THREE.ACESFilmicToneMapping,
          }}
          fallback={<Unavailable />}
        >
          <LabelPortal.Provider value={labelPortal}>
            <color attach="background" args={["#080d14"]} />
            <fog
              attach="fog"
              args={["#080d14", graph.radius * 3, graph.radius * 8]}
            />
            <ambientLight intensity={0.6} />
            <hemisphereLight args={["#a7c7da", "#172329", 1.1]} />
            <directionalLight
              position={[30, 70, 35]}
              intensity={2.8}
              color="#dbe7ed"
              castShadow
              shadow-mapSize={[2048, 2048]}
              shadow-camera-left={-graph.radius}
              shadow-camera-right={graph.radius}
              shadow-camera-top={graph.radius}
              shadow-camera-bottom={-graph.radius}
              shadow-camera-far={700}
              shadow-normalBias={0.08}
            />
            <directionalLight
              position={[-50, 25, -30]}
              intensity={1.7}
              color="#5f96b6"
            />
            <Environment resolution={64} frames={1}>
              <Lightformer
                form="rect"
                intensity={2.2}
                position={[0, 20, 0]}
                scale={[40, 40, 1]}
                rotation={[Math.PI / 2, 0, 0]}
                color="#d1e5ef"
              />
              <Lightformer
                form="rect"
                intensity={1.2}
                position={[-20, 5, 0]}
                scale={[10, 30, 1]}
                rotation={[0, Math.PI / 2, 0]}
                color="#75a9bc"
              />
            </Environment>
            <Grid
              position={[0, -0.3, 0]}
              args={[graph.radius * 5, graph.radius * 5]}
              cellSize={4}
              sectionSize={20}
              cellColor="#1a2b39"
              sectionColor="#263d4c"
              cellThickness={0.45}
              sectionThickness={0.65}
              fadeDistance={graph.radius * 5}
              fadeStrength={1.3}
              infiniteGrid
            />
            <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.32, 0]}>
              <planeGeometry args={[graph.radius * 12, graph.radius * 12]} />
              <meshBasicMaterial color="#080d14" />
            </mesh>
            {graph.systems.map((system) => (
              <SystemScene
                key={system.system.id}
                layout={system}
                graph={graph}
                data={data}
                navigation={navigation}
                selection={selection}
                interactions={interactions}
              />
            ))}
            <CameraController intent={intent} sceneRadius={graph.radius} />
            <ContextMonitor
              onLost={setContextLost}
              topology={graph.systems
                .map(
                  (s) =>
                    `${s.system.id}:${s.facilities.map((f) => `${f.facility.id}:${f.facility.wells.length}`).join(",")}`,
                )
                .join("|")}
            />
          </LabelPortal.Provider>
        </Canvas>
        <div className="scene-labels" ref={labelPortal} />
        {contextLost && (
          <Unavailable message="The graphics context was lost. It may recover automatically; reload if the scene does not return." />
        )}
      </div>
    </SceneBoundary>
  );
}
