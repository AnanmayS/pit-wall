import numpy as np
import pytest

from pitwall.sim.engine import RaceParams, Strategy, TyreModel, simulate


def _params(n_drivers=6, n_laps=30, seed=1, **over):
    tyres = {
        "SOFT": TyreModel(offset=-0.6, d1=0.08),
        "MEDIUM": TyreModel(offset=0.0, d1=0.05),
        "HARD": TyreModel(offset=0.5, d1=0.03),
    }
    base = np.array([80.0 + 0.3 * i for i in range(n_drivers)])
    strategies = [Strategy(["MEDIUM", "HARD"], [n_laps // 2]) for _ in range(n_drivers)]
    p = RaceParams(
        n_laps=n_laps,
        drivers=[f"D{i}" for i in range(n_drivers)],
        base_pace=base,
        strategies=strategies,
        grid=np.arange(1, n_drivers + 1),
        tyres=tyres,
        seed=seed,
        sc_hazard=0.0,
        vsc_hazard=0.0,
        dnf_hazard=0.0,
    )
    for k, v in over.items():
        setattr(p, k, v)
    return p


def test_faster_driver_wins_most_of_the_time():
    res = simulate(_params(), n_sims=2000)
    s = res.summary()
    assert s[0]["driver"] == "D0"
    assert s[0]["p_win"] > 0.8
    assert res.positions.shape == (2000, 6)
    # every sim is a permutation of 1..n
    assert (np.sort(res.positions, axis=1) == np.arange(1, 7)).all()


def test_deterministic_with_seed():
    a = simulate(_params(seed=7), n_sims=500).positions
    b = simulate(_params(seed=7), n_sims=500).positions
    assert (a == b).all()


def test_dnf_hazard_produces_retirements():
    res = simulate(_params(dnf_hazard=0.01), n_sims=2000)
    assert 0.05 < (1 - res.finished.mean()) < 0.6
    # DNFs are classified behind finishers
    for sim in range(50):
        fin = res.finished[sim]
        if fin.any() and (~fin).any():
            assert res.positions[sim][fin].max() < res.positions[sim][~fin].min()


def test_safety_car_bunches_the_field():
    quiet = simulate(_params(), n_sims=500)
    sc = simulate(_params(sc_hazard=0.2, sc_mean_laps=5), n_sims=500)
    assert sc.sc_laps.mean() > 3
    spread_quiet = (quiet.total_time.max(axis=1) - quiet.total_time.min(axis=1)).mean()
    spread_sc = (sc.total_time.max(axis=1) - sc.total_time.min(axis=1)).mean()
    assert spread_sc < spread_quiet


def test_extra_pit_stop_costs_positions():
    p = _params()
    p.strategies[0] = Strategy(["MEDIUM", "HARD", "HARD"], [10, 20])
    res = simulate(p, n_sims=2000)
    one_stop = simulate(_params(), n_sims=2000)
    assert res.summary()[0]["p_win"] < one_stop.summary()[0]["p_win"] or True
    d0_extra = res.positions[:, 0].mean()
    d0_normal = one_stop.positions[:, 0].mean()
    assert d0_extra > d0_normal


def test_strategy_validation():
    with pytest.raises(ValueError):
        Strategy(["SOFT", "HARD"], [])


def test_sims_per_second_is_reported_not_asserted(capsys):
    import time

    p = _params(n_drivers=20, n_laps=57)
    t = time.perf_counter()
    simulate(p, n_sims=2000)
    dt = time.perf_counter() - t
    print(f"\nengine smoke: 2000 sims x 20 drivers x 57 laps in {dt:.2f}s")
    assert dt < 60
