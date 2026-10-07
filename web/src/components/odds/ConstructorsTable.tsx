import type { OddsEntry } from "@/lib/types";
import { ProbabilityCell } from "./TitleOddsTable";

export function ConstructorsTable({ rows }: { rows: OddsEntry[] }) {
  const teams = rows.filter((e) => e.team);
  if (teams.length === 0) return <p className="text-sm text-muted">No constructors&apos; odds in this forecast.</p>;
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <table className="tabular w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="px-3 py-2 font-medium">#</th>
            <th className="px-3 py-2 font-medium">Team</th>
            <th className="px-3 py-2 text-right font-medium">P(title)</th>
          </tr>
        </thead>
        <tbody>
          {teams.map((e, i) => (
            <tr key={e.team} className="border-b border-border/60 last:border-0">
              <td className="px-3 py-1.5 text-muted">{i + 1}</td>
              <td className="px-3 py-1.5 font-medium">{e.team}</td>
              <td className="px-3 py-1.5 text-right">
                <ProbabilityCell p={e.probability} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
