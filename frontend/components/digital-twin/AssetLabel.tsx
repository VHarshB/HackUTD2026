"use client";
import {
  createContext,
  useContext,
  type RefObject,
  type ComponentProps,
} from "react";
import { Html } from "@react-three/drei";

// Keep all projected labels in one stable DOM layer, independent of Canvas event targets.
export const LabelPortal = createContext<RefObject<HTMLElement> | undefined>(
  undefined,
);
export function AssetLabel(props: ComponentProps<typeof Html>) {
  const portal = useContext(LabelPortal);
  return <Html {...props} portal={portal} />;
}
