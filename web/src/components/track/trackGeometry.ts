/**
 * Shared SVG geometry for the circuit maps (Coach lap comparison and What-If race state).
 *
 * Input coordinates are raw FastF1 position units (1/10 m). They are rotated by the circuit's
 * `rotation_deg`, y-flipped so north is up on screen, then scaled to fit a fixed-width viewBox.
 * Everything here is plain functions with no React state; only `clientToView` touches the DOM.
 */

export const VIEW_W = 1000;
export const PAD = 64;
export const SURFACE = "#13161b";
export const LIGHT = "#e6e8eb";

export interface Pt {
  x: number;
  y: number;
}

/** A circuit path projected into viewBox coordinates. */
export interface TrackGeometry {
  n: number;
  width: number;
  height: number;
  /** Screen coordinates of each path point. */
  px: number[];
  py: number[];
  /** Lap distance (m) of each path point, non-decreasing. */
  dist: number[];
  /** SVG path data for the whole lap. */
  path: string;
  /** Project a raw (unrotated) position into viewBox coordinates. */
  toScreen: (x: number, y: number) => Pt;
}

export interface CornerLabel {
  key: string;
  name: string;
  x: number;
  y: number;
}

/** A corner to label: its name, lap distance and on-screen anchor. */
export interface CornerSource {
  name: string;
  distance_m: number;
  p: Pt;
}

export interface StartFinishGeometry {
  /** Start/finish point and the normal across the track there. */
  p0: Pt;
  n0: Pt;
  /** Direction arrow shaft, drawn beside the track shortly after the line. */
  pts: Pt[];
  /** Unit tangent at the arrow head. */
  tEnd: Pt;
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
export const fmt = (v: number) => v.toFixed(1);

/** FastF1 convention: rotate by `rotationDeg`, then flip y so north is up on screen. */
export function makeRotation(rotationDeg: number): (x: number, y: number) => Pt {
  const r = ((Number.isFinite(rotationDeg) ? rotationDeg : 0) * Math.PI) / 180;
  const cos = Math.cos(r);
  const sin = Math.sin(r);
  return (x, y) => ({ x: x * cos - y * sin, y: -(x * sin + y * cos) });
}

/**
 * Cumulative distance (m) along a raw path. FastF1 positions are in 1/10 m, hence the default
 * `unitsPerMetre` of 10.
 */
export function cumulativeDistance(xs: number[], ys: number[], unitsPerMetre = 10): number[] {
  const n = Math.min(xs.length, ys.length);
  const out: number[] = new Array(n);
  let total = 0;
  for (let i = 0; i < n; i++) {
    if (i > 0) {
      const step = Math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]) / unitsPerMetre;
      if (Number.isFinite(step)) total += step;
    }
    out[i] = total;
  }
  return out;
}

/**
 * Rotate, flip and fit a raw path into a `VIEW_W`-wide viewBox. The height follows the circuit's
 * aspect ratio, clamped to 0.45..0.75 of the width. Returns null when the path is unusable
 * (too short, all zeros or non-finite values).
 */
export function buildTrackGeometry(
  xs: number[] | null | undefined,
  ys: number[] | null | undefined,
  dist: number[],
  rotationDeg: number,
): TrackGeometry | null {
  if (!Array.isArray(xs) || !Array.isArray(ys)) return null;
  const n = Math.min(xs.length, ys.length, dist.length);
  if (n < 10 || xs.every((v) => v === 0)) return null;
  for (let i = 0; i < n; i++) {
    if (!Number.isFinite(xs[i]) || !Number.isFinite(ys[i]) || !Number.isFinite(dist[i])) return null;
  }

  const rotate = makeRotation(rotationDeg);
  const rx: number[] = new Array(n);
  const ry: number[] = new Array(n);
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (let i = 0; i < n; i++) {
    const p = rotate(xs[i], ys[i]);
    rx[i] = p.x;
    ry[i] = p.y;
    minX = Math.min(minX, p.x);
    maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y);
    maxY = Math.max(maxY, p.y);
  }
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const width = VIEW_W;
  const height = Math.round(VIEW_W * clamp(spanY / spanX, 0.45, 0.75));
  const scale = Math.min((width - 2 * PAD) / spanX, (height - 2 * PAD) / spanY);
  const ox = (width - spanX * scale) / 2 - minX * scale;
  const oy = (height - spanY * scale) / 2 - minY * scale;
  const toScreen = (x: number, y: number): Pt => {
    const p = rotate(x, y);
    return { x: p.x * scale + ox, y: p.y * scale + oy };
  };
  const px = rx.map((x) => x * scale + ox);
  const py = ry.map((y) => y * scale + oy);

  let path = `M${fmt(px[0])} ${fmt(py[0])}`;
  for (let i = 1; i < n; i++) path += `L${fmt(px[i])} ${fmt(py[i])}`;

  return { n, width, height, px, py, dist: dist.slice(0, n), path, toScreen };
}

/** Screen position at a lap distance, linearly interpolated along the path. */
export function pointAt(geo: TrackGeometry, d: number): Pt {
  const { dist, px, py, n } = geo;
  if (d <= dist[0]) return { x: px[0], y: py[0] };
  if (d >= dist[n - 1]) return { x: px[n - 1], y: py[n - 1] };
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (dist[mid] <= d) lo = mid;
    else hi = mid;
  }
  const span = dist[hi] - dist[lo];
  const t = span > 0 ? (d - dist[lo]) / span : 0;
  return { x: px[lo] + (px[hi] - px[lo]) * t, y: py[lo] + (py[hi] - py[lo]) * t };
}

/** Unit tangent (direction of travel) at a lap distance. */
export function tangentAt(geo: TrackGeometry, d: number): Pt {
  const a = pointAt(geo, d - 12);
  const b = pointAt(geo, d + 12);
  const len = Math.hypot(b.x - a.x, b.y - a.y);
  return len > 1e-6 ? { x: (b.x - a.x) / len, y: (b.y - a.y) / len } : { x: 1, y: 0 };
}

/** Index of the path point closest to a screen position, with its distance in viewBox units. */
export function nearestIndex(geo: TrackGeometry, p: Pt): { index: number; distance: number } {
  let best = -1;
  let bestD = Infinity;
  for (let i = 0; i < geo.n; i++) {
    const dd = (geo.px[i] - p.x) ** 2 + (geo.py[i] - p.y) ** 2;
    if (dd < bestD) {
      bestD = dd;
      best = i;
    }
  }
  return { index: best, distance: Math.sqrt(bestD) };
}

/** +1 or -1: which side of the path (along the left normal) has more free space at `p`. */
export function freeSide(geo: TrackGeometry, p: Pt, normal: Pt, offset: number): 1 | -1 {
  const stride = Math.max(1, Math.floor(geo.n / 400));
  const clearance = (q: Pt) => {
    let best = Infinity;
    for (let i = 0; i < geo.n; i += stride) {
      best = Math.min(best, (geo.px[i] - q.x) ** 2 + (geo.py[i] - q.y) ** 2);
    }
    const inside = q.x > 0 && q.x < geo.width && q.y > 0 && q.y < geo.height;
    return inside ? best : best / 4;
  };
  const plus = clearance({ x: p.x + normal.x * offset, y: p.y + normal.y * offset });
  const minus = clearance({ x: p.x - normal.x * offset, y: p.y - normal.y * offset });
  return plus >= minus ? 1 : -1;
}

export function nearestCornerName(d: number, corners: { name: string; distance_m: number }[]): string | null {
  let best: string | null = null;
  let bestGap = Infinity;
  for (const c of corners) {
    const gap = Math.abs(c.distance_m - d);
    if (gap < bestGap) {
      bestGap = gap;
      best = c.name;
    }
  }
  return best;
}

/**
 * Corner labels pushed off the track towards the side with more free space, kept inside the
 * viewBox. `k` scales sizes up on narrow screens.
 */
export function placeCornerLabels(geo: TrackGeometry, corners: CornerSource[], k: number): CornerLabel[] {
  const offset = 22 * k;
  return corners.map((c) => {
    const t = tangentAt(geo, c.distance_m);
    const normal = { x: -t.y, y: t.x };
    const s = freeSide(geo, c.p, normal, offset);
    return {
      key: `${c.name}-${c.distance_m}`,
      name: c.name,
      x: clamp(c.p.x + normal.x * offset * s, 14 * k, geo.width - 14 * k),
      y: clamp(c.p.y + normal.y * offset * s, 10 * k, geo.height - 10 * k),
    };
  });
}

/** Start/finish bar position and a short direction-of-travel arrow beside the track. */
export function startFinishGeometry(geo: TrackGeometry): StartFinishGeometry {
  const lapLen = geo.dist[geo.n - 1] - geo.dist[0];
  const p0 = pointAt(geo, geo.dist[0]);
  const t0 = tangentAt(geo, geo.dist[0] + 6);
  const n0 = { x: -t0.y, y: t0.x };
  const from = geo.dist[0] + Math.min(60, lapLen * 0.012);
  const to = from + Math.min(240, lapLen * 0.05);
  const mid = pointAt(geo, (from + to) / 2);
  const tm = tangentAt(geo, (from + to) / 2);
  const side = freeSide(geo, mid, { x: -tm.y, y: tm.x }, 20);
  const pts: Pt[] = [];
  for (let i = 0; i <= 8; i++) {
    const d = from + ((to - from) * i) / 8;
    const p = pointAt(geo, d);
    const t = tangentAt(geo, d);
    pts.push({ x: p.x - t.y * 18 * side, y: p.y + t.x * 18 * side });
  }
  const tEnd = tangentAt(geo, to);
  return { p0, n0, pts, tEnd };
}

/** SVG `points` for a triangle centred at (x, y) pointing along the unit vector (tx, ty). */
export function trianglePoints(x: number, y: number, tx: number, ty: number, size: number): string {
  const nx = -ty;
  const ny = tx;
  const tip = `${fmt(x + tx * size)},${fmt(y + ty * size)}`;
  const l = `${fmt(x - tx * size * 0.7 + nx * size * 0.75)},${fmt(y - ty * size * 0.7 + ny * size * 0.75)}`;
  const r = `${fmt(x - tx * size * 0.7 - nx * size * 0.75)},${fmt(y - ty * size * 0.7 - ny * size * 0.75)}`;
  return `${tip} ${l} ${r}`;
}

/** Convert a client (pointer) position to viewBox coordinates using the SVG's screen CTM. */
export function clientToView(svg: SVGSVGElement, clientX: number, clientY: number): Pt | null {
  const ctm = svg.getScreenCTM();
  if (!ctm) return null;
  const local = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
  return { x: local.x, y: local.y };
}
