"""Build a simulation from a real race at a branch lap and apply What If changes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pitwall.sim.engine import COMPOUND_INDEX, RaceParams, RaceResult, RaceState, Strategy, simulate
from pitwall.sim.fit import fit_race, load_race_frames
from pitwall.whatif.models import Change, ScenarioSpec


@dataclass
class ScenarioOutcome:
    scenario_id: str | None
    season: int
    round: int
    branch_lap: int
    n_runs: int
    compute_ms: float
    summary: list[dict]
    changed_drivers: list[dict]
    assumptions: dict[str, str]
    fit: dict

    def to_dict(self) -> dict:
        return {
            "season": self.season,
            "round": self.round,
            "branch_lap": self.branch_lap,
            "n_runs": self.n_runs,
            "compute_ms": self.compute_ms,
            "summary": self.summary,
            "changed_drivers": self.changed_drivers,
            "assumptions": self.assumptions,
            "fit": self.fit,
        }


@dataclass
class _DriverSnapshot:
    time_s: float
    alive: bool
    laps_done: int
    tyre_age: int
    compound: str
    remaining: Strategy = field(default_factory=lambda: Strategy(["MEDIUM"], []))


def _status_at_lap_starts(track_status: pd.DataFrame, laps: pd.DataFrame) -> dict[int, int]:
    leader = (
        laps[laps["position"] == 1]
        .dropna(subset=["lap_start_session_ms"])
        .sort_values("lap_number")
    )
    if leader.empty or track_status.empty:
        return {}
    ts = track_status.sort_values("session_ms")
    starts = leader["lap_start_session_ms"].astype(float).to_numpy()
    idx = np.searchsorted(ts["session_ms"].astype(float).to_numpy(), starts, side="right") - 1
    statuses = ts["status"].to_numpy()[np.clip(idx, 0, len(ts) - 1)]
    return {int(lap): int(st) for lap, st in zip(leader["lap_number"], statuses, strict=True)}


def snapshot_at_branch(
    frames: dict, params: RaceParams, branch_lap: int
) -> dict[str, _DriverSnapshot]:
    """Per-driver state at the start of `branch_lap`, from real lap data."""
    laps = frames["laps"]
    stints = frames["stints"]
    t0 = float(laps.loc[laps["lap_number"] == 1, "lap_start_session_ms"].min())
    out: dict[str, _DriverSnapshot] = {}
    for i, d in enumerate(params.drivers):
        dl = laps[laps["driver"] == d].sort_values("lap_number")
        row = dl[dl["lap_number"] == branch_lap]
        st = stints[stints["driver"] == d].sort_values("stint")
        full = params.strategies[i]
        if row.empty or pd.isna(row["lap_start_session_ms"].iloc[0]):
            # retired (or no data) before the branch lap
            last = dl.dropna(subset=["lap_start_session_ms"]).tail(1)
            t = float(last["lap_start_session_ms"].iloc[0] - t0) if not last.empty else 0.0
            out[d] = _DriverSnapshot(
                t, False, int(dl["lap_number"].max()) if not dl.empty else 0, 0, "MEDIUM"
            )
            continue
        r = row.iloc[0]
        stint_no = int(r["stint"]) if pd.notna(r["stint"]) else 1
        compound = str(r["compound"]) if str(r["compound"]) in COMPOUND_INDEX else "MEDIUM"
        remaining_comps = full.compounds[max(stint_no - 1, 0) :] or [compound]
        remaining_stops = [s for s in full.stop_laps if s >= branch_lap]
        remaining_comps = remaining_comps[: len(remaining_stops) + 1]
        while len(remaining_comps) < len(remaining_stops) + 1:
            remaining_comps.append(remaining_comps[-1])
        out[d] = _DriverSnapshot(
            time_s=float(r["lap_start_session_ms"] - t0),
            alive=True,
            laps_done=branch_lap - 1,
            tyre_age=int(r["tyre_life"]) - 1 if pd.notna(r["tyre_life"]) else 0,
            compound=compound,
            remaining=Strategy(remaining_comps, remaining_stops),
        )
        _ = st
    return out


def apply_changes(
    params: RaceParams, snaps: dict[str, _DriverSnapshot], changes: list[Change], branch_lap: int
) -> None:
    for c in changes:
        if c.type == "no_safety_car":
            params.sc_hazard = 0.0
            params.vsc_hazard = 0.0
            params.forced_sc = {}
            continue
        if c.type == "safety_car":
            params.forced_sc[int(c.lap)] = int(round(params.sc_mean_laps))
            continue
        if c.driver not in snaps:
            raise ValueError(f"unknown driver {c.driver}")
        snap = snaps[c.driver]
        comps, stops = list(snap.remaining.compounds), list(snap.remaining.stop_laps)
        if c.type == "dnf":
            params.forced_dnf[c.driver] = int(c.lap)
        elif c.type == "pit_lap":
            if int(c.lap) < branch_lap:
                raise ValueError("pit_lap must be at or after the branch lap")
            if stops:
                stops[0] = int(c.lap)
            else:
                stops.append(int(c.lap))
                comps.append(c.compound or comps[-1])
            if c.compound:
                comps[1] = c.compound
        elif c.type == "compound":
            k = int(c.stop)
            if k < 1 or k > len(stops):
                raise ValueError(
                    f"{c.driver} has {len(stops)} remaining stop(s); cannot change stop {k}"
                )
            comps[k] = c.compound
        elif c.type == "skip_stop":
            k = int(c.stop)
            if k < 1 or k > len(stops):
                raise ValueError(
                    f"{c.driver} has {len(stops)} remaining stop(s); cannot skip stop {k}"
                )
            del stops[k - 1]
            del comps[k]
        elif c.type == "extra_stop":
            stops.append(int(c.lap))
            order = np.argsort(stops)
            stops = [stops[i] for i in order]
            comps = comps[:1] + [comps[j + 1] if j + 1 < len(comps) else c.compound for j in order]
            comps[list(order).index(len(stops) - 1) + 1] = c.compound
        snap.remaining = Strategy(comps, sorted(stops))


def build_state(
    params: RaceParams, snaps: dict[str, _DriverSnapshot], n_sims: int, sc_remaining: int
) -> RaceState:
    n = params.n_drivers
    max_stops = max((len(s.remaining.stop_laps) for s in snaps.values()), default=0)
    stop_laps = np.zeros((n_sims, n, max_stops), dtype=np.int32)
    strategies = []
    for i, d in enumerate(params.drivers):
        s = snaps[d]
        strategies.append(s.remaining)
        for k, lap in enumerate(s.remaining.stop_laps):
            stop_laps[:, i, k] = lap
    params.strategies = strategies
    return RaceState(
        time=np.tile(np.array([snaps[d].time_s for d in params.drivers]), (n_sims, 1)),
        tyre_age=np.tile(
            np.array([snaps[d].tyre_age for d in params.drivers], dtype=np.int32), (n_sims, 1)
        ),
        stint_idx=np.zeros((n_sims, n), dtype=np.int32),
        compound_idx=np.tile(
            np.array([COMPOUND_INDEX[snaps[d].compound] for d in params.drivers]), (n_sims, 1)
        ),
        alive=np.tile(np.array([snaps[d].alive for d in params.drivers]), (n_sims, 1)),
        laps_done=np.tile(
            np.array([snaps[d].laps_done for d in params.drivers], dtype=np.int32), (n_sims, 1)
        ),
        stop_laps=stop_laps,
        sc_remaining=np.full(n_sims, sc_remaining, dtype=np.int32),
        vsc_remaining=np.zeros(n_sims, dtype=np.int32),
        pace_offset=np.zeros((n_sims, n)),
    )


def run_scenario(
    spec: ScenarioSpec, *, client=None, frames: dict | None = None, scenario_id: str | None = None
) -> ScenarioOutcome:
    t_start = time.perf_counter()
    frames = frames or load_race_frames(spec.season, spec.round, client)
    params, report = fit_race(spec.season, spec.round, frames=frames)
    branch = spec.effective_branch_lap()
    if branch < 2 or branch > params.n_laps:
        raise ValueError(f"branch lap must be between 2 and {params.n_laps}")
    snaps = snapshot_at_branch(frames, params, branch)
    apply_changes(params, snaps, spec.changes, branch)
    status = _status_at_lap_starts(frames["track_status"], frames["laps"])
    sc_rem = 0
    if status.get(branch) == 4:
        lap = branch
        while status.get(lap) == 4:
            sc_rem += 1
            lap += 1
    state = build_state(params, snaps, spec.n_runs, sc_rem)
    params.seed = int.from_bytes((scenario_id or "0").encode()[:8].ljust(8, b"0"), "big") % (2**32)
    result: RaceResult = simulate(params, state=state, start_lap=branch)
    summary = result.summary()
    actual = frames["results"].set_index("driver")["position"]
    changed = []
    for d in sorted({c.driver for c in spec.changes if c.driver}):
        i = params.drivers.index(d)
        pos = result.positions[:, i]
        act = int(actual.get(d)) if pd.notna(actual.get(d)) else None
        changed.append(
            {
                "driver": d,
                "actual_position": act,
                "expected_position": float(pos.mean()),
                "p_better_than_actual": float((pos < act).mean()) if act else None,
                "p_worse_than_actual": float((pos > act).mean()) if act else None,
                "position_probs": [
                    float((pos == k).mean()) for k in range(1, params.n_drivers + 1)
                ],
            }
        )
    return ScenarioOutcome(
        scenario_id=scenario_id,
        season=spec.season,
        round=spec.round,
        branch_lap=branch,
        n_runs=spec.n_runs,
        compute_ms=(time.perf_counter() - t_start) * 1000.0,
        summary=summary,
        changed_drivers=changed,
        assumptions=params.assumptions,
        fit={
            "clean_laps": report.clean_laps,
            "pit_stops_used": report.pit_stops_used,
            "sc_deployments": report.sc_deployments,
        },
    )
