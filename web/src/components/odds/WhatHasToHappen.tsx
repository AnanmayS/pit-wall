import { formatPct } from "@/lib/format";
import type { OddsEntry } from "@/lib/types";

const TOP_N = 3;

/** "If VER wins the next race his title chance is 62%, otherwise 41%" for the title favourites. */
export function WhatHasToHappen({
  title,
  ifWin,
  ifNotWin,
  nextRace,
}: {
  title: OddsEntry[];
  ifWin: OddsEntry[];
  ifNotWin: OddsEntry[];
  nextRace: string | null;
}) {
  const win = new Map(ifWin.filter((e) => e.driver).map((e) => [e.driver as string, e.probability]));
  const notWin = new Map(ifNotWin.filter((e) => e.driver).map((e) => [e.driver as string, e.probability]));
  const lines = title
    .filter((e) => e.driver && (win.has(e.driver) || notWin.has(e.driver)))
    .slice(0, TOP_N)
    .map((e) => {
      const d = e.driver as string;
      return { driver: d, now: e.probability, win: win.get(d), notWin: notWin.get(d) };
    });
  if (lines.length === 0) return null;

  const race = nextRace ?? "the next race";
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <h3 className="text-sm font-medium">What has to happen</h3>
      <p className="mt-0.5 text-xs text-muted">How {race} moves the title picture for the current top {lines.length}.</p>
      <ul className="mt-3 space-y-2 text-sm">
        {lines.map((l) => (
          <li key={l.driver} className="flex gap-2">
            <span className="w-10 shrink-0 font-mono font-medium">{l.driver}</span>
            <span>
              {l.win != null && l.notWin != null ? (
                <>
                  If {l.driver} wins {race} his title chance is{" "}
                  <span className="tabular text-emerald-300">{formatPct(l.win, 0)}</span>, otherwise{" "}
                  <span className="tabular text-red-300">{formatPct(l.notWin, 0)}</span>
                </>
              ) : l.win != null ? (
                <>
                  If {l.driver} wins {race} his title chance is{" "}
                  <span className="tabular text-emerald-300">{formatPct(l.win, 0)}</span>
                </>
              ) : (
                <>
                  If {l.driver} does not win {race} his title chance is{" "}
                  <span className="tabular text-red-300">{formatPct(l.notWin, 0)}</span>
                </>
              )}
              <span className="tabular text-muted"> (now {formatPct(l.now, 0)})</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
