import { deltaTone, formatDelta } from "@/lib/format";
import type { CompareInsight } from "@/lib/types";

export function InsightList({ insights }: { insights: CompareInsight[] }) {
  if (insights.length === 0) {
    return <p className="text-sm text-muted">No notable differences found.</p>;
  }
  return (
    <ul className="space-y-2">
      {insights.map((ins, i) => (
        <li
          key={`${ins.kind}-${ins.corner ?? "lap"}-${i}`}
          className="flex gap-3 rounded-lg border border-border bg-surface px-4 py-3 text-sm"
        >
          <span className="mt-0.5 shrink-0 rounded bg-surface-2 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted">
            {ins.kind.replace(/_/g, " ")}
          </span>
          <span className="flex-1">{ins.text}</span>
          {ins.delta_ms != null && (
            <span className={`tabular shrink-0 ${deltaTone(ins.delta_ms)}`}>{formatDelta(ins.delta_ms)}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
