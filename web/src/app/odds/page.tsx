import type { Metadata } from "next";
import OddsClient from "@/components/odds/OddsClient";

export const metadata: Metadata = { title: "Title Odds" };

export default function OddsPage() {
  return <OddsClient />;
}
