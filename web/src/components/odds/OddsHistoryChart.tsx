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
import { driverName, driverSurname, type DriverMap } from "@/lib/drivers";
import { formatPct, formatTimestamp } from "@/lib/format";
import { raceName, shortRaceName } from "@/lib/races";
import type { OddsHistory, SessionSummary } from "@/lib/types";
import { seriesColor } from "./seriesColors";

/** Probability over time, one line per series; x = the race the forecast was made after. */
export function OddsHistoryChart({
  history,
  sessions,
  drivers,
}: {
  history: OddsHistory;
  /** Fallback for snapshots stored without a race name. */
  sessions?: SessionSummary[] | null;
  /** Season driver list, the fallback for driver names the history lacks. */
  drivers?: DriverMap;
}) {
  // Driver series: surname in the legend, full name in the tooltip. Team series keep their name.
  const isDrivers = history.kind !== "constructors";
  const fullName = (s: string) =>
    isDrivers ? driverName(drivers, s, history.series_names?.[s]) : (history.series_names?.[s] ?? s);
  const shortName = (s: string) =>
    isDrivers ? driverSurname(drivers, s, history.series_names?.[s]) : (history.series_names?.[s] ?? s);
  const rows = history.points.map((p, i) => {
    const race = p.after_race || (p.after_round > 0 ? raceName(sessions, p.after_round) : "Pre-season");
    return { ...p, _i: i, _race: race, _label: shortRaceName(race) };
  });
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
              return row ? `After ${row._race} · ${formatTimestamp(row.as_of)}` : "";
            }}
            formatter={(value, name, item) => [
              formatPct(Number(value)),
              item?.dataKey != null ? fullName(String(item.dataKey)) : String(name),
            ]}
            itemSorter={(item) => -Number(item.value ?? 0)}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {history.series.map((s, i) => (
            <Line
              key={s}
              type="monotone"
              dataKey={s}
              name={shortName(s)}
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
