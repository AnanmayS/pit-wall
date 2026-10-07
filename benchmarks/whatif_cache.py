"""Measure What If cache behaviour under a replayed access log.

The access log is SYNTHETIC: `--requests` requests drawn from `--scenarios` distinct scenarios with a
Zipf(a=--zipf) popularity distribution (a few popular share links, a long tail). Report: hit rate,
cold and cached latency percentiles. Numbers depend on the chosen distribution; the command line
is printed with the results so the measurement is reproducible.

Usage: uv run python benchmarks/whatif_cache.py --season 2025 --rounds 2,3 --scenarios 40 --requests 400
"""

from __future__ import annotations

import argparse
import statistics
import time

import numpy as np

from pitwall.db.dynamo import create_table
from pitwall.whatif.models import Change, ScenarioSpec
from pitwall.whatif.service import run_or_cached

DRIVERS = ["VER", "NOR", "PIA", "LEC", "HAM", "RUS", "ANT", "ALB", "SAI", "GAS"]


def make_scenarios(
    season: int, rounds: list[int], n: int, rng: np.random.Generator
) -> list[ScenarioSpec]:
    out = []
    for i in range(n):
        rnd = int(rng.choice(rounds))
        kind = i % 4
        drv = DRIVERS[i % len(DRIVERS)]
        lap = int(rng.integers(12, 40))
        if kind == 0:
            ch = [Change(type="pit_lap", driver=drv, lap=lap)]
        elif kind == 1:
            ch = [Change(type="no_safety_car")]
            return_lap = lap
            spec = ScenarioSpec(
                season=season, round=rnd, changes=ch, branch_lap=return_lap, n_runs=10_000
            )
            out.append(spec)
            continue
        elif kind == 2:
            ch = [Change(type="dnf", driver=drv, lap=lap)]
        else:
            ch = [Change(type="safety_car", lap=lap)]
        out.append(ScenarioSpec(season=season, round=rnd, changes=ch, n_runs=10_000))
    return out


def pct(xs, p):
    return float(np.percentile(xs, p)) if xs else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--rounds", type=str, default="2,3")
    ap.add_argument("--scenarios", type=int, default=40)
    ap.add_argument("--requests", type=int, default=400)
    ap.add_argument("--zipf", type=float, default=1.2)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    create_table()
    rng = np.random.default_rng(args.seed)
    rounds = [int(r) for r in args.rounds.split(",")]
    scenarios = make_scenarios(args.season, rounds, args.scenarios, rng)
    # zipf ranks -> scenario index (clipped to the pool)
    draws = rng.zipf(args.zipf, size=args.requests * 3)
    order = [int(d) - 1 for d in draws if d - 1 < len(scenarios)][: args.requests]
    cold, hot, hits = [], [], 0
    t_all = time.perf_counter()
    for idx in order:
        t = time.perf_counter()
        resp = run_or_cached(scenarios[idx])
        ms = (time.perf_counter() - t) * 1000
        if resp.cache_hit:
            hits += 1
            hot.append(ms)
        else:
            cold.append(ms)
    wall = time.perf_counter() - t_all
    cmd = (
        f"`uv run python benchmarks/whatif_cache.py --season {args.season} --rounds {args.rounds} "
        f"--scenarios {args.scenarios} --requests {args.requests} --zipf {args.zipf}`"
    )
    print("| Metric | Value | Command |")
    print("|---|---|---|")
    print(
        f"| Requests / distinct scenarios (synthetic Zipf a={args.zipf} access log) | {len(order)} / {len(set(order))} | {cmd} |"
    )
    print(f"| DynamoDB cache hit rate | {hits / len(order):.1%} | |")
    print(
        f"| Cold (compute 10k runs + store) p50 / p99 | {pct(cold, 50):.0f} / {pct(cold, 99):.0f} ms | |"
    )
    print(f"| Cached p50 / p99 | {pct(hot, 50):.1f} / {pct(hot, 99):.1f} ms | |")
    print(f"| Mean cold compute | {statistics.mean(cold):.0f} ms over {len(cold)} misses | |")
    print(f"| Wall time | {wall:.1f} s | |")


if __name__ == "__main__":
    main()
