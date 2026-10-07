import { deltaTone, formatDelta, formatNumber } from "@/lib/format";
import type { CompareCorner } from "@/lib/types";

function Pair({ a, b, digits = 0, unit = "" }: { a: number | null; b: number | null; digits?: number; unit?: string }) {
  return (
    <>
      <td className="px-3 py-2 text-right text-driver-a">{formatNumber(a, digits, unit)}</td>
      <td className="px-3 py-2 text-right text-driver-b">{formatNumber(b, digits, unit)}</td>
    </>
  );
}

export function CornerTable({
  corners,
  driverA,
  driverB,
}: {
  corners: CompareCorner[];
  driverA: string;
  driverB: string;
}) {
  if (corners.length === 0) {
    return <p className="text-sm text-muted">No corners were detected for this lap.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="tabular w-full min-w-[720px] text-sm">
        <thead className="bg-surface-2 text-xs text-muted">
          <tr>
            <th rowSpan={2} className="px-3 py-2 text-left font-medium">Corner</th>
            <th colSpan={2} className="px-3 pt-2 text-center font-medium">Brake point (m)</th>
            <th colSpan={2} className="px-3 pt-2 text-center font-medium">Apex speed (km/h)</th>
            <th colSpan={2} className="px-3 pt-2 text-center font-medium">Throttle on (m)</th>
            <th rowSpan={2} className="px-3 py-2 text-right font-medium">Delta</th>
          </tr>
          <tr>
            {[0, 1, 2].map((i) => (
              <FragmentHeads key={i} driverA={driverA} driverB={driverB} />
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {corners.map((c) => (
            <tr key={`${c.name}-${c.distance_m}`} className="hover:bg-surface-2/60">
              <td className="px-3 py-2">
                <span className="font-medium">{c.name}</span>
                <span className="ml-2 text-xs text-muted">{formatNumber(c.distance_m, 0, " m")}</span>
              </td>
              <Pair a={c.brake_point_a_m} b={c.brake_point_b_m} />
              <Pair a={c.apex_speed_a_kph} b={c.apex_speed_b_kph} />
              <Pair a={c.throttle_on_a_m} b={c.throttle_on_b_m} />
              <td className={`px-3 py-2 text-right font-medium ${deltaTone(c.delta_ms)}`}>
                {formatDelta(c.delta_ms)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FragmentHeads({ driverA, driverB }: { driverA: string; driverB: string }) {
  return (
    <>
      <th className="px-3 pb-2 text-right font-medium text-driver-a">{driverA}</th>
      <th className="px-3 pb-2 text-right font-medium text-driver-b">{driverB}</th>
    </>
  );
}
