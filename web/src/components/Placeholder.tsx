import Link from "next/link";

export function Placeholder({ title, milestone, blurb }: { title: string; milestone: number; blurb: string }) {
  return (
    <div className="mx-auto max-w-xl py-16 text-center">
      <p className="text-xs font-medium uppercase tracking-widest text-accent">Milestone {milestone}</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-3 text-muted">{blurb}</p>
      <p className="mt-6 inline-block rounded-full border border-border bg-surface px-4 py-1.5 text-sm">
        Coming in milestone {milestone}
      </p>
      <div className="mt-8">
        <Link href="/" className="text-sm text-muted underline-offset-4 hover:text-foreground hover:underline">
          Back to home
        </Link>
      </div>
    </div>
  );
}
