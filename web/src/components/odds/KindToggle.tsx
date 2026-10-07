import type { OddsKind } from "@/lib/types";

export const ODDS_KINDS: { value: OddsKind; label: string }[] = [
  { value: "title", label: "Drivers' title" },
  { value: "constructors", label: "Constructors' title" },
  { value: "race_win", label: "Next race win" },
];

export function KindToggle({ value, onChange }: { value: OddsKind; onChange: (k: OddsKind) => void }) {
  return (
    <div role="radiogroup" aria-label="Chart" className="inline-flex rounded-md border border-border bg-surface-2 p-0.5">
      {ODDS_KINDS.map((k) => {
        const active = k.value === value;
        return (
          <button
            key={k.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(k.value)}
            className={`rounded px-3 py-1 text-xs transition-colors ${
              active ? "bg-surface text-foreground shadow-sm" : "text-muted hover:text-foreground"
            }`}
          >
            {k.label}
          </button>
        );
      })}
    </div>
  );
}
