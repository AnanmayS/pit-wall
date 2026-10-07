# Pit Wall

F1 simulation and telemetry platform: a **Telemetry Coach** (distance-aligned lap comparison on ClickHouse),
a **What If** counterfactual race simulator (vectorized NumPy Monte Carlo, cached in DynamoDB), and
**Title Odds** (season Monte Carlo scored against Polymarket).

See [PLAN.md](PLAN.md) for the design, [DECISIONS.md](DECISIONS.md) for why, and
[RESULTS.md](RESULTS.md) for measured numbers and the commands that produced them.

## Quick start

```bash
make setup      # uv venv + deps
make up         # ClickHouse + DynamoDB Local via docker compose
make migrate    # apply ClickHouse DDL
make ingest-season SEASON=2025
make test
```
