"""Backtest the simulator on real races: simulate from the grid with the real strategies, compare
the predicted finishing-position distribution with the actual classification.

Metrics per race: MAE of expected position vs actual, Spearman rank correlation, winner hit (argmax
P(win) == actual winner), podium overlap (|predicted top-3 by expected position ∩ actual top-3|),
mean log-score of the actual position under the predicted distribution.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from pitwall.db.clickhouse import get_client
from pitwall.sim.engine import simulate
from pitwall.sim.fit import fit_race, load_race_frames


@dataclass
class RaceBacktest:
    season: int
    round: int
    event: str
    n_drivers: int
    wet: bool
    mae_position: float
    spearman: float
    winner_hit: bool
    podium_overlap: int
    mean_log_score: float
    clean_laps: int
    assumptions: int


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def backtest_race(season: int, round: int, n_sims: int = 5000, client=None) -> RaceBacktest:
    frames = load_race_frames(season, round, client)
    params, report = fit_race(season, round, frames=frames)
    params.seed = 0
    res = simulate(params, n_sims=n_sims)
    results = frames["results"].set_index("driver")
    actual = np.array([results.loc[d, "position"] for d in params.drivers], dtype=float)
    classified = ~np.isnan(actual)
    expected = res.positions.mean(axis=0)
    dist = res.position_distribution()
    log_scores = []
    for i in range(params.n_drivers):
        if classified[i]:
            p = dist[i, int(actual[i]) - 1]
            log_scores.append(np.log(max(p, 1e-6)))
    p_win = dist[:, 0]
    pred_winner = params.drivers[int(np.argmax(p_win))]
    actual_winner = params.drivers[int(np.nanargmin(actual))]
    pred_top3 = {params.drivers[i] for i in np.argsort(expected)[:3]}
    actual_top3 = {params.drivers[i] for i in np.argsort(np.where(classified, actual, 99))[:3]}
    return RaceBacktest(
        season=season,
        round=round,
        event=str(frames["session"]["event_name"].iloc[0]) if not frames["session"].empty else "",
        n_drivers=params.n_drivers,
        wet="wet_race" in params.assumptions,
        mae_position=float(np.abs(expected[classified] - actual[classified]).mean()),
        spearman=_spearman(expected[classified], actual[classified]),
        winner_hit=pred_winner == actual_winner,
        podium_overlap=len(pred_top3 & actual_top3),
        mean_log_score=float(np.mean(log_scores)) if log_scores else float("nan"),
        clean_laps=report.clean_laps,
        assumptions=len(params.assumptions),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("season", type=int)
    ap.add_argument(
        "--rounds", type=str, default="", help="comma-separated; default = all ingested"
    )
    ap.add_argument("--sims", type=int, default=5000)
    ap.add_argument("--json", type=str, default="", help="write per-race rows to this path")
    args = ap.parse_args()
    client = get_client()
    if args.rounds:
        rounds = [int(r) for r in args.rounds.split(",")]
    else:
        rows = client.query(
            "SELECT DISTINCT round FROM sessions FINAL WHERE season={s:UInt16} AND session_type='R' ORDER BY round",
            parameters={"s": args.season},
        ).result_rows
        rounds = [r[0] for r in rows]
    out: list[RaceBacktest] = []
    for r in rounds:
        try:
            bt = backtest_race(args.season, r, args.sims, client)
        except ValueError as e:
            print(f"round {r}: skipped ({e})")
            continue
        out.append(bt)
        print(
            f"R{r:02d} {bt.event[:24]:24s} wet={int(bt.wet)} MAE={bt.mae_position:.2f} "
            f"rho={bt.spearman:.2f} winner={int(bt.winner_hit)} podium={bt.podium_overlap}/3 "
            f"logscore={bt.mean_log_score:.2f} clean_laps={bt.clean_laps}"
        )
    if not out:
        return
    df = pd.DataFrame([asdict(b) for b in out])
    dry = df[~df["wet"]]
    print("\n| Metric | All races | Dry races | Command |")
    print("|---|---|---|---|")
    cmd = f"`uv run python -m pitwall.sim.backtest {args.season} --sims {args.sims}`"
    print(f"| Races | {len(df)} | {len(dry)} | {cmd} |")
    print(
        f"| MAE of expected finishing position | {df.mae_position.mean():.2f} | {dry.mae_position.mean():.2f} | |"
    )
    print(
        f"| Spearman rank correlation (mean) | {df.spearman.mean():.2f} | {dry.spearman.mean():.2f} | |"
    )
    print(f"| Winner hit rate | {df.winner_hit.mean():.0%} | {dry.winner_hit.mean():.0%} | |")
    print(
        f"| Podium overlap (mean of 3) | {df.podium_overlap.mean():.2f} | {dry.podium_overlap.mean():.2f} | |"
    )
    print(
        f"| Mean log-score of actual position | {df.mean_log_score.mean():.2f} | {dry.mean_log_score.mean():.2f} | |"
    )
    if args.json:
        with open(args.json, "w") as f:
            json.dump([asdict(b) for b in out], f, indent=1)


if __name__ == "__main__":
    main()
