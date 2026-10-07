import { Badge, Section } from "@/components/Field";
import type { AskResponse } from "@/lib/types";
import { ToolCallList } from "./ToolCallList";

function VerificationBadge({ response }: { response: AskResponse }) {
  if (response.refused) return <Badge tone="warn">Declined</Badge>;
  if (response.grounded) return <Badge tone="good">Grounded in data</Badge>;
  const unmatched = response.unmatched ?? [];
  return (
    <Badge tone="warn">
      {unmatched.length > 0 ? `Could not verify: ${unmatched.join(", ")}` : "Not verified against data"}
    </Badge>
  );
}

export function AskAnswer({ response }: { response: AskResponse }) {
  const inTokens = response.input_tokens ?? 0;
  const outTokens = response.output_tokens ?? 0;
  const calls = response.tool_calls ?? [];
  return (
    <div className="space-y-6">
      <div className="space-y-3 rounded-xl border border-border bg-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="text-sm text-muted">{response.question}</p>
          <VerificationBadge response={response} />
        </div>
        <div className="whitespace-pre-wrap text-[15px] leading-relaxed">{response.answer}</div>
        <div className="tabular flex flex-wrap gap-x-4 gap-y-1 border-t border-border pt-3 text-xs text-muted">
          <span>{((response.latency_ms ?? 0) / 1000).toFixed(1)} s</span>
          <span>
            {(inTokens + outTokens).toLocaleString("en-US")} tokens ({inTokens.toLocaleString("en-US")} in /{" "}
            {outTokens.toLocaleString("en-US")} out)
          </span>
          <span>
            {response.turns} turn{response.turns === 1 ? "" : "s"}
          </span>
          {(response.rewrites ?? 0) > 0 && (
            <span>
              {response.rewrites} rewrite{response.rewrites === 1 ? "" : "s"}
            </span>
          )}
          {response.stop_reason && <span>stop: {response.stop_reason}</span>}
        </div>
      </div>

      <Section title={`Tool calls (${calls.length})`}>
        <ToolCallList calls={calls} />
      </Section>
    </div>
  );
}
