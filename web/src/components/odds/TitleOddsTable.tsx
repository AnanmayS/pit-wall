import { formatPct } from "@/lib/format";
import type { OddsEntry } from "@/lib/types";

export function TitleOddsTable({
  title,
  raceWin,
  teams,
  nameOf,
  nextRace,
}: {
  title: OddsEntry[];
  raceWin: OddsEntry[];
  /** driver code -> team name, when known. */
  teams: Map<string, string>;
  /** driver code -> full name. */
  nameOf: (code: string) => string;
  /** Name of the next race, e.g. "Singapore Grand Prix". */
  nextRace: string | null;
}) {
  const winByDriver = new Map(raceWin.filter((e) => e.driver).map((e) => [e.driver as string, e.probability]));
  const rows = title.filter((e) => e.driver);
  if (rows.length === 0) return <p className="text-sm text-muted">No drivers&apos; title odds in this forecast.</p>;

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <table className="tabular w-full min-w-[28rem] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="px-3 py-2 font-medium">#</th>
            <th className="px-3 py-2 font-medium">Driver</th>
            <th className="px-3 py-2 font-medium">Team</th>
            <th className="px-3 py-2 text-right font-medium">P(title)</th>
            <th className="px-3 py-2 text-right font-medium">
              P(win {nextRace ?? "next race"})
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e, i) => {
            const driver = e.driver as string;
            return (
              <tr key={driver} className="border-b border-border/60 last:border-0">
                <td className="px-3 py-1.5 text-muted">{i + 1}</td>
                <td className="px-3 py-1.5 font-medium">{e.driver_name || nameOf(driver)}</td>
                <td className="px-3 py-1.5 text-muted">{teams.get(driver) ?? ""}</td>
                <td className="px-3 py-1.5 text-right">
                  <ProbabilityCell p={e.probability} />
                </td>
                <td className="px-3 py-1.5 text-right">{formatPct(winByDriver.get(driver))}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Percentage with a thin bar behind it, so the table reads at a glance. */
export function ProbabilityCell({ p }: { p: number }) {
  const width = Math.max(0, Math.min(1, p)) * 100;
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-surface-2 sm:inline-block" aria-hidden>
        <span className="block h-full rounded-full bg-accent/80" style={{ width: `${width}%` }} />
      </span>
      <span className="w-14">{formatPct(p)}</span>
    </span>
  );
}
