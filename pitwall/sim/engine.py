"""Vectorized Monte Carlo race simulator.

State arrays are shaped (n_sims, n_drivers). The only Python loop is over laps (plus a short loop over
grid slots for the overtaking pass). Model spec: PLAN.md section 4. Every parameter is supplied through
RaceParams so that fitted values, assumptions and counterfactual overrides are explicit.

Conventions: times in seconds, laps are 1-based, positions are 1-based.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

COMPOUNDS = ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET")
COMPOUND_INDEX = {c: i for i, c in enumerate(COMPOUNDS)}


@dataclass
class TyreModel:
    """Lap-time penalty of a compound as a function of tyre age (laps on the set).

    penalty(age) = offset + d1 * age + d2 * age**2, in seconds relative to a fresh reference tyre.
    """

    offset: float
    d1: float
    d2: float = 0.0

    def penalty(self, age: np.ndarray) -> np.ndarray:
        return self.offset + self.d1 * age + self.d2 * age * age


@dataclass
class Strategy:
    """Planned stints for one driver: compounds in order and the laps on which to stop."""

    compounds: list[str]
    stop_laps: list[int]  # len == len(compounds) - 1; the lap on which the car pits

    def __post_init__(self) -> None:
        if len(self.stop_laps) != len(self.compounds) - 1:
            raise ValueError("stop_laps must have one fewer entry than compounds")
        for c in self.compounds:
            if c not in COMPOUND_INDEX:
                raise ValueError(f"unknown compound {c!r}")


@dataclass
class RaceParams:
    """Everything the engine needs for one race. See PLAN.md section 4 for the model."""

    n_laps: int
    drivers: list[str]
    base_pace: np.ndarray  # (n_drivers,) seconds per lap on fresh reference tyre, no fuel
    strategies: list[Strategy]
    grid: np.ndarray  # (n_drivers,) grid positions, 1-based
    tyres: dict[str, TyreModel]
    fuel_per_lap: float = 0.035  # seconds of lap time per lap of fuel on board
    lap_noise_sigma: np.ndarray | float = 0.25  # per-lap Gaussian noise (seconds)
    race_pace_sigma: np.ndarray | float = 0.0  # per-sim race-level pace offset (forecast mode)
    pit_loss: float = 21.0
    pit_loss_sc: float = 10.0
    pit_loss_vsc: float = 14.0
    sc_hazard: float = 0.012  # per-lap probability that a safety car is deployed
    sc_mean_laps: float = 4.0
    vsc_hazard: float = 0.015
    vsc_mean_laps: float = 2.0
    sc_lap_factor: float = 1.45  # lap time multiplier under SC (relative to leader's clean pace)
    vsc_lap_factor: float = 1.30
    sc_bunch_gap: float = 0.8  # seconds between consecutive cars behind the SC
    sc_pit_tyre_age: int = (
        8  # pit under SC if the current set is older than this and a stop remains
    )
    dnf_hazard: np.ndarray | float = 0.0015  # per-lap retirement probability
    lap1_dnf_multiplier: float = 6.0
    overtake_p_base: float = 0.35  # chance that a faster car completes an overtake on a given lap
    overtake_pace_scale: float = 0.5  # pace-delta (s/lap) at which overtake prob rises by ~e
    follow_gap: float = 0.9  # seconds a held-up car sits behind the car ahead
    grid_slot_gap: float = 0.35  # lap-1 time lost per grid slot
    stop_lap_jitter: float = 1.0  # std-dev (laps) of random variation around planned stop laps
    forced_sc: dict[int, int] = field(default_factory=dict)  # lap -> SC duration (laps), every sim
    forced_dnf: dict[str, int] = field(
        default_factory=dict
    )  # driver -> lap of retirement, every sim
    seed: int | None = None
    assumptions: dict[str, str] = field(default_factory=dict)  # labels for unfitted parameters

    @property
    def n_drivers(self) -> int:
        return len(self.drivers)

    def validate(self) -> None:
        n = self.n_drivers
        if len(self.strategies) != n or len(self.base_pace) != n or len(self.grid) != n:
            raise ValueError("drivers, strategies, base_pace and grid must have the same length")
        for s in self.strategies:
            for c in s.compounds:
                if c not in self.tyres:
                    raise ValueError(f"no tyre model for compound {c!r}")


@dataclass
class RaceState:
    """Mutable per-sim state. Shapes are (n_sims, n_drivers) unless noted."""

    time: np.ndarray  # cumulative race time
    tyre_age: np.ndarray  # laps on current set (int)
    stint_idx: np.ndarray  # index into Strategy.compounds (int)
    compound_idx: np.ndarray  # index into COMPOUNDS (int)
    alive: np.ndarray  # bool
    laps_done: np.ndarray  # int
    stop_laps: np.ndarray  # (n_sims, n_drivers, max_stops) planned stop laps (0 = none)
    sc_remaining: np.ndarray  # (n_sims,) laps of SC left (0 = none)
    vsc_remaining: np.ndarray  # (n_sims,)
    pace_offset: np.ndarray  # (n_sims, n_drivers) race-level pace offset


@dataclass
class RaceResult:
    drivers: list[str]
    positions: np.ndarray  # (n_sims, n_drivers) finishing position, 1-based; DNFs ranked last
    finished: np.ndarray  # (n_sims, n_drivers) bool
    total_time: np.ndarray  # (n_sims, n_drivers)
    sc_laps: np.ndarray  # (n_sims,) number of SC laps in each sim
    n_sims: int

    def position_distribution(self) -> np.ndarray:
        """(n_drivers, n_drivers) matrix: P(driver i finishes in position j+1)."""
        n = len(self.drivers)
        out = np.zeros((n, n))
        for j in range(n):
            out[:, j] = (self.positions == j + 1).mean(axis=0)
        return out

    def summary(self) -> list[dict]:
        dist = self.position_distribution()
        rows = []
        for i, d in enumerate(self.drivers):
            rows.append(
                {
                    "driver": d,
                    "p_win": float(dist[i, 0]),
                    "p_podium": float(dist[i, :3].sum()),
                    "p_points": float(dist[i, :10].sum()),
                    "p_dnf": float(1.0 - self.finished[:, i].mean()),
                    "expected_position": float((self.positions[:, i]).mean()),
                    "position_probs": [float(x) for x in dist[i]],
                }
            )
        rows.sort(key=lambda r: r["expected_position"])
        return rows


def _as_array(value: np.ndarray | float, n: int) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    return np.full(n, float(arr)) if arr.ndim == 0 else arr


def initial_state(params: RaceParams, n_sims: int, rng: np.random.Generator) -> RaceState:
    n = params.n_drivers
    max_stops = max((len(s.stop_laps) for s in params.strategies), default=0)
    stop_laps = np.zeros((n_sims, n, max_stops), dtype=np.int32)
    for i, s in enumerate(params.strategies):
        for k, lap in enumerate(s.stop_laps):
            jitter = (
                rng.normal(0.0, params.stop_lap_jitter, size=n_sims)
                if params.stop_lap_jitter
                else 0
            )
            planned = np.clip(np.rint(lap + jitter), 2, params.n_laps - 1)
            stop_laps[:, i, k] = planned
    # keep stops in increasing order and at least one lap apart
    if max_stops > 1:
        stop_laps.sort(axis=2)
        for k in range(1, max_stops):
            stop_laps[:, :, k] = np.where(
                (stop_laps[:, :, k] > 0) & (stop_laps[:, :, k] <= stop_laps[:, :, k - 1]),
                stop_laps[:, :, k - 1] + 1,
                stop_laps[:, :, k],
            )
    compound_idx = np.array([COMPOUND_INDEX[s.compounds[0]] for s in params.strategies])
    sigma_race = _as_array(params.race_pace_sigma, n)
    return RaceState(
        time=np.zeros((n_sims, n)),
        tyre_age=np.zeros((n_sims, n), dtype=np.int32),
        stint_idx=np.zeros((n_sims, n), dtype=np.int32),
        compound_idx=np.tile(compound_idx, (n_sims, 1)),
        alive=np.ones((n_sims, n), dtype=bool),
        laps_done=np.zeros((n_sims, n), dtype=np.int32),
        stop_laps=stop_laps,
        sc_remaining=np.zeros(n_sims, dtype=np.int32),
        vsc_remaining=np.zeros(n_sims, dtype=np.int32),
        pace_offset=rng.normal(0.0, 1.0, size=(n_sims, n)) * sigma_race,
    )


def _tyre_penalty(params: RaceParams, compound_idx: np.ndarray, age: np.ndarray) -> np.ndarray:
    """Vectorized tyre penalty over an (n_sims, n_drivers) grid of compound indices and ages."""
    out = np.zeros_like(age, dtype=float)
    for name, model in params.tyres.items():
        mask = compound_idx == COMPOUND_INDEX[name]
        if mask.any():
            out[mask] = model.penalty(age[mask].astype(float))
    return out


def _next_compound_idx(params: RaceParams, stint_idx: np.ndarray) -> np.ndarray:
    """Compound index for each driver's stint number (clamped to the last planned stint)."""
    n_sims, n = stint_idx.shape
    out = np.empty_like(stint_idx)
    for i, s in enumerate(params.strategies):
        idx = np.minimum(stint_idx[:, i], len(s.compounds) - 1)
        table = np.array([COMPOUND_INDEX[c] for c in s.compounds])
        out[:, i] = table[idx]
    return out


def _overtaking_pass(
    params: RaceParams,
    time_start: np.ndarray,
    time_new: np.ndarray,
    lap_pace: np.ndarray,
    alive: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Resolve on-track position changes for one lap.

    Cars are processed in their running order at the start of the lap. A car that would finish the
    lap ahead of the car in front of it attempts an overtake; on failure it is held up `follow_gap`
    behind. This resolves one swap per pair per lap, which is a documented simplification.
    """
    n_sims, n = time_new.shape
    order = np.argsort(
        np.where(alive, time_start, np.inf), axis=1
    )  # (n_sims, n) driver ids by position
    rows = np.arange(n_sims)[:, None]
    t_sorted = np.take_along_axis(time_new, order, axis=1)
    pace_sorted = np.take_along_axis(lap_pace, order, axis=1)
    alive_sorted = np.take_along_axis(alive, order, axis=1)
    for k in range(1, n):
        behind = t_sorted[:, k]
        ahead = t_sorted[:, k - 1]
        both_alive = alive_sorted[:, k] & alive_sorted[:, k - 1]
        would_pass = both_alive & (behind < ahead)
        if not would_pass.any():
            continue
        pace_delta = pace_sorted[:, k - 1] - pace_sorted[:, k]  # >0 when the car behind is faster
        p = 1.0 - (1.0 - params.overtake_p_base) * np.exp(
            -np.maximum(pace_delta, 0.0) / params.overtake_pace_scale
        )
        success = rng.random(n_sims) < p
        held = would_pass & ~success
        t_sorted[:, k] = np.where(held, ahead + params.follow_gap, behind)
    resolved = np.empty_like(time_new)
    np.put_along_axis(resolved, order, t_sorted, axis=1)
    _ = rows
    return resolved


def simulate(
    params: RaceParams,
    n_sims: int = 10_000,
    *,
    state: RaceState | None = None,
    start_lap: int = 1,
    rng: np.random.Generator | None = None,
) -> RaceResult:
    """Run the race from `start_lap` to the end for every sim.

    Pass `state` (e.g. built from real lap data) with `start_lap` > 1 to continue a race from a branch
    point for counterfactuals; otherwise the race starts from the grid.
    """
    params.validate()
    rng = rng or np.random.default_rng(params.seed)
    n = params.n_drivers
    st = state or initial_state(params, n_sims, rng)
    n_sims = st.time.shape[0]
    base = params.base_pace[None, :] + st.pace_offset
    noise_sigma = _as_array(params.lap_noise_sigma, n)[None, :]
    dnf_hazard = _as_array(params.dnf_hazard, n)[None, :]
    sc_laps = np.zeros(n_sims, dtype=np.int32)

    if state is None:
        # lap-1 grid effect: time lost per slot, so pole starts the race ahead
        st.time += (params.grid[None, :].astype(float) - 1.0) * params.grid_slot_gap

    for lap in range(start_lap, params.n_laps + 1):
        fuel_laps = params.n_laps - lap
        # --- safety car / VSC deployment ---
        no_neutralisation = (st.sc_remaining == 0) & (st.vsc_remaining == 0)
        new_sc = no_neutralisation & (rng.random(n_sims) < params.sc_hazard)
        if lap in params.forced_sc:
            new_sc = no_neutralisation | True
            st.sc_remaining = np.full(n_sims, max(1, params.forced_sc[lap]), dtype=np.int32)
            st.vsc_remaining[:] = 0
        st.sc_remaining = np.where(
            new_sc, np.maximum(1, rng.poisson(params.sc_mean_laps, n_sims)), st.sc_remaining
        )
        new_vsc = no_neutralisation & ~new_sc & (rng.random(n_sims) < params.vsc_hazard)
        st.vsc_remaining = np.where(
            new_vsc, np.maximum(1, rng.poisson(params.vsc_mean_laps, n_sims)), st.vsc_remaining
        )
        sc_on = st.sc_remaining > 0
        vsc_on = st.vsc_remaining > 0
        sc_laps += sc_on

        # --- clean lap time ---
        pace = (
            base
            + params.fuel_per_lap * fuel_laps
            + _tyre_penalty(params, st.compound_idx, st.tyre_age)
        )
        lap_time = pace + rng.normal(0.0, 1.0, size=(n_sims, n)) * noise_sigma

        # --- pit stops (planned, or opportunistic under SC) ---
        remaining_stops = (
            (st.stop_laps > 0).any(axis=2) if st.stop_laps.shape[2] else np.zeros_like(st.alive)
        )
        planned_now = (
            (st.stop_laps == lap).any(axis=2) if st.stop_laps.shape[2] else np.zeros_like(st.alive)
        )
        sc_pit = sc_on[:, None] & remaining_stops & (st.tyre_age >= params.sc_pit_tyre_age)
        pitting = st.alive & (planned_now | sc_pit)
        if pitting.any():
            loss = np.where(
                sc_on[:, None],
                params.pit_loss_sc,
                np.where(vsc_on[:, None], params.pit_loss_vsc, params.pit_loss),
            )
            lap_time = lap_time + np.where(pitting, loss, 0.0)
            # consume the earliest remaining planned stop for cars that pit now
            if st.stop_laps.shape[2]:
                first_stop = np.argmax(st.stop_laps > 0, axis=2)
                idx = np.indices(pitting.shape)
                sel = (idx[0][pitting], idx[1][pitting], first_stop[pitting])
                st.stop_laps[sel] = 0
            st.stint_idx = np.where(pitting, st.stint_idx + 1, st.stint_idx)
            st.compound_idx = np.where(
                pitting, _next_compound_idx(params, st.stint_idx), st.compound_idx
            )
            st.tyre_age = np.where(pitting, 0, st.tyre_age)

        # --- neutralised laps ---
        leader_pace = np.min(np.where(st.alive, pace, np.inf), axis=1, keepdims=True)
        lap_time = np.where(
            sc_on[:, None],
            leader_pace * params.sc_lap_factor + np.where(pitting, params.pit_loss_sc, 0.0),
            lap_time,
        )
        lap_time = np.where(vsc_on[:, None], lap_time * params.vsc_lap_factor, lap_time)

        # --- retirements ---
        hazard = dnf_hazard * (params.lap1_dnf_multiplier if lap == 1 else 1.0)
        dnf_now = st.alive & (rng.random((n_sims, n)) < hazard)
        for drv, dnf_lap in params.forced_dnf.items():
            if dnf_lap == lap and drv in params.drivers:
                dnf_now[:, params.drivers.index(drv)] = st.alive[:, params.drivers.index(drv)]
        st.alive &= ~dnf_now

        # --- advance time with overtaking resolution ---
        time_new = st.time + lap_time
        if not sc_on.all():
            time_new = _overtaking_pass(params, st.time, time_new, pace, st.alive, rng)
        if sc_on.any():
            # bunch the field behind the safety car in running order
            order = np.argsort(np.where(st.alive, st.time, np.inf), axis=1)
            ranks = np.argsort(order, axis=1)
            leader_time = np.take_along_axis(time_new, order[:, :1], axis=1)
            bunched = leader_time + ranks * params.sc_bunch_gap
            time_new = np.where(sc_on[:, None] & st.alive, bunched, time_new)
        st.time = np.where(st.alive, time_new, st.time)
        st.laps_done += st.alive
        st.tyre_age += st.alive
        st.sc_remaining = np.maximum(st.sc_remaining - 1, 0)
        st.vsc_remaining = np.maximum(st.vsc_remaining - 1, 0)

    # classification: most laps first, then time; DNFs ordered by laps completed then by time
    key_laps = -st.laps_done.astype(float)
    key_time = st.time
    order = np.lexsort((key_time, key_laps), axis=1)
    positions = np.empty_like(order)
    np.put_along_axis(positions, order, np.tile(np.arange(1, n + 1), (n_sims, 1)), axis=1)
    return RaceResult(
        drivers=list(params.drivers),
        positions=positions,
        finished=st.alive.copy(),
        total_time=st.time.copy(),
        sc_laps=sc_laps,
        n_sims=n_sims,
    )
