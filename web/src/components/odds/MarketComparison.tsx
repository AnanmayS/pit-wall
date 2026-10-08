"use client";

import { useState } from "react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Section } from "@/components/Field";
import { Spinner } from "@/components/Notice";
import { paths } from "@/lib/api";
import type { DriverMap } from "@/lib/drivers";
import { formatPct, formatTimestamp } from "@/lib/format";
import type { MarketComparisonRow, OddsMarket } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { MarketHistoryChart } from "./MarketHistoryChart";

const TOP_ROWS = 10;
/** Differences smaller than this (1 percentage point) read as agreement. */
const AGREE_WITHIN = 0.01;
const DEFAULT_MARKET = "Polymarket";

export interface MarketComparisonProps {
  season: number;
  /** Bump to refetch (shared with the page's retry). */
  reload?: number;
  /** Driver code -> full name, the fallback when a row lacks one. */
  nameOf: (code: string) => string;
  /** Season driver list, for chart legend surnames. */
  drivers?: DriverMap;
  /** The next race's name from the forecast, used when the market payload lacks one. */
  nextRace?: string | null;
}

/**
 * "Ours vs Polymarket": our title and next-race odds next to the market's, plus the market's title
 * odds over time with our forecasts overlaid. Renders nothing when the API has neither (404).
 */
export function MarketComparison({ season, reload = 0, nameOf, drivers, nextRace }: MarketComparisonProps) {
  const [nonce, setNonce] = useState(0);
  const market = useApi<OddsMarket>(paths.oddsMarket(season), reload + nonce);
  const data = market.data;
  const marketName = data?.market_name || DEFAULT_MARKET;
  const heading = `Ours vs ${marketName}`;

  if (market.error?.isNotFound) return null;
  if (market.loading) {
    return (
      <Section title={heading}>
        <div className="rounded-xl border border-border bg-surface px-4 py-12 text-center">
          <Spinner label={`Loading ${marketName} odds...`} />
        </div>
      </Section>
    );
  }
  if (market.error) {
    return (
      <Section title={heading}>
        <ErrorBanner
          title={`Could not load ${marketName} odds`}
          error={market.error}
          onRetry={() => setNonce((n) => n + 1)}
        />
      </Section>
    );
  }
  if (!data) return null;

  const rowName = (r: MarketComparisonRow) => r.driver_name || nameOf(r.driver);
  const titleRows = data.title?.rows ?? [];
  const raceRows = data.next_race?.rows ?? [];
  const raceName = data.next_race?.event_name || nextRace || "next race";
  const reading = describeBiggestGap(titleRows, rowName, marketName);
  const hasHistory = (data.history?.market?.length ?? 0) > 0 || (data.history?.ours?.length ?? 0) > 0;

  return (
    <Section title={heading}>
      <div className={`grid gap-6 ${raceRows.length > 0 ? "lg:grid-cols-2" : ""}`}>
        <ComparisonTable
          title="Drivers' title"
          rows={titleRows}
          rowName={rowName}
          marketName={marketName}
          oursAsOf={data.forecast_as_of}
          marketAsOf={data.title?.market_as_of ?? null}
        />
        {raceRows.length > 0 && (
          <ComparisonTable
            title={`P(win ${raceName})`}
            rows={raceRows}
            rowName={rowName}
            marketName={marketName}
            oursAsOf={data.forecast_as_of}
            marketAsOf={data.next_race?.market_as_of ?? null}
          />
        )}
      </div>

      {hasHistory && (
        <div className="space-y-3 rounded-xl border border-border bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-medium">Title probability over time</h3>
            <p className="flex items-center gap-4 text-xs text-muted">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-0.5 w-4 rounded bg-muted" aria-hidden />
                {marketName}, daily
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-muted" aria-hidden />
                Our forecast
              </span>
            </p>
          </div>
          <MarketHistoryChart history={data.history} marketName={marketName} drivers={drivers} />
          {reading && <p className="text-sm text-muted">{reading}</p>}
        </div>
      )}
      {!hasHistory && reading && <p className="text-sm text-muted">{reading}</p>}
    </Section>
  );
}

/** The driver with the largest |ours - market| among those both sources price. */
function describeBiggestGap(
  rows: MarketComparisonRow[],
  rowName: (r: MarketComparisonRow) => string,
  marketName: string,
): string | null {
  let best: MarketComparisonRow | null = null;
  for (const r of rows) {
    if (r.diff == null || !Number.isFinite(r.diff)) continue;
    if (!best || Math.abs(r.diff) > Math.abs(best.diff as number)) best = r;
  }
  if (!best || best.diff == null) return null;
  if (Math.abs(best.diff) < AGREE_WITHIN) {
    return `Our title odds and ${marketName}'s agree within 1 pt for every driver both price.`;
  }
  const pts = (Math.abs(best.diff) * 100).toFixed(1);
  const direction = best.diff > 0 ? "higher" : "lower";
  return `Our forecast is ${pts} pts ${direction} than the market on ${rowName(best)} (${formatPct(best.ours)} vs ${formatPct(best.market)}), the biggest gap in the title race.`;
}

function ComparisonTable({
  title,
  rows,
  rowName,
  marketName,
  oursAsOf,
  marketAsOf,
}: {
  title: string;
  rows: MarketComparisonRow[];
  rowName: (r: MarketComparisonRow) => string;
  marketName: string;
  oursAsOf: string | null;
  marketAsOf: string | null;
}) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? rows : rows.slice(0, TOP_ROWS);
  const hidden = rows.length - TOP_ROWS;

  return (
    <div className="min-w-0 rounded-xl border border-border bg-surface">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border px-3 py-2.5">
        <h3 className="text-sm font-medium">{title}</h3>
        <p className="text-xs text-muted">
          Ours as of {oursAsOf ? formatTimestamp(oursAsOf) : "-"} · {marketName} as of{" "}
          {marketAsOf ? formatTimestamp(marketAsOf) : "-"}
        </p>
      </div>
      {rows.length === 0 ? (
        <p className="px-3 py-6 text-center text-sm text-muted">No odds from either source yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="tabular w-full min-w-[30rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted">
                <th className="px-3 py-2 font-medium">Driver</th>
                <th className="px-3 py-2 text-right font-medium">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-sm bg-accent/80" aria-hidden />
                    Ours
                  </span>
                </th>
                <th className="px-3 py-2 text-right font-medium">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-sm bg-driver-a/80" aria-hidden />
                    {marketName}
                  </span>
                </th>
                <th className="px-3 py-2 text-right font-medium">Difference</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.driver} className="border-b border-border/60 last:border-0">
                  <td className="px-3 py-1.5 font-medium">{rowName(r)}</td>
                  <td className="px-3 py-1.5 text-right">
                    <BarCell p={r.ours} barClass="bg-accent/80" />
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <BarCell
                      p={r.market}
                      barClass="bg-driver-a/80"
                      title={r.market_raw != null ? `Raw price ${formatPct(r.market_raw)}` : undefined}
                    />
                  </td>
                  <td className={`px-3 py-1.5 text-right ${diffTone(r.diff)}`}>{formatPts(r.diff)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {hidden > 0 && (
        <div className="border-t border-border px-3 py-2 text-right">
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="text-xs text-muted transition-colors hover:text-foreground"
            aria-expanded={showAll}
          >
            {showAll ? `Show top ${TOP_ROWS}` : `Show all ${rows.length}`}
          </button>
        </div>
      )}
    </div>
  );
}

/** Percentage with a thin bar beside it. */
function BarCell({ p, barClass, title }: { p: number | null; barClass: string; title?: string }) {
  const width = p == null ? 0 : Math.max(0, Math.min(1, p)) * 100;
  return (
    <span className="inline-flex items-center justify-end gap-2" title={title}>
      <span className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-surface-2 sm:inline-block" aria-hidden>
        <span className={`block h-full rounded-full ${barClass}`} style={{ width: `${width}%` }} />
      </span>
      <span className="w-14">{formatPct(p)}</span>
    </span>
  );
}

/** +0.0315 -> "+3.2 pts" */
function formatPts(diff: number | null): string {
  if (diff == null || !Number.isFinite(diff)) return "-";
  const pts = diff * 100;
  const sign = pts > 0 ? "+" : pts < 0 ? "-" : "±";
  return `${sign}${Math.abs(pts).toFixed(1)} pts`;
}

/** Green when we are higher, amber when lower, muted within 1 pt. */
function diffTone(diff: number | null): string {
  if (diff == null || !Number.isFinite(diff) || Math.abs(diff) < AGREE_WITHIN) return "text-muted";
  return diff > 0 ? "text-emerald-300" : "text-amber-300";
}
