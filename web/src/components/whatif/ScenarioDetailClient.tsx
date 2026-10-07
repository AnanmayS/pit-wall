"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Notice, Spinner } from "@/components/Notice";
import { WHATIF_TIMEOUT_MS, paths } from "@/lib/api";
import type { RecentScenario, ScenarioResult, SessionSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { RecentScenarios } from "./RecentScenarios";
import { ScenarioResultView } from "./ScenarioResultView";

export default function ScenarioDetailClient({ id }: { id: string }) {
  const [nonce, setNonce] = useState(0);
  const scenario = useApi<ScenarioResult>(paths.whatif(id), nonce, WHATIF_TIMEOUT_MS);
  const result = scenario.data;

  // Event name for the header; /recent is only a fallback for older results stored without a spec.
  const sessions = useApi<SessionSummary[]>(result ? paths.sessions(result.season) : null);
  const recent = useApi<RecentScenario[]>(
    result && !result.spec ? paths.whatifRecent(result.season, result.round) : null,
  );
  const eventName =
    sessions.data?.find((s) => s.round === result?.round && s.session_type === "R")?.event_name ??
    sessions.data?.find((s) => s.round === result?.round)?.event_name ??
    null;
  const spec = result?.spec ?? recent.data?.find((r) => r.id === id)?.spec ?? null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">What-If Scenario</h1>
          <p className="mt-1 font-mono text-xs text-muted">{id}</p>
        </div>
        <Link
          href="/what-if"
          className="rounded-md border border-border px-3 py-1.5 text-sm text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
        >
          Build a new scenario
        </Link>
      </div>

      <div aria-live="polite">
        {scenario.loading && (
          <div className="rounded-xl border border-border bg-surface px-4 py-12 text-center">
            <Spinner label="Loading scenario..." />
          </div>
        )}
        {scenario.error?.isNotFound && (
          <Notice title="Scenario not found">
            No scenario with this id exists. It may have expired.{" "}
            <Link href="/what-if" className="underline underline-offset-4 hover:text-foreground">
              Build a new one
            </Link>
            .
          </Notice>
        )}
        {scenario.error && !scenario.error.isNotFound && (
          <ErrorBanner
            title="Could not load scenario"
            error={scenario.error}
            onRetry={() => setNonce((n) => n + 1)}
          />
        )}
        {result && <ScenarioResultView result={result} spec={spec} eventName={eventName} />}
      </div>

      {result && <RecentScenarios season={result.season} round={result.round} nonce={0} currentId={id} />}
    </div>
  );
}
