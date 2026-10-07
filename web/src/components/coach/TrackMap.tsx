"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { deltaTone } from "@/lib/format";
import type { CompareCorner, CompareGrid, CompareTrack } from "@/lib/types";
import { COLORS } from "./chartTheme";

const VIEW_W = 1000;
const PAD = 64;
/** Distance (m) over which the local gain is averaged before colouring. */
const SMOOTH_M = 24;
/** Local gains below this many ms per metre count as noise and stay neutral. */
const MIN_RATE = 0.01;
/** Rates at or above this percentile of |rate| get full intensity. */
const SATURATE_PCT = 0.9;
const LEVELS = 5;
const SURFACE = "#13161b";
const LIGHT = "#e6e8eb";
/** Pointer must be within this many viewBox units of the path to show the tooltip. */
const HOVER_RADIUS = 90;

interface Pt {
  x: number;
  y: number;
}

interface Run {
  d: string;
  side: "a" | "b";
  level: number;
}

interface Geometry {
  n: number;
  width: number;
  height: number;
  px: number[];
  py: number[];
  dist: number[];
  delta: number[];
  /** Smoothed local gain per segment (ms per metre); negative = A gaining. */
  rate: number[];
  refRate: number;
  path: string;
  runs: Run[];
  toScreen: (x: number, y: number) => Pt;
}

interface Label {
  key: string;
  name: string;
  x: number;
  y: number;
}

type MarkerKind = "brake" | "apex" | "throttle";

interface Marker {
  key: string;
  kind: MarkerKind;
  side: "a" | "b";
  x: number;
  y: number;
  /** Unit tangent (direction of travel). */
  tx: number;
  ty: number;
  title: string;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const fmt = (v: number) => v.toFixed(1);

function levelOf(rate: number, refRate: number): number {
  const m = Math.abs(rate);
  if (!Number.isFinite(m) || m < MIN_RATE) return 0;
  return clamp(Math.ceil((m / refRate) * LEVELS), 1, LEVELS);
}

function buildGeometry(track: CompareTrack | null | undefined, grid: CompareGrid): Geometry | null {
  if (!track || !Array.isArray(track.x) || !Array.isArray(track.y)) return null;
  const dist = grid.distance_m ?? [];
  const rawDelta = grid.delta_ms ?? [];
  const n = Math.min(track.x.length, track.y.length, dist.length);
  if (n < 10 || track.x.every((v) => v === 0)) return null;
  for (let i = 0; i < n; i++) {
    if (!Number.isFinite(track.x[i]) || !Number.isFinite(track.y[i]) || !Number.isFinite(dist[i])) {
      return null;
    }
  }

  // FastF1 convention: rotate, then flip y so north is up on screen.
  const r = ((Number.isFinite(track.rotation_deg) ? track.rotation_deg : 0) * Math.PI) / 180;
  const cos = Math.cos(r);
  const sin = Math.sin(r);
  const rotate = (x: number, y: number): Pt => ({ x: x * cos - y * sin, y: -(x * sin + y * cos) });

  const rx: number[] = new Array(n);
  const ry: number[] = new Array(n);
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (let i = 0; i < n; i++) {
    const p = rotate(track.x[i], track.y[i]);
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
  const delta = Array.from({ length: n }, (_, i) => {
    const v = rawDelta[i];
    return Number.isFinite(v) ? v : 0;
  });

  // Local gain: d(delta)/d(distance), averaged over a short window via prefix sums.
  const segs = n - 1;
  const sumD = new Array<number>(segs + 1).fill(0);
  const sumS = new Array<number>(segs + 1).fill(0);
  for (let i = 0; i < segs; i++) {
    sumD[i + 1] = sumD[i] + (delta[i + 1] - delta[i]);
    sumS[i + 1] = sumS[i] + Math.max(dist[i + 1] - dist[i], 0);
  }
  const step = Math.max((dist[n - 1] - dist[0]) / segs, 1e-6);
  const half = Math.max(1, Math.round(SMOOTH_M / (2 * step)));
  const rate: number[] = new Array(segs);
  for (let i = 0; i < segs; i++) {
    const lo = Math.max(0, i - half);
    const hi = Math.min(segs - 1, i + half);
    const ds = sumS[hi + 1] - sumS[lo];
    rate[i] = ds > 1e-6 ? (sumD[hi + 1] - sumD[lo]) / ds : 0;
  }
  const sorted = rate.map(Math.abs).sort((p, q) => p - q);
  const refRate = Math.max(sorted[Math.floor((sorted.length - 1) * SATURATE_PCT)] ?? 0, MIN_RATE * 2);

  // Merge consecutive segments with the same side and intensity into one path.
  const runs: Run[] = [];
  let cur: (Run & { key: number }) | null = null;
  for (let i = 0; i < segs; i++) {
    const level = levelOf(rate[i], refRate);
    const side = rate[i] < 0 ? "a" : "b";
    const key = level === 0 ? 0 : side === "a" ? -level : level;
    if (!cur || cur.key !== key) {
      if (cur && cur.key !== 0) runs.push(cur);
      cur = { key, side, level, d: `M${fmt(px[i])} ${fmt(py[i])}` };
    }
    cur.d += `L${fmt(px[i + 1])} ${fmt(py[i + 1])}`;
  }
  if (cur && cur.key !== 0) runs.push(cur);

  let path = `M${fmt(px[0])} ${fmt(py[0])}`;
  for (let i = 1; i < n; i++) path += `L${fmt(px[i])} ${fmt(py[i])}`;

  return { n, width, height, px, py, dist: dist.slice(0, n), delta, rate, refRate, path, runs, toScreen };
}

/** Screen position at a lap distance, linearly interpolated along the grid. */
function pointAt(geo: Geometry, d: number): Pt {
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
function tangentAt(geo: Geometry, d: number): Pt {
  const a = pointAt(geo, d - 12);
  const b = pointAt(geo, d + 12);
  const len = Math.hypot(b.x - a.x, b.y - a.y);
  return len > 1e-6 ? { x: (b.x - a.x) / len, y: (b.y - a.y) / len } : { x: 1, y: 0 };
}

/** +1 or -1: which side of the path (along the left normal) has more free space at `p`. */
function freeSide(geo: Geometry, p: Pt, normal: Pt, offset: number): 1 | -1 {
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

function nearestCornerName(d: number, corners: { name: string; distance_m: number }[]): string | null {
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

function formatGap(ms: number, driverA: string): string {
  const s = ms / 1000;
  if (Math.abs(s) < 0.005) return "level";
  return `${s > 0 ? "+" : "-"}${Math.abs(s).toFixed(2)} s ${driverA} ${s > 0 ? "behind" : "ahead"}`;
}

function TrianglePoints({ x, y, tx, ty, size }: { x: number; y: number; tx: number; ty: number; size: number }) {
  const nx = -ty;
  const ny = tx;
  const tip = `${fmt(x + tx * size)},${fmt(y + ty * size)}`;
  const l = `${fmt(x - tx * size * 0.7 + nx * size * 0.75)},${fmt(y - ty * size * 0.7 + ny * size * 0.75)}`;
  const r = `${fmt(x - tx * size * 0.7 - nx * size * 0.75)},${fmt(y - ty * size * 0.7 - ny * size * 0.75)}`;
  return <polygon points={`${tip} ${l} ${r}`} />;
}

function MarkerShape({ m, k }: { m: Marker; k: number }) {
  const color = m.side === "a" ? COLORS.a : COLORS.b;
  if (m.kind === "brake") {
    return (
      <circle cx={m.x} cy={m.y} r={4.2 * k} fill={color} stroke={SURFACE} strokeWidth={1.2 * k}>
        <title>{m.title}</title>
      </circle>
    );
  }
  if (m.kind === "apex") {
    return (
      <circle cx={m.x} cy={m.y} r={5.5 * k} fill="none" stroke={color} strokeWidth={1.8 * k}>
        <title>{m.title}</title>
      </circle>
    );
  }
  return (
    <g fill={color} stroke={SURFACE} strokeWidth={1 * k}>
      <title>{m.title}</title>
      <TrianglePoints x={m.x} y={m.y} tx={m.tx} ty={m.ty} size={6.5 * k} />
    </g>
  );
}

function LegendIcon({ kind, color }: { kind: MarkerKind; color: string }) {
  return (
    <svg viewBox="0 0 14 14" className="h-3.5 w-3.5" aria-hidden>
      {kind === "brake" && <circle cx={7} cy={7} r={4} fill={color} />}
      {kind === "apex" && <circle cx={7} cy={7} r={4.5} fill="none" stroke={color} strokeWidth={1.6} />}
      {kind === "throttle" && <polygon points="12,7 3,2.5 3,11.5" fill={color} />}
    </svg>
  );
}

const MARKER_LABELS: Record<MarkerKind, string> = {
  brake: "Brake point",
  apex: "Apex",
  throttle: "Throttle on",
};

const TOGGLE_LABELS: Record<MarkerKind, string> = {
  brake: "Brake points",
  apex: "Apexes",
  throttle: "Throttle on",
};

export function TrackMap({
  track,
  grid,
  corners,
  driverA,
  driverB,
  onHoverDistance,
}: {
  track: CompareTrack | null | undefined;
  grid: CompareGrid;
  corners: CompareCorner[];
  driverA: string;
  driverB: string;
  onHoverDistance?: (distance: number | null) => void;
}) {
  const geo = useMemo(() => buildGeometry(track, grid), [track, grid]);
  const [show, setShow] = useState<Record<MarkerKind, boolean>>({ brake: true, apex: false, throttle: false });
  const [hover, setHover] = useState<number | null>(null);
  const [pxWidth, setPxWidth] = useState(VIEW_W);
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const frame = useRef<number | null>(null);
  const pending = useRef<Pt | null>(null);

  const hasGeo = geo != null;
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.width > 0) setPxWidth(entry.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [hasGeo]);

  useEffect(
    () => () => {
      if (frame.current != null) cancelAnimationFrame(frame.current);
    },
    [],
  );

  // Marker and label sizes are in viewBox units; scale them up on narrow screens.
  const k = clamp(VIEW_W / pxWidth, 1, 2.4);

  const labels = useMemo<Label[]>(() => {
    if (!geo) return [];
    const source =
      track?.corners && track.corners.length > 0
        ? track.corners.map((c) => ({
            name: c.name,
            distance_m: c.distance_m,
            p: c.x !== 0 || c.y !== 0 ? geo.toScreen(c.x, c.y) : pointAt(geo, c.distance_m),
          }))
        : corners.map((c) => ({ name: c.name, distance_m: c.distance_m, p: pointAt(geo, c.distance_m) }));
    const offset = 22 * k;
    return source.map((c) => {
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
  }, [geo, track, corners, k]);

  const markers = useMemo<Marker[]>(() => {
    if (!geo) return [];
    const out: Marker[] = [];
    const add = (kind: MarkerKind, side: "a" | "b", d: number | null | undefined, corner: string) => {
      if (d == null || !Number.isFinite(d)) return;
      const p = pointAt(geo, d);
      const t = tangentAt(geo, d);
      // Nudge A and B to opposite sides of the line so coincident markers stay readable.
      const nudge = (side === "a" ? -1 : 1) * 3.5;
      const driver = side === "a" ? driverA : driverB;
      out.push({
        key: `${kind}-${side}-${corner}-${d}`,
        kind,
        side,
        x: p.x - t.y * nudge,
        y: p.y + t.x * nudge,
        tx: t.x,
        ty: t.y,
        title: `${driver} ${MARKER_LABELS[kind].toLowerCase()} at ${Math.round(d)} m (${corner})`,
      });
    };
    for (const c of corners) {
      add("brake", "a", c.brake_point_a_m, c.name);
      add("brake", "b", c.brake_point_b_m, c.name);
      add("apex", "a", c.apex_a_m, c.name);
      add("apex", "b", c.apex_b_m, c.name);
      add("throttle", "a", c.throttle_on_a_m, c.name);
      add("throttle", "b", c.throttle_on_b_m, c.name);
    }
    return out;
  }, [geo, corners, driverA, driverB]);

  const startFinish = useMemo(() => {
    if (!geo) return null;
    const lapLen = geo.dist[geo.n - 1] - geo.dist[0];
    const p0 = pointAt(geo, geo.dist[0]);
    const t0 = tangentAt(geo, geo.dist[0] + 6);
    const n0 = { x: -t0.y, y: t0.x };
    // Direction arrow: a short stretch shortly after the line, drawn beside the track.
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
  }, [geo]);

  if (!geo) return null;

  const hoverIdx = hover != null && hover < geo.n ? hover : null;

  function flush() {
    frame.current = null;
    const svg = svgRef.current;
    const p = pending.current;
    if (!svg || !p || !geo) return;
    const ctm = svg.getScreenCTM();
    if (!ctm) return;
    const local = new DOMPoint(p.x, p.y).matrixTransform(ctm.inverse());
    let best = -1;
    let bestD = Infinity;
    for (let i = 0; i < geo.n; i++) {
      const dd = (geo.px[i] - local.x) ** 2 + (geo.py[i] - local.y) ** 2;
      if (dd < bestD) {
        bestD = dd;
        best = i;
      }
    }
    const idx = best >= 0 && Math.sqrt(bestD) <= HOVER_RADIUS * k ? best : null;
    setHover(idx);
    onHoverDistance?.(idx == null ? null : geo.dist[idx]);
  }

  function handleMove(e: React.PointerEvent<SVGSVGElement>) {
    pending.current = { x: e.clientX, y: e.clientY };
    if (frame.current == null) frame.current = requestAnimationFrame(flush);
  }

  function handleLeave() {
    if (frame.current != null) cancelAnimationFrame(frame.current);
    frame.current = null;
    pending.current = null;
    setHover(null);
    onHoverDistance?.(null);
  }

  const tooltip = (() => {
    if (hoverIdx == null) return null;
    const d = geo.dist[hoverIdx];
    const gap = geo.delta[hoverIdx];
    const rate = geo.rate[Math.min(hoverIdx, geo.rate.length - 1)];
    const level = levelOf(rate, geo.refRate);
    const corner = nearestCornerName(d, corners.length > 0 ? corners : (track?.corners ?? []));
    const speedA = grid.speed_a?.[hoverIdx];
    const speedB = grid.speed_b?.[hoverIdx];
    const x = geo.px[hoverIdx];
    const y = geo.py[hoverIdx];
    const flipX = x > geo.width * 0.6;
    const flipY = y > geo.height * 0.65;
    return (
      <div
        className="tabular pointer-events-none absolute z-10 min-w-40 rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-lg"
        style={{
          left: `${(x / geo.width) * 100}%`,
          top: `${(y / geo.height) * 100}%`,
          transform: `translate(${flipX ? "calc(-100% - 14px)" : "14px"}, ${flipY ? "calc(-100% - 10px)" : "10px"})`,
        }}
      >
        <p className="text-muted">
          {Math.round(d).toLocaleString("en-US")} m{corner ? ` · near ${corner}` : ""}
        </p>
        <p className={`mt-1 font-medium ${deltaTone(gap)}`}>{formatGap(gap, driverA)}</p>
        <p className="mt-1 flex gap-3">
          <span className="text-driver-a">
            {driverA} {Number.isFinite(speedA) ? `${Math.round(speedA)} km/h` : "-"}
          </span>
          <span className="text-driver-b">
            {driverB} {Number.isFinite(speedB) ? `${Math.round(speedB)} km/h` : "-"}
          </span>
        </p>
        <p className="mt-1 text-muted">
          {level === 0 ? (
            "Even here"
          ) : (
            <>
              <span className={rate < 0 ? "text-driver-a" : "text-driver-b"}>{rate < 0 ? driverA : driverB}</span>{" "}
              gaining here ({(Math.abs(rate) * 100).toFixed(1)} ms/100 m)
            </>
          )}
        </p>
      </div>
    );
  })();

  const visibleMarkers = markers.filter((m) => show[m.kind]);
  const hx = hoverIdx != null ? geo.px[hoverIdx] : 0;
  const hy = hoverIdx != null ? geo.py[hoverIdx] : 0;

  return (
    <figure className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h3 className="text-sm font-medium">Where the time goes</h3>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {(Object.keys(MARKER_LABELS) as MarkerKind[]).map((kind) => (
            <label key={kind} className="flex cursor-pointer items-center gap-2 text-xs text-muted">
              <input
                type="checkbox"
                checked={show[kind]}
                onChange={(e) => setShow((s) => ({ ...s, [kind]: e.target.checked }))}
                className="accent-[var(--accent)]"
              />
              {TOGGLE_LABELS[kind]}
            </label>
          ))}
        </div>
      </div>

      <div ref={wrapRef} className="relative w-full">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${geo.width} ${geo.height}`}
          width="100%"
          className="block h-auto touch-none select-none"
          role="img"
          aria-label={`Track map coloured by where ${driverA} and ${driverB} gain time`}
          onPointerMove={handleMove}
          onPointerLeave={handleLeave}
        >
          <path d={geo.path} fill="none" stroke={COLORS.grid} strokeWidth={14} strokeLinejoin="round" strokeLinecap="round" />
          <path d={geo.path} fill="none" stroke={COLORS.zero} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {geo.runs.map((run, i) => (
            <path
              key={i}
              d={run.d}
              fill="none"
              stroke={run.side === "a" ? COLORS.a : COLORS.b}
              strokeOpacity={0.3 + (0.7 * run.level) / LEVELS}
              strokeWidth={2.5 + (5.5 * run.level) / LEVELS}
              strokeLinejoin="round"
              strokeLinecap="butt"
            />
          ))}

          {startFinish && (
            <g>
              <line
                x1={startFinish.p0.x - startFinish.n0.x * 12 * k}
                y1={startFinish.p0.y - startFinish.n0.y * 12 * k}
                x2={startFinish.p0.x + startFinish.n0.x * 12 * k}
                y2={startFinish.p0.y + startFinish.n0.y * 12 * k}
                stroke={LIGHT}
                strokeWidth={4 * k}
              />
              <line
                x1={startFinish.p0.x - startFinish.n0.x * 12 * k}
                y1={startFinish.p0.y - startFinish.n0.y * 12 * k}
                x2={startFinish.p0.x + startFinish.n0.x * 12 * k}
                y2={startFinish.p0.y + startFinish.n0.y * 12 * k}
                stroke={SURFACE}
                strokeWidth={4 * k}
                strokeDasharray={`${3 * k} ${3 * k}`}
              />
              <polyline
                points={startFinish.pts.map((p) => `${fmt(p.x)},${fmt(p.y)}`).join(" ")}
                fill="none"
                stroke={COLORS.axis}
                strokeWidth={1.6 * k}
                strokeLinecap="round"
              />
              <g fill={COLORS.axis}>
                <TrianglePoints
                  x={startFinish.pts[startFinish.pts.length - 1].x}
                  y={startFinish.pts[startFinish.pts.length - 1].y}
                  tx={startFinish.tEnd.x}
                  ty={startFinish.tEnd.y}
                  size={6 * k}
                />
              </g>
              <title>Start/finish line and direction of travel</title>
            </g>
          )}

          {visibleMarkers.map((m) => (
            <MarkerShape key={m.key} m={m} k={k} />
          ))}

          {labels.map((l) => (
            <text
              key={l.key}
              x={l.x}
              y={l.y}
              textAnchor="middle"
              dominantBaseline="central"
              fill={COLORS.axis}
              fontSize={12 * k}
              fontWeight={500}
              stroke={SURFACE}
              strokeWidth={3 * k}
              paintOrder="stroke"
            >
              {l.name}
            </text>
          ))}

          {hoverIdx != null && (
            <g pointerEvents="none">
              <circle cx={hx} cy={hy} r={11 * k} fill="none" stroke={LIGHT} strokeOpacity={0.35} strokeWidth={1.5 * k} />
              <circle cx={hx} cy={hy} r={5 * k} fill={LIGHT} stroke={SURFACE} strokeWidth={1.5 * k} />
            </g>
          )}
        </svg>
        {tooltip}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-1 w-5 rounded-full bg-driver-a" />
          {driverA} gaining
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-1 w-5 rounded-full bg-driver-b" />
          {driverB} gaining
        </span>
        {(Object.keys(MARKER_LABELS) as MarkerKind[]).map((kind) => (
          <span key={kind} className="flex items-center gap-1">
            <LegendIcon kind={kind} color={COLORS.a} />
            <LegendIcon kind={kind} color={COLORS.b} />
            <span className="ml-0.5">{MARKER_LABELS[kind]}</span>
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <svg viewBox="0 0 14 14" className="h-3.5 w-3.5" aria-hidden>
            <line x1={7} y1={1} x2={7} y2={13} stroke={LIGHT} strokeWidth={4} />
            <line x1={7} y1={1} x2={7} y2={13} stroke={SURFACE} strokeWidth={4} strokeDasharray="3 3" />
          </svg>
          Start/finish
        </span>
      </div>
      <figcaption className="mt-2 text-xs text-muted">
        Driver {driverA}&apos;s line, coloured by who is gaining time on each stretch; thicker and brighter means
        a bigger gain per metre. Hover the track to read the gap and speeds at that point.
      </figcaption>
    </figure>
  );
}
