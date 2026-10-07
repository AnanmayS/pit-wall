"use client";

import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartRow, Zone } from "@/lib/chart";
import { COLORS, axisTick, formatMeters, tooltipStyle } from "./chartTheme";

export function SpeedChart({
  rows,
  lapLength,
  driverA,
  driverB,
  brakeZonesA,
  brakeZonesB,
}: {
  rows: ChartRow[];
  lapLength: number;
  driverA: string;
  driverB: string;
  brakeZonesA: Zone[];
  brakeZonesB: Zone[];
}) {
  const [showBrakes, setShowBrakes] = useState(true);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">Speed</h3>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={showBrakes}
            onChange={(e) => setShowBrakes(e.target.checked)}
            className="accent-[var(--accent)]"
          />
          Shade braking zones
        </label>
      </div>
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
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
              domain={[0, "auto"]}
              tickFormatter={(v: number) => `${Math.round(v)}`}
              label={{ value: "km/h", angle: -90, position: "insideLeft", fill: COLORS.axis, fontSize: 11 }}
            />
            {showBrakes &&
              brakeZonesA.map((z, i) => (
                <ReferenceArea
                  key={`a-${i}`}
                  x1={z.start}
                  x2={z.end}
                  fill={COLORS.a}
                  fillOpacity={0.1}
                  ifOverflow="hidden"
                />
              ))}
            {showBrakes &&
              brakeZonesB.map((z, i) => (
                <ReferenceArea
                  key={`b-${i}`}
                  x1={z.start}
                  x2={z.end}
                  fill={COLORS.b}
                  fillOpacity={0.1}
                  ifOverflow="hidden"
                />
              ))}
            <Tooltip
              {...tooltipStyle}
              labelFormatter={formatMeters}
              formatter={(value, name) => {
                const n = Number(value);
                return [Number.isFinite(n) ? `${n.toFixed(0)} km/h` : "-", name];
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line
              type="monotone"
              dataKey="speedA"
              name={driverA}
              stroke={COLORS.a}
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="speedB"
              name={driverB}
              stroke={COLORS.b}
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
