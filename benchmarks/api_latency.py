"""HTTP-level latency for the API (compare + what-if), measured against a running server.

Usage: uv run python -m pitwall.api &  then
       uv run python benchmarks/api_latency.py --base http://localhost:8080 --season 2025 --n 200
Reports p50/p95/p99 per endpoint; what-if is split into cold (first request per scenario) and cached.
"""

from __future__ import annotations

import argparse
import random
import time

import httpx
import numpy as np


def pct(xs, p):
    return float(np.percentile(xs, p)) if xs else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    c = httpx.Client(base_url=args.base, timeout=60)
    sessions = [
        s
        for s in c.get("/api/sessions", params={"season": args.season}).json()
        if s["session_type"] in ("R", "Q")
    ]
    drivers_by = {}
    for s in sessions:
        r = c.get(f"/api/sessions/{s['season']}/{s['round']}/{s['session_type']}/drivers")
        if r.status_code == 200:
            drivers_by[(s["round"], s["session_type"])] = [d["driver"] for d in r.json()]
    # compare: random session + two drivers, fastest laps
    comp = []
    for _ in range(args.n):
        key = rnd.choice(list(drivers_by))
        a, b = rnd.sample(drivers_by[key], 2)
        t = time.perf_counter()
        r = c.get(
            "/api/compare",
            params={
                "season": args.season,
                "round": key[0],
                "session_type": key[1],
                "driver_a": a,
                "driver_b": b,
            },
        )
        if r.status_code == 200:
            comp.append((time.perf_counter() - t) * 1000)
    # what-if: 20 distinct scenarios, each requested once cold then repeatedly cached
    race_rounds = sorted({k[0] for k in drivers_by if k[1] == "R"})
    cold, hot = [], []
    for _i in range(min(20, args.n // 5)):
        rr = rnd.choice(race_rounds)
        drv = rnd.choice(drivers_by[(rr, "R")])
        spec = {
            "season": args.season,
            "round": rr,
            "changes": [{"type": "pit_lap", "driver": drv, "lap": rnd.randint(15, 35)}],
            "n_runs": 10000,
        }
        for _k in range(5):
            t = time.perf_counter()
            r = c.post("/api/whatif", json=spec)
            ms = (time.perf_counter() - t) * 1000
            if r.status_code != 200:
                break
            (hot if r.json()["cache_hit"] else cold).append(ms)
    cmd = f"`uv run python benchmarks/api_latency.py --season {args.season} --n {args.n}`"
    print("| Endpoint (HTTP, uvicorn, local) | n | p50 | p95 | p99 | Command |")
    print("|---|---:|---:|---:|---:|---|")
    print(
        f"| GET /api/compare (fastest laps, random pair) | {len(comp)} | {pct(comp, 50):.0f} ms | {pct(comp, 95):.0f} ms | {pct(comp, 99):.0f} ms | {cmd} |"
    )
    print(
        f"| POST /api/whatif cold (10k runs) | {len(cold)} | {pct(cold, 50):.0f} ms | {pct(cold, 95):.0f} ms | {pct(cold, 99):.0f} ms | |"
    )
    print(
        f"| POST /api/whatif cached | {len(hot)} | {pct(hot, 50):.1f} ms | {pct(hot, 95):.1f} ms | {pct(hot, 99):.1f} ms | |"
    )


if __name__ == "__main__":
    main()
