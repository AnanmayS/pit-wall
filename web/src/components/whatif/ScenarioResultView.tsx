import { Badge, Section } from "@/components/Field";
import { formatTimestamp } from "@/lib/whatif";
import type { ScenarioResult, ScenarioSpec } from "@/lib/types";
import { ChangedDriverCard } from "./ChangedDriverCard";
import { ModelNotes } from "./ModelNotes";
import { RaceStateMap } from "./RaceStateMap";
import { ShareLink } from "./ShareLink";
import { SpecSummary } from "./SpecSummary";
import { SummaryTable } from "./SummaryTable";

export function ScenarioResultView({
  result,
  spec,
  eventName,
}: {
  result: ScenarioResult;
  /** The scenario's changes, when known (the result itself may omit them). */
  spec: ScenarioSpec | null;
  eventName?: string | null;
}) {
  const changed = new Set(result.changed_drivers.map((d) => d.driver));
  // Drivers the scenario touches: the result's changed drivers plus any named in the spec.
  const scenarioDrivers = [
    ...new Set([
      ...changed,
      ...(spec?.changes ?? []).map((c) => c.driver).filter((d): d is string => !!d),
    ]),
  ].sort();

  return (
    <div className="space-y-8">
      <div className="space-y-4 rounded-xl border border-border bg-surface p-5">
        <div>
          <p className="text-xs text-muted">
            {result.season} &middot; Round {result.round}
            {eventName ? ` · ${eventName}` : ""} &middot; branching at lap {result.branch_lap}
          </p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">Scenario result</h2>
        </div>
        {spec && <SpecSummary spec={spec} />}
        <div className="flex flex-wrap gap-2">
          <Badge tone={result.cache_hit ? "good" : "muted"}>
            {result.cache_hit ? "Cache hit" : "Fresh run"}
          </Badge>
          <Badge>{result.n_runs.toLocaleString("en-US")} runs</Badge>
          <Badge>{result.compute_ms.toLocaleString("en-US")} ms compute</Badge>
          <Badge>
            {result.views.toLocaleString("en-US")} view{result.views === 1 ? "" : "s"}
          </Badge>
          {result.created_at && <Badge>{formatTimestamp(result.created_at)}</Badge>}
        </div>
        <ShareLink id={result.id} />
      </div>

      {result.changed_drivers.length > 0 && (
        <Section title="Changed drivers">
          <div className="grid gap-4 lg:grid-cols-2">
            {result.changed_drivers.map((d) => (
              <ChangedDriverCard key={d.driver} outcome={d} />
            ))}
          </div>
        </Section>
      )}

      <RaceStateMap
        season={result.season}
        round={result.round}
        lap={result.branch_lap}
        changedDrivers={scenarioDrivers}
      />

      <Section title="Full field">
        <SummaryTable rows={result.summary} highlight={changed} />
      </Section>

      <ModelNotes assumptions={result.assumptions} fit={result.fit} />
    </div>
  );
}
