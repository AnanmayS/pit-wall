"""Fit RaceParams for one race from ClickHouse (laps, stints, pit_stops, track_status, results).

Every fitted quantity records its sample size; anything that falls back to a default is listed in
RaceParams.assumptions so it can never be mistaken for a measurement.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pitwall.db.clickhouse import get_client
from pitwall.sim.engine import COMPOUNDS, RaceParams, Strategy, TyreModel

DEFAULTS = {
    "fuel_per_lap": 0.035,
    "d1": {"SOFT": 0.08, "MEDIUM": 0.05, "HARD": 0.03, "INTERMEDIATE": 0.05, "WET": 0.05},
    "pit_loss": 21.0,
    "sc_hazard": 0.012,
    "vsc_hazard": 0.015,
    "sc_mean_laps": 4.0,
    "vsc_mean_laps": 2.0,
    "dnf_per_lap": 0.0015,
    "lap_noise_sigma": 0.35,
}
MIN_CLEAN_LAPS = 40
MIN_DRIVER_LAPS = 5


@dataclass
class FitReport:
    """What was fitted from how many samples (for RESULTS/DECISIONS and the API)."""

    clean_laps: int
    drivers_fitted: int
    compounds: dict[str, int]
    pit_stops_used: int
    sc_deployments: int
    sc_laps_observed: int
    assumptions: dict[str, str]


def _q(client, sql, params):
    return client.query_df(sql, parameters=params)


def load_race_frames(season: int, round: int, client=None) -> dict[str, pd.DataFrame]:
    client = client or get_client()
    p = {"season": season, "round": round}
    return {
        "session": _q(
            client,
            "SELECT * FROM sessions FINAL WHERE season={season:UInt16} AND round={round:UInt8} AND session_type='R'",
            p,
        ),
        "laps": _q(
            client,
            "SELECT * FROM laps FINAL WHERE season={season:UInt16} AND round={round:UInt8} AND session_type='R' ORDER BY driver, lap_number",
            p,
        ),
        "stints": _q(
            client,
            "SELECT * FROM stints FINAL WHERE season={season:UInt16} AND round={round:UInt8} AND session_type='R' ORDER BY driver, stint",
            p,
        ),
        "pit_stops": _q(
            client,
            "SELECT * FROM pit_stops FINAL WHERE season={season:UInt16} AND round={round:UInt8} AND session_type='R'",
            p,
        ),
        "track_status": _q(
            client,
            "SELECT * FROM track_status FINAL WHERE season={season:UInt16} AND round={round:UInt8} AND session_type='R' ORDER BY session_ms",
            p,
        ),
        "results": _q(
            client,
            "SELECT * FROM results FINAL WHERE season={season:UInt16} AND round={round:UInt8} AND session_type='R' ORDER BY position",
            p,
        ),
    }


def clean_laps(laps: pd.DataFrame) -> pd.DataFrame:
    """Laps usable for pace fitting: accurate, green flag, no pit in/out, not lap 1, not deleted."""
    m = (
        laps["is_accurate"].astype(bool)
        & (laps["track_status"].astype(str) == "1")
        & laps["pit_in_session_ms"].isna()
        & laps["pit_out_session_ms"].isna()
        & (laps["lap_number"] > 1)
        & laps["lap_time_ms"].notna()
        & ~laps["deleted"].astype(bool)
    )
    out = laps.loc[m].copy()
    out["lap_time_s"] = out["lap_time_ms"].astype(float) / 1000.0
    return out


def fit_pace_model(
    clean: pd.DataFrame, n_laps: int
) -> tuple[dict, dict[str, TyreModel], float, dict]:
    """Least squares: lap_time = a_driver + off_compound + fuel*(L-lap) + d1_c*age + d2_c*age^2.

    Returns (driver pace dict, tyre models, fuel slope, diagnostics). The reference compound
    (offset fixed to 0) is the most-used one.
    """
    drivers = sorted(clean["driver"].unique())
    compounds = [c for c in COMPOUNDS if c in set(clean["compound"])]
    ref = clean["compound"].value_counts().idxmax()
    cols: list[str] = []
    x_parts = []
    for d in drivers:
        x_parts.append((clean["driver"] == d).astype(float).to_numpy())
        cols.append(f"pace:{d}")
    for c in compounds:
        if c != ref:
            x_parts.append((clean["compound"] == c).astype(float).to_numpy())
            cols.append(f"off:{c}")
    x_parts.append((n_laps - clean["lap_number"]).astype(float).to_numpy())
    cols.append("fuel")
    age = clean["tyre_life"].astype(float).to_numpy()
    for c in compounds:
        mask = (clean["compound"] == c).astype(float).to_numpy()
        x_parts.append(mask * age)
        cols.append(f"d1:{c}")
        x_parts.append(mask * age * age)
        cols.append(f"d2:{c}")
    x_mat = np.column_stack(x_parts)
    y = clean["lap_time_s"].to_numpy()
    # ridge on the degradation/fuel terms keeps them sane when a race has one compound
    lam = np.zeros(x_mat.shape[1])
    for i, c in enumerate(cols):
        if c.startswith(("d1:", "d2:", "fuel")):
            lam[i] = 1e-3
    beta = np.linalg.solve(x_mat.T @ x_mat + np.diag(lam), x_mat.T @ y)
    coef = dict(zip(cols, beta, strict=True))
    resid = y - x_mat @ beta
    assumptions: dict[str, str] = {}
    fuel = float(coef["fuel"])
    if not (0.0 <= fuel <= 0.12):
        assumptions["fuel_per_lap"] = (
            f"fitted {fuel:.3f} s/lap out of range, using default {DEFAULTS['fuel_per_lap']}"
        )
        fuel = DEFAULTS["fuel_per_lap"]
    tyres: dict[str, TyreModel] = {}
    for c in compounds:
        d1, d2 = float(coef[f"d1:{c}"]), float(coef[f"d2:{c}"])
        n_c = int((clean["compound"] == c).sum())
        if n_c < 15 or not (0.0 <= d1 <= 0.4):
            assumptions[f"tyre:{c}"] = (
                f"{n_c} clean laps, fitted d1={d1:.3f}; using default d1={DEFAULTS['d1'].get(c, 0.05)}"
            )
            d1, d2 = DEFAULTS["d1"].get(c, 0.05), 0.0
        d2 = float(np.clip(d2, -0.002, 0.01))
        offset = float(coef.get(f"off:{c}", 0.0))
        if abs(offset) > 3.0:
            assumptions[f"tyre_offset:{c}"] = (
                f"fitted offset {offset:.1f} s vs {ref} is implausible; clipped to ±3 s"
            )
            offset = float(np.clip(offset, -3.0, 3.0))
        tyres[c] = TyreModel(offset=offset, d1=d1, d2=d2)
    pace = {d: float(coef[f"pace:{d}"]) for d in drivers}
    diag = {
        "residual_std": float(resid.std()),
        "ref_compound": ref,
        "per_driver_sigma": {
            d: float(resid[(clean["driver"] == d).to_numpy()].std())
            for d in drivers
            if (clean["driver"] == d).sum() >= MIN_DRIVER_LAPS
        },
    }
    return pace, tyres, fuel, diag | {"assumptions": assumptions}


def fit_pit_loss(
    laps: pd.DataFrame, pit_stops: pd.DataFrame, clean: pd.DataFrame
) -> tuple[float, int, str | None]:
    """Pit loss = in-lap + out-lap − 2 × driver's median clean lap, over green-flag stops."""
    med = clean.groupby("driver")["lap_time_s"].median()
    samples = []
    by = laps.set_index(["driver", "lap_number"])
    for _, s in pit_stops.iterrows():
        d, lap_in = s["driver"], int(s["lap_in"])
        try:
            in_lap, out_lap = by.loc[(d, lap_in)], by.loc[(d, lap_in + 1)]
        except KeyError:
            continue
        if str(in_lap["track_status"]) != "1" or str(out_lap["track_status"]) != "1":
            continue
        if pd.isna(in_lap["lap_time_ms"]) or pd.isna(out_lap["lap_time_ms"]) or d not in med:
            continue
        samples.append((in_lap["lap_time_ms"] + out_lap["lap_time_ms"]) / 1000.0 - 2 * med[d])
    if len(samples) < 3:
        return (
            DEFAULTS["pit_loss"],
            len(samples),
            f"only {len(samples)} green-flag stops; default pit loss",
        )
    return float(np.median(samples)), len(samples), None


def sc_stats(track_status: pd.DataFrame, laps: pd.DataFrame) -> dict:
    """Count SC/VSC deployments and the laps they covered, using the leader's lap start times."""
    leader = laps[laps["position"] == 1].dropna(subset=["lap_start_session_ms"])
    lap_starts = leader.sort_values("lap_number")["lap_start_session_ms"].astype(float).to_numpy()
    n_laps = int(laps["lap_number"].max())
    ts = track_status.sort_values("session_ms")
    out = {
        "sc_deployments": 0,
        "vsc_deployments": 0,
        "sc_laps": 0,
        "vsc_laps": 0,
        "race_laps": n_laps,
    }
    prev = None
    for _, row in ts.iterrows():
        status = int(row["status"])
        if status == 4 and prev != 4:
            out["sc_deployments"] += 1
        if status in (6,) and prev not in (6,):
            out["vsc_deployments"] += 1
        prev = status
    # laps under each status: status at each lap start
    if len(lap_starts) and len(ts):
        idx = (
            np.searchsorted(ts["session_ms"].astype(float).to_numpy(), lap_starts, side="right") - 1
        )
        st_at_lap = ts["status"].to_numpy()[np.clip(idx, 0, len(ts) - 1)]
        out["sc_laps"] = int((st_at_lap == 4).sum())
        out["vsc_laps"] = int(np.isin(st_at_lap, (6, 7)).sum())
    return out


def strategies_from_laps(laps: pd.DataFrame, drivers: list[str]) -> list[Strategy]:
    """Stint plan per driver from the laps table.

    A real tyre change is a lap where tyre_life resets (does not increase) or the compound changes.
    FastF1's own stint numbering also increments on safety-car drive-throughs (e.g. Australia 2025
    laps 2-4), which would otherwise look like extra stops.
    """
    out = []
    for d in drivers:
        dl = laps[laps["driver"] == d].sort_values("lap_number")
        if dl.empty:
            out.append(Strategy(["MEDIUM"], []))
            continue
        comps: list[str] = []
        stops: list[int] = []
        prev_life, prev_comp = None, None
        for lap_no, comp, life in zip(
            dl["lap_number"], dl["compound"], dl["tyre_life"], strict=True
        ):
            comp = comp if comp in COMPOUNDS else "MEDIUM"
            life = int(life) if pd.notna(life) else 0
            if prev_comp is None:
                comps.append(comp)
            elif comp != prev_comp or (life <= prev_life and life <= 1):
                comps.append(comp)
                stops.append(int(lap_no) - 1)  # the car pitted on the previous lap
            prev_life, prev_comp = life, comp
        out.append(Strategy(comps, stops))
    return out


def fit_race(
    season: int, round: int, *, client=None, frames: dict | None = None
) -> tuple[RaceParams, FitReport]:
    f = frames or load_race_frames(season, round, client)
    laps, results = f["laps"], f["results"]
    if laps.empty or results.empty:
        raise ValueError(f"no race data for {season} round {round}")
    n_laps = (
        int(f["session"]["total_laps"].iloc[0])
        if not f["session"].empty and pd.notna(f["session"]["total_laps"].iloc[0])
        else int(laps["lap_number"].max())
    )
    drivers = results["driver"].tolist()
    clean = clean_laps(laps)
    assumptions: dict[str, str] = {}
    wet_share = float(clean["compound"].isin(["INTERMEDIATE", "WET"]).mean()) if len(clean) else 0.0
    if wet_share > 0.2:
        assumptions["wet_race"] = (
            f"{wet_share:.0%} of clean laps on wet-weather tyres; pace/tyre fit is unreliable"
        )
    if len(clean) >= MIN_CLEAN_LAPS:
        pace, tyres, fuel, diag = fit_pace_model(clean, n_laps)
        assumptions.update(diag["assumptions"])
    else:
        raise ValueError(f"only {len(clean)} clean laps; cannot fit pace model")
    # drivers with too few clean laps: pace = field median + penalty, labelled
    pace_arr = []
    for d in drivers:
        if d in pace and int((clean["driver"] == d).sum()) >= MIN_DRIVER_LAPS:
            pace_arr.append(pace[d])
        else:
            pace_arr.append(float(np.median(list(pace.values()))) + 0.5)
            assumptions[f"pace:{d}"] = "fewer than 5 clean laps; field median + 0.5 s"
    sigma_global = diag["residual_std"]
    sigmas = np.array([diag["per_driver_sigma"].get(d, sigma_global) for d in drivers])
    pit_loss, n_pit, pit_note = fit_pit_loss(laps, f["pit_stops"], clean)
    if pit_note:
        assumptions["pit_loss"] = pit_note
    sc = sc_stats(f["track_status"], laps)
    # single-race SC rate is noisy: shrink toward the default with a prior weight of 100 laps
    prior = 100.0
    sc_hazard = (sc["sc_deployments"] + prior * DEFAULTS["sc_hazard"]) / (sc["race_laps"] + prior)
    vsc_hazard = (sc["vsc_deployments"] + prior * DEFAULTS["vsc_hazard"]) / (
        sc["race_laps"] + prior
    )
    assumptions["sc_hazard"] = (
        "single-race SC/VSC rates shrunk toward defaults (prior weight 100 laps)"
    )
    sc_mean = (
        sc["sc_laps"] / sc["sc_deployments"] if sc["sc_deployments"] else DEFAULTS["sc_mean_laps"]
    )
    assumptions["dnf_hazard"] = (
        f"default {DEFAULTS['dnf_per_lap']}/lap for every driver (season-level fit not yet implemented)"
    )
    grid = (
        results["grid_position"]
        .fillna(len(drivers))
        .astype(int)
        .replace(0, len(drivers))
        .to_numpy()
    )
    params = RaceParams(
        n_laps=n_laps,
        drivers=drivers,
        base_pace=np.array(pace_arr),
        strategies=strategies_from_laps(laps, drivers),
        grid=grid,
        tyres=tyres,
        fuel_per_lap=fuel,
        lap_noise_sigma=sigmas,
        pit_loss=pit_loss,
        pit_loss_sc=max(pit_loss * 0.5, 5.0),
        pit_loss_vsc=max(pit_loss * 0.7, 5.0),
        sc_hazard=float(sc_hazard),
        vsc_hazard=float(vsc_hazard),
        sc_mean_laps=float(sc_mean),
        dnf_hazard=DEFAULTS["dnf_per_lap"],
        assumptions=assumptions,
    )
    report = FitReport(
        clean_laps=len(clean),
        drivers_fitted=len(diag["per_driver_sigma"]),
        compounds={c: int((clean["compound"] == c).sum()) for c in tyres},
        pit_stops_used=n_pit,
        sc_deployments=sc["sc_deployments"],
        sc_laps_observed=sc["sc_laps"],
        assumptions=assumptions,
    )
    return params, report
