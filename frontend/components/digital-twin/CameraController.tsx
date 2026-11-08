"use client";
import { useEffect, useRef } from "react";
import { CameraControls } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import type { CameraIntent } from "../../lib/types";

/** Intent is the sole camera interface, so future input devices can issue the same commands. */
export default function CameraController({
  intent,
  sceneRadius,
}: {
  intent: CameraIntent;
  sceneRadius: number;
}) {
  const controls = useRef<CameraControls>(null);
  const { size } = useThree();
  const initialized = useRef(false);
  useEffect(() => {
    const c = controls.current;
    if (!c) return;
    const aspect = size.width / Math.max(size.height, 1);
    const halfFov = (42 * Math.PI) / 360;
    const limitingFov = Math.min(
      halfFov,
      Math.atan(Math.tan(halfFov) * aspect),
    );
    const distance = intent.radius / Math.sin(limitingFov);
    const [x, y, z] = intent.target;
    // Keep an isometric approach while fitting the limiting viewport dimension.
    void c.setLookAt(
      x + distance * 0.55,
      y + distance * 0.64,
      z + distance * 0.55,
      x,
      y,
      z,
      initialized.current,
    );
    initialized.current = true;
  }, [intent, size.width, size.height]);
  return (
    <CameraControls
      ref={controls}
      makeDefault
      smoothTime={0.65}
      draggingSmoothTime={0.14}
      minDistance={3}
      maxDistance={Math.max(250, sceneRadius * 7)}
      minPolarAngle={0.16}
      maxPolarAngle={Math.PI / 2 - 0.04}
      dollySpeed={0.8}
      truckSpeed={1.2}
      infinityDolly={false}
    />
  );
}
