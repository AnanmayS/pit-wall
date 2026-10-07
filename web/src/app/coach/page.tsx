import type { Metadata } from "next";
import CoachClient from "@/components/coach/CoachClient";

export const metadata: Metadata = { title: "Telemetry Coach" };

export default function CoachPage() {
  return <CoachClient />;
}
