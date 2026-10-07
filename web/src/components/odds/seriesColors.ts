/** Distinct line colours for up to eight series on the dark background. */
export const SERIES_COLORS = [
  "#38bdf8",
  "#f59e0b",
  "#e10600",
  "#34d399",
  "#a78bfa",
  "#f472b6",
  "#facc15",
  "#94a3b8",
];

export function seriesColor(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}
