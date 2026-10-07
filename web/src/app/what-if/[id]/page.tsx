import type { Metadata } from "next";
import ScenarioDetailClient from "@/components/whatif/ScenarioDetailClient";

export const metadata: Metadata = { title: "What-If Scenario" };

export default async function WhatIfScenarioPage(props: PageProps<"/what-if/[id]">) {
  const { id } = await props.params;
  return <ScenarioDetailClient id={id} />;
}
