"use client";

import { useMemo, useState } from "react";
import { buildChartRows, contiguousZones, nearestRow } from "@/lib/chart";
import { driverName, useDrivers } from "@/lib/drivers";
import { formatDelta, formatLapTime } from "@/lib/format";
import { SESSION_TYPES, type CompareResult } from "@/lib/types";
import { CornerTable } from "./CornerTable";
import { DeltaChart } from "./DeltaChart";
import { InsightList } from "./InsightList";
import { SpeedChart } from "./SpeedChart";
import { TrackMap } from "./TrackMap";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-medium uppercase tracking-widest text-muted">{title}</h2>
      {children}
    </section>
  );
}

export function CompareView({ result }: { result: CompareResult }) {
  const { meta, grid, corners, insights, total_delta_ms, track } = result;
  const rows = useMemo(() => buildChartRows(grid), [grid]);
  const brakeZonesA = useMemo(() => contiguousZones(grid.distance_m ?? [], grid.brake_a ?? []), [grid]);
  const brakeZonesB = useMemo(() => contiguousZones(grid.distance_m ?? [], grid.brake_b ?? []), [grid]);
  // Distance hovered on the track map, mirrored as a dot on the gap chart.
  const [hoverDistance, setHoverDistance] = useState<number | null>(null);
  const highlight = useMemo(
    () => (hoverDistance == null ? null : nearestRow(rows, hoverDistance)),
    [rows, hoverDistance],
  );

  const sessionLabel =
    SESSION_TYPES.find((s) => s.value === meta.session_type)?.label ?? meta.session_type;
  const names = useDrivers(meta.season);
  const a = driverName(names, meta.driver_a, meta.driver_a_name);
  const b = driverName(names, meta.driver_b, meta.driver_b_name);
  const absDelta = formatDelta(Math.abs(total_delta_ms)).replace(/^\+/, "");
  const headline =
    Math.abs(total_delta_ms) < 0.5
      ? "Dead heat"
      : total_delta_ms < 0
        ? `${a} faster by ${absDelta}`
        : `${b} faster by ${absDelta}`;
  const headlineTone =
    Math.abs(total_delta_ms) < 0.5 ? "" : total_delta_ms < 0 ? "text-driver-a" : "text-driver-b";

  // Hovering the map re-renders this view on every frame; keep the speed chart out of that.
  const speedChart = useMemo(
    () => (
      <SpeedChart
        rows={rows}
        lapLength={meta.lap_length_m}
        driverA={a}
        driverB={b}
        brakeZonesA={brakeZonesA}
        brakeZonesB={brakeZonesB}
      />
    ),
    [rows, meta.lap_length_m, a, b, brakeZonesA, brakeZonesB],
  );

  return (
    <div className="space-y-8">
      <div className="rounded-xl border border-border bg-surface p-5">
        <p className="text-xs text-muted">
          {meta.season} {meta.event_name} &middot; {sessionLabel}
          {meta.lap_length_m ? ` · ${(meta.lap_length_m / 1000).toFixed(3)} km` : ""}
        </p>
        <h2 className={`mt-1 text-3xl font-semibold tracking-tight ${headlineTone}`}>{headline}</h2>
        <div className="tabular mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <span>
            <span className="font-medium text-driver-a">{a}</span>{" "}
            <span className="text-muted">lap {meta.lap_a}</span> {formatLapTime(meta.lap_time_a_ms)}
          </span>
          <span>
            <span className="font-medium text-driver-b">{b}</span>{" "}
            <span className="text-muted">lap {meta.lap_b}</span> {formatLapTime(meta.lap_time_b_ms)}
          </span>
        </div>
      </div>

      <TrackMap
        track={track}
        grid={grid}
        corners={corners}
        driverA={a}
        driverB={b}
        onHoverDistance={setHoverDistance}
      />

      <div className="space-y-6 rounded-xl border border-border bg-surface p-4">
        <DeltaChart
          rows={rows}
          corners={corners}
          lapLength={meta.lap_length_m}
          driverA={a}
          driverB={b}
          highlight={highlight}
        />
        {speedChart}
      </div>

      <Section title="Insights">
        <InsightList insights={insights} />
      </Section>

      <Section title="Corners">
        <CornerTable corners={corners} driverA={a} driverB={b} />
      </Section>
    </div>
  );
}
