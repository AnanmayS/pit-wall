import { formatPct } from "@/lib/whatif";
import type { DriverOutcome } from "@/lib/types";

export function SummaryTable({ rows, highlight }: { rows: DriverOutcome[]; highlight: Set<string> }) {
  const sorted = [...rows].sort((a, b) => a.expected_position - b.expected_position);
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <table className="tabular w-full min-w-[34rem] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="px-3 py-2 font-medium">#</th>
            <th className="px-3 py-2 font-medium">Driver</th>
            <th className="px-3 py-2 text-right font-medium">P(win)</th>
            <th className="px-3 py-2 text-right font-medium">P(podium)</th>
            <th className="px-3 py-2 text-right font-medium">P(points)</th>
            <th className="px-3 py-2 text-right font-medium">P(DNF)</th>
            <th className="px-3 py-2 text-right font-medium">Expected pos.</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const changed = highlight.has(r.driver);
            return (
              <tr
                key={r.driver}
                className={`border-b border-border/60 last:border-0 ${changed ? "bg-accent/10" : ""}`}
              >
                <td className="px-3 py-1.5 text-muted">{i + 1}</td>
                <td className="px-3 py-1.5 font-mono font-medium">
                  {r.driver}
                  {changed && <span className="ml-2 font-sans text-xs text-accent">changed</span>}
                </td>
                <td className="px-3 py-1.5 text-right">{formatPct(r.p_win)}</td>
                <td className="px-3 py-1.5 text-right">{formatPct(r.p_podium)}</td>
                <td className="px-3 py-1.5 text-right">{formatPct(r.p_points)}</td>
                <td className="px-3 py-1.5 text-right">{formatPct(r.p_dnf)}</td>
                <td className="px-3 py-1.5 text-right">P{r.expected_position.toFixed(1)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
