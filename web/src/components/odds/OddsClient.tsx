"use client";

import { useMemo, useState } from "react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Field, Section, controlClass } from "@/components/Field";
import { Notice, Spinner } from "@/components/Notice";
import { API_BASE_URL, paths } from "@/lib/api";
import { driverName, useDrivers } from "@/lib/drivers";
import type { DriverSummary, OddsHistory, OddsKind, OddsLatest, SessionSummary } from "@/lib/types";
import { raceName } from "@/lib/races";
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

  // Race names come with the forecast; the session list (or the bare round) is the fallback.
  const nextRound = forecast?.next_round ?? forecast?.race_win?.find((e) => e.round != null)?.round ?? null;
  const nextRaceName =
    forecast?.next_race || (nextRound != null ? raceName(sessions.data, nextRound) : null);
  const afterRaceName =
    forecast && forecast.after_round > 0
      ? forecast.after_race || raceName(sessions.data, forecast.after_round)
      : null;

  // Driver -> team from the last completed race (best effort; blank when unavailable).
  const teamRound = forecast && forecast.after_round > 0 ? forecast.after_round : null;
  const hasTeamSession = sessions.data?.some((s) => s.round === teamRound && s.session_type === "R") ?? false;
  const drivers = useApi<DriverSummary[]>(
    teamRound != null && hasTeamSession ? paths.drivers(season, teamRound, "R") : null,
    reload,
  );
  const driverNames = useDrivers(season);
  const teams = useMemo(() => {
    const out = new Map<string, string>();
    for (const [code, d] of driverNames) if (d.team) out.set(code, d.team);
    for (const d of drivers.data ?? []) if (d.team) out.set(d.driver, d.team);
    return out;
  }, [drivers.data, driverNames]);
  // Names sent with the forecast win; the season's driver list covers the rest.
  const nameOf = useMemo(() => {
    const known = new Map<string, string>();
    for (const list of [forecast?.title, forecast?.race_win, forecast?.title_if_next_win, forecast?.title_if_next_not_win]) {
      for (const e of list ?? []) if (e.driver && e.driver_name) known.set(e.driver, e.driver_name);
    }
    return (code: string) => driverName(driverNames, code, known.get(code));
  }, [forecast, driverNames]);

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
            <OddsHeader latest={forecast} afterRace={afterRaceName} nextRace={nextRaceName} />

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
              {history.data && <OddsHistoryChart history={history.data} sessions={sessions.data} drivers={driverNames} />}
            </section>

            <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
              <Section title="Drivers' championship">
                <TitleOddsTable
                  title={forecast.title ?? []}
                  raceWin={forecast.race_win ?? []}
                  teams={teams}
                  nameOf={nameOf}
                  nextRace={nextRaceName}
                />
              </Section>
              <div className="space-y-6">
                <WhatHasToHappen
                  title={forecast.title ?? []}
                  ifWin={forecast.title_if_next_win ?? []}
                  ifNotWin={forecast.title_if_next_not_win ?? []}
                  nameOf={nameOf}
                  nextRace={nextRaceName}
                />
                <Section title="Constructors' championship">
                  <ConstructorsTable rows={forecast.constructors ?? []} />
                </Section>
              </div>
            </div>

            {/* Market odds are not wired up yet; renders nothing while `market` is empty. */}
            <MarketComparison ours={toMap(forecast.title)} market={{}} marketName="Polymarket" nameOf={nameOf} />
          </>
        )}
      </div>

      <p className="text-right font-mono text-xs text-muted">API: {API_BASE_URL}</p>
    </div>
  );
}
