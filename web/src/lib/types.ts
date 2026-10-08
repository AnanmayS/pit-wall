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

/** GET /api/drivers?season= : every driver who took part in the season. */
export interface DriverInfo {
  /** 3-letter code, e.g. "NOR". */
  driver: string;
  driver_number: number | string | null;
  /** "Lando Norris" */
  full_name: string;
  first_name: string;
  last_name: string;
  team: string;
  country_code: string;
}

/** GET /api/sessions/{season}/{round}/{session_type}/drivers */
export interface DriverSummary {
  driver: string;
  driver_number: number | string;
  team: string;
  /** "Lando Norris"; absent from older API builds. */
  full_name?: string | null;
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
  /** Full names, e.g. "Lando Norris"; absent from older API builds. */
  driver_a_name?: string | null;
  driver_b_name?: string | null;
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
  /** Full name, e.g. "Lando Norris". */
  driver_name?: string | null;
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
  /** Full name, e.g. "Lando Norris". */
  driver_name?: string | null;
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

/** One car's position on track in a race-state snapshot. */
export interface CarOnTrack {
  driver: string;
  /** Full name, e.g. "Lando Norris". */
  driver_name?: string | null;
  team: string;
  position: number | null;
  /** The lap the car is on; below the leader's lap means it has been lapped. */
  lap_number: number;
  distance_m: number;
  /** Raw FastF1 position units, same frame as `CompareTrack.x/y`. */
  x: number;
  y: number;
  gap_to_leader_ms: number;
  compound: string;
  tyre_life: number;
  in_pit: boolean;
}

/** GET /api/whatif/track?season&round&lap: where every car was when the leader started `lap`. */
export interface RaceStateMap {
  season: number;
  round: number;
  lap: number;
  leader: string;
  session_ms: number;
  /** The leader's lap as the circuit path. */
  track: CompareTrack;
  /** Sorted by position. */
  cars: CarOnTrack[];
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
  /** Full name for driver entries, e.g. "Lando Norris"; null for constructors. */
  driver_name?: string | null;
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
  /** Name of the race the forecast was made after, e.g. "Bahrain Grand Prix". */
  after_race?: string | null;
  next_round?: number | null;
  /** Name of the next race, e.g. "Singapore Grand Prix". */
  next_race?: string | null;
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
  /** Name of the race the snapshot was made after; may be null on older snapshots. */
  after_race: string | null;
  [series: string]: number | string | null;
}

/** GET /api/odds/history?season=&kind=&top= */
export interface OddsHistory {
  season: number;
  kind: OddsKind;
  series: string[];
  /** Display name per series: driver code -> full name (team names map to themselves). */
  series_names?: Record<string, string>;
  /** Ordered by as_of ascending. */
  points: OddsHistoryPoint[];
}

/** One driver in a "vs market" table; probabilities are 0..1 and null when that source lacks the driver. */
export interface MarketComparisonRow {
  driver: string;
  /** Full name, e.g. "Kimi Antonelli". */
  driver_name?: string | null;
  /** Our model's probability. */
  ours: number | null;
  /** Market implied probability, normalised to sum to 1 across drivers. */
  market: number | null;
  /** Raw "Yes" price of the driver's market. */
  market_raw: number | null;
  /** ours - market. */
  diff: number | null;
}

/** One day of normalised market title probabilities, keyed by driver code. */
export interface MarketHistoryPoint {
  /** "YYYY-MM-DD" (older builds append a time). */
  date: string;
  [driver: string]: number | string | null;
}

/** One of our stored forecasts, keyed by driver code. */
export interface OursHistoryPoint {
  date: string;
  as_of: string;
  after_round: number;
  [driver: string]: number | string | null;
}

/** GET /api/odds/market?season= : our odds next to prediction-market odds. Rows sorted by max(ours, market) desc. */
export interface OddsMarket {
  season: number;
  forecast_as_of: string | null;
  /** e.g. "Polymarket". */
  market_name: string;
  title: {
    market_as_of: string | null;
    rows: MarketComparisonRow[];
  };
  next_race: {
    round: number | null;
    /** e.g. "Singapore Grand Prix". */
    event_name?: string | null;
    market_as_of: string | null;
    rows: MarketComparisonRow[];
  };
  history: {
    /** Driver codes of the top contenders. */
    series: string[];
    /** Driver code -> full name. */
    series_names?: Record<string, string>;
    /** Daily market title probability. */
    market: MarketHistoryPoint[];
    /** Our stored title forecasts; may be a single point. */
    ours: OursHistoryPoint[];
  };
}
