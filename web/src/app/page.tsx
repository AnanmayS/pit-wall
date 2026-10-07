import Link from "next/link";

const CARDS = [
  {
    href: "/coach",
    title: "Telemetry Coach",
    body: "Overlay two laps, see where time is won and lost corner by corner.",
    status: "Live",
  },
  {
    href: "/what-if",
    title: "What-If",
    body: "Re-run a race with a different strategy and compare outcomes.",
    status: "Live",
  },
  {
    href: "/ask",
    title: "Ask the Pit Wall",
    body: "Ask a question in plain English and get an answer checked against the data.",
    status: "Live",
  },
  {
    href: "/odds",
    title: "Odds",
    body: "Title and next-race probabilities from simulating the rest of the season.",
    status: "Live",
  },
];

export default function Home() {
  return (
    <div className="py-8">
      <section className="max-w-2xl">
        <h1 className="text-4xl font-semibold tracking-tight">Pit Wall</h1>
        <p className="mt-3 text-lg text-muted">
          F1 telemetry analysis and race simulation. Pick a tool to get started.
        </p>
      </section>
      <section className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {CARDS.map((card) => (
          <Link
            key={card.href}
            href={card.href}
            className="group flex flex-col rounded-xl border border-border bg-surface p-5 transition-colors hover:border-accent/60 hover:bg-surface-2"
          >
            <span
              className={`self-start rounded-full px-2 py-0.5 text-xs ${
                card.status === "Live" ? "bg-accent/15 text-accent" : "bg-surface-2 text-muted"
              }`}
            >
              {card.status}
            </span>
            <h2 className="mt-3 text-lg font-medium">{card.title}</h2>
            <p className="mt-1 flex-1 text-sm text-muted">{card.body}</p>
            <span className="mt-4 text-sm text-muted transition-colors group-hover:text-foreground">
              Open &rarr;
            </span>
          </Link>
        ))}
      </section>
    </div>
  );
}
