import type { ReactNode } from "react";

export function Notice({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-4 py-6 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted" role="status">
      <span
        className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-muted border-t-transparent"
        aria-hidden
      />
      {label}
    </span>
  );
}
