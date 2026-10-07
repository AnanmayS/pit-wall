import numpy as np

from pitwall.odds.season import (
    RACE_POINTS,
    SPRINT_POINTS,
    DriverForm,
    _points_matrix,
    generic_race_params,
)


def test_points_matrix_awards_table_and_zeroes_dnfs():
    positions = np.array([[1, 2, 3, 11], [4, 1, 2, 3]])
    finished = np.array([[True, True, False, True], [True, True, True, True]])
    pts = _points_matrix(positions, finished, RACE_POINTS)
    assert pts.tolist() == [[25, 18, 0, 0], [12, 25, 18, 15]]
    assert _points_matrix(np.array([[9]]), np.array([[True]]), SPRINT_POINTS).tolist() == [[0]]


def test_generic_params_orders_drivers_by_pace():
    form = {
        "SLO": DriverForm("SLO", "T1", 0.5, 0.2, 3, 0.001),
        "FAS": DriverForm("FAS", "T2", -0.5, 0.2, 3, 0.001),
    }
    p = generic_race_params(form, 50, np.random.default_rng(0))
    assert p.drivers == ["FAS", "SLO"]
    assert p.base_pace[0] < p.base_pace[1]
    assert p.strategies[0].stop_laps == [22]
