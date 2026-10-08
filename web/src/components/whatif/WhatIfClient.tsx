"use client";

import { usePathname } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Field, controlClass, primaryButtonClass, secondaryButtonClass } from "@/components/Field";
import { Notice, Spinner } from "@/components/Notice";
import { API_BASE_URL, paths, runScenario, toApiError, type ApiError } from "@/lib/api";
import type { DriverSummary, ScenarioResult, ScenarioSpec, SessionSummary } from "@/lib/types";
import { raceName, raceOptions } from "@/lib/races";
import { useApi } from "@/lib/useApi";
import {
  DEFAULT_RUNS,
  MAX_CHANGES,
  MAX_RUNS,
  MIN_RUNS,
  buildChange,
  newDraft,
  type ChangeDraft,
} from "@/lib/whatif";
import { ChangeRow } from "./ChangeRow";
import { RecentScenarios } from "./RecentScenarios";
import { ScenarioResultView } from "./ScenarioResultView";

const DEFAULT_SEASON = 2025;

function parseSeason(input: string): number | null {
  const n = Number(input);
  return Number.isInteger(n) && n >= 1950 && n <= 2100 ? n : null;
}

function raceRounds(sessions: SessionSummary[] | null) {
  return raceOptions((sessions ?? []).filter((s) => s.session_type === "R").sort((a, b) => a.round - b.round));
}

type RunState =
  | { status: "idle" }
  | { status: "running" }
  | { status: "error"; error: ApiError }
  | { status: "done"; result: ScenarioResult; spec: ScenarioSpec; eventName: string | null };

export default function WhatIfClient() {
  const pathname = usePathname();
  const [seasonInput, setSeasonInput] = useState(String(DEFAULT_SEASON));
  const [roundSel, setRoundSel] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<ChangeDraft[]>(() => [newDraft(0)]);
  const nextKey = useRef(1);
  const [branchLap, setBranchLap] = useState("");
  const [runsInput, setRunsInput] = useState(String(DEFAULT_RUNS));
  const [reload, setReload] = useState(0);
  const [recentNonce, setRecentNonce] = useState(0);
  const [attempted, setAttempted] = useState(false);
  const [run, setRun] = useState<RunState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  // --- Season / race ------------------------------------------------------
  const season = parseSeason(seasonInput);
  const sessions = useApi<SessionSummary[]>(season ? paths.sessions(season) : null, reload);
  const races = useMemo(() => raceRounds(sessions.data), [sessions.data]);
  const race = races.find((r) => r.round === roundSel) ?? races.at(-1) ?? null;
  const round = race?.round ?? null;

  // --- Drivers ------------------------------------------------------------
  const drivers = useApi<DriverSummary[]>(
    season && round != null ? paths.drivers(season, round, "R") : null,
    reload,
  );
  const driverList = useMemo(
    () => [...(drivers.data ?? [])].sort((a, b) => a.driver.localeCompare(b.driver)),
    [drivers.data],
  );
  const maxLap = driverList.length > 0 ? Math.max(...driverList.map((d) => d.laps || 0)) || null : null;
  const resolveDriver = (pick: string) =>
    driverList.some((d) => d.driver === pick) ? pick : (driverList[0]?.driver ?? "");

  // --- Validation ---------------------------------------------------------
  const built = drafts.map((d) => buildChange(d, resolveDriver(d.driver), maxLap));
  const runs = Number(runsInput);
  const runsOk = Number.isInteger(runs) && runs >= MIN_RUNS && runs <= MAX_RUNS;
  const branchTrim = branchLap.trim();
  const branch = branchTrim === "" ? null : Number(branchTrim);
  const branchOk =
    branch === null || (Number.isInteger(branch) && branch >= 1 && (maxLap == null || branch <= maxLap));
  const formProblems = [
    ...(season ? [] : ["enter a valid season"]),
    ...(round != null ? [] : ["pick a race"]),
    ...(runsOk ? [] : [`runs must be between ${MIN_RUNS.toLocaleString("en-US")} and ${MAX_RUNS.toLocaleString("en-US")}`]),
    ...(branchOk ? [] : [`branch lap must be between 1 and ${maxLap ?? "the race distance"}`]),
  ];
  const valid = formProblems.length === 0 && built.every((b) => b.problems.length === 0);
  const running = run.status === "running";

  // --- Actions ------------------------------------------------------------
  const updateDraft = (key: number, patch: Partial<ChangeDraft>) =>
    setDrafts((list) => list.map((d) => (d.key === key ? { ...d, ...patch } : d)));
  const addDraft = () =>
    setDrafts((list) => (list.length >= MAX_CHANGES ? list : [...list, newDraft(nextKey.current++)]));
  const removeDraft = (key: number) => setDrafts((list) => list.filter((d) => d.key !== key));

  const submit = async () => {
    setAttempted(true);
    if (!valid || !season || round == null) return;
    const spec: ScenarioSpec = {
      season,
      round,
      changes: built.map((b) => b.change),
      branch_lap: branch,
      n_runs: runs,
    };
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRun({ status: "running" });
    try {
      const result = await runScenario(spec, controller.signal);
      if (controller.signal.aborted) return;
      setRun({ status: "done", result, spec, eventName: race?.event_name || raceName(sessions.data, result.round) });
      window.history.pushState(null, "", `/what-if/${encodeURIComponent(result.id)}`);
      setRecentNonce((n) => n + 1);
    } catch (err) {
      if (controller.signal.aborted) return;
      setRun({ status: "error", error: toApiError(err, "/api/whatif") });
    }
  };

  // The result follows the URL: going "back" to /what-if hides it, "forward" shows it again.
  const shownResult =
    run.status === "done" && pathname === `/what-if/${encodeURIComponent(run.result.id)}` ? run : null;
  const retryBase = () => setReload((n) => n + 1);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">What-If Strategy Simulator</h1>
        <p className="mt-1 text-sm text-muted">
          Change a pit lap, tyre, safety car or retirement, then re-simulate the rest of the race thousands of times.
        </p>
      </div>

      <form
        className="space-y-4 rounded-xl border border-border bg-surface p-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-[7rem_1fr_8rem_8rem]">
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
          <Field label={sessions.loading ? "Race (loading...)" : "Race"}>
            <select
              className={controlClass}
              value={round ?? ""}
              disabled={races.length === 0}
              onChange={(e) => setRoundSel(Number(e.target.value))}
            >
              {races.length === 0 && <option value="">-</option>}
              {races.map((r) => (
                <option key={r.round} value={r.round}>
                  {r.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Branch lap (optional)">
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={maxLap ?? undefined}
              placeholder="auto"
              className={controlClass}
              value={branchLap}
              onChange={(e) => setBranchLap(e.target.value)}
            />
          </Field>
          <Field label="Runs">
            <input
              type="number"
              inputMode="numeric"
              min={MIN_RUNS}
              max={MAX_RUNS}
              step={100}
              className={controlClass}
              value={runsInput}
              onChange={(e) => setRunsInput(e.target.value)}
            />
          </Field>
        </div>

        <div className="space-y-2">
          {drafts.map((d, i) => (
            <ChangeRow
              key={d.key}
              index={i}
              draft={d}
              driver={resolveDriver(d.driver)}
              drivers={driverList}
              maxLap={maxLap}
              problems={built[i].problems}
              showProblems={attempted}
              onChange={(patch) => updateDraft(d.key, patch)}
              onRemove={drafts.length > 1 ? () => removeDraft(d.key) : null}
              disabled={running}
            />
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" disabled={running || (attempted && !valid)} className={primaryButtonClass}>
            {running ? "Simulating..." : "Run scenario"}
          </button>
          <button
            type="button"
            onClick={addDraft}
            disabled={running || drafts.length >= MAX_CHANGES}
            className={secondaryButtonClass}
          >
            Add change ({drafts.length}/{MAX_CHANGES})
          </button>
          {(sessions.loading || drivers.loading) && <Spinner label="Loading race data" />}
          <span className="ml-auto font-mono text-xs text-muted">API: {API_BASE_URL}</span>
        </div>
        {attempted && formProblems.length > 0 && (
          <p className="text-xs text-amber-300">Before running: {formProblems.join(", ")}.</p>
        )}
      </form>

      {season === null && (
        <Notice title="Enter a valid season">Seasons from 1950 to 2100 are accepted.</Notice>
      )}
      {sessions.error && (
        <ErrorBanner title="Could not load races" error={sessions.error} onRetry={retryBase} />
      )}
      {sessions.data && races.length === 0 && (
        <Notice title={`No races found for ${season}`}>Ingest race sessions for this season, then reload.</Notice>
      )}
      {drivers.error && (
        <ErrorBanner title="Could not load drivers" error={drivers.error} onRetry={retryBase} />
      )}

      <div aria-live="polite">
        {run.status === "running" && (
          <div className="rounded-xl border border-border bg-surface px-4 py-12 text-center">
            <Spinner label={`Simulating ${runsOk ? runs.toLocaleString("en-US") : ""} races...`} />
          </div>
        )}
        {run.status === "error" && (
          <ErrorBanner
            title={run.error.status === 422 ? "The API rejected this scenario" : "Scenario failed"}
            error={run.error}
            onRetry={run.error.status === 422 ? undefined : () => void submit()}
          />
        )}
        {shownResult && (
          <ScenarioResultView
            result={shownResult.result}
            spec={shownResult.result.spec ?? shownResult.spec}
            eventName={shownResult.eventName}
          />
        )}
        {run.status === "idle" && !sessions.error && (
          <Notice title="Describe a change and press Run scenario">
            Leave the branch lap empty to branch just before the first change.
          </Notice>
        )}
      </div>

      {season && round != null && (
        <RecentScenarios
          season={season}
          round={round}
          nonce={recentNonce}
          raceLabel={race?.event_name ?? null}
          currentId={shownResult?.result.id ?? null}
        />
      )}
    </div>
  );
}
