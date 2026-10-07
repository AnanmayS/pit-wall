import type { Metadata } from "next";
import AskClient from "@/components/ask/AskClient";

export const metadata: Metadata = { title: "Ask the Pit Wall" };

export default function AskPage() {
  return <AskClient />;
}
