"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { COLORS, axisTick, tooltipStyle } from "@/components/coach/chartTheme";
import { formatPct, formatTimestamp } from "@/lib/format";
import type { OddsHistory } from "@/lib/types";
import { seriesColor } from "./seriesColors";

/** Probability over time, one line per series; x = round the forecast was made after. */
export function OddsHistoryChart({ history }: { history: OddsHistory }) {
  const rows = history.points.map((p, i) => ({ ...p, _i: i, _label: `R${p.after_round}` }));
  const byIndex = new Map(rows.map((r) => [r._i, r]));

  if (rows.length === 0 || history.series.length === 0) {
    return <p className="py-12 text-center text-sm text-muted">No history recorded yet.</p>;
  }
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" />
          <XAxis
            dataKey="_i"
            type="category"
            tick={axisTick}
            stroke={COLORS.grid}
            tickFormatter={(i: number) => byIndex.get(i)?._label ?? ""}
          />
          <YAxis
            domain={[0, 1]}
            tick={axisTick}
            stroke={COLORS.grid}
            width={44}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
          />
          <Tooltip
            {...tooltipStyle}
            labelFormatter={(i) => {
              const row = byIndex.get(Number(i));
              return row ? `After R${row.after_round} · ${formatTimestamp(row.as_of)}` : "";
            }}
            formatter={(value, name) => [formatPct(Number(value)), String(name)]}
            itemSorter={(item) => -Number(item.value ?? 0)}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {history.series.map((s, i) => (
            <Line
              key={s}
              type="monotone"
              dataKey={s}
              name={s}
              stroke={seriesColor(i)}
              strokeWidth={1.75}
              dot={rows.length <= 12 ? { r: 2.5 } : false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
