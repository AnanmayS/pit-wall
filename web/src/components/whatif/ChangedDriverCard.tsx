import { formatPct } from "@/lib/whatif";
import type { ChangedDriverOutcome } from "@/lib/types";
import { PositionChart } from "./PositionChart";

export function changedDriverHeadline(d: ChangedDriverOutcome, name: string = d.driver_name || d.driver): string {
  const expected = `expected P${d.expected_position.toFixed(1)}`;
  if (d.actual_position == null) {
    return `${name} was not classified in the actual race; in this scenario ${expected}`;
  }
  const odds: string[] = [];
  if (d.p_better_than_actual != null) odds.push(`${formatPct(d.p_better_than_actual, 0)} better than actual`);
  if (d.p_worse_than_actual != null) odds.push(`${formatPct(d.p_worse_than_actual, 0)} worse`);
  const tail = odds.length > 0 ? ` — ${odds.join(", ")}` : "";
  return `${name} actually finished P${d.actual_position}; in this scenario ${expected}${tail}`;
}

export function ChangedDriverCard({ outcome, name }: { outcome: ChangedDriverOutcome; name: string }) {
  const shift =
    outcome.actual_position == null ? null : outcome.expected_position - outcome.actual_position;
  const tone =
    shift == null || Math.abs(shift) < 0.25 ? "text-foreground" : shift < 0 ? "text-emerald-300" : "text-red-300";

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-lg font-semibold">{name}</span>
        <span className={`tabular text-sm ${tone}`}>
          {shift == null ? "" : `${shift > 0 ? "+" : ""}${shift.toFixed(1)} places vs actual`}
        </span>
      </div>
      <p className="mt-1 text-sm text-muted">{changedDriverHeadline(outcome, name)}</p>
      <div className="mt-3">
        <PositionChart probs={outcome.position_probs} actualPosition={outcome.actual_position} />
      </div>
      <p className="mt-1 text-xs text-muted">
        Finishing-position probability.{" "}
        {outcome.actual_position != null && (
          <>
            <span className="text-driver-b">Amber</span> marks the actual result.
          </>
        )}
      </p>
    </div>
  );
}
