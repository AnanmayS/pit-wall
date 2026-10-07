import { describeSpec } from "@/lib/whatif";
import type { ScenarioSpec } from "@/lib/types";

export function SpecSummary({ spec }: { spec: ScenarioSpec }) {
  const lines = describeSpec(spec);
  if (lines.length === 0) return <p className="text-sm text-muted">No changes (baseline replay).</p>;
  return (
    <ul className="space-y-1 text-sm">
      {lines.map((line, i) => (
        <li key={i} className="flex gap-2">
          <span className="text-accent" aria-hidden>
            &bull;
          </span>
          {line}
        </li>
      ))}
    </ul>
  );
}
