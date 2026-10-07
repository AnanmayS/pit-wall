# Results

Every number here was measured by the command shown next to it. Nothing is estimated. Placeholders are
marked **TBD** until the benchmark has been run.

Machine: Apple Silicon Mac (Darwin 25.3), Docker Desktop, ClickHouse 25.8 in a container, Python 3.12.

## Milestone 1 — Ingestion + Telemetry Coach

| Metric | Value | Command |
|---|---|---|
| Sessions ingested (2025, R/Q/S/SQ) | TBD | `uv run pitwall ingest status 2025` |
| Telemetry rows ingested | TBD | `uv run pitwall ingest status 2025` |
| Lap rows ingested | TBD | `uv run pitwall ingest status 2025` |
| Ingestion wall time, full season | TBD | `uv run python benchmarks/ingest_report.py` |
| Telemetry compressed size / uncompressed | TBD | `SELECT ... FROM system.parts` (see benchmarks/ingest_report.py) |
| Compare query latency p50 / p95 / p99 | TBD | `uv run python benchmarks/coach_latency.py` |

## Milestone 2 — Simulator + What If + AI

| Metric | Value | Command |
|---|---|---|
| Sims/second (10k-run scenario) | TBD | |
| Wall time per 10k-run scenario | TBD | |
| DynamoDB cache hit rate (replayed access log) | TBD | |
| What If API p99 (cold / cached) | TBD | |
| Backtest: races, MAE of expected finishing position, winner hit rate | TBD | |
| AI grounding rate / parse accuracy (eval set size) | TBD | |

## Milestone 3 — Title Odds

| Metric | Value | Command |
|---|---|---|
| Brier score vs Polymarket, N races | TBD | |
