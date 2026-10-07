import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Pit Wall",
    template: "%s | Pit Wall",
  },
  description: "F1 telemetry analysis and race simulation.",
};

const NAV = [
  { href: "/coach", label: "Telemetry Coach" },
  { href: "/what-if", label: "What-If" },
  { href: "/odds", label: "Odds" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <header className="border-b border-border bg-surface/80 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
            <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
              <span className="inline-block h-4 w-1.5 rounded-sm bg-accent" aria-hidden />
              Pit Wall
            </Link>
            <nav className="flex gap-1 text-sm">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-md px-3 py-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
        <footer className="border-t border-border py-4 text-center text-xs text-muted">
          Pit Wall. Unofficial; not associated with Formula 1.
        </footer>
      </body>
    </html>
  );
}
