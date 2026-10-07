"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartRow } from "@/lib/chart";
import type { CompareCorner } from "@/lib/types";
import { COLORS, axisTick, formatMeters, tooltipStyle } from "./chartTheme";

export function DeltaChart({
  rows,
  corners,
  lapLength,
  driverA,
  driverB,
  highlight,
}: {
  rows: ChartRow[];
  corners: CompareCorner[];
  lapLength: number;
  driverA: string;
  driverB: string;
  /** Point to mark, e.g. the distance hovered on the track map. */
  highlight?: ChartRow | null;
}) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">Gap over the lap</h3>
        <p className="text-xs text-muted">
          above 0: <span className="text-driver-a">{driverA}</span> behind, below 0:{" "}
          <span className="text-driver-a">{driverA}</span> ahead of{" "}
          <span className="text-driver-b">{driverB}</span>
        </p>
      </div>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 16, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" />
            <XAxis
              dataKey="d"
              type="number"
              domain={[0, lapLength || "dataMax"]}
              tick={axisTick}
              tickFormatter={formatMeters}
              stroke={COLORS.grid}
            />
            <YAxis
              tick={axisTick}
              stroke={COLORS.grid}
              width={52}
              tickFormatter={(v: number) => `${v.toFixed(2)}s`}
            />
            {corners.map((c) => (
              <ReferenceLine
                key={`${c.name}-${c.distance_m}`}
                x={c.distance_m}
                stroke={COLORS.corner}
                strokeDasharray="2 4"
                label={{ value: c.name, position: "top", fill: COLORS.axis, fontSize: 10 }}
              />
            ))}
            <ReferenceLine y={0} stroke={COLORS.zero} />
            {highlight && (
              <ReferenceLine x={highlight.d} stroke={COLORS.delta} strokeOpacity={0.35} />
            )}
            {highlight && (
              <ReferenceDot
                x={highlight.d}
                y={highlight.delta}
                r={4}
                fill={COLORS.delta}
                stroke="#13161b"
                strokeWidth={1.5}
              />
            )}
            <Tooltip
              {...tooltipStyle}
              labelFormatter={formatMeters}
              formatter={(value) => {
                const n = Number(value);
                return [Number.isFinite(n) ? `${n >= 0 ? "+" : ""}${n.toFixed(3)} s` : "-", "Gap"];
              }}
            />
            <Line
              type="monotone"
              dataKey="delta"
              stroke={COLORS.delta}
              strokeWidth={1.75}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
