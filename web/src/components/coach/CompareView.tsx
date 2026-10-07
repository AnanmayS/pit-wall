"use client";

import { useMemo } from "react";
import { buildChartRows, contiguousZones } from "@/lib/chart";
import { formatDelta, formatLapTime } from "@/lib/format";
import { SESSION_TYPES, type CompareResult } from "@/lib/types";
import { CornerTable } from "./CornerTable";
import { DeltaChart } from "./DeltaChart";
import { InsightList } from "./InsightList";
import { SpeedChart } from "./SpeedChart";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-medium uppercase tracking-widest text-muted">{title}</h2>
      {children}
    </section>
  );
}

export function CompareView({ result }: { result: CompareResult }) {
  const { meta, grid, corners, insights, total_delta_ms } = result;
  const rows = useMemo(() => buildChartRows(grid), [grid]);
  const brakeZonesA = useMemo(() => contiguousZones(grid.distance_m ?? [], grid.brake_a ?? []), [grid]);
  const brakeZonesB = useMemo(() => contiguousZones(grid.distance_m ?? [], grid.brake_b ?? []), [grid]);

  const sessionLabel =
    SESSION_TYPES.find((s) => s.value === meta.session_type)?.label ?? meta.session_type;
  const a = meta.driver_a;
  const b = meta.driver_b;
  const absDelta = formatDelta(Math.abs(total_delta_ms)).replace(/^\+/, "");
  const headline =
    Math.abs(total_delta_ms) < 0.5
      ? "Dead heat"
      : total_delta_ms < 0
        ? `${a} faster by ${absDelta}`
        : `${b} faster by ${absDelta}`;
  const headlineTone =
    Math.abs(total_delta_ms) < 0.5 ? "" : total_delta_ms < 0 ? "text-driver-a" : "text-driver-b";

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

      <div className="space-y-6 rounded-xl border border-border bg-surface p-4">
        <DeltaChart
          rows={rows}
          corners={corners}
          lapLength={meta.lap_length_m}
          driverA={a}
          driverB={b}
        />
        <SpeedChart
          rows={rows}
          lapLength={meta.lap_length_m}
          driverA={a}
          driverB={b}
          brakeZonesA={brakeZonesA}
          brakeZonesB={brakeZonesB}
        />
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
