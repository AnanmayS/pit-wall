"""Telemetry Coach latency benchmark against a live ClickHouse.

Runs N random lap comparisons over ingested sessions and prints a markdown table with
p50/p95/p99 latency of:
  * compare_laps (everything /api/compare does except HTTP/JSON), and
  * the two get_lap_telemetry reads on their own,
plus rows read by ClickHouse per telemetry query (from the X-ClickHouse-Summary header).

    uv run python benchmarks/coach_latency.py --iterations 200 --warmup 20
    uv run python benchmarks/coach_latency.py --season 2025 --round 1 --session-type Q
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time

import numpy as np

from pitwall.telemetry import queries
from pitwall.telemetry.coach import compare_laps


def available_laps(season: int | None, round: int | None, session_type: str | None):
    """{(season, round, session_type): {driver: [lap_number, ...]}} for laps with telemetry."""
    sql = """
        SELECT season, round, session_type, driver, groupArray(lap_number) AS laps
        FROM (
            SELECT DISTINCT season, round, session_type, driver, lap_number
            FROM telemetry
            WHERE ({season:Nullable(UInt16)} IS NULL OR season = {season:Nullable(UInt16)})
              AND ({round:Nullable(UInt8)} IS NULL OR round = {round:Nullable(UInt8)})
              AND ({session_type:Nullable(String)} IS NULL
                   OR session_type = {session_type:Nullable(String)})
              AND lap_number > 0
        )
        GROUP BY season, round, session_type, driver
    """
    params = {"season": season, "round": round, "session_type": session_type}
    rows = queries.client_for_thread().query(sql, parameters=params).result_rows
    sessions: dict[tuple[int, int, str], dict[str, list[int]]] = {}
    for s, r, st, driver, laps in rows:
        sessions.setdefault((int(s), int(r), str(st)), {})[str(driver)] = sorted(laps)
    # A comparison needs two drivers.
    return {k: v for k, v in sessions.items() if len(v) >= 2}


def random_pair(rng: random.Random, sessions):
    key = rng.choice(sorted(sessions))
    driver_a, driver_b = rng.sample(sorted(sessions[key]), 2)
    lap_a = rng.choice(sessions[key][driver_a])
    lap_b = rng.choice(sessions[key][driver_b])
    return (*key, driver_a, driver_b, lap_a, lap_b)


def percentiles(values_ms: list[float]) -> tuple[float, float, float, float]:
    arr = np.asarray(values_ms)
    p50, p95, p99 = np.percentile(arr, [50, 95, 99])
    return float(p50), float(p95), float(p99), float(arr.max())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--season", type=int)
    parser.add_argument("--round", type=int)
    parser.add_argument("--session-type", type=str.upper)
    parser.add_argument("--step-m", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    sessions = available_laps(args.season, args.round, args.session_type)
    if not sessions:
        print("No ingested telemetry matches the filters; run the ingest first.", file=sys.stderr)
        return 1
    rng = random.Random(args.seed)
    client = queries.client_for_thread()

    compare_ms: list[float] = []
    telemetry_ms: list[float] = []
    rows_read: list[int] = []
    rows_returned: list[int] = []
    failures = 0

    completed = 0
    max_attempts = 5 * (args.warmup + args.iterations)
    for _ in range(max_attempts):
        if completed >= args.warmup + args.iterations:
            break
        season, rnd, st, driver_a, driver_b, lap_a, lap_b = random_pair(rng, sessions)
        measured = completed >= args.warmup

        start = time.perf_counter()
        try:
            compare_laps(season, rnd, st, driver_a, driver_b, lap_a, lap_b, step_m=args.step_m)
        except LookupError:
            failures += 1  # e.g. a car that stopped on the formation lap: draw another pair
            continue
        elapsed = (time.perf_counter() - start) * 1000.0
        completed += 1

        start = time.perf_counter()
        frames = [
            queries.get_lap_telemetry(season, rnd, st, driver, lap)
            for driver, lap in ((driver_a, lap_a), (driver_b, lap_b))
        ]
        tel_elapsed = (time.perf_counter() - start) * 1000.0

        if not measured:
            continue
        compare_ms.append(elapsed)
        telemetry_ms.append(tel_elapsed)
        for (driver, lap), frame in zip(
            ((driver_a, lap_a), (driver_b, lap_b)), frames, strict=True
        ):
            params = queries.lap_telemetry_params(season, rnd, st, driver, lap)
            summary = client.query(queries.LAP_TELEMETRY_SQL, parameters=params).summary
            rows_read.append(int(summary.get("read_rows", 0)))
            rows_returned.append(len(frame))

    if not compare_ms:
        print("All comparisons failed.", file=sys.stderr)
        return 1

    n_sessions = len(sessions)
    print(
        f"Telemetry Coach latency: {len(compare_ms)} comparisons (+{args.warmup} warmup) over "
        f"{n_sessions} session(s), step {args.step_m} m, seed {args.seed}"
        + (f"; {failures} pair(s) without usable telemetry redrawn" if failures else "")
    )
    print()
    print("| measurement | n | p50 ms | p95 ms | p99 ms | max ms |")
    print("|---|---:|---:|---:|---:|---:|")
    for label, values in (
        ("compare_laps (end to end: 5 queries + alignment)", compare_ms),
        ("2 x get_lap_telemetry", telemetry_ms),
    ):
        p50, p95, p99, mx = percentiles(values)
        print(f"| {label} | {len(values)} | {p50:.1f} | {p95:.1f} | {p99:.1f} | {mx:.1f} |")
    print()
    print("| per telemetry query | median | p99 | max |")
    print("|---|---:|---:|---:|")
    for label, values in (("rows read (ClickHouse)", rows_read), ("rows returned", rows_returned)):
        p99 = float(np.percentile(values, 99))
        print(f"| {label} | {statistics.median(values):.0f} | {p99:.0f} | {max(values)} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
