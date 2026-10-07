import type { CompareGrid } from "./types";

export interface ChartRow {
  d: number;
  /** Gap in seconds, positive = driver A behind. */
  delta: number;
  speedA: number;
  speedB: number;
}

export interface Zone {
  start: number;
  end: number;
}

/** Turn the column-oriented grid into chart rows, thinning to at most `maxPoints`. */
export function buildChartRows(grid: CompareGrid, maxPoints = 1500): ChartRow[] {
  const n = grid.distance_m.length;
  if (n === 0) return [];
  const stride = Math.max(1, Math.ceil(n / maxPoints));
  const rows: ChartRow[] = [];
  for (let i = 0; i < n; i += stride) {
    rows.push(rowAt(grid, i));
  }
  if ((n - 1) % stride !== 0) rows.push(rowAt(grid, n - 1));
  return rows;
}

function rowAt(grid: CompareGrid, i: number): ChartRow {
  return {
    d: grid.distance_m[i],
    delta: (grid.delta_ms[i] ?? 0) / 1000,
    speedA: grid.speed_a[i],
    speedB: grid.speed_b[i],
  };
}

/** Row closest to distance `d` (rows sorted by distance), or null when there are none. */
export function nearestRow(rows: ChartRow[], d: number): ChartRow | null {
  if (rows.length === 0 || !Number.isFinite(d)) return null;
  let lo = 0;
  let hi = rows.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].d <= d) lo = mid;
    else hi = mid;
  }
  return Math.abs(rows[hi].d - d) < Math.abs(rows[lo].d - d) ? rows[hi] : rows[lo];
}

/** Contiguous distance ranges where `flags` is true. */
export function contiguousZones(distance: number[], flags: boolean[]): Zone[] {
  const zones: Zone[] = [];
  let start: number | null = null;
  for (let i = 0; i < distance.length; i++) {
    const on = Boolean(flags[i]);
    if (on && start === null) start = distance[i];
    if (!on && start !== null) {
      zones.push({ start, end: distance[i - 1] ?? start });
      start = null;
    }
  }
  if (start !== null) zones.push({ start, end: distance[distance.length - 1] });
  return zones;
}
