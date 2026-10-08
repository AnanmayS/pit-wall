"use client";

import type { ReactNode } from "react";
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
import type { OddsMarket } from "@/lib/types";
import { seriesColor } from "./seriesColors";

type ChartRow = { _t: number; _oursAsOf?: string } & Record<string, number | string | undefined>;

const marketKey = (code: string) => `m_${code}`;
const oursKey = (code: string) => `o_${code}`;

/** "2026-10-07" (or "2026-10-07 00:00:00") -> UTC midnight in ms; NaN when unparseable. */
function dayMs(date: string): number {
  const [y, m, d] = date.slice(0, 10).split("-").map(Number);
  return Date.UTC(y, (m ?? 1) - 1, d ?? 1);
}

const dayFormat = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const fullDayFormat = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/**
 * Polymarket's daily title probability (solid lines) with our stored forecasts on top (large dots,
 * joined by a dashed line once there are two or more). One colour per driver.
 */
export function MarketHistoryChart({
  history,
  marketName,
  drivers,
}: {
  history: OddsMarket["history"];
  marketName: string;
  /** Season driver list, the fallback for names the payload lacks. */
  drivers?: DriverMap;
}) {
  const series = history.series;
  const fullName = (code: string) => driverName(drivers, code, history.series_names?.[code]);
  const shortName = (code: string) => driverSurname(drivers, code, history.series_names?.[code]);

  const byDay = new Map<number, ChartRow>();
  const rowAt = (t: number) => {
    let row = byDay.get(t);
    if (!row) {
      row = { _t: t };
      byDay.set(t, row);
    }
    return row;
  };
  for (const p of history.market) {
    const t = dayMs(p.date);
    if (!Number.isFinite(t)) continue;
    const row = rowAt(t);
    for (const code of series) {
      const v = num(p[code]);
      if (v != null) row[marketKey(code)] = v;
    }
  }
  let oursPoints = 0;
  for (const p of history.ours) {
    const t = dayMs(p.date);
    if (!Number.isFinite(t)) continue;
    const row = rowAt(t);
    row._oursAsOf = p.as_of;
    oursPoints += 1;
    for (const code of series) {
      const v = num(p[code]);
      if (v != null) row[oursKey(code)] = v;
    }
  }
  const rows = [...byDay.values()].sort((a, b) => a._t - b._t);

  if (rows.length === 0 || series.length === 0) {
    return <p className="py-12 text-center text-sm text-muted">No title odds recorded yet.</p>;
  }

  const renderTooltip = (payload: readonly { payload?: unknown }[] | undefined): ReactNode => {
    const row = payload?.[0]?.payload as ChartRow | undefined;
    if (!row) return null;
    const entries = series
      .map((code, i) => ({
        code,
        color: seriesColor(i),
        market: num(row[marketKey(code)]),
        ours: num(row[oursKey(code)]),
      }))
      .filter((e) => e.market != null || e.ours != null)
      .sort((a, b) => Math.max(b.market ?? 0, b.ours ?? 0) - Math.max(a.market ?? 0, a.ours ?? 0));
    if (entries.length === 0) return null;
    return (
      <div className="tabular space-y-1 px-3 py-2" style={tooltipStyle.contentStyle}>
        <p style={tooltipStyle.labelStyle}>
          {fullDayFormat.format(new Date(row._t))}
          {row._oursAsOf ? ` · our forecast ${formatTimestamp(row._oursAsOf)}` : ""}
        </p>
        {entries.map((e) => (
          <p key={e.code} className="flex items-center gap-2">
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: e.color }} aria-hidden />
            <span className="font-medium">{fullName(e.code)}</span>
            <span className="text-muted">
              {e.market != null && `${marketName} ${formatPct(e.market)}`}
              {e.market != null && e.ours != null && " · "}
              {e.ours != null && `Ours ${formatPct(e.ours)}`}
            </span>
          </p>
        ))}
      </div>
    );
  };

  return (
    <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" />
          <XAxis
            dataKey="_t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tick={axisTick}
            stroke={COLORS.grid}
            tickFormatter={(t: number) => dayFormat.format(new Date(t))}
            minTickGap={24}
            padding={{ right: 10 }}
          />
          <YAxis
            domain={[0, 1]}
            tick={axisTick}
            stroke={COLORS.grid}
            width={44}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
          />
          <Tooltip content={({ active, payload }) => (active ? renderTooltip(payload) : null)} />
          {/* Keep the series order (top contenders first) rather than alphabetical. */}
          <Legend wrapperStyle={{ fontSize: 12 }} itemSorter={null} />
          {series.map((code, i) => (
            <Line
              key={marketKey(code)}
              type="monotone"
              dataKey={marketKey(code)}
              name={shortName(code)}
              stroke={seriesColor(i)}
              strokeWidth={1.75}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
          {series.map((code, i) => (
            <Line
              key={oursKey(code)}
              type="linear"
              dataKey={oursKey(code)}
              name={`${shortName(code)} (ours)`}
              legendType="none"
              stroke={oursPoints > 1 ? seriesColor(i) : "transparent"}
              strokeWidth={1.5}
              strokeDasharray="5 4"
              dot={{ r: 5, fill: seriesColor(i), stroke: "#0b0d10", strokeWidth: 1.5 }}
              activeDot={{ r: 6.5, fill: seriesColor(i), stroke: "#0b0d10", strokeWidth: 1.5 }}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
