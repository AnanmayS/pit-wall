import type { ScenarioFit } from "@/lib/types";

export function ModelNotes({
  assumptions,
  fit,
}: {
  assumptions: Record<string, string>;
  fit: ScenarioFit;
}) {
  const entries = Object.entries(assumptions ?? {});
  return (
    <details className="group rounded-xl border border-border bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium">
        <span>
          Model notes
          <span className="ml-2 text-xs font-normal text-muted">
            {entries.length === 0 ? "no fallbacks used" : `${entries.length} assumption${entries.length === 1 ? "" : "s"}`}
          </span>
        </span>
        <span className="text-muted transition-transform group-open:rotate-90" aria-hidden>
          &rsaquo;
        </span>
      </summary>
      <div className="space-y-4 border-t border-border px-4 py-3 text-sm">
        <dl className="tabular grid grid-cols-3 gap-3">
          <FitStat label="Clean laps" value={fit?.clean_laps} />
          <FitStat label="Pit stops used" value={fit?.pit_stops_used} />
          <FitStat label="SC deployments" value={fit?.sc_deployments} />
        </dl>
        {entries.length > 0 ? (
          <ul className="space-y-1.5">
            {entries.map(([key, text]) => (
              <li key={key} className="flex flex-col gap-0.5 sm:flex-row sm:gap-3">
                <span className="shrink-0 font-mono text-xs text-muted sm:w-48">{key}</span>
                <span>{text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">The model fit did not need any fallback assumptions.</p>
        )}
      </div>
    </details>
  );
}

function FitStat({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="rounded-md bg-surface-2 px-3 py-2">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-base font-medium">{value ?? "-"}</dd>
    </div>
  );
}
