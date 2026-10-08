"use client";

import Link from "next/link";
import { Spinner } from "@/components/Notice";
import { paths } from "@/lib/api";
import { driverName, useDrivers } from "@/lib/drivers";
import type { RecentScenario } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { describeSpec, formatTimestamp } from "@/lib/whatif";

export function RecentScenarios({
  season,
  round,
  raceLabel,
  nonce,
  currentId,
}: {
  season: number;
  round: number;
  /** Race name for the heading, e.g. "Chinese Grand Prix". */
  raceLabel?: string | null;
  nonce: number;
  currentId?: string | null;
}) {
  const recent = useApi<RecentScenario[]>(paths.whatifRecent(season, round), nonce);
  const items = recent.data ?? [];
  const names = useDrivers(season);
  const nameOf = (code: string) => driverName(names, code);

  return (
    <section className="space-y-3">
      <h2 className="text-xs font-medium uppercase tracking-widest text-muted">
        {raceLabel ? `Recent scenarios: ${season} ${raceLabel}` : "Recent scenarios for this race"}
      </h2>
      {recent.loading && <Spinner label="Loading recent scenarios" />}
      {recent.error && (
        <p className="text-sm text-muted">Recent scenarios are unavailable ({recent.error.message}).</p>
      )}
      {recent.data && items.length === 0 && (
        <p className="text-sm text-muted">No scenarios have been run for this race yet.</p>
      )}
      {items.length > 0 && (
        <ul className="divide-y divide-border/60 rounded-xl border border-border bg-surface">
          {items.map((s) => {
            const lines = s.spec ? describeSpec(s.spec, nameOf) : [];
            return (
              <li key={s.id}>
                <Link
                  href={`/what-if/${encodeURIComponent(s.id)}`}
                  className={`flex flex-col gap-0.5 px-4 py-2.5 text-sm transition-colors hover:bg-surface-2 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4 ${
                    s.id === currentId ? "bg-accent/10" : ""
                  }`}
                >
                  <span className="min-w-0 truncate">
                    {lines.length > 0 ? lines.join("; ") : "Baseline replay"}
                  </span>
                  <span className="tabular shrink-0 text-xs text-muted">
                    {formatTimestamp(s.created_at)}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
