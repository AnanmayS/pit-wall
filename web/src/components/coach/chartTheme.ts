export const COLORS = {
  a: "#38bdf8",
  b: "#f59e0b",
  grid: "#262b33",
  axis: "#8a919c",
  delta: "#e6e8eb",
  zero: "#4b5563",
  corner: "#3a404a",
};

export const tooltipStyle = {
  contentStyle: {
    background: "#13161b",
    border: "1px solid #262b33",
    borderRadius: 8,
    fontSize: 12,
  },
  labelStyle: { color: "#8a919c" },
};

export const axisTick = { fill: COLORS.axis, fontSize: 11 };

export function formatMeters(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? `${Math.round(n)} m` : "";
}
