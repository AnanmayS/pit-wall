import type { AskToolCall } from "@/lib/types";

const MAX_INPUT_CHARS = 160;

/** {season: 2025, driver: "NOR"} -> "season=2025, driver=NOR" */
export function compactInput(input: Record<string, unknown> | null | undefined): string {
  if (!input || typeof input !== "object") return "";
  const text = Object.entries(input)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
  return text.length > MAX_INPUT_CHARS ? `${text.slice(0, MAX_INPUT_CHARS - 1)}…` : text;
}

export function ToolCallList({ calls }: { calls: AskToolCall[] }) {
  if (calls.length === 0) {
    return <p className="text-sm text-muted">No data tools were called for this answer.</p>;
  }
  return (
    <ol className="divide-y divide-border/60 rounded-xl border border-border bg-surface">
      {calls.map((c, i) => (
        <li key={i} className="flex items-start gap-3 px-4 py-2 text-sm">
          <span className="tabular w-5 shrink-0 text-xs text-muted">{i + 1}</span>
          <div className="min-w-0 flex-1">
            <span className={`font-mono ${c.is_error ? "text-red-300" : "text-foreground"}`}>{c.name}</span>
            {c.is_error && <span className="ml-2 text-xs text-red-300">error</span>}
            <p className="break-words font-mono text-xs text-muted">{compactInput(c.input)}</p>
          </div>
          <span className="tabular shrink-0 text-xs text-muted">{Math.round(c.ms)} ms</span>
        </li>
      ))}
    </ol>
  );
}
