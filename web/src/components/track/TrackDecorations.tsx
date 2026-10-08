import { COLORS } from "@/components/coach/chartTheme";
import {
  LIGHT,
  SURFACE,
  fmt,
  trianglePoints,
  type CornerLabel,
  type StartFinishGeometry,
} from "./trackGeometry";

/** Chequered start/finish bar across the track plus a direction-of-travel arrow beside it. */
export function StartFinishMark({ sf, k }: { sf: StartFinishGeometry; k: number }) {
  const x1 = sf.p0.x - sf.n0.x * 12 * k;
  const y1 = sf.p0.y - sf.n0.y * 12 * k;
  const x2 = sf.p0.x + sf.n0.x * 12 * k;
  const y2 = sf.p0.y + sf.n0.y * 12 * k;
  const head = sf.pts[sf.pts.length - 1];
  return (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={LIGHT} strokeWidth={4 * k} />
      <line
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        stroke={SURFACE}
        strokeWidth={4 * k}
        strokeDasharray={`${3 * k} ${3 * k}`}
      />
      <polyline
        points={sf.pts.map((p) => `${fmt(p.x)},${fmt(p.y)}`).join(" ")}
        fill="none"
        stroke={COLORS.axis}
        strokeWidth={1.6 * k}
        strokeLinecap="round"
      />
      <g fill={COLORS.axis}>
        <polygon points={trianglePoints(head.x, head.y, sf.tEnd.x, sf.tEnd.y, 6 * k)} />
      </g>
      <title>Start/finish line and direction of travel</title>
    </g>
  );
}

export function CornerLabels({ labels, k }: { labels: CornerLabel[]; k: number }) {
  return (
    <>
      {labels.map((l) => (
        <text
          key={l.key}
          x={l.x}
          y={l.y}
          textAnchor="middle"
          dominantBaseline="central"
          fill={COLORS.axis}
          fontSize={12 * k}
          fontWeight={500}
          stroke={SURFACE}
          strokeWidth={3 * k}
          paintOrder="stroke"
        >
          {l.name}
        </text>
      ))}
    </>
  );
}

/** Legend swatch for the start/finish bar. */
export function StartFinishIcon() {
  return (
    <svg viewBox="0 0 14 14" className="h-3.5 w-3.5" aria-hidden>
      <line x1={7} y1={1} x2={7} y2={13} stroke={LIGHT} strokeWidth={4} />
      <line x1={7} y1={1} x2={7} y2={13} stroke={SURFACE} strokeWidth={4} strokeDasharray="3 3" />
    </svg>
  );
}
