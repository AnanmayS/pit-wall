"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { COLORS, axisTick, tooltipStyle } from "@/components/coach/chartTheme";
import { formatPct } from "@/lib/whatif";

/** Finishing-position distribution; the actual finishing position is highlighted. */
export function PositionChart({
  probs,
  actualPosition,
}: {
  probs: number[];
  actualPosition: number | null;
}) {
  const rows = probs.map((p, i) => ({ pos: `P${i + 1}`, p, actual: actualPosition === i + 1 }));
  if (rows.length === 0) {
    return <p className="py-8 text-center text-sm text-muted">No position distribution returned.</p>;
  }
  return (
    <div className="h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="pos" tick={axisTick} stroke={COLORS.grid} interval={rows.length > 12 ? 1 : 0} />
          <YAxis
            tick={axisTick}
            stroke={COLORS.grid}
            width={40}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
          />
          <Tooltip
            {...tooltipStyle}
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            formatter={(value) => [formatPct(Number(value)), "Probability"]}
          />
          <Bar dataKey="p" isAnimationActive={false} radius={[3, 3, 0, 0]}>
            {rows.map((r) => (
              <Cell key={r.pos} fill={r.actual ? COLORS.b : COLORS.a} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
