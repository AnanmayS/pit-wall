import { Badge } from "@/components/Field";
import { formatTimestamp } from "@/lib/format";
import type { OddsLatest } from "@/lib/types";

export function OddsHeader({ latest, nextRace }: { latest: OddsLatest; nextRace: string | null }) {
  return (
    <div className="space-y-3 rounded-xl border border-border bg-surface p-5">
      <div>
        <p className="text-xs text-muted">
          {latest.season} season &middot; forecast after round {latest.after_round}
          {nextRace ? ` · next: ${nextRace}` : ""}
        </p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">Championship forecast</h2>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge>As of {formatTimestamp(latest.as_of)}</Badge>
        <Badge>After R{latest.after_round}</Badge>
        <Badge>{latest.n_sims.toLocaleString("en-US")} simulated seasons</Badge>
        <Badge>Model {latest.model_version}</Badge>
      </div>
    </div>
  );
}
