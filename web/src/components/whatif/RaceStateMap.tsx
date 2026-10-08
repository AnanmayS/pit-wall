"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { COLORS } from "@/components/coach/chartTheme";
import { Section } from "@/components/Field";
import { Spinner } from "@/components/Notice";
import { CornerLabels, StartFinishIcon, StartFinishMark } from "@/components/track/TrackDecorations";
import {
  LIGHT,
  SURFACE,
  VIEW_W,
  buildTrackGeometry,
  clamp,
  clientToView,
  cumulativeDistance,
  freeSide,
  nearestIndex,
  placeCornerLabels,
  pointAt,
  startFinishGeometry,
  tangentAt,
  type CornerLabel,
  type Pt,
  type TrackGeometry,
} from "@/components/track/trackGeometry";
import { ApiError, getWhatIfTrack, paths, toApiError } from "@/lib/api";
import { driverName, driverSurname, useDrivers, type DriverMap } from "@/lib/drivers";
import { teamColor } from "@/lib/teams";
import type { CarOnTrack, RaceStateMap as RaceState } from "@/lib/types";

/** Pointer must be within this many viewBox units of a dot (times `k`) to pick it. */
const HOVER_RADIUS = 26;
const DOT_R = 7;
const CHANGED_R = 10;
const RING = "#ffffff";

interface Car extends CarOnTrack {
  /** "Lando Norris" */
  name: string;
  /** "Norris", for the map label and the running order. */
  surname: string;
  /** Gap behind the leader car (ms), never negative. */
  gapMs: number;
  isLeader: boolean;
  lapped: boolean;
  changed: boolean;
  color: string;
  /** Screen position, or null when the car has no usable coordinates. */
  p: Pt | null;
}

interface DotLabel {
  driver: string;
  text: string;
  x: number;
  y: number;
  /** Where a short leader line meets the dot when the label had to move away from it. */
  lineFrom: Pt | null;
  lineTo: Pt | null;
}

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

function formatGap(car: Car): string {
  if (car.isLeader || car.gapMs <= 0) return "leader";
  return `+${(car.gapMs / 1000).toFixed(1)} s to leader`;
}

function formatTyre(car: CarOnTrack): string | null {
  const compound = (car.compound ?? "").trim().toUpperCase();
  if (!compound || compound === "UNKNOWN" || compound === "NAN" || compound === "NONE") return null;
  if (!Number.isFinite(car.tyre_life)) return compound;
  return `${compound}, ${car.tyre_life} lap${car.tyre_life === 1 ? "" : "s"}`;
}

/** "P2 Lando Norris · McLaren · +2.8 s to leader · MEDIUM, 15 laps" */
function describeCar(car: Car): string {
  const parts = [
    car.position != null ? `P${car.position} ${car.name}` : car.name,
    car.team || "Unknown team",
    `${formatGap(car)}${car.lapped ? " (lapped)" : ""}`,
  ];
  const tyre = formatTyre(car);
  if (tyre) parts.push(tyre);
  if (car.in_pit) parts.push("in the pit lane");
  return parts.join(" · ");
}

function prepareCars(
  state: RaceState,
  geo: TrackGeometry | null,
  changed: Set<string>,
  names: DriverMap,
): Car[] {
  const cars = state.cars ?? [];
  const leaderCar =
    cars.find((c) => c.driver === state.leader) ?? cars.find((c) => c.position === 1) ?? cars[0] ?? null;
  const leaderGap = leaderCar && Number.isFinite(leaderCar.gap_to_leader_ms) ? leaderCar.gap_to_leader_ms : 0;
  const leaderLap = leaderCar && Number.isFinite(leaderCar.lap_number) ? leaderCar.lap_number : state.lap;
  return cars.map((c) => {
    const usable = geo != null && Number.isFinite(c.x) && Number.isFinite(c.y) && (c.x !== 0 || c.y !== 0);
    const gap = Number.isFinite(c.gap_to_leader_ms) ? c.gap_to_leader_ms - leaderGap : 0;
    return {
      ...c,
      name: driverName(names, c.driver, c.driver_name),
      surname: driverSurname(names, c.driver, c.driver_name),
      gapMs: Math.max(0, gap),
      isLeader: c === leaderCar,
      lapped: Number.isFinite(c.lap_number) && c.lap_number < leaderLap,
      changed: changed.has(c.driver),
      color: teamColor(c.team),
      p: usable && geo ? geo.toScreen(c.x, c.y) : null,
    };
  });
}

const overlap = (a: Box, b: Box) =>
  Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));

/**
 * Put each driver's surname beside its dot, on the side of the track with more room, stepping further
 * out (or to the other side) when the spot is already taken by another label or dot.
 */
function placeDotLabels(geo: TrackGeometry, cars: Car[], k: number): DotLabel[] {
  const onMap = cars.filter((c) => c.p != null);
  const dots: Box[] = onMap.map((c) => {
    const r = (c.changed ? CHANGED_R : DOT_R) * k;
    return { x0: c.p!.x - r, y0: c.p!.y - r, x1: c.p!.x + r, y1: c.p!.y + r };
  });
  const placed: Box[] = [];
  const out: DotLabel[] = [];
  // Changed drivers pick first so their labels get the clearest spots.
  const order = [...onMap].sort((a, b) => Number(b.changed) - Number(a.changed));
  for (const car of order) {
    const p = car.p!;
    const fontSize = (car.changed ? 13 : 11.5) * k;
    const w = car.surname.length * fontSize * 0.66 + 6 * k;
    const h = fontSize * 1.1;
    const r = (car.changed ? CHANGED_R : DOT_R) * k;
    const idx = nearestIndex(geo, p).index;
    const t = tangentAt(geo, geo.dist[Math.max(0, idx)]);
    const normal = { x: -t.y, y: t.x };
    const free = freeSide(geo, p, normal, 24 * k);
    // Distance from the dot centre to the label centre so the box just clears the dot.
    const reach = r + 4 * k + (w / 2) * Math.abs(normal.x) + (h / 2) * Math.abs(normal.y);

    let best: { box: Box; step: number; c: Pt; cost: number } | null = null;
    for (const side of [free, -free]) {
      for (let step = 0; step < 4; step++) {
        const d = reach + step * h * 1.05;
        const c = {
          x: clamp(p.x + normal.x * d * side, w / 2 + 2, geo.width - w / 2 - 2),
          y: clamp(p.y + normal.y * d * side, h / 2 + 2, geo.height - h / 2 - 2),
        };
        const box = { x0: c.x - w / 2, y0: c.y - h / 2, x1: c.x + w / 2, y1: c.y + h / 2 };
        let cost = 0;
        for (const b of placed) cost += overlap(box, b);
        for (const b of dots) cost += overlap(box, b);
        // Prefer near spots on the free side; overlap dominates.
        const score = cost * 10 + step + (side === free ? 0 : 0.5);
        if (!best || score < best.cost) best = { box, step, c, cost: score };
        if (cost === 0) break;
      }
      if (best && best.cost < 1) break;
    }
    if (!best) continue;
    placed.push(best.box);
    const far = best.step > 0;
    const dx = best.c.x - p.x;
    const dy = best.c.y - p.y;
    const len = Math.hypot(dx, dy) || 1;
    out.push({
      driver: car.driver,
      text: car.surname,
      x: best.c.x,
      y: best.c.y,
      lineFrom: far ? { x: p.x + (dx / len) * r, y: p.y + (dy / len) * r } : null,
      lineTo: far ? { x: best.c.x - (dx / len) * (h / 2), y: best.c.y - (dy / len) * (h / 2) } : null,
    });
  }
  return out;
}

function CarDot({ car, k, hovered }: { car: Car; k: number; hovered: boolean }) {
  const p = car.p!;
  const r = (car.changed ? CHANGED_R : DOT_R) * k;
  return (
    <g>
      {car.changed && (
        <circle cx={p.x} cy={p.y} r={r + 3.5 * k} fill="none" stroke={RING} strokeWidth={2.2 * k} />
      )}
      {hovered && (
        <circle cx={p.x} cy={p.y} r={r + 8 * k} fill="none" stroke={LIGHT} strokeOpacity={0.45} strokeWidth={1.5 * k} />
      )}
      <circle
        cx={p.x}
        cy={p.y}
        r={car.in_pit ? r - 1.2 * k : r}
        fill={car.in_pit ? SURFACE : car.color}
        stroke={car.in_pit ? car.color : SURFACE}
        strokeWidth={(car.in_pit ? 2.6 : 1.5) * k}
      />
    </g>
  );
}

function RaceStateFigure({ state, changed }: { state: RaceState; changed: Set<string> }) {
  const track = state.track;
  const geo = useMemo(() => {
    if (!track || !Array.isArray(track.x) || !Array.isArray(track.y)) return null;
    return buildTrackGeometry(track.x, track.y, cumulativeDistance(track.x, track.y), track.rotation_deg);
  }, [track]);
  const names = useDrivers(state.season);
  const cars = useMemo(() => prepareCars(state, geo, changed, names), [state, geo, changed, names]);
  const leaderName = cars.find((c) => c.driver === state.leader)?.name ?? driverName(names, state.leader);

  const [hover, setHover] = useState<string | null>(null);
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

  // Dot and label sizes are in viewBox units; scale them up on narrow screens.
  const k = clamp(VIEW_W / pxWidth, 1, 2.4);

  const labels = useMemo<CornerLabel[]>(() => {
    if (!geo) return [];
    const source = (track?.corners ?? []).map((c) => {
      const hasXY = Number.isFinite(c.x) && Number.isFinite(c.y) && (c.x !== 0 || c.y !== 0);
      const p = hasXY ? geo.toScreen(c.x, c.y) : pointAt(geo, c.distance_m);
      // The path's own distances come from its shape, so take the tangent at the nearest point.
      const d = hasXY ? geo.dist[Math.max(0, nearestIndex(geo, p).index)] : c.distance_m;
      return { name: c.name, distance_m: d, p };
    });
    return placeCornerLabels(geo, source, k);
  }, [geo, track, k]);

  const startFinish = useMemo(() => (geo ? startFinishGeometry(geo) : null), [geo]);
  const dotLabels = useMemo(() => (geo ? placeDotLabels(geo, cars, k) : []), [geo, cars, k]);

  const byDriver = useMemo(() => new Map(cars.map((c) => [c.driver, c])), [cars]);
  const hovered = hover != null ? (byDriver.get(hover) ?? null) : null;

  function flush() {
    frame.current = null;
    const svg = svgRef.current;
    const p = pending.current;
    if (!svg || !p) return;
    const local = clientToView(svg, p.x, p.y);
    if (!local) return;
    let best: Car | null = null;
    let bestD = Infinity;
    for (const c of cars) {
      if (!c.p) continue;
      const d = Math.hypot(c.p.x - local.x, c.p.y - local.y);
      if (d < bestD) {
        bestD = d;
        best = c;
      }
    }
    setHover(best && bestD <= HOVER_RADIUS * k ? best.driver : null);
  }

  function handlePointer(e: React.PointerEvent<SVGSVGElement>) {
    pending.current = { x: e.clientX, y: e.clientY };
    if (frame.current == null) frame.current = requestAnimationFrame(flush);
  }

  function handleLeave() {
    if (frame.current != null) cancelAnimationFrame(frame.current);
    frame.current = null;
    pending.current = null;
    setHover(null);
  }

  // Draw order: regular cars, then changed drivers, then the hovered car on top.
  const drawOrder = [...cars]
    .filter((c) => c.p != null)
    .sort((a, b) => Number(a.changed) - Number(b.changed) || Number(a.driver === hover) - Number(b.driver === hover));

  const tooltip =
    geo && hovered?.p ? (
      <div
        className="tabular pointer-events-none absolute z-10 w-max max-w-72 rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-lg"
        style={{
          left: `${(hovered.p.x / geo.width) * 100}%`,
          top: `${(hovered.p.y / geo.height) * 100}%`,
          transform: `translate(${hovered.p.x > geo.width * 0.6 ? "calc(-100% - 16px)" : "16px"}, ${
            hovered.p.y > geo.height * 0.65 ? "calc(-100% - 12px)" : "12px"
          })`,
        }}
      >
        <span className="inline-block h-2 w-2 rounded-full align-middle" style={{ background: hovered.color }} />{" "}
        <span className={hovered.changed ? "font-semibold" : "font-medium"}>{describeCar(hovered)}</span>
      </div>
    ) : null;

  return (
    <figure className="rounded-xl border border-border bg-surface p-4">
      <h3 className="mb-3 text-sm font-medium">
        Race state when the leader started lap {state.lap} &middot; leader{" "}
        <span>{leaderName}</span>
      </h3>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_13rem]">
        {geo ? (
          <div ref={wrapRef} className="relative w-full self-start">
            <svg
              ref={svgRef}
              viewBox={`0 0 ${geo.width} ${geo.height}`}
              width="100%"
              className="block h-auto touch-pan-y select-none"
              role="img"
              aria-label={`Circuit map with each car's position when ${leaderName} started lap ${state.lap}`}
              onPointerMove={handlePointer}
              onPointerDown={handlePointer}
              onPointerLeave={handleLeave}
            >
              <path d={geo.path} fill="none" stroke={COLORS.grid} strokeWidth={14} strokeLinejoin="round" strokeLinecap="round" />
              <path d={geo.path} fill="none" stroke={COLORS.zero} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
              {startFinish && <StartFinishMark sf={startFinish} k={k} />}
              <CornerLabels labels={labels} k={k} />

              <g pointerEvents="none">
                {dotLabels
                  .filter((l) => l.lineFrom && l.lineTo)
                  .map((l) => (
                    <line
                      key={`line-${l.driver}`}
                      x1={l.lineFrom!.x}
                      y1={l.lineFrom!.y}
                      x2={l.lineTo!.x}
                      y2={l.lineTo!.y}
                      stroke={COLORS.axis}
                      strokeOpacity={0.6}
                      strokeWidth={1 * k}
                    />
                  ))}
                {drawOrder.map((c) => (
                  <CarDot key={c.driver} car={c} k={k} hovered={c.driver === hover} />
                ))}
                {dotLabels.map((l) => {
                  const car = byDriver.get(l.driver);
                  const strong = car?.changed || l.driver === hover;
                  return (
                    <text
                      key={`label-${l.driver}`}
                      x={l.x}
                      y={l.y}
                      textAnchor="middle"
                      dominantBaseline="central"
                      fill={strong ? "#ffffff" : "#c9cdd3"}
                      fontSize={(car?.changed ? 13 : 11.5) * k}
                      fontWeight={car?.changed ? 700 : 500}
                      fontFamily="var(--font-mono)"
                      stroke={SURFACE}
                      strokeWidth={3 * k}
                      paintOrder="stroke"
                    >
                      {l.text}
                    </text>
                  );
                })}
              </g>
            </svg>
            {tooltip}
          </div>
        ) : (
          <p className="text-sm text-muted">The circuit outline is not available for this lap.</p>
        )}

        <RunningOrder cars={cars} hover={hover} onHover={setHover} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden>
            <circle cx={8} cy={8} r={6.5} fill="none" stroke={RING} strokeWidth={1.4} />
            <circle cx={8} cy={8} r={4.5} fill={COLORS.axis} />
          </svg>
          Driver in this scenario
        </span>
        <span className="flex items-center gap-1.5">
          <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden>
            <circle cx={8} cy={8} r={4.5} fill={SURFACE} stroke={COLORS.axis} strokeWidth={1.8} />
          </svg>
          In the pit lane
        </span>
        <span className="flex items-center gap-1.5">
          <StartFinishIcon />
          Start/finish
        </span>
        <span>Dots use team colours</span>
      </div>
      <figcaption className="mt-2 text-xs text-muted">
        The scenario branches from this moment: everything before lap {state.lap} is the real race, and every
        simulated run starts with the cars where they are here. Hover or tap a car for its gap and tyres.
      </figcaption>
    </figure>
  );
}

function RunningOrder({
  cars,
  hover,
  onHover,
}: {
  cars: Car[];
  hover: string | null;
  onHover: (driver: string | null) => void;
}) {
  return (
    <div>
      <p className="mb-1.5 text-xs text-muted">Running order</p>
      <ol className="tabular text-xs" onMouseLeave={() => onHover(null)}>
        {cars.map((c, i) => (
          <li
            key={c.driver}
            tabIndex={0}
            title={describeCar(c)}
            onMouseEnter={() => onHover(c.driver)}
            onFocus={() => onHover(c.driver)}
            onBlur={() => onHover(null)}
            className={`grid grid-cols-[1.75rem_1fr_auto] items-center gap-2 rounded px-1.5 py-0.5 outline-none focus-visible:ring-1 focus-visible:ring-accent ${
              c.changed ? "bg-accent/10" : ""
            } ${hover === c.driver ? "bg-surface-2" : ""}`}
          >
            <span className="text-muted">{c.position != null ? `P${c.position}` : `${i + 1}`}</span>
            <span className={`flex min-w-0 items-center gap-1.5 ${c.changed ? "font-bold" : "font-medium"}`}>
              <span
                className={`inline-block h-2 w-2 shrink-0 rounded-full ${c.changed ? "ring-1 ring-white" : ""}`}
                style={c.in_pit ? { boxShadow: `inset 0 0 0 1.5px ${c.color}` } : { background: c.color }}
                aria-hidden
              />
              <span className="truncate">{c.surname}</span>
              {c.in_pit && <span className="text-[10px] font-medium text-amber-300">PIT</span>}
            </span>
            <span className="text-right text-muted">
              {c.isLeader || c.gapMs <= 0 ? "Leader" : `+${(c.gapMs / 1000).toFixed(1)}`}
              {c.lapped && <span className="ml-1 text-[10px]">lapped</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

interface Loaded {
  key: string;
  data: RaceState | null;
  error: ApiError | null;
}

/**
 * Circuit map of the race at the scenario's branch lap: every car at its real position, coloured
 * by team, with the drivers the scenario changes ringed. Renders nothing for races without
 * position telemetry.
 */
export function RaceStateMap({
  season,
  round,
  lap,
  changedDrivers,
}: {
  season: number;
  round: number;
  lap: number;
  changedDrivers: string[];
}) {
  const [nonce, setNonce] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const key = `${nonce}:${season}:${round}:${lap}`;
  const changedKey = changedDrivers.join(",");
  const changed = useMemo(() => new Set(changedKey ? changedKey.split(",") : []), [changedKey]);

  useEffect(() => {
    const controller = new AbortController();
    getWhatIfTrack(season, round, lap, controller.signal).then(
      (data) => setLoaded({ key, data, error: null }),
      (err: unknown) => {
        if (controller.signal.aborted) return;
        setLoaded({ key, data: null, error: toApiError(err, paths.whatifTrack(season, round, lap)) });
      },
    );
    return () => controller.abort();
  }, [key, season, round, lap]);

  const current = loaded?.key === key ? loaded : null;

  if (!current) {
    return (
      <Section title="Branch point">
        <div className="flex aspect-[5/3] max-h-96 w-full animate-pulse items-center justify-center rounded-xl border border-border bg-surface">
          <Spinner label="Loading track map..." />
        </div>
      </Section>
    );
  }

  if (current.error) {
    return (
      <Section title="Branch point">
        <p className="text-sm text-muted">
          Could not load the track map.{" "}
          <button
            type="button"
            onClick={() => setNonce((n) => n + 1)}
            className="underline underline-offset-4 hover:text-foreground"
          >
            Retry
          </button>
        </p>
      </Section>
    );
  }

  if (!current.data || !Array.isArray(current.data.cars) || current.data.cars.length === 0) return null;

  return (
    <Section title="Branch point">
      <RaceStateFigure state={current.data} changed={changed} />
    </Section>
  );
}
