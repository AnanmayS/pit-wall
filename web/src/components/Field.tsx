import type { ReactNode } from "react";

export const controlClass =
  "h-9 w-full rounded-md border border-border bg-surface-2 px-2.5 text-sm text-foreground outline-none focus:border-accent/70 disabled:cursor-not-allowed disabled:opacity-50";

export const primaryButtonClass =
  "h-9 rounded-md bg-accent px-5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40";

export const secondaryButtonClass =
  "h-9 rounded-md border border-border px-3 text-sm text-muted transition-colors hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      {children}
    </label>
  );
}

export function Badge({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "good" | "warn" | "bad" }) {
  const toneClass = {
    muted: "border-border bg-surface-2 text-muted",
    good: "border-emerald-800/60 bg-emerald-950/40 text-emerald-300",
    warn: "border-amber-800/60 bg-amber-950/40 text-amber-300",
    bad: "border-red-900/60 bg-red-950/40 text-red-300",
  }[tone];
  return (
    <span className={`tabular inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs ${toneClass}`}>
      {children}
    </span>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-medium uppercase tracking-widest text-muted">{title}</h2>
      {children}
    </section>
  );
}
