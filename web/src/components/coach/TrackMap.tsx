"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { deltaTone } from "@/lib/format";
import type { CompareCorner, CompareGrid, CompareTrack } from "@/lib/types";
import { CornerLabels, StartFinishIcon, StartFinishMark } from "@/components/track/TrackDecorations";
import {
  LIGHT,
  SURFACE,
  VIEW_W,
  buildTrackGeometry,
  clamp,
  clientToView,
  fmt,
  nearestCornerName,
  nearestIndex,
  placeCornerLabels,
  pointAt,
  startFinishGeometry,
  tangentAt,
  trianglePoints,
  type CornerLabel,
  type Pt,
  type TrackGeometry,
} from "@/components/track/trackGeometry";
import { COLORS } from "./chartTheme";

/** Distance (m) over which the local gain is averaged before colouring. */
const SMOOTH_M = 24;
/** Local gains below this many ms per metre count as noise and stay neutral. */
const MIN_RATE = 0.01;
/** Rates at or above this percentile of |rate| get full intensity. */
const SATURATE_PCT = 0.9;
const LEVELS = 5;
/** Pointer must be within this many viewBox units of the path to show the tooltip. */
const HOVER_RADIUS = 90;

interface Run {
  d: string;
  side: "a" | "b";
  level: number;
}

interface Geometry extends TrackGeometry {
  delta: number[];
  /** Smoothed local gain per segment (ms per metre); negative = A gaining. */
  rate: number[];
  refRate: number;
  runs: Run[];
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

function levelOf(rate: number, refRate: number): number {
  const m = Math.abs(rate);
  if (!Number.isFinite(m) || m < MIN_RATE) return 0;
  return clamp(Math.ceil((m / refRate) * LEVELS), 1, LEVELS);
}

function buildGeometry(track: CompareTrack | null | undefined, grid: CompareGrid): Geometry | null {
  if (!track) return null;
  const dist = grid.distance_m ?? [];
  const rawDelta = grid.delta_ms ?? [];
  const base = buildTrackGeometry(track.x, track.y, dist, track.rotation_deg);
  if (!base) return null;
  const { n, px, py } = base;
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

  return { ...base, delta, rate, refRate, runs };
}

function formatGap(ms: number, driverA: string): string {
  const s = ms / 1000;
  if (Math.abs(s) < 0.005) return "level";
  return `${s > 0 ? "+" : "-"}${Math.abs(s).toFixed(2)} s ${driverA} ${s > 0 ? "behind" : "ahead"}`;
}

function TrianglePoints({ x, y, tx, ty, size }: { x: number; y: number; tx: number; ty: number; size: number }) {
  return <polygon points={trianglePoints(x, y, tx, ty, size)} />;
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

  const labels = useMemo<CornerLabel[]>(() => {
    if (!geo) return [];
    const source =
      track?.corners && track.corners.length > 0
        ? track.corners.map((c) => ({
            name: c.name,
            distance_m: c.distance_m,
            p: c.x !== 0 || c.y !== 0 ? geo.toScreen(c.x, c.y) : pointAt(geo, c.distance_m),
          }))
        : corners.map((c) => ({ name: c.name, distance_m: c.distance_m, p: pointAt(geo, c.distance_m) }));
    return placeCornerLabels(geo, source, k);
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

  const startFinish = useMemo(() => (geo ? startFinishGeometry(geo) : null), [geo]);

  if (!geo) return null;

  const hoverIdx = hover != null && hover < geo.n ? hover : null;

  function flush() {
    frame.current = null;
    const svg = svgRef.current;
    const p = pending.current;
    if (!svg || !p || !geo) return;
    const local = clientToView(svg, p.x, p.y);
    if (!local) return;
    const { index: best, distance } = nearestIndex(geo, local);
    const idx = best >= 0 && distance <= HOVER_RADIUS * k ? best : null;
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

          {startFinish && <StartFinishMark sf={startFinish} k={k} />}

          {visibleMarkers.map((m) => (
            <MarkerShape key={m.key} m={m} k={k} />
          ))}

          <CornerLabels labels={labels} k={k} />

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
          <StartFinishIcon />
          Start/finish
        </span>
      </div>
      <figcaption className="mt-2 text-xs text-muted">
        {driverA}&apos;s line, coloured by who is gaining time on each stretch; thicker and brighter means
        a bigger gain per metre. Hover the track to read the gap and speeds at that point.
      </figcaption>
    </figure>
  );
}
