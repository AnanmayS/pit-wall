"use client";

import { useMemo, useState } from "react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Notice, Spinner } from "@/components/Notice";
import { API_BASE_URL, paths } from "@/lib/api";
import { driverName, useDrivers, type DriverMap } from "@/lib/drivers";
import { formatLapTime } from "@/lib/format";
import {
  SESSION_TYPES,
  type CompareParams,
  type CompareResult,
  type DriverSummary,
  type LapSelector,
  type LapSummary,
  type SessionSummary,
  type SessionType,
} from "@/lib/types";
import { raceOptions } from "@/lib/races";
import { useApi } from "@/lib/useApi";
import { CompareView } from "./CompareView";

const DEFAULT_SEASON = 2025;
const COMPARE_TIMEOUT_MS = 120_000;

interface RoundOption {
  round: number;
  event_name: string;
  types: Set<SessionType>;
}

const controlClass =
  "h-9 w-full rounded-md border border-border bg-surface-2 px-2.5 text-sm text-foreground outline-none focus:border-accent/70 disabled:cursor-not-allowed disabled:opacity-50";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      {children}
    </label>
  );
}

function parseSeason(input: string): number | null {
  const n = Number(input);
  return Number.isInteger(n) && n >= 1950 && n <= 2100 ? n : null;
}

function groupRounds(sessions: SessionSummary[] | null): (RoundOption & { label: string })[] {
  if (!sessions) return [];
  const byRound = new Map<number, RoundOption>();
  for (const s of sessions) {
    const entry = byRound.get(s.round) ?? { round: s.round, event_name: s.event_name, types: new Set() };
    entry.types.add(s.session_type);
    byRound.set(s.round, entry);
  }
  return raceOptions([...byRound.values()].sort((x, y) => x.round - y.round));
}

function lapLabel(lap: LapSummary): string {
  const parts = [`Lap ${lap.lap_number}`, formatLapTime(lap.lap_time_ms)];
  if (lap.compound) parts.push(lap.compound);
  if (!lap.is_accurate) parts.push("(inaccurate)");
  return parts.join("  ");
}

function resolveLap(selected: LapSelector, laps: LapSummary[] | null): LapSelector {
  if (selected === "fastest" || !laps) return selected;
  return laps.some((l) => l.lap_number === selected) ? selected : "fastest";
}

function DriverLapControls({
  label,
  tone,
  drivers,
  names,
  driver,
  onDriver,
  lap,
  onLap,
  laps,
  disabled,
}: {
  label: string;
  tone: string;
  drivers: DriverSummary[];
  names: DriverMap;
  driver: string;
  onDriver: (d: string) => void;
  lap: LapSelector;
  onLap: (l: LapSelector) => void;
  laps: { data: LapSummary[] | null; loading: boolean; error: unknown };
  disabled: boolean;
}) {
  const info = drivers.find((d) => d.driver === driver);
  const timedLaps = (laps.data ?? []).filter((l) => l.lap_time_ms != null);
  const fastestLabel = info?.fastest_lap_number
    ? `Fastest (lap ${info.fastest_lap_number}, ${formatLapTime(info.fastest_lap_ms)})`
    : "Fastest";

  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label={label}>
        <select
          className={`${controlClass} ${tone}`}
          value={driver}
          disabled={disabled || drivers.length === 0}
          onChange={(e) => onDriver(e.target.value)}
        >
          {drivers.length === 0 && <option value="">-</option>}
          {drivers.map((d) => (
            <option key={d.driver} value={d.driver}>
              {driverName(names, d.driver, d.full_name)} &middot; {d.team}
            </option>
          ))}
        </select>
      </Field>
      <Field label={laps.loading ? "Lap (loading...)" : laps.error ? "Lap (list unavailable)" : "Lap"}>
        <select
          className={controlClass}
          value={String(lap)}
          disabled={disabled || !driver}
          onChange={(e) => onLap(e.target.value === "fastest" ? "fastest" : Number(e.target.value))}
        >
          <option value="fastest">{fastestLabel}</option>
          {timedLaps.map((l) => (
            <option key={l.lap_number} value={l.lap_number}>
              {lapLabel(l)}
            </option>
          ))}
        </select>
      </Field>
    </div>
  );
}

export default function CoachClient() {
  const [seasonInput, setSeasonInput] = useState(String(DEFAULT_SEASON));
  const [roundSel, setRoundSel] = useState<number | null>(null);
  const [typeSel, setTypeSel] = useState<SessionType>("R");
  const [driverASel, setDriverASel] = useState("");
  const [driverBSel, setDriverBSel] = useState("");
  const [lapASel, setLapASel] = useState<LapSelector>("fastest");
  const [lapBSel, setLapBSel] = useState<LapSelector>("fastest");
  const [reload, setReload] = useState(0);
  const [compareReq, setCompareReq] = useState<{ params: CompareParams; nonce: number } | null>(null);

  // --- Sessions / rounds -------------------------------------------------
  const season = parseSeason(seasonInput);
  const sessions = useApi<SessionSummary[]>(season ? paths.sessions(season) : null, reload);
  const rounds = useMemo(() => groupRounds(sessions.data), [sessions.data]);
  const roundInfo = rounds.find((r) => r.round === roundSel) ?? rounds.at(-1) ?? null;
  const round = roundInfo?.round ?? null;
  const sessionType: SessionType =
    roundInfo && !roundInfo.types.has(typeSel)
      ? (SESSION_TYPES.find((t) => roundInfo.types.has(t.value))?.value ?? typeSel)
      : typeSel;

  // --- Drivers -------------------------------------------------------------
  const drivers = useApi<DriverSummary[]>(
    season && round != null ? paths.drivers(season, round, sessionType) : null,
    reload,
  );
  const driverList = useMemo(() => drivers.data ?? [], [drivers.data]);
  const driverNames = useDrivers(season);
  const pickDriver = (selected: string, fallbackIndex: number) =>
    driverList.some((d) => d.driver === selected)
      ? selected
      : (driverList[fallbackIndex]?.driver ?? driverList[0]?.driver ?? "");
  const driverA = pickDriver(driverASel, 0);
  const driverB = pickDriver(driverBSel, 1);

  // --- Laps ----------------------------------------------------------------
  const lapsA = useApi<LapSummary[]>(
    season && round != null && driverA ? paths.laps(season, round, sessionType, driverA) : null,
    reload,
  );
  const lapsB = useApi<LapSummary[]>(
    season && round != null && driverB ? paths.laps(season, round, sessionType, driverB) : null,
    reload,
  );
  const lapA = resolveLap(lapASel, lapsA.data);
  const lapB = resolveLap(lapBSel, lapsB.data);

  // --- Compare -------------------------------------------------------------
  const compare = useApi<CompareResult>(
    compareReq ? paths.compare(compareReq.params) : null,
    compareReq?.nonce ?? 0,
    COMPARE_TIMEOUT_MS,
  );

  const canCompare = Boolean(season && round != null && driverA && driverB);
  const runCompare = () => {
    if (!season || round == null || !driverA || !driverB) return;
    setCompareReq((prev) => ({
      params: {
        season,
        round,
        session_type: sessionType,
        driver_a: driverA,
        driver_b: driverB,
        lap_a: lapA,
        lap_b: lapB,
      },
      nonce: (prev?.nonce ?? 0) + 1,
    }));
  };

  const retryBase = () => setReload((n) => n + 1);
  const noTelemetry =
    compare.error?.isNotFound ||
    (compare.data !== null && (compare.data.grid?.distance_m?.length ?? 0) === 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Telemetry Coach</h1>
        <p className="mt-1 text-sm text-muted">
          Compare two laps and see where the time goes, corner by corner.
        </p>
      </div>

      <form
        className="space-y-4 rounded-xl border border-border bg-surface p-4"
        onSubmit={(e) => {
          e.preventDefault();
          runCompare();
        }}
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-[7rem_1fr_12rem]">
          <Field label="Season">
            <input
              type="number"
              inputMode="numeric"
              min={1950}
              max={2100}
              className={controlClass}
              value={seasonInput}
              onChange={(e) => {
                setSeasonInput(e.target.value);
                setRoundSel(null);
              }}
            />
          </Field>
          <Field label={sessions.loading ? "Race weekend (loading...)" : "Race weekend"}>
            <select
              className={controlClass}
              value={round ?? ""}
              disabled={rounds.length === 0}
              onChange={(e) => setRoundSel(Number(e.target.value))}
            >
              {rounds.length === 0 && <option value="">-</option>}
              {rounds.map((r) => (
                <option key={r.round} value={r.round}>
                  {r.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Session">
            <select
              className={controlClass}
              value={sessionType}
              onChange={(e) => setTypeSel(e.target.value as SessionType)}
            >
              {SESSION_TYPES.map((t) => {
                const unavailable = roundInfo !== null && !roundInfo.types.has(t.value);
                return (
                  <option key={t.value} value={t.value} disabled={unavailable}>
                    {t.label}
                    {unavailable ? " (n/a)" : ""}
                  </option>
                );
              })}
            </select>
          </Field>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <DriverLapControls
            label="Driver A"
            tone="text-driver-a"
            drivers={driverList}
            names={driverNames}
            driver={driverA}
            onDriver={(d) => {
              setDriverASel(d);
              setLapASel("fastest");
            }}
            lap={lapA}
            onLap={setLapASel}
            laps={lapsA}
            disabled={drivers.loading}
          />
          <DriverLapControls
            label="Driver B"
            tone="text-driver-b"
            drivers={driverList}
            names={driverNames}
            driver={driverB}
            onDriver={(d) => {
              setDriverBSel(d);
              setLapBSel("fastest");
            }}
            lap={lapB}
            onLap={setLapBSel}
            laps={lapsB}
            disabled={drivers.loading}
          />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={!canCompare || compare.loading}
            className="h-9 rounded-md bg-accent px-5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {compare.loading ? "Comparing..." : "Compare"}
          </button>
          {(sessions.loading || drivers.loading) && <Spinner label="Loading session data" />}
          <span className="ml-auto font-mono text-xs text-muted">API: {API_BASE_URL}</span>
        </div>
      </form>

      {season === null && (
        <Notice title="Enter a valid season">Seasons from 1950 to 2100 are accepted.</Notice>
      )}
      {sessions.error && (
        <ErrorBanner title="Could not load sessions" error={sessions.error} onRetry={retryBase} />
      )}
      {sessions.data && rounds.length === 0 && (
        <Notice title={`No sessions found for ${season}`}>
          Ingest some sessions for this season, then reload.
        </Notice>
      )}
      {drivers.error && (
        <ErrorBanner title="Could not load drivers" error={drivers.error} onRetry={retryBase} />
      )}
      {drivers.data && driverList.length === 0 && (
        <Notice title="No drivers for this session">
          This session may not have been ingested yet.
        </Notice>
      )}

      <div aria-live="polite">
        {compare.loading && (
          <div className="rounded-xl border border-border bg-surface px-4 py-12 text-center">
            <Spinner label="Aligning telemetry..." />
          </div>
        )}
        {compare.error && !noTelemetry && (
          <ErrorBanner title="Comparison failed" error={compare.error} onRetry={runCompare} />
        )}
        {noTelemetry && (
          <Notice title="No telemetry for this comparison">
            {compare.error?.message ??
              "The API returned no telemetry samples for one or both of these laps."}
          </Notice>
        )}
        {compare.data && !noTelemetry && <CompareView result={compare.data} />}
        {!compareReq && !sessions.error && (
          <Notice title="Pick two drivers and press Compare">
            Defaults to each driver&apos;s fastest lap.
          </Notice>
        )}
      </div>
    </div>
  );
}
