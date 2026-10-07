"use client";

import { useMemo, useState } from "react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Field, Section, controlClass } from "@/components/Field";
import { Notice, Spinner } from "@/components/Notice";
import { API_BASE_URL, paths } from "@/lib/api";
import type { DriverSummary, OddsHistory, OddsKind, OddsLatest, SessionSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { ConstructorsTable } from "./ConstructorsTable";
import { KindToggle, ODDS_KINDS } from "./KindToggle";
import { MarketComparison, type ProbabilityMap } from "./MarketComparison";
import { OddsHeader } from "./OddsHeader";
import { OddsHistoryChart } from "./OddsHistoryChart";
import { TitleOddsTable } from "./TitleOddsTable";
import { WhatHasToHappen } from "./WhatHasToHappen";

/** Seasons with stored data, newest first. */
const SEASONS = [2026, 2025];
const DEFAULT_SEASON = 2026;
const HISTORY_TOP = 6;

function toMap(entries: { driver: string | null; probability: number }[] | undefined): ProbabilityMap {
  const out: ProbabilityMap = {};
  for (const e of entries ?? []) if (e.driver) out[e.driver] = e.probability;
  return out;
}

export default function OddsClient() {
  const [season, setSeason] = useState(DEFAULT_SEASON);
  const [kind, setKind] = useState<OddsKind>("title");
  const [reload, setReload] = useState(0);

  const latest = useApi<OddsLatest>(paths.oddsLatest(season), reload);
  const history = useApi<OddsHistory>(paths.oddsHistory(season, kind, HISTORY_TOP), reload);
  const sessions = useApi<SessionSummary[]>(paths.sessions(season), reload);
  const forecast = latest.data;

  // Next race name, from the round carried on race_win entries.
  const nextRound = forecast?.race_win?.find((e) => e.round != null)?.round ?? null;
  const nextRaceName =
    nextRound != null
      ? (sessions.data?.find((s) => s.round === nextRound)?.event_name ?? `round ${nextRound}`)
      : null;

  // Driver -> team from the last completed race (best effort; blank when unavailable).
  const teamRound = forecast && forecast.after_round > 0 ? forecast.after_round : null;
  const hasTeamSession = sessions.data?.some((s) => s.round === teamRound && s.session_type === "R") ?? false;
  const drivers = useApi<DriverSummary[]>(
    teamRound != null && hasTeamSession ? paths.drivers(season, teamRound, "R") : null,
    reload,
  );
  const teams = useMemo(
    () => new Map((drivers.data ?? []).map((d) => [d.driver, d.team] as [string, string])),
    [drivers.data],
  );

  const noForecast = latest.error?.isNotFound ?? false;
  const kindLabel = ODDS_KINDS.find((k) => k.value === kind)?.label ?? kind;
  const retry = () => setReload((n) => n + 1);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Title Odds</h1>
          <p className="mt-1 text-sm text-muted">
            Championship and next-race probabilities from simulating the rest of the season.
          </p>
        </div>
        <div className="w-32">
          <Field label="Season">
            <select className={controlClass} value={season} onChange={(e) => setSeason(Number(e.target.value))}>
              {SEASONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </div>

      <div aria-live="polite" className="space-y-6">
        {latest.loading && (
          <div className="rounded-xl border border-border bg-surface px-4 py-12 text-center">
            <Spinner label="Loading forecast..." />
          </div>
        )}
        {noForecast && (
          <Notice title="No forecast yet for this season">
            Run <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs">pitwall odds forecast --season {season}</code>{" "}
            to create one.
          </Notice>
        )}
        {latest.error && !noForecast && (
          <ErrorBanner title="Could not load the forecast" error={latest.error} onRetry={retry} />
        )}

        {forecast && (
          <>
            <OddsHeader latest={forecast} nextRace={nextRaceName} />

            <section className="space-y-3 rounded-xl border border-border bg-surface p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-sm font-medium">{kindLabel} probability over time</h2>
                <KindToggle value={kind} onChange={setKind} />
              </div>
              {history.loading && (
                <div className="py-12 text-center">
                  <Spinner label="Loading history..." />
                </div>
              )}
              {history.error?.isNotFound && (
                <p className="py-12 text-center text-sm text-muted">No history recorded for this view yet.</p>
              )}
              {history.error && !history.error.isNotFound && (
                <ErrorBanner title="Could not load history" error={history.error} onRetry={retry} />
              )}
              {history.data && <OddsHistoryChart history={history.data} />}
            </section>

            <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
              <Section title="Drivers' championship">
                <TitleOddsTable
                  title={forecast.title ?? []}
                  raceWin={forecast.race_win ?? []}
                  teams={teams}
                  nextRound={nextRound}
                />
              </Section>
              <div className="space-y-6">
                <WhatHasToHappen
                  title={forecast.title ?? []}
                  ifWin={forecast.title_if_next_win ?? []}
                  ifNotWin={forecast.title_if_next_not_win ?? []}
                  nextRace={nextRaceName}
                />
                <Section title="Constructors' championship">
                  <ConstructorsTable rows={forecast.constructors ?? []} />
                </Section>
              </div>
            </div>

            {/* Market odds are not wired up yet; renders nothing while `market` is empty. */}
            <MarketComparison ours={toMap(forecast.title)} market={{}} marketName="Polymarket" />
          </>
        )}
      </div>

      <p className="text-right font-mono text-xs text-muted">API: {API_BASE_URL}</p>
    </div>
  );
}
