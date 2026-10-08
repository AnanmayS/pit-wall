import { Badge } from "@/components/Field";
import { formatTimestamp } from "@/lib/format";
import { shortRaceName, theRace } from "@/lib/races";
import type { OddsLatest } from "@/lib/types";

export function OddsHeader({
  latest,
  afterRace,
  nextRace,
}: {
  latest: OddsLatest;
  /** Name of the last completed race; null before the season starts. */
  afterRace: string | null;
  nextRace: string | null;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-border bg-surface p-5">
      <div>
        <p className="text-xs text-muted">
          {latest.season} season &middot; {afterRace ? `forecast after ${theRace(afterRace)}` : "pre-season forecast"}
          {nextRace ? ` · next: ${theRace(nextRace)}` : ""}
        </p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">Championship forecast</h2>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge>As of {formatTimestamp(latest.as_of)}</Badge>
        {afterRace && <Badge>After {shortRaceName(afterRace)}</Badge>}
        <Badge>{latest.n_sims.toLocaleString("en-US")} simulated seasons</Badge>
        <Badge>Model {latest.model_version}</Badge>
      </div>
    </div>
  );
}
