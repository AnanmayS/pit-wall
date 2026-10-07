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

## D12. Real pit stops are detected from tyre-life resets, not FastF1 stint numbers (2026-10-06)
At Australia 2025 the safety car led the field through the pit lane on laps 2-4; FastF1 records each
pass as a pit in/out and a new stint with the same compound. A stop is counted as a tyre change only
when `tyre_life` resets to 1 or the compound changes. The raw `pit_stops` table keeps every pass so
the rule can be revisited.

## D13. Coach aligns on a length-normalised distance grid
FastF1 integrates distance from speed, so the same lap measures ±0.5 % differently per driver. Both
laps are rescaled to their mean length before aligning; the raw lengths are returned in `meta`. The
official lap-time difference is reported as `total_delta_ms`; the telemetry-derived end-of-lap delta is
reported separately so disagreement is visible.

## D14. Brake point = start of the longest braking zone in the window
The literal "first brake-on sample" rule picked up stray brake dabs on real data. Braking zones with
gaps under 20 m are merged; the window is bounded by the neighbouring corners.

## D15. Wet races are flagged, not silently fitted
When more than 20 % of clean laps are on intermediates/wets, the fit marks `wet_race` and the backtest
reports wet and dry races separately. The pace/tyre model is not designed for a drying track.

## D16. Single-race fits are shrunk toward defaults and every fallback is labelled
SC/VSC hazard from one race is pooled with a prior of 100 laps; tyre offsets are clipped to ±3 s;
implausible fuel or degradation slopes fall back to labelled defaults. `RaceParams.assumptions`
travels with every result so the UI and the AI can show what was fitted vs assumed.

## D17. Manual tool-use loop instead of the SDK tool runner
The grounding check needs every tool result and input captured, and a failed check must trigger one
rewrite before refusing. The runner hides the history; the manual loop is ~60 lines.

## D18. What If cold vs cached is served by the same endpoint
`POST /api/whatif` computes on a miss and returns `cache_hit` either way, so hit rate can be measured
from logs under a replayed access pattern rather than claimed.

## D19. Season forecast = per-race engine in forecast mode with recent-form pace priors (2026-10-06)
Each completed race is fitted (D16) and every driver's pace relative to the field median is averaged
with an exponential half-life of 3 races (wet races down-weighted ×0.3). Future races draw a race-level
pace offset from that driver's observed race-to-race spread and run the same engine with generic
strategies and track defaults, so one model serves What If and Title Odds. Known gaps, all labelled in
the forecast's `assumptions`: no qualifying model (grid = drawn pace order), no in-season development
trend, no track-specific parameters for future rounds. Calibration is what the Polymarket comparison
measures, so these gaps are visible rather than hidden.

## D20. Share links carry the scenario spec
`POST /api/whatif` and `GET /api/whatif/{id}` return the canonical spec so a share page can render
the scenario sentences without a second lookup.

## D21. Polymarket data handling (2026-10-06)
- Price history is fetched backwards in 14-day windows: the CLOB endpoint rejects longer
  `startTs`/`endTs` spans and `interval=max` returns nothing for closed markets.
- Race-winner events are mapped to rounds by date first (within 8 days of the race) and name second,
  because slugs are inconsistent (typos, no year before 2026, "Italy" meaning Imola in May).
- Placeholder markets ("Driver A".."J") and the "Other" outcome are stored but excluded from scoring;
  implied probabilities are the Yes prices normalised to sum to 1 across the event's drivers.
- Market probability is sampled at a stated number of hours before the race start. One hour before,
  the market already knows the grid and our model does not (no qualifying model, D19), so RESULTS
  reports both a 1 h and a 48 h (pre-qualifying) comparison rather than picking the flattering one.

## D22. FastF1 rate limit shapes the ingest design (2026-10-06)
The F1 timing API behind FastF1 allows ~500 calls/hour. A full season with telemetry is ~60 sessions
and the first pass stopped at 45 after about 21 minutes. Ingestion is therefore idempotent and
resumable (`ingest season` skips sessions already present; `scripts/finish_ingest.sh` retries on a
20-minute cadence) rather than parallel. Re-ingesting from the on-disk FastF1 cache makes no API calls.

## D23. Session time zero without telemetry (2026-10-07)
FastF1 computes `t0_date` only when car data is loaded, so a laps-only ingest (used for the live 2026
season, where telemetry is not needed for Title Odds) failed on every session. t0 is now derived from
any lap's absolute `LapStartDate` minus its session-relative `LapStartTime`, which matches FastF1's
value; `session.date` is the last-resort fallback.
