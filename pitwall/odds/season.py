"""Season Monte Carlo: championship and race-win probabilities after a given round.

Forecast mode of the race engine: for each remaining race every driver's pace is drawn from a
recent-form estimate (exponentially weighted relative pace from fitted completed races) plus a
race-to-race spread, then the race is simulated with generic strategies and track defaults. All
unfitted quantities are listed in `SeasonForecast.assumptions`. Model spec: PLAN.md section 6.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pitwall.db.clickhouse import get_client
from pitwall.sim.engine import RaceParams, Strategy, TyreModel, simulate
from pitwall.sim.fit import DEFAULTS, fit_race, load_race_frames

log = logging.getLogger(__name__)

RACE_POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]
SPRINT_POINTS = [8, 7, 6, 5, 4, 3, 2, 1]
MODEL_VERSION = "season-v1"
HALF_LIFE_RACES = 3.0


@dataclass
class DriverForm:
    driver: str
    team: str
    pace_delta: float  # seconds per lap vs field median (negative = faster)
    pace_sigma: float  # race-to-race spread of the delta
    races: int
    dnf_hazard: float


@dataclass
class SeasonForecast:
    season: int
    after_round: int
    as_of: str
    n_sims: int
    remaining_rounds: list[int]
    remaining_sprints: list[int]
    standings: dict[str, float]
    team_standings: dict[str, float]
    p_title: dict[str, float]
    p_constructors: dict[str, float]
    p_next_win: dict[str, float]
    expected_points: dict[str, float]
    conditionals: list[dict]
    assumptions: dict[str, str] = field(default_factory=dict)
    compute_s: float = 0.0


def completed_rounds(season: int, client) -> pd.DataFrame:
    return client.query_df(
        "SELECT round, session_type, event_name, event_format, session_date FROM sessions FINAL "
        "WHERE season={s:UInt16} AND session_type IN ('R','S') ORDER BY round, session_type",
        parameters={"s": season},
    )


def standings_after(
    season: int, after_round: int, client
) -> tuple[dict[str, float], dict[str, float], dict[str, str]]:
    df = client.query_df(
        "SELECT driver, team, sum(points) AS pts FROM results FINAL WHERE season={s:UInt16} AND round<={r:UInt8} "
        "AND session_type IN ('R','S') GROUP BY driver, team ORDER BY pts DESC",
        parameters={"s": season, "r": after_round},
    )
    drivers: dict[str, float] = {}
    teams: dict[str, float] = {}
    team_of: dict[str, str] = {}
    for row in df.itertuples():
        drivers[row.driver] = drivers.get(row.driver, 0.0) + float(row.pts)
        teams[row.team] = teams.get(row.team, 0.0) + float(row.pts)
        team_of.setdefault(row.driver, row.team)  # first = most recent-ish; refined below
    latest = client.query_df(
        "SELECT driver, argMax(team, round) AS team FROM results FINAL WHERE season={s:UInt16} AND round<={r:UInt8} "
        "AND session_type='R' GROUP BY driver",
        parameters={"s": season, "r": after_round},
    )
    for row in latest.itertuples():
        team_of[row.driver] = row.team
    return drivers, teams, team_of


def fit_form(season: int, after_round: int, client) -> tuple[dict[str, DriverForm], dict[str, str]]:
    """Exponentially weighted relative pace per driver from fitted completed races."""
    rounds = completed_rounds(season, client)
    race_rounds = sorted(set(rounds.loc[rounds.session_type == "R", "round"].tolist()))
    race_rounds = [r for r in race_rounds if r <= after_round]
    deltas: dict[str, list[tuple[float, float]]] = {}  # driver -> [(weight, delta)]
    notes: dict[str, str] = {}
    for rnd in race_rounds:
        try:
            frames = load_race_frames(season, rnd, client)
            params, _ = fit_race(season, rnd, frames=frames)
        except ValueError as e:
            notes[f"round_{rnd}"] = f"skipped in form fit: {e}"
            continue
        wet = "wet_race" in params.assumptions
        age = after_round - rnd
        w = math.exp(-math.log(2) * age / HALF_LIFE_RACES) * (0.3 if wet else 1.0)
        med = float(np.median(params.base_pace))
        for (
            d,
            pace,
        ) in zip(params.drivers, params.base_pace, strict=True):
            if f"pace:{d}" in params.assumptions:
                continue  # fallback pace, not a measurement
            deltas.setdefault(d, []).append((w, float(pace - med)))
    # DNF hazard per driver from results (season-level, shrunk toward the default)
    res = client.query_df(
        "SELECT driver, countIf(status NOT LIKE 'Finished' AND status NOT LIKE '+%') AS dnfs, "
        "sum(laps_completed) AS laps FROM results FINAL WHERE season={s:UInt16} AND round<={r:UInt8} AND session_type='R' GROUP BY driver",
        parameters={"s": season, "r": after_round},
    )
    dnf = {
        row.driver: (float(row.dnfs) + 50 * DEFAULTS["dnf_per_lap"]) / (float(row.laps) + 50)
        for row in res.itertuples()
    }
    _, _, team_of = standings_after(season, after_round, client)
    form: dict[str, DriverForm] = {}
    for d, obs in deltas.items():
        w = np.array([o[0] for o in obs])
        x = np.array([o[1] for o in obs])
        mean = float(np.average(x, weights=w))
        var = float(np.average((x - mean) ** 2, weights=w)) if len(x) > 1 else 0.25**2
        form[d] = DriverForm(
            d,
            team_of.get(d, ""),
            mean,
            max(math.sqrt(var), 0.15),
            len(obs),
            dnf.get(d, DEFAULTS["dnf_per_lap"]),
        )
    return form, notes


def generic_race_params(
    form: dict[str, DriverForm], n_laps: int, rng: np.random.Generator
) -> RaceParams:
    drivers = sorted(form, key=lambda d: form[d].pace_delta)
    base = np.array([90.0 + form[d].pace_delta for d in drivers])
    sigma_race = np.array([form[d].pace_sigma for d in drivers])
    tyres = {
        "MEDIUM": TyreModel(0.0, DEFAULTS["d1"]["MEDIUM"], 0.0005),
        "HARD": TyreModel(0.4, DEFAULTS["d1"]["HARD"], 0.0002),
        "SOFT": TyreModel(-0.5, DEFAULTS["d1"]["SOFT"], 0.001),
    }
    stop = max(8, int(n_laps * 0.45))
    strategies = [Strategy(["MEDIUM", "HARD"], [stop]) for _ in drivers]
    return RaceParams(
        n_laps=n_laps,
        drivers=drivers,
        base_pace=base,
        strategies=strategies,
        grid=np.arange(1, len(drivers) + 1),
        tyres=tyres,
        race_pace_sigma=sigma_race,
        dnf_hazard=np.array([form[d].dnf_hazard for d in drivers]),
        stop_lap_jitter=3.0,
        seed=int(rng.integers(0, 2**31 - 1)),
    )


def _points_matrix(positions: np.ndarray, finished: np.ndarray, table: list[int]) -> np.ndarray:
    pts = np.zeros(positions.shape)
    for k, p in enumerate(table, start=1):
        pts[positions == k] = p
    return pts * finished


def simulate_season(
    season: int,
    after_round: int,
    *,
    n_sims: int = 20_000,
    client=None,
    remaining: list[tuple[int, bool, int]] | None = None,
    seed: int = 0,
) -> SeasonForecast:
    """remaining = [(round, is_sprint_weekend, race_laps)], defaults to the FastF1 schedule."""
    t0 = time.perf_counter()
    client = client or get_client()
    rng = np.random.default_rng(seed)
    standings, team_pts, team_of = standings_after(season, after_round, client)
    form, notes = fit_form(season, after_round, client)
    assumptions = dict(notes)
    for d in standings:
        if d not in form:
            form[d] = DriverForm(d, team_of.get(d, ""), 1.0, 0.3, 0, DEFAULTS["dnf_per_lap"])
            assumptions[f"form:{d}"] = "no fitted race pace; placed 1.0 s/lap behind field median"
    if remaining is None:
        remaining = remaining_schedule(season, after_round)
    assumptions["grid"] = (
        "grid order = drawn race pace order (no qualifying model); strategies = generic one-stop MEDIUM->HARD at 45% distance ±3 laps; track pit loss/SC/tyre parameters = engine defaults"
    )
    assumptions["points"] = (
        "2025+ points: 25-18-15-12-10-8-6-4-2-1, sprint 8-7-6-5-4-3-2-1, no fastest-lap point"
    )
    drivers = sorted(form)
    idx = {d: i for i, d in enumerate(drivers)}
    pts = np.zeros((n_sims, len(drivers)))
    for d, p in standings.items():
        pts[:, idx[d]] = p
    p_next_win: dict[str, float] = {}
    next_race_winner = None
    for k, (_rnd, is_sprint, laps) in enumerate(remaining):
        params = generic_race_params(form, laps, rng)
        # grid from drawn pace order: emulate by letting the engine's grid effect follow pace rank
        res = simulate(params, n_sims=n_sims)
        order = [idx[d] for d in params.drivers]
        race_pts = _points_matrix(res.positions, res.finished, RACE_POINTS)
        pts[:, order] += race_pts
        if is_sprint:
            sp = generic_race_params(form, max(15, laps // 3), rng)
            sres = simulate(sp, n_sims=n_sims)
            pts[:, [idx[d] for d in sp.drivers]] += _points_matrix(
                sres.positions, sres.finished, SPRINT_POINTS
            )
        if k == 0:
            wins = res.positions == 1
            p_next_win = {d: float(wins[:, j].mean()) for j, d in enumerate(params.drivers)}
            next_race_winner = np.array(params.drivers)[np.argmax(res.positions == 1, axis=1)]
    # ties broken by standing order (approximation: no countback)
    champion = np.argmax(pts + rng.random(pts.shape) * 1e-6, axis=1)
    p_title = {d: float((champion == idx[d]).mean()) for d in drivers}
    teams = sorted({form[d].team for d in drivers if form[d].team})
    team_pts_sim = np.zeros((n_sims, len(teams)))
    for d in drivers:
        t = form[d].team
        if t:
            team_pts_sim[:, teams.index(t)] += pts[:, idx[d]]
    tchamp = np.argmax(team_pts_sim + rng.random(team_pts_sim.shape) * 1e-6, axis=1)
    p_constructors = {t: float((tchamp == j).mean()) for j, t in enumerate(teams)}
    conditionals = []
    if next_race_winner is not None:
        top = sorted(p_title, key=p_title.get, reverse=True)[:3]
        for d in top:
            won_next = next_race_winner == d
            if won_next.any() and (~won_next).any():
                conditionals.append(
                    {
                        "driver": d,
                        "kind": "title_if_next_win",
                        "probability": float((champion[won_next] == idx[d]).mean()),
                        "n": int(won_next.sum()),
                    }
                )
                conditionals.append(
                    {
                        "driver": d,
                        "kind": "title_if_next_not_win",
                        "probability": float((champion[~won_next] == idx[d]).mean()),
                        "n": int((~won_next).sum()),
                    }
                )
    return SeasonForecast(
        season=season,
        after_round=after_round,
        as_of=pd.Timestamp.utcnow().isoformat(timespec="seconds"),
        n_sims=n_sims,
        remaining_rounds=[r for r, _, _ in remaining],
        remaining_sprints=[r for r, s, _ in remaining if s],
        standings=dict(sorted(standings.items(), key=lambda kv: -kv[1])),
        team_standings=dict(sorted(team_pts.items(), key=lambda kv: -kv[1])),
        p_title=dict(sorted(p_title.items(), key=lambda kv: -kv[1])),
        p_constructors=dict(sorted(p_constructors.items(), key=lambda kv: -kv[1])),
        p_next_win=dict(sorted(p_next_win.items(), key=lambda kv: -kv[1])),
        expected_points={d: float(pts[:, idx[d]].mean()) for d in drivers},
        conditionals=conditionals,
        assumptions=assumptions,
        compute_s=time.perf_counter() - t0,
    )


def remaining_schedule(season: int, after_round: int) -> list[tuple[int, bool, int]]:
    """Remaining rounds from the FastF1 schedule; race lap counts from ClickHouse where known, else 57."""
    import fastf1

    from pitwall.config import get_settings

    fastf1.Cache.enable_cache(str(get_settings().fastf1_cache_dir))
    sched = fastf1.get_event_schedule(season, include_testing=False)
    out = []
    for row in sched.itertuples():
        if int(row.RoundNumber) <= after_round:
            continue
        is_sprint = "sprint" in str(row.EventFormat)
        out.append((int(row.RoundNumber), is_sprint, 57))
    return out


def store_forecast(fc: SeasonForecast, client=None) -> int:
    client = client or get_client()
    rows = []
    for d, p in fc.p_title.items():
        rows.append(
            [fc.season, fc.as_of, fc.after_round, "title", None, d, "", p, fc.n_sims, MODEL_VERSION]
        )
    for t, p in fc.p_constructors.items():
        rows.append(
            [
                fc.season,
                fc.as_of,
                fc.after_round,
                "constructors",
                None,
                "",
                t,
                p,
                fc.n_sims,
                MODEL_VERSION,
            ]
        )
    nxt = fc.remaining_rounds[0] if fc.remaining_rounds else None
    for d, p in fc.p_next_win.items():
        rows.append(
            [
                fc.season,
                fc.as_of,
                fc.after_round,
                "race_win",
                nxt,
                d,
                "",
                p,
                fc.n_sims,
                MODEL_VERSION,
            ]
        )
    for c in fc.conditionals:
        rows.append(
            [
                fc.season,
                fc.as_of,
                fc.after_round,
                c["kind"],
                nxt,
                c["driver"],
                "",
                c["probability"],
                c["n"],
                MODEL_VERSION,
            ]
        )
    as_of = pd.Timestamp(fc.as_of).to_pydatetime().replace(tzinfo=None)
    for r in rows:
        r[1] = as_of
    client.insert(
        "forecasts",
        rows,
        column_names=[
            "season",
            "as_of",
            "after_round",
            "kind",
            "round",
            "driver",
            "team",
            "probability",
            "n_sims",
            "model_version",
        ],
    )
    return len(rows)
