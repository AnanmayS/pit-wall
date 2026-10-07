# Decisions

Short, defensible explanations of non-obvious choices. Newest at the bottom.

## D1. ClickHouse for telemetry, not Postgres (2026-10-06)
The hot query (two laps' samples ordered by distance) is a narrow range scan over tens of millions of
rows, and model fitting needs full-table aggregates (degradation slopes, pit loss, SC frequency).
ClickHouse's sparse primary index + columnar codecs serve both; Postgres would need large B-tree indexes
and ~10× the storage. Trade-off: no transactions / point updates, so ingestion is idempotent by
delete-then-insert (telemetry) and ReplacingMergeTree (everything else).

## D2. `telemetry` ORDER BY (season, round, session_type, driver, lap_number, distance_m), PARTITION BY (season, round)
The key is exactly the Coach's filter columns in selectivity order, ending in the sort the Coach needs.
Partitioning by event makes re-ingesting one weekend a partition-local operation and keeps parts small.
Not partitioning by session_type: 60 partitions/season is already enough; more partitions hurt merges.

## D3. Integer milliseconds everywhere
FastF1 returns `Timedelta`s. Storing `UInt32` ms avoids float drift, compresses well (DoubleDelta on
monotone session time), and makes SQL arithmetic obvious. Nullable only where FastF1 legitimately has
no value (in/out lap times, missing sectors).

## D4. DynamoDB single-table for What If; forecasts and market prices in ClickHouse
What If is key-value by scenario hash with TTL and atomic view counters; one `Query` on `PK` returns
spec + result + stats. Forecast history and Polymarket prices are time series that get joined and
aggregated for Brier scoring, which is a ClickHouse shape. Using both where each fits is the point.

## D5. Deterministic scenario ids
`id = base62(sha256(canonical_json)[:10 bytes])`. Same scenario → same id → same share link → cache hit,
no link table, no id generator. Collision risk ~2⁻⁸⁰; the full hash is stored and verified on read.

## D6. Simulator in vectorized NumPy, loop only over laps
10k sims × 20 drivers × ~60 laps is ~12M lap-time evaluations; as `(n_sims, n_drivers)` array ops per
lap that is well under a second of NumPy time. No C++/Numba until measurements say otherwise.

## D7. Grounding is checked programmatically, not by a judge model
Numbers in the answer are extracted with a regex and matched against the set of numbers in tool
results (with rounding/unit variants). A judge model could hallucinate approval; a set-membership check
cannot. Cost: the answer may be rejected for a correct derived number (e.g. a sum), which we accept and
count.

## D8. Python 3.12, uv, pandas 2.x
FastF1 3.8 pins pandas < 3. uv gives a lockfile and fast CI installs.

## D9. 2025 as the primary ingested season
Last completed season (2026 is mid-season). The simulator backtests on complete races; Title Odds (M3)
runs live on 2026.

## D10. R/Q/S/SQ only by default
Practice sessions triple the data volume and add little for the three features. The CLI accepts them.

## D11. API on port 8080
DynamoDB Local owns 8000 in docker compose.
