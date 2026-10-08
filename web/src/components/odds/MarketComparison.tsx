import { formatPct } from "@/lib/format";

/** Probabilities keyed by driver code (or team name). */
export type ProbabilityMap = Record<string, number>;

export interface MarketComparisonProps {
  /** Our model's probabilities. */
  ours: ProbabilityMap;
  /** Prediction-market implied probabilities; empty until the market feed is wired up. */
  market: ProbabilityMap;
  /** Shown in the heading, e.g. "Polymarket". */
  marketName?: string;
  /** Display name for a key, e.g. "NOR" -> "Lando Norris". */
  nameOf?: (key: string) => string;
}

/**
 * "vs market" panel: our odds next to prediction-market odds.
 * Renders nothing until `market` has entries, so it can be mounted now and wired up later.
 */
export function MarketComparison({ ours, market, marketName = "market", nameOf }: MarketComparisonProps) {
  const names = Object.keys(market);
  if (names.length === 0) return null;

  const rows = names
    .map((name) => ({ name, ours: ours[name] ?? null, market: market[name] }))
    .sort((a, b) => (b.ours ?? 0) - (a.ours ?? 0));

  return (
    <section className="space-y-3">
      <h2 className="text-xs font-medium uppercase tracking-widest text-muted">vs {marketName}</h2>
      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <table className="tabular w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 text-right font-medium">Model</th>
              <th className="px-3 py-2 text-right font-medium">{marketName}</th>
              <th className="px-3 py-2 text-right font-medium">Difference</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const edge = r.ours == null ? null : r.ours - r.market;
              return (
                <tr key={r.name} className="border-b border-border/60 last:border-0">
                  <td className="px-3 py-1.5 font-medium">{nameOf ? nameOf(r.name) : r.name}</td>
                  <td className="px-3 py-1.5 text-right">{formatPct(r.ours)}</td>
                  <td className="px-3 py-1.5 text-right">{formatPct(r.market)}</td>
                  <td
                    className={`px-3 py-1.5 text-right ${
                      edge == null || Math.abs(edge) < 0.005 ? "text-muted" : edge > 0 ? "text-emerald-300" : "text-red-300"
                    }`}
                  >
                    {edge == null ? "-" : `${edge > 0 ? "+" : ""}${(edge * 100).toFixed(1)} pts`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
