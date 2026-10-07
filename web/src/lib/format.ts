/** 83456 -> "1:23.456" */
export function formatLapTime(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "-";
  const totalMs = Math.round(ms);
  const minutes = Math.floor(totalMs / 60_000);
  const seconds = (totalMs % 60_000) / 1000;
  const secStr = seconds.toFixed(3).padStart(6, "0");
  return minutes > 0 ? `${minutes}:${secStr}` : seconds.toFixed(3);
}

/** 123 -> "+0.123s", -45 -> "-0.045s" */
export function formatDelta(ms: number | null | undefined, digits = 3): string {
  if (ms == null || !Number.isFinite(ms)) return "-";
  const s = ms / 1000;
  const sign = s > 0 ? "+" : s < 0 ? "-" : "±";
  return `${sign}${Math.abs(s).toFixed(digits)}s`;
}

export function formatNumber(
  value: number | null | undefined,
  digits = 0,
  unit = "",
): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return `${value.toFixed(digits)}${unit}`;
}

/** Tailwind text color for a delta from driver A's perspective (negative = A ahead). */
export function deltaTone(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || Math.abs(ms) < 0.5) return "text-muted";
  return ms < 0 ? "text-driver-a" : "text-driver-b";
}

/** 0.123 -> "12.3%"; tiny non-zero values show as "<0.1%". */
export function formatPct(p: number | null | undefined, digits = 1): string {
  if (p == null || !Number.isFinite(p)) return "-";
  const pct = p * 100;
  const floor = 10 ** -digits;
  if (pct > 0 && pct < floor) return `<${floor.toFixed(digits)}%`;
  return `${pct.toFixed(digits)}%`;
}

export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
