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
  /** Distance of each driver's minimum-speed point; null when no apex was found. */
  apex_a_m?: number | null;
  apex_b_m?: number | null;
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

export interface TrackCorner {
  name: string;
  distance_m: number;
  /** Raw FastF1 position units (1/10 m), same frame as CompareTrack.x/y. */
  x: number;
  y: number;
}

/**
 * Driver A's path around the lap, index-aligned with `grid.distance_m` / `grid.delta_ms`.
 * Raw FastF1 position units (1/10 m), not rotated: rotate by `rotation_deg`
 * (x' = x cos r - y sin r, y' = x sin r + y cos r) and flip y for screen coordinates.
 */
export interface CompareTrack {
  x: number[];
  y: number[];
  rotation_deg: number;
  corners: TrackCorner[];
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
  /** Absent from older API builds; the track map is hidden when missing or unusable. */
  track?: CompareTrack | null;
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

// ---------------------------------------------------------------------------
// What-If simulator
// ---------------------------------------------------------------------------

export type ChangeType =
  | "pit_lap"
  | "compound"
  | "skip_stop"
  | "extra_stop"
  | "no_safety_car"
  | "safety_car"
  | "dnf";

export type Compound = "SOFT" | "MEDIUM" | "HARD" | "INTERMEDIATE" | "WET";

export const COMPOUNDS: Compound[] = ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"];

/** One modification to the actual race. Which fields are required depends on `type`. */
export interface Change {
  type: ChangeType;
  /** 3-letter driver code. */
  driver?: string | null;
  lap?: number | null;
  /** 1-based index among the driver's remaining stops. */
  stop?: number | null;
  compound?: Compound | null;
}

/** Body of POST /api/whatif. */
export interface ScenarioSpec {
  season: number;
  round: number;
  changes: Change[];
  branch_lap?: number | null;
  /** 100..100000, server default 10000. */
  n_runs?: number;
}

export interface DriverOutcome {
  driver: string;
  p_win: number;
  p_podium: number;
  p_points: number;
  p_dnf: number;
  expected_position: number;
  /** Index 0 = P1. */
  position_probs: number[];
}

export interface ChangedDriverOutcome {
  driver: string;
  actual_position: number | null;
  expected_position: number;
  p_better_than_actual: number | null;
  p_worse_than_actual: number | null;
  position_probs: number[];
}

export interface ScenarioFit {
  clean_laps: number;
  pit_stops_used: number;
  sc_deployments: number;
}

/** Response of POST /api/whatif and GET /api/whatif/{id}. */
export interface ScenarioResult {
  id: string;
  cache_hit: boolean;
  views: number;
  created_at: string;
  /** The full spec; older stored results may still return null. */
  spec: ScenarioSpec | null;
  season: number;
  round: number;
  branch_lap: number;
  n_runs: number;
  compute_ms: number;
  /** Sorted by expected_position. */
  summary: DriverOutcome[];
  changed_drivers: ChangedDriverOutcome[];
  /** Labelled fallbacks the model fit had to use. */
  assumptions: Record<string, string>;
  fit: ScenarioFit;
}

/** GET /api/whatif/recent?season&round */
export interface RecentScenario {
  id: string;
  created_at: string;
  spec: ScenarioSpec;
}

// ---------------------------------------------------------------------------
// Ask the Pit Wall
// ---------------------------------------------------------------------------

export type AskEffort = "low" | "medium" | "high";

export interface AskRequest {
  question: string;
  effort?: AskEffort;
}

export interface AskToolCall {
  name: string;
  input: Record<string, unknown>;
  is_error: boolean;
  ms: number;
}

/** Response of POST /api/ask. */
export interface AskResponse {
  question: string;
  answer: string;
  grounded: boolean;
  refused: boolean;
  /** Claims in the answer that could not be matched to tool output. */
  unmatched: string[];
  tool_calls: AskToolCall[];
  rewrites: number;
  turns: number;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  stop_reason: string | null;
  model: string;
}

// ---------------------------------------------------------------------------
// Championship odds
// ---------------------------------------------------------------------------

export type OddsKind = "title" | "constructors" | "race_win";

export interface OddsEntry {
  driver: string | null;
  team: string | null;
  /** Set for race_win (the next round) and the conditional lists. */
  round: number | null;
  probability: number;
}

/** GET /api/odds/latest?season= ; every list is sorted by probability desc and may be absent. */
export interface OddsLatest {
  season: number;
  as_of: string;
  after_round: number;
  model_version: string;
  n_sims: number;
  title?: OddsEntry[];
  constructors?: OddsEntry[];
  race_win?: OddsEntry[];
  /** P(title) given the driver wins the next race. */
  title_if_next_win?: OddsEntry[];
  /** P(title) given the driver does not win the next race. */
  title_if_next_not_win?: OddsEntry[];
}

/** One snapshot in GET /api/odds/history; series values are keyed by series name. */
export interface OddsHistoryPoint {
  as_of: string;
  after_round: number;
  [series: string]: number | string | null;
}

/** GET /api/odds/history?season=&kind=&top= */
export interface OddsHistory {
  season: number;
  kind: OddsKind;
  series: string[];
  /** Ordered by as_of ascending. */
  points: OddsHistoryPoint[];
}
