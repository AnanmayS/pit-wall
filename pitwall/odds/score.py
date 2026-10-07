"""Score our pre-race win probabilities against Polymarket's with the Brier score.

For round r the forecast is built from races 1..r-1 only (recent-form fit, PLAN.md section 6); the
market probability is the last stored Yes price at `hours_before` hours before the race start,
normalised across the event's driver markets. Winner = results.position == 1.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import timedelta

import numpy as np

from pitwall.db.clickhouse import get_client
from pitwall.odds import markets_store
from pitwall.odds.scoring import score_race
from pitwall.odds.season import fit_form, generic_race_params
from pitwall.sim.engine import simulate

SKIP_CODES = {"PLACEHOLDER", "OTHER", "UNKNOWN", ""}


@dataclass
class RaceScore:
    season: int
    round: int
    event: str
    winner: str
    our_p_winner: float
    market_p_winner: float
    our_brier: float
    market_brier: float
    our_log_loss: float
    market_log_loss: float
    market_drivers: int
    market_total_raw: float
    n_sims: int


def race_win_forecast(
    season: int, after_round: int, n_laps: int, n_sims: int, client, seed: int = 0
) -> dict[str, float]:
    form, _ = fit_form(season, after_round, client)
    if not form:
        return {}
    params = generic_race_params(form, n_laps, np.random.default_rng(seed))
    res = simulate(params, n_sims=n_sims)
    wins = res.positions == 1
    return {d: float(wins[:, j].mean()) for j, d in enumerate(params.drivers)}


def market_prices_for_round(client, season: int, round: int, ts) -> dict[str, float]:
    out: dict[str, float] = {}
    for m in markets_store.load_markets(client, season, ["race_winner"]):
        if m.get("round") != round or m.get("driver") in SKIP_CODES:
            continue
        p = markets_store.price_at(client, m["market_id"], ts)
        if p is not None:
            out[m["driver"]] = p
    return out


def backtest_season(
    season: int,
    rounds: list[int] | None = None,
    *,
    n_sims: int = 5000,
    hours_before: float = 1.0,
    client=None,
) -> tuple[list[RaceScore], list[str]]:
    client = client or get_client()
    races = client.query_df(
        "SELECT round, event_name, session_date, total_laps FROM sessions FINAL "
        "WHERE season={s:UInt16} AND session_type='R' ORDER BY round",
        parameters={"s": season},
    )
    winners = client.query_df(
        "SELECT round, driver FROM results FINAL WHERE season={s:UInt16} AND session_type='R' AND position=1",
        parameters={"s": season},
    ).set_index("round")["driver"]
    out: list[RaceScore] = []
    notes: list[str] = []
    for row in races.itertuples():
        r = int(row.round)
        if rounds and r not in rounds:
            continue
        if r == 1:
            notes.append(f"R{r}: no completed race to fit form from; skipped")
            continue
        if r not in winners.index:
            notes.append(f"R{r}: no winner in results; skipped")
            continue
        ts = row.session_date.to_pydatetime() - timedelta(hours=hours_before)
        market = market_prices_for_round(client, season, r, ts)
        if len(market) < 5:
            notes.append(
                f"R{r}: only {len(market)} market prices at {ts:%Y-%m-%d %H:%M} UTC; skipped"
            )
            continue
        n_laps = int(row.total_laps) if row.total_laps == row.total_laps and row.total_laps else 57
        ours = race_win_forecast(season, r - 1, n_laps, n_sims, client, seed=r)
        if not ours:
            notes.append(f"R{r}: no form fit; skipped")
            continue
        sr = score_race(ours, market, str(winners[r]))
        raw_total = float(sum(market.values()))
        out.append(
            RaceScore(
                season,
                r,
                str(row.event_name),
                sr["winner"],
                sr["our"]["p_winner"],
                sr["market"]["p_winner"],
                sr["our"]["brier"],
                sr["market"]["brier"],
                sr["our"]["log_loss"],
                sr["market"]["log_loss"],
                len(market),
                raw_total,
                n_sims,
            )
        )
    return out, notes


def markdown_summary(scores: list[RaceScore], notes: list[str], cmd: str) -> str:
    lines = [
        "| Round | Race | Winner | Our P(win) | Market P(win) | Our Brier | Market Brier |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for s in scores:
        lines.append(
            f"| {s.round} | {s.event} | {s.winner} | {s.our_p_winner:.2f} | {s.market_p_winner:.2f} | {s.our_brier:.3f} | {s.market_brier:.3f} |"
        )
    n = len(scores)
    if n:
        ob = sum(s.our_brier for s in scores) / n
        mb = sum(s.market_brier for s in scores) / n
        ol = sum(s.our_log_loss for s in scores) / n
        ml = sum(s.market_log_loss for s in scores) / n
        beat = sum(s.our_brier < s.market_brier for s in scores)
        lines += [
            "",
            "| Metric | Ours | Polymarket | Command |",
            "|---|---:|---:|---|",
            f"| Races scored | {n} | {n} | {cmd} |",
            f"| Mean Brier (lower is better) | {ob:.3f} | {mb:.3f} | |",
            f"| Mean log-loss | {ol:.3f} | {ml:.3f} | |",
            f"| Races where ours beat the market (Brier) | {beat}/{n} | | |",
        ]
    if notes:
        lines += ["", "Skipped: " + "; ".join(notes)]
    return "\n".join(lines)


def dump_json(scores: list[RaceScore], path: str) -> None:
    with open(path, "w") as f:
        json.dump([asdict(s) for s in scores], f, indent=1)
