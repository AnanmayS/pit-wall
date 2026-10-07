"""Measure simulator throughput: sims/second and wall time per 10k-run scenario.

Usage: uv run python benchmarks/sim_throughput.py [--runs 10000] [--repeat 5]
Uses a synthetic 20-driver, 57-lap race with the engine's default parameters. Prints a markdown row.
"""

from __future__ import annotations

import argparse
import statistics
import time

import numpy as np

from pitwall.sim.engine import RaceParams, Strategy, TyreModel, simulate


def synthetic_params(n_drivers: int = 20, n_laps: int = 57) -> RaceParams:
    tyres = {
        "SOFT": TyreModel(offset=-0.6, d1=0.08, d2=0.001),
        "MEDIUM": TyreModel(offset=0.0, d1=0.05, d2=0.0005),
        "HARD": TyreModel(offset=0.5, d1=0.03, d2=0.0002),
    }
    rng = np.random.default_rng(0)
    base = 90.0 + np.sort(rng.normal(0, 0.4, n_drivers))
    strategies = [
        Strategy(["MEDIUM", "HARD"], [int(rng.integers(15, 30))]) for _ in range(n_drivers)
    ]
    return RaceParams(
        n_laps=n_laps,
        drivers=[f"D{i:02d}" for i in range(n_drivers)],
        base_pace=base,
        strategies=strategies,
        grid=np.arange(1, n_drivers + 1),
        tyres=tyres,
        seed=0,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10_000)
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()
    params = synthetic_params()
    simulate(params, n_sims=1000)  # warmup
    times = []
    for _ in range(args.repeat):
        t = time.perf_counter()
        simulate(params, n_sims=args.runs)
        times.append(time.perf_counter() - t)
    med = statistics.median(times)
    print("| Metric | Value | Command |")
    print("|---|---|---|")
    print(
        f"| Sims/second (20 drivers, 57 laps) | {args.runs / med:,.0f} | "
        f"`uv run python benchmarks/sim_throughput.py --runs {args.runs}` |"
    )
    print(
        f"| Wall time per {args.runs:,}-run scenario (median of {args.repeat}) | {med * 1000:.0f} ms | same |"
    )


if __name__ == "__main__":
    main()
