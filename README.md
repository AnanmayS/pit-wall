# Pit Wall

F1 simulation and telemetry platform. One ingestion pipeline (FastF1 → ClickHouse) feeds three features:

| Feature | What it does | Storage |
|---|---|---|
| **Telemetry Coach** | Aligns two drivers' laps by track distance and says exactly where time is gained or lost ("NOR brakes 22 m later than VER into T1 ... worth 0.15 s") | ClickHouse |
| **What If** | Replays a real race to a branch lap, changes one decision (pit lap, compound, safety car, DNF) and simulates the rest 10,000× with a vectorized NumPy Monte Carlo; results are cached and shareable | DynamoDB single-table |
| **Title Odds** (milestone 3) | Season Monte Carlo after each session, scored against Polymarket with Brier score | ClickHouse |
| **Ask** | Plain-English questions answered through tool calls into the above; every number in an answer is checked against tool output before it is returned | — |

Design: [PLAN.md](PLAN.md) · Why: [DECISIONS.md](DECISIONS.md) · Measured numbers: [RESULTS.md](RESULTS.md)

## Run it locally

```bash
make setup                       # uv venv + deps (Python 3.12)
make up                          # ClickHouse 25.8 + DynamoDB Local (docker compose)
make migrate                     # apply ClickHouse DDL
uv run pitwall ingest session 2025 2 R     # one session (~20 s cached, ~1 M telemetry rows)
uv run pitwall ingest season 2025          # full season: 60 R/Q/S/SQ sessions
uv run python -m pitwall.api               # FastAPI on :8080
cd web && pnpm install && pnpm dev         # Next.js on :3000
```

Ask needs a Claude API key: `ANTHROPIC_API_KEY=... uv run python -m pitwall.api`.

## Layout

```
pitwall/ingest      FastF1 → DataFrames (exact DDL columns) → ClickHouse, idempotent, timed
pitwall/telemetry   distance alignment, corner metrics, insight sentences
pitwall/sim         engine.py (vectorized Monte Carlo), fit.py (parameters from ClickHouse),
                    counterfactual.py (branch a real race), backtest.py
pitwall/whatif      scenario spec, deterministic ids, DynamoDB store, cached service
pitwall/ai          tool definitions, grounded ask loop, eval set + runner
pitwall/api         FastAPI
web/                Next.js (coach, what-if, ask)
benchmarks/         every script that produces a number in RESULTS.md
```

## Tests

```bash
make test        # unit (no services)
make test-all    # + integration against docker compose services
```
