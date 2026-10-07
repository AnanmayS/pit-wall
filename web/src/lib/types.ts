/** Session type codes accepted by the API. */
export type SessionType = "R" | "Q" | "S" | "SQ";

export const SESSION_TYPES: { value: SessionType; label: string }[] = [
  { value: "R", label: "Race" },
  { value: "Q", label: "Qualifying" },
  { value: "S", label: "Sprint" },
  { value: "SQ", label: "Sprint Qualifying" },
];

/** GET /api/sessions?season= */
export interface SessionSummary {
  season: number;
  round: number;
  session_type: SessionType;
  event_name: string;
  session_date: string;
}

/** GET /api/sessions/{season}/{round}/{session_type}/drivers */
export interface DriverSummary {
  driver: string;
  driver_number: number | string;
  team: string;
  laps: number;
  fastest_lap_number: number | null;
  fastest_lap_ms: number | null;
}

/** GET /api/sessions/{season}/{round}/{session_type}/laps?driver= */
export interface LapSummary {
  lap_number: number;
  lap_time_ms: number | null;
  compound: string | null;
  tyre_life: number | null;
  stint: number | null;
  is_accurate: boolean;
  position: number | null;
}

/** "fastest" or an explicit lap number. */
export type LapSelector = "fastest" | number;

export interface CompareMeta {
  season: number;
  round: number;
  session_type: SessionType;
  event_name: string;
  driver_a: string;
  driver_b: string;
  lap_a: number;
  lap_b: number;
  lap_time_a_ms: number;
  lap_time_b_ms: number;
  lap_length_m: number;
  step_m: number;
}

/** Telemetry resampled onto a common distance grid; all arrays share one length. */
export interface CompareGrid {
  distance_m: number[];
  /** Cumulative time_a - time_b at each point; positive = driver A behind. */
  delta_ms: number[];
  speed_a: number[];
  speed_b: number[];
  throttle_a: number[];
  throttle_b: number[];
  brake_a: boolean[];
  brake_b: boolean[];
  gear_a: number[];
  gear_b: number[];
}

export interface CompareSegment {
  name: string;
  start_m: number;
  end_m: number;
  delta_ms: number;
  full_throttle_pct_a: number;
  full_throttle_pct_b: number;
}

export interface CompareCorner {
  name: string;
  distance_m: number;
  brake_point_a_m: number | null;
  brake_point_b_m: number | null;
  brake_delta_m: number | null;
  apex_speed_a_kph: number | null;
  apex_speed_b_kph: number | null;
  throttle_on_a_m: number | null;
  throttle_on_b_m: number | null;
  delta_ms: number;
}

export interface CompareInsight {
  text: string;
  corner: string | null;
  delta_ms: number | null;
  kind: string;
}

/** GET /api/compare */
export interface CompareResult {
  meta: CompareMeta;
  /** time_a - time_b at the end of the lap; positive = driver A slower. */
  total_delta_ms: number;
  grid: CompareGrid;
  segments: CompareSegment[];
  corners: CompareCorner[];
  insights: CompareInsight[];
}

export interface CompareParams {
  season: number;
  round: number;
  session_type: SessionType;
  driver_a: string;
  driver_b: string;
  lap_a: LapSelector;
  lap_b: LapSelector;
}
