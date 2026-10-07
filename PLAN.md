# Pit Wall — Plan

One platform, three features, one shared engine.

```
FastF1 / OpenF1 data
  → ingestion pipeline (laps, stints, pit stops, weather, telemetry samples)
       → ClickHouse ───────────────────────────→ (1) Telemetry Coach
       → pace & tyre-degradation models ──→ race simulator (NumPy Monte Carlo)
                                             ├─→ (2) What If ──→ DynamoDB (cached runs, share links)
                                             └─→ (3) Title Odds ──→ scored vs Polymarket (Brier)
  AI layer: question → tool calls → answer that may only contain numbers that appear in tool output
```

Status legend: ✅ done · 🔨 in progress · ⬜ not started. Numbers live in [RESULTS.md](RESULTS.md) only.

---

## 0. Repo layout

```
pitwall/            Python package (uv, Python 3.12)
  config.py         pydantic-settings (env / .env)
  db/               ClickHouse client + ddl.sql; DynamoDB client (M2)
  ingest/           FastF1 → DataFrames → ClickHouse
  telemetry/        distance alignment, corner metrics, coach insights
  sim/              race model fitting + vectorized Monte Carlo (M2)
  ai/               Claude tool definitions, grounding check, eval runner (M2)
  odds/             season Monte Carlo + Polymarket scoring (M3)
  api/              FastAPI app (port 8080)
  cli.py            `pitwall` Typer CLI
web/                Next.js 15 / TypeScript / Tailwind (port 3000)
infra/terraform/    AWS (deferred until the app is worth hosting; see § 7)
benchmarks/         scripts that produce every number in RESULTS.md
tests/              unit (default) + `integration` (ClickHouse/DynamoDB Local) + `network` markers
docker-compose.yml  ClickHouse 25.8 + DynamoDB Local
.github/workflows   ruff, pytest unit + integration (service containers), web lint + build
```

---

## 1. Data sources and ingestion

**Primary source: FastF1 3.8** (wraps the official F1 live-timing archive; gives laps, car telemetry at
~3-5 Hz merged with position data, weather, track status, race control messages, results, circuit corner
markers). **OpenF1** is a fallback for live 2026 sessions if FastF1's archive lags; not needed for M1.

**Scope for M1:** the full **2025** season (last completed season; 2026 is mid-season as of Oct 2026).
Sessions: Race (R), Qualifying (Q), Sprint (S), Sprint Qualifying (SQ) = 18×2 + 6×4 = 60 sessions.
Practice sessions are supported by the CLI but off by default (3× more data, little value for the three
features).

**Pipeline** (`pitwall ingest season 2025`): for each (round, session): FastF1 load (disk-cached) →
`transform_session()` → DataFrames with exactly the DDL columns → ClickHouse insert (telemetry in ~500k-row
chunks). Idempotent: `laps`/`stints`/… use ReplacingMergeTree keyed on their natural key; `telemetry`
rows for the session are deleted before insert. Every load writes a row to `ingest_runs` (rows, seconds)
so ingestion time per season is measured, not estimated.

**Known FastF1 quirks handled:** missing telemetry for some laps (skipped and counted), `NaT` lap times
on in/out laps and red-flag laps (`lap_time_ms` NULL), `TrackStatus` is a concatenation of codes
("124"), stint/compound corrections logged by FastF1, 2023 `sprint_shootout` vs 2024+ `sprint_qualifying`
naming, rate limiting (retry with backoff; sequential ingestion).

---

## 2. ClickHouse schema (see `pitwall/db/ddl.sql`)

Why ClickHouse: the Coach query is "all samples of two laps, ordered by distance" (range scan returning
~1.5k rows out of tens of millions) plus analytical aggregates for model fitting (per-track pit loss,
SC frequency, degradation slopes over millions of laps). Columnar storage + sparse primary index + per-column
codecs make both cheap; Postgres would need a B-tree per lookup column and stores ~10× more bytes.

| Table | Engine | ORDER BY (primary key) | Partition | Why |
|---|---|---|---|---|
| `telemetry` | MergeTree | (season, round, session_type, driver, lap_number, distance_m) | (season, round) | The Coach's hot query filters on the first five key columns and reads in distance order → one contiguous granule range. Partition = one event, so a weekend can be re-ingested or dropped in O(1). |
| `laps` | ReplacingMergeTree(ingested_at) | (season, round, session_type, driver, lap_number) | — | Natural key; re-ingest overwrites. ~1k rows/session so no partitioning needed. |
| `stints`, `pit_stops`, `results`, `sessions` | ReplacingMergeTree | natural key | — | Small derived/dimension tables. |
| `weather`, `track_status`, `race_control` | ReplacingMergeTree | (season, round, session_type, session_ms, …) | — | Time-ordered within a session for "what was the status at lap N" lookups. |
| `circuit_corners` | ReplacingMergeTree | (season, round, corner) | — | Segments the lap for the Coach. |
| `ingest_runs` | MergeTree | (started_at, …) | — | Measurement log. |

Codecs on `telemetry`: `DoubleDelta` for monotonically increasing `session_ms`, `Delta` for
`distance_m`, `Gorilla` for slowly varying floats (speed, throttle, x/y/z), `T64` for `rpm`,
`LowCardinality` for strings; all with `ZSTD(1)`. Compression ratio is reported in RESULTS.md.

Reads from ReplacingMergeTree tables use `FINAL` (cheap at this size); `telemetry` never has duplicates
because the ingest deletes before insert.

---

## 3. Telemetry Coach (M1)

Input: two (driver, lap) pairs in one session. Steps:

1. Fetch both laps' telemetry (ClickHouse, ordered by `distance_m`).
2. Resample each lap onto a uniform **distance grid** (1 m): elapsed time, speed, throttle interpolated;
   gear/brake/DRS step-sampled. Aligning by distance rather than time is what makes "where" meaningful.
3. `delta_ms(d) = time_a(d) − time_b(d)` (positive = A behind). Total delta ≈ lap-time difference.
4. Segment the lap by corner markers (boundaries at midpoints between corners) → delta per segment.
5. Per corner: braking point (first brake=true in a window before the corner), apex (min speed),
   throttle-on point (first ≥90 % throttle after apex); differences between drivers.
6. Deterministic insight sentences ranked by |delta|, e.g. "VER brakes 8 m later than NOR into T1 and
   carries 4 km/h more through the apex, worth 0.12 s."

API: `GET /api/compare?season&round&session_type&driver_a&driver_b&lap_a&lap_b`. Web: `/coach`.

Caveats (documented, not hidden): FastF1 `Distance` is integrated from speed so lap lengths differ by a
few metres between drivers (grid is truncated to the shorter lap); position data is interpolated between
~4 Hz samples; braking point is the first sample where the brake flag is on (±1 sample ≈ ±5-10 m at speed).

---

## 4. Race simulator (M2) — model spec

Vectorized NumPy. State arrays have shape `(n_sims, n_drivers)`; the only Python loop is over laps
(≤ ~78). A What If run = 10,000 sims; a Title Odds run = ~100,000 season sims built from per-race runs.

**Lap time for driver i on lap l:**

```
t_i(l) = pace_i
       + fuel · (L − l)                       # linear fuel effect, per-track slope
       + deg_c(age)                           # tyre model: d1_c·age + d2_c·age², per compound (+ per-track scale)
       + traffic_i(l)                         # following penalty if within gap_follow of car ahead and no overtake
       + sc_effect(l)                         # SC / VSC multiplies lap time, SC also bunches the field
       + pit_loss_track · 1[pit on lap l]     # pit-lane delta time, fit per track, reduced under SC/VSC
       + ε_i(l),  ε ~ N(0, σ_i)               # per-lap noise from clean-lap residuals
```

Plus: per-sim race-level pace offset `η_i ~ N(0, σ_race)` (forecast mode only; What If mode uses the
observed race pace up to the branch lap), per-lap DNF hazard `h_i` (team/driver rate with shrinkage,
higher on lap 1 for collisions), per-lap SC hazard `λ_track` (from `track_status` history), overtake
probability `p_ov(track, Δpace, DRS)` when a faster car closes within `gap_follow`.

**Parameters are fit from ClickHouse** (`pitwall sim fit`): clean laps = `is_accurate`, no pit in/out,
track status "1", not lap 1. Fuel slope and tyre curves by regression with driver fixed effects; pit loss
from `pit_stops` (pit lane time − time to drive the same distance at racing speed); SC rate from
`track_status`; DNF rate from `results.status`; noise from residuals. Every fitted parameter is written
to `data/models/<season>.json` with its sample size; anything we could not fit is a labelled assumption.

**Counterfactual (What If):** replay the real race (actual lap times) up to the branch lap, then simulate
forward with the modified strategy for one driver (pit lap, compound, skip stop, no SC, forced SC, DNF).
Output: finishing-position distribution per driver, P(win), P(podium), expected position, and the
distribution of the changed driver's gain/loss vs the real result.

**Validation (backtest):** for each 2025 race, simulate from the actual grid with the actual strategies
and compare to the real classification: mean absolute error of expected finishing position, Spearman
rank correlation, winner hit rate, podium overlap, calibration of P(position ≤ k). Also pit-window
accuracy: the lap range in which the sim's optimal stop lands vs the real stop. Reported in RESULTS.md.

---

## 5. What If storage — DynamoDB single-table design

**Access patterns (in priority order):**

| # | Pattern | Frequency | Key |
|---|---|---|---|
| A1 | Get cached result for a scenario by canonical id (hot path, every page view) | very high reads | `PK=SCEN#<id>`, `SK=RESULT#<model_version>` |
| A2 | Get scenario spec by id (share link open) | high | `PK=SCEN#<id>`, `SK=META` |
| A3 | Increment and read view count | high writes | `PK=SCEN#<id>`, `SK=STATS` (atomic `ADD`) |
| A4 | List recent scenarios for a race (discovery page) | medium | GSI1: `GSI1PK=RACE#<season>#<round>`, `GSI1SK=<created_at>#<id>` |
| A5 | Expire stale cached results | background | TTL attribute on RESULT items |

A1–A3 are one `Query` on `PK = SCEN#<id>` (all three items come back together). The scenario **id is
deterministic**: `base62(sha256(canonical_json)[:10 bytes])` where canonical JSON = sorted keys, no
whitespace, changes list sorted, floats normalized, plus `model_version` and `n_runs`. Same scenario →
same id → same share link → cache hit without a separate link table. The full hash is stored and
verified on read. RESULT items carry a 30-day TTL; META never expires (links keep working; a miss
recomputes). "Popular" = recent page sorted by view count client-side, to avoid rewriting a GSI key on
every view.

Why not Postgres: the workload is key-value by hash, read-heavy, joinless, wants TTL and atomic counters,
and should cost nothing at idle. Postgres would work; DynamoDB's single-table model is the better fit and
the thing this project is meant to demonstrate. Title Odds forecasts and Polymarket prices are
time-series that get joined and aggregated, so they go to ClickHouse instead (§ 6).

Local dev: DynamoDB Local via docker compose; `pitwall db create-ddb` creates the table + GSI.

---

## 6. Title Odds + Polymarket (M3)

After each 2026 session: simulate the remaining races ~100k times (per-race sims reuse § 4 in forecast
mode with pace priors from recent form) → P(driver wins title), P(constructor), P(next race win),
"what has to happen" scenarios (conditional probabilities, e.g. title odds if X wins next race).
Store every forecast in ClickHouse (`forecasts`: as_of, after_round, driver, p_title, p_next_win).

Polymarket: Gamma API `events?tag_slug=f1` lists markets (season champion, per-race winner/podium/pole,
head-to-head); CLOB `prices-history?market=<clobTokenId>` gives hourly prices. Race-winner markets exist
back to Aug 2024 (41 closed race-winner events as of 2026-10-06), so the backtest can cover late-2024 and
2025 races as well as live 2026. Score: Brier score of our pre-race P(win) vs the market's implied
probability (normalized to sum to 1) vs the outcome, per race and cumulative; also log-loss.

---

## 7. AI layer (M2)

Model: `claude-opus-5-5` via the Python SDK with tool use. Tools (JSON schema, `strict: true`):

| Tool | Args | Returns |
|---|---|---|
| `list_sessions` | season | sessions |
| `compare_laps` | season, round, session_type, driver_a, driver_b, lap_a?, lap_b? | Coach summary (total delta, corners, insights) |
| `get_lap_times` | season, round, session_type, driver, lap_from?, lap_to? | laps with times, compounds, stints |
| `get_gaps` | season, round, lap | gap to leader per driver at that lap |
| `get_stints` | season, round, driver? | stints and pit stops |
| `simulate_scenario` | season, round, changes[], n_runs | What If distribution summary |
| `get_title_odds` | season, as_of? | latest forecast (M3) |

**Grounding rule:** every number in the final answer must appear in a tool result (or in the user's
question / tool inputs, for things like years and lap numbers). Implementation: walk every tool result
recursively and collect an allowed set of numbers including rounded variants (0–3 dp), ms→s conversions,
`m:ss.mmm` lap-time strings and percent forms; extract all numeric tokens from the answer; any token with
no match (within rounding tolerance) fails the check. On failure: one retry with the offending numbers
listed; if it fails again the API returns a refusal naming what it could not verify. The check is
programmatic, not model-judged.

**Eval set:** 50–200 questions in `pitwall/ai/evals/questions.jsonl` with expected tool calls (for parse
accuracy) and, for grounding, the check above. Metrics: grounding rate (answers passing first try), parse
accuracy (tool name + args match), tool-call count, latency, cost.

---

## 8. Milestones

### M1 — Ingestion + ClickHouse + Telemetry Coach  🔨 (code done; full-season ingest + benchmarks running)
Done means: `pitwall ingest season 2025` has loaded all 60 R/Q/S/SQ sessions; `pitwall ingest status`
shows every session; `/coach` compares any two laps of any ingested session end-to-end; CI green
(unit + integration + web build). Metrics produced: rows ingested per table, ingestion wall time per
season, telemetry compression ratio, compare query latency p50/p95/p99 (`benchmarks/coach_latency.py`).

### M2 — Simulator + What If + DynamoDB + AI  🔨 (engine, fit, counterfactual, cache, API, web, AI loop + eval set done; live eval needs an API key)
Done means: `pitwall sim fit 2025` writes a parameter file with sample sizes; `pitwall sim backtest
2025` reports accuracy on all 24 races; `/what-if` page runs a scenario, shows the distribution and a
share link; second open of a link is a DynamoDB cache hit; `/api/ask` answers questions through tools
with the grounding check; eval runner reports grounding rate and parse accuracy. Metrics: sims/second,
wall time per 10k-run scenario, cache hit rate under a replayed access log, p99 API latency (cold vs
cached), backtest metrics on 24 races, grounding rate, parse accuracy.

### M3 — Title Odds + Polymarket  🔨 (season Monte Carlo + odds API done; Polymarket ingestion/scoring in progress)
Done means: forecast job runs after each 2026 session and stores results; Polymarket prices ingested
hourly; `/odds` page charts our odds vs market over time; Brier score vs Polymarket over N races
(backtest + live). Metrics: Brier (ours vs market), N races scored.

### Deployment (optional, after M2)
Terraform for: ECS Fargate (API) or Lambda+API Gateway, DynamoDB table with GSI + TTL, S3 for FastF1
cache, CloudWatch. ClickHouse hosting is the cost question (ClickHouse Cloud vs a small EC2); deferred
until there is something worth hosting.
