-- Pit Wall ClickHouse schema. Every statement is idempotent (applied by `pitwall db migrate`).
-- Conventions: all durations are integer milliseconds; "session_ms" = ms since session start
-- (FastF1 SessionTime). session_type is one of FP1, FP2, FP3, Q, SQ, S, R.
-- Rationale for keys/partitions: see PLAN.md § ClickHouse schema.

-- One row per ingested session (dimension table).
CREATE TABLE IF NOT EXISTS sessions (
    season          UInt16,
    round           UInt8,
    session_type    LowCardinality(String),
    event_name      String,
    country         LowCardinality(String),
    location        LowCardinality(String),
    event_format    LowCardinality(String),       -- conventional | sprint_qualifying | ...
    session_date    DateTime64(3, 'UTC'),
    total_laps      Nullable(UInt8),
    circuit_rotation Float32,
    fastf1_version  String,
    ingested_at     DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (season, round, session_type);

-- One row per driver per lap. Re-ingesting a session replaces rows (ReplacingMergeTree + FINAL on read).
CREATE TABLE IF NOT EXISTS laps (
    season          UInt16,
    round           UInt8,
    session_type    LowCardinality(String),
    driver          LowCardinality(String),       -- 3-letter abbreviation, e.g. VER
    driver_number   UInt8,
    team            LowCardinality(String),
    lap_number      UInt8,
    stint           UInt8,
    lap_time_ms     Nullable(UInt32),
    sector1_ms      Nullable(UInt32),
    sector2_ms      Nullable(UInt32),
    sector3_ms      Nullable(UInt32),
    lap_start_session_ms Nullable(UInt32),
    pit_in_session_ms    Nullable(UInt32),        -- set on the lap the car entered the pit lane
    pit_out_session_ms   Nullable(UInt32),        -- set on the lap the car left the pit lane
    compound        LowCardinality(String),       -- SOFT | MEDIUM | HARD | INTERMEDIATE | WET | UNKNOWN
    tyre_life       UInt8,                        -- laps on this set at the end of this lap
    fresh_tyre      Bool,
    track_status    String,                       -- concatenated FastF1 codes, e.g. "124"; 4=SC, 6/7=VSC, 5=red
    position        Nullable(UInt8),
    speed_i1        Nullable(Float32),
    speed_i2        Nullable(Float32),
    speed_fl        Nullable(Float32),
    speed_st        Nullable(Float32),
    is_personal_best Bool,
    is_accurate     Bool,                         -- FastF1: lap is complete and uninterrupted
    deleted         Bool,
    ingested_at     DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (season, round, session_type, driver, lap_number);

-- Car telemetry samples (~3-5 Hz car data merged with position data by FastF1), ~0.9M rows per race.
-- Partitioned per event so a weekend can be re-ingested with DROP PARTITION; ordered so that
-- "all samples of one lap, by distance" is a single contiguous primary-key range.
CREATE TABLE IF NOT EXISTS telemetry (
    season          UInt16,
    round           UInt8,
    session_type    LowCardinality(String),
    driver          LowCardinality(String),
    lap_number      UInt8,
    session_ms      UInt32 CODEC(DoubleDelta, ZSTD(1)),
    distance_m      Float32 CODEC(Delta, ZSTD(1)),   -- distance from the lap start line
    rel_distance    Float32 CODEC(Delta, ZSTD(1)),   -- 0..1 fraction of the lap
    speed_kph       Float32 CODEC(Gorilla, ZSTD(1)),
    rpm             UInt16  CODEC(T64, ZSTD(1)),
    gear            UInt8,
    throttle_pct    Float32 CODEC(Gorilla, ZSTD(1)),
    brake           Bool,
    drs             UInt8,                           -- raw FastF1 DRS code; 10/12/14 = open
    x               Float32 CODEC(Gorilla, ZSTD(1)),
    y               Float32 CODEC(Gorilla, ZSTD(1)),
    z               Float32 CODEC(Gorilla, ZSTD(1)),
    source          LowCardinality(String)           -- car | pos | interpolation
) ENGINE = MergeTree
PARTITION BY (season, round)
ORDER BY (season, round, session_type, driver, lap_number, distance_m)
SETTINGS index_granularity = 8192;

-- Stints derived from laps (one row per driver per stint).
CREATE TABLE IF NOT EXISTS stints (
    season          UInt16,
    round           UInt8,
    session_type    LowCardinality(String),
    driver          LowCardinality(String),
    stint           UInt8,
    compound        LowCardinality(String),
    start_lap       UInt8,
    end_lap         UInt8,
    laps            UInt8,
    tyre_life_at_start UInt8,                     -- >1 means the set was used before (scrubbed)
    ingested_at     DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (season, round, session_type, driver, stint);

-- Pit stops derived from laps (pit lane time = pit_out - pit_in; stationary time is not in FastF1).
CREATE TABLE IF NOT EXISTS pit_stops (
    season          UInt16,
    round           UInt8,
    session_type    LowCardinality(String),
    driver          LowCardinality(String),
    stop_number     UInt8,
    lap_in          UInt8,                        -- lap on which the car entered the pits
    pit_in_session_ms  UInt32,
    pit_out_session_ms UInt32,
    pit_lane_ms     UInt32,
    compound_before LowCardinality(String),
    compound_after  LowCardinality(String),
    ingested_at     DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (season, round, session_type, driver, stop_number);

-- Weather samples (~1/min).
CREATE TABLE IF NOT EXISTS weather (
    season          UInt16,
    round           UInt8,
    session_type    LowCardinality(String),
    session_ms      UInt32,
    air_temp_c      Float32,
    track_temp_c    Float32,
    humidity_pct    Float32,
    pressure_mbar   Float32,
    rainfall        Bool,
    wind_dir_deg    UInt16,
    wind_speed_ms   Float32
) ENGINE = ReplacingMergeTree
ORDER BY (season, round, session_type, session_ms);

-- Track status changes (1=clear 2=yellow 4=SC 5=red 6=VSC 7=VSC ending).
CREATE TABLE IF NOT EXISTS track_status (
    season          UInt16,
    round           UInt8,
    session_type    LowCardinality(String),
    session_ms      UInt32,
    status          UInt8,
    message         LowCardinality(String)
) ENGINE = ReplacingMergeTree
ORDER BY (season, round, session_type, session_ms, status);

-- Race control messages (penalties, investigations, flags, SC deployment text).
CREATE TABLE IF NOT EXISTS race_control (
    season          UInt16,
    round           UInt8,
    session_type    LowCardinality(String),
    session_ms      UInt32,
    lap             Nullable(UInt8),
    category        LowCardinality(String),
    flag            LowCardinality(String),
    scope           LowCardinality(String),
    sector          Nullable(UInt8),
    racing_number   Nullable(UInt8),
    message         String
) ENGINE = ReplacingMergeTree
ORDER BY (season, round, session_type, session_ms, message);

-- Classification / results per session.
CREATE TABLE IF NOT EXISTS results (
    season          UInt16,
    round           UInt8,
    session_type    LowCardinality(String),
    driver          LowCardinality(String),
    driver_number   UInt8,
    team            LowCardinality(String),
    grid_position   Nullable(UInt8),
    position        Nullable(UInt8),
    classified_position String,                   -- "1".."20", "R" (retired), "D", "W", "N"
    status          String,                       -- "Finished", "+1 Lap", "Collision", ...
    points          Float32,
    laps_completed  Nullable(UInt8),
    q1_ms           Nullable(UInt32),
    q2_ms           Nullable(UInt32),
    q3_ms           Nullable(UInt32),
    ingested_at     DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (season, round, session_type, driver);

-- Corner markers from FastF1 circuit info (distance along the lap), used to segment telemetry.
CREATE TABLE IF NOT EXISTS circuit_corners (
    season          UInt16,
    round           UInt8,
    corner_number   UInt8,
    corner_letter   String,
    distance_m      Float32,
    angle_deg       Float32,
    x               Float32,
    y               Float32
) ENGINE = ReplacingMergeTree
ORDER BY (season, round, corner_number, corner_letter);

-- Ingest log: one row per (session, table) load, so ingestion time and row counts are measured, not guessed.
CREATE TABLE IF NOT EXISTS ingest_runs (
    season          UInt16,
    round           UInt8,
    session_type    LowCardinality(String),
    table           LowCardinality(String),
    rows            UInt64,
    load_seconds    Float32,                      -- FastF1 fetch + transform time (shared across tables of a session)
    insert_seconds  Float32,                      -- ClickHouse insert time for this table
    started_at      DateTime64(3, 'UTC'),
    fastf1_version  String
) ENGINE = MergeTree
ORDER BY (started_at, season, round, session_type, table);

-- Polymarket markets (Gamma API), one row per binary market. Re-fetching replaces the row
-- (ReplacingMergeTree on fetched_at). Timestamps are UTC.
CREATE TABLE IF NOT EXISTS pm_markets (
    market_id       String,                       -- Gamma market id
    condition_id    String,
    event_slug      String,
    event_title     String,
    question        String,
    market_kind     LowCardinality(String),       -- season_champion | constructors_champion | race_winner | race_podium | race_pole | other
    season          UInt16,
    round           Nullable(UInt8),              -- race-level markets mapped to the calendar; NULL if unknown
    driver          LowCardinality(String),       -- 3-letter code, OTHER, PLACEHOLDER, UNKNOWN; '' if not a driver market
    team            LowCardinality(String),       -- constructors markets only (FastF1-style team name)
    yes_token_id    String,                       -- CLOB token id of the "Yes" outcome
    created_at      DateTime('UTC'),
    end_date        DateTime('UTC'),
    closed          Bool,
    resolved_outcome Nullable(UInt8),             -- 1 = Yes won, 0 = No won, NULL = unresolved
    fetched_at      DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(fetched_at)
ORDER BY (market_id);

-- Polymarket "Yes" price history (CLOB prices-history), one row per market per point.
CREATE TABLE IF NOT EXISTS pm_prices (
    market_id       String,
    ts              DateTime('UTC'),
    price           Float32,                      -- Yes price, 0..1
    fidelity_min    UInt16                        -- sampling resolution requested from the CLOB, minutes
) ENGINE = ReplacingMergeTree
ORDER BY (market_id, ts);

-- Season forecasts written after each session (title, next-race win, constructors).
-- round is NULL for season-long kinds, hence allow_nullable_key.
CREATE TABLE IF NOT EXISTS forecasts (
    season          UInt16,
    as_of           DateTime,
    after_round     UInt8,
    kind            LowCardinality(String),       -- title | race_win | constructors
    round           Nullable(UInt8),
    driver          LowCardinality(String),
    team            LowCardinality(String),
    probability     Float32,
    n_sims          UInt32,
    model_version   LowCardinality(String)
) ENGINE = ReplacingMergeTree
ORDER BY (season, kind, as_of, round, driver)
SETTINGS allow_nullable_key = 1;
