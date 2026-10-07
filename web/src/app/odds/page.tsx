import type { Metadata } from "next";
import { Placeholder } from "@/components/Placeholder";

export const metadata: Metadata = { title: "Odds" };

export default function OddsPage() {
  return (
    <Placeholder
      title="Race Odds"
      milestone={3}
      blurb="Simulation-driven win, podium, and points probabilities for upcoming sessions."
    />
  );
}
