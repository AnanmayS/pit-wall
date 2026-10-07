import type { Metadata } from "next";
import WhatIfClient from "@/components/whatif/WhatIfClient";

export const metadata: Metadata = { title: "What-If" };

export default function WhatIfPage() {
  return <WhatIfClient />;
}
