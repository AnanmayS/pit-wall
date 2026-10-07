import type { Metadata } from "next";
import { Placeholder } from "@/components/Placeholder";

export const metadata: Metadata = { title: "What-If" };

export default function WhatIfPage() {
  return (
    <Placeholder
      title="What-If Strategy Simulator"
      milestone={2}
      blurb="Replay a race with a different pit window, tyre choice, or safety car timing and see how the result changes."
    />
  );
}
