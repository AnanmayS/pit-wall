"""Unit tests for distance alignment, corner metrics and insights (synthetic telemetry, no DB)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pitwall.telemetry.align import (
    braking_zones,
    corner_metrics,
    corner_name,
    delta_time,
    downsample_indices,
    resample_to_distance,
    scale_distance,
    segment_by_corners,
)
from pitwall.telemetry.coach import (
    MAX_GRID_POINTS,
    build_comparison,
    format_lap_time,
    format_seconds,
)

# ---------------------------------------------------------------------------
# synthetic telemetry helpers
# ---------------------------------------------------------------------------


def constant_speed_lap(speed_kph: float, length_m: float = 1000.0, spacing_m: float = 7.0):
    """Telemetry for a lap at constant speed; samples every `spacing_m` plus the exact end."""
    distance = np.append(np.arange(0.0, length_m, spacing_m), length_m)
    session_ms = 50_000 + distance / (speed_kph / 3.6) * 1000.0
    n = len(distance)
    return pd.DataFrame(
        {
            "session_ms": session_ms,
            "distance_m": distance,
            "rel_distance": distance / length_m,
            "speed_kph": np.full(n, speed_kph),
            "throttle_pct": np.full(n, 100.0),
            "brake": np.zeros(n, dtype=bool),
            "gear": np.full(n, 7),
            "drs": np.zeros(n, dtype=int),
            "x": np.zeros(n),
            "y": np.zeros(n),
        }
    )


def corner_lap(
    brake_point_m: float,
    apex_kph: float,
    throttle_on_m: float,
    corner_m: float = 800.0,
    length_m: float = 1500.0,
    top_kph: float = 300.0,
    spacing_m: float = 2.0,
) -> pd.DataFrame:
    """A lap with one corner: brake at brake_point_m, apex at corner_m, full throttle again
    at throttle_on_m and back to top speed 140 m later. Time is integrated from the speed
    profile, so it is self-consistent."""
    d = np.arange(0.0, length_m + spacing_m / 2, spacing_m)
    exit_end = throttle_on_m + 140.0
    speed = np.interp(
        d,
        [0.0, brake_point_m, corner_m, exit_end, length_m],
        [top_kph, top_kph, apex_kph, top_kph, top_kph],
    )
    v_ms = speed / 3.6
    dt_s = np.diff(d) / ((v_ms[1:] + v_ms[:-1]) / 2.0)
    session_ms = 100_000 + np.concatenate([[0.0], np.cumsum(dt_s)]) * 1000.0
    brake = (d >= brake_point_m) & (d < corner_m - 10.0)
    throttle = np.where(d < brake_point_m, 100.0, 0.0)
    exit_ramp = np.interp(d, [corner_m, throttle_on_m], [20.0, 80.0])
    throttle = np.where(d >= corner_m, np.where(d >= throttle_on_m, 100.0, exit_ramp), throttle)
    gear = np.where(brake | ((d >= corner_m) & (d < throttle_on_m)), 3, 8)
    return pd.DataFrame(
        {
            "session_ms": session_ms,
            "distance_m": d,
            "rel_distance": d / d[-1],
            "speed_kph": speed,
            "throttle_pct": throttle,
            "brake": brake,
            "gear": gear,
            "drs": np.zeros(len(d), dtype=int),
            "x": d,
            "y": np.zeros(len(d)),
        }
    )


# ---------------------------------------------------------------------------
# resample_to_distance / delta_time
# ---------------------------------------------------------------------------


def test_constant_speed_delta_is_analytic():
    a = resample_to_distance(constant_speed_lap(200.0))
    b = resample_to_distance(constant_speed_lap(210.0))
    d = delta_time(a, b)

    assert len(d) == 1001
    assert d["distance_m"].iloc[-1] == pytest.approx(1000.0)
    expected = d["distance_m"] / (200 / 3.6) * 1000 - d["distance_m"] / (210 / 3.6) * 1000
    np.testing.assert_allclose(d["delta_ms"], expected, atol=1e-6)
    # A is slower everywhere, so the delta is positive and growing.
    assert d["delta_ms"].iloc[-1] == pytest.approx(
        1000 / (200 / 3.6) * 1000 - 1000 / (210 / 3.6) * 1000
    )
    assert (np.diff(d["delta_ms"]) >= 0).all()


def test_resample_grid_and_elapsed_time():
    grid = resample_to_distance(constant_speed_lap(180.0), step_m=2.5)
    assert len(grid) == 401
    np.testing.assert_allclose(np.diff(grid["distance_m"]), 2.5)
    assert grid["time_ms"].iloc[0] == 0.0  # elapsed, not session time
    assert grid["time_ms"].iloc[-1] == pytest.approx(1000 / (180 / 3.6) * 1000)
    assert list(grid.columns) == [
        "distance_m",
        "time_ms",
        "speed_kph",
        "throttle_pct",
        "brake",
        "gear",
        "drs",
    ]


def test_resample_sorts_input_and_handles_duplicates_and_time_glitches():
    tel = constant_speed_lap(200.0, length_m=100.0, spacing_m=10.0)
    dup = tel.iloc[[5]].copy()
    dup["session_ms"] += 999.0  # a later duplicate of the same distance must be ignored
    glitch = tel.copy()
    glitch.loc[7, "session_ms"] = glitch.loc[6, "session_ms"] - 50.0  # time going backwards
    tel = pd.concat([glitch, dup]).sample(frac=1.0, random_state=1)  # shuffled

    grid = resample_to_distance(tel, step_m=1.0)
    assert len(grid) == 101
    assert (np.diff(grid["time_ms"]) >= 0).all()
    at_50 = grid.loc[grid["distance_m"] == 50.0, "time_ms"].item()
    assert at_50 == pytest.approx(50 / (200 / 3.6) * 1000)


def test_step_sampled_channels_take_previous_sample():
    tel = constant_speed_lap(150.0, length_m=100.0, spacing_m=10.0)
    tel["gear"] = np.where(tel["distance_m"] >= 50, 5, 4)
    tel["brake"] = tel["distance_m"].between(30, 40)
    grid = resample_to_distance(tel)
    by_d = grid.set_index("distance_m")
    assert by_d.loc[49.0, "gear"] == 4
    assert by_d.loc[50.0, "gear"] == 5
    assert not by_d.loc[29.0, "brake"]
    assert by_d.loc[30.0, "brake"] and by_d.loc[49.0, "brake"]  # held until the next sample
    assert not by_d.loc[50.0, "brake"]


def test_resample_rejects_degenerate_input():
    with pytest.raises(ValueError):
        resample_to_distance(constant_speed_lap(200.0).iloc[:1])
    with pytest.raises(ValueError):
        resample_to_distance(constant_speed_lap(200.0), step_m=0)


def test_delta_time_truncates_to_shorter_lap_and_checks_step():
    a = resample_to_distance(constant_speed_lap(200.0, length_m=1000.0))
    b = resample_to_distance(constant_speed_lap(200.0, length_m=950.0))
    d = delta_time(a, b)
    assert d["distance_m"].iloc[-1] == pytest.approx(950.0)
    np.testing.assert_allclose(d["delta_ms"], 0.0, atol=1e-9)
    with pytest.raises(ValueError):
        delta_time(a, resample_to_distance(constant_speed_lap(200.0), step_m=2.0))


def test_scale_distance():
    tel = constant_speed_lap(200.0, length_m=1000.0)
    scaled = scale_distance(tel, 1010.0)
    assert scaled["distance_m"].max() == pytest.approx(1010.0)
    assert tel["distance_m"].max() == pytest.approx(1000.0)  # input untouched


# ---------------------------------------------------------------------------
# segments and corners
# ---------------------------------------------------------------------------


def test_segment_boundaries_are_midpoints_with_wraparound():
    segs = segment_by_corners([600.0, 200.0, 1500.0, 2500.0], 2000.0)  # unsorted, one off-lap
    assert [s.name for s in segs] == ["T1", "T2", "T3"]
    assert [(s.start_m, s.end_m) for s in segs] == [(0.0, 400.0), (400.0, 1050.0), (1050.0, 2000.0)]
    assert segs[0].corner_distance_m == 200.0


def test_segment_names_and_letters():
    names = [corner_name(1), corner_name(4, "a"), corner_name(4, "B")]
    assert names == ["T1", "T4A", "T4B"]
    segs = segment_by_corners([100.0, 300.0, 340.0], 500.0, names=names)
    assert [s.name for s in segs] == names
    assert segment_by_corners([], 500.0) == []
    with pytest.raises(ValueError):
        segment_by_corners([100.0], 500.0, names=["T1", "T2"])


def test_corner_metrics_brake_apex_throttle():
    grid = resample_to_distance(
        corner_lap(brake_point_m=700.0, apex_kph=100.0, throttle_on_m=860.0)
    )
    m = corner_metrics(grid, 800.0, segment_start_m=0.0, segment_end_m=1500.0)
    assert m.brake_point_m == 700.0
    assert m.min_speed_kph == pytest.approx(100.0)
    assert m.min_speed_m == 800.0
    assert m.throttle_on_m == pytest.approx(860.0, abs=2.0)
    assert m.max_speed_before_kph == pytest.approx(300.0)
    assert 0 < m.full_throttle_pct < 100
    assert m.segment_time_ms == pytest.approx(grid["time_ms"].iloc[-1])


def test_brake_points_differ_by_known_offset():
    a = resample_to_distance(corner_lap(brake_point_m=708.0, apex_kph=100.0, throttle_on_m=860.0))
    b = resample_to_distance(corner_lap(brake_point_m=700.0, apex_kph=100.0, throttle_on_m=860.0))
    ma, mb = corner_metrics(a, 800.0), corner_metrics(b, 800.0)
    assert ma.brake_point_m - mb.brake_point_m == pytest.approx(8.0)


def test_brake_point_is_start_of_the_main_braking_zone():
    tel = corner_lap(brake_point_m=700.0, apex_kph=100.0, throttle_on_m=860.0)
    d = tel["distance_m"]
    tel["brake"] = (
        d.between(600, 604)  # an early dab: ignored
        | d.between(700, 730)
        | d.between(740, 789)  # 10 m flicker inside the real zone: merged
    )
    grid = resample_to_distance(tel)
    m = corner_metrics(grid, 800.0)
    assert m.brake_point_m == 700.0
    starts, ends = braking_zones(grid["distance_m"].to_numpy(), grid["brake"].to_numpy())
    assert starts.tolist() == [600.0, 700.0]
    assert ends.tolist() == [605.0, 789.0]  # step-sampled: held until the next 2 m sample


def test_corner_metrics_flat_out_corner():
    flat_out = resample_to_distance(constant_speed_lap(250.0))
    m = corner_metrics(flat_out, 500.0)
    assert m.brake_point_m is None
    assert m.throttle_on_m is None  # never lifted, so there is no throttle application


def test_corner_metrics_ignores_braking_that_started_before_the_window():
    grid = resample_to_distance(corner_lap(brake_point_m=600.0, apex_kph=90.0, throttle_on_m=860.0))
    # e.g. the second part of a chicane: the window starts at the previous corner
    m = corner_metrics(grid, 800.0, window_before_m=100.0)
    assert m.brake_point_m is None
    assert m.apex_found and m.min_speed_m == 800.0


def test_corner_metrics_no_apex_when_speed_minimum_is_on_the_window_edge():
    # still accelerating out of the corner at 800 m when the next window opens at 850 m
    grid = resample_to_distance(
        corner_lap(brake_point_m=700.0, apex_kph=100.0, throttle_on_m=860.0)
    )
    m = corner_metrics(grid, 950.0, window_before_m=100.0, segment_start_m=850.0)
    assert not m.apex_found
    assert m.min_speed_m == 850.0
    assert m.throttle_on_m is None


# ---------------------------------------------------------------------------
# full comparison (pure part of compare_laps)
# ---------------------------------------------------------------------------


def _compare(tel_a, tel_b, corners, **kwargs):
    defaults = dict(
        season=2025,
        round=1,
        session_type="Q",
        event_name="Test Grand Prix",
        driver_a="AAA",
        driver_b="BBB",
        lap_a=10,
        lap_b=12,
        lap_time_a_ms=None,
        lap_time_b_ms=None,
    )
    return build_comparison(tel_a, tel_b, corners, **(defaults | kwargs))


CORNERS = pd.DataFrame({"distance_m": [800.0], "name": ["T1"]})


def test_build_comparison_brake_later_insight():
    tel_a = corner_lap(brake_point_m=708.0, apex_kph=104.0, throttle_on_m=860.0)
    tel_b = corner_lap(brake_point_m=700.0, apex_kph=100.0, throttle_on_m=860.0)
    result = _compare(tel_a, tel_b, CORNERS)

    assert result.total_delta_ms < 0  # A is faster
    assert result.total_delta_ms == result.telemetry_delta_ms  # no official lap times given
    assert sum(s.delta_ms for s in result.segments) == pytest.approx(
        result.telemetry_delta_ms, abs=0.2
    )
    corner = result.corners[0]
    assert corner.brake_delta_m == pytest.approx(8.0)
    assert corner.apex_speed_a_kph - corner.apex_speed_b_kph == pytest.approx(4.0)

    insight = result.insights[0]
    assert insight.faster_driver == "AAA"
    assert insight.corner == "T1"
    assert insight.text.startswith("AAA brakes 8 m later than BBB into T1")
    assert "carries 4 km/h more through the apex" in insight.text
    assert insight.text.endswith(f"worth {format_seconds(corner.delta_ms)} s")
    assert result.key_segments[0].faster_driver == "AAA"
    assert result.summary.startswith("AAA (lap 10) is ")


def test_build_comparison_traction_insight_for_driver_b():
    tel_a = corner_lap(brake_point_m=700.0, apex_kph=100.0, throttle_on_m=880.0)
    tel_b = corner_lap(brake_point_m=700.0, apex_kph=100.0, throttle_on_m=860.0)
    result = _compare(tel_a, tel_b, CORNERS, lap_time_a_ms=90_123, lap_time_b_ms=90_000)

    assert result.total_delta_ms == 123.0  # official lap times win over the telemetry delta
    assert result.telemetry_delta_ms > 0
    assert "1:30.123" in result.summary
    insight = result.insights[0]
    assert insight.faster_driver == "BBB"
    assert insight.kind == "traction"
    assert insight.delta_ms > 0  # sign stays "time lost by A"
    assert insight.text.startswith("BBB gets back on full throttle 20 m earlier than AAA out of T1")


def test_build_comparison_grid_is_downsampled_and_consistent():
    tel_a = corner_lap(brake_point_m=700.0, apex_kph=100.0, throttle_on_m=860.0)
    tel_b = corner_lap(brake_point_m=690.0, apex_kph=95.0, throttle_on_m=870.0)
    result = _compare(tel_a, tel_b, CORNERS, step_m=0.5)
    g = result.grid
    n = len(g.distance_m)
    assert n <= MAX_GRID_POINTS
    for series in (g.delta_ms, g.speed_a, g.speed_b, g.throttle_a, g.brake_b, g.gear_a, g.gear_b):
        assert len(series) == n
    assert g.distance_m[0] == 0.0
    assert g.distance_m[-1] == pytest.approx(result.meta.lap_length_m)


def test_build_comparison_normalizes_lap_length():
    # Same driving, but B's distance integrated 1 % long: normalized, the laps are identical.
    tel_a = corner_lap(brake_point_m=700.0, apex_kph=100.0, throttle_on_m=860.0)
    tel_b = scale_distance(tel_a, tel_a["distance_m"].max() * 1.01)
    result = _compare(tel_a, tel_b, CORNERS)
    assert result.meta.raw_lap_length_b_m > result.meta.raw_lap_length_a_m
    assert max(abs(x) for x in result.grid.delta_ms) < 1.0
    assert result.insights == []


def test_build_comparison_without_corners():
    tel = constant_speed_lap(200.0)
    result = _compare(tel, constant_speed_lap(210.0), CORNERS.iloc[0:0])
    assert result.segments == [] and result.corners == [] and result.insights == []
    assert result.total_delta_ms > 0
    assert result.summary.startswith("BBB (lap 12) is ")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def test_downsample_indices():
    assert downsample_indices(10, 2000).tolist() == list(range(10))
    for n in (2001, 5000, 5401, 10_799):
        idx = downsample_indices(n, 2000)
        assert len(idx) <= 2000
        assert idx[0] == 0 and idx[-1] == n - 1
        assert (np.diff(idx) > 0).all()


def test_formatting():
    assert format_seconds(-123.4) == "0.12"
    assert format_seconds(48.0) == "0.048"
    assert format_seconds(84.0, 3) == "0.084"
    assert format_lap_time(75_096) == "1:15.096"
    assert format_lap_time(59_999) == "0:59.999"


def _corner(**overrides):
    from pitwall.telemetry.models import CornerComparison

    values = dict(
        name="T6",
        distance_m=1870.0,
        brake_point_a_m=None,
        brake_point_b_m=None,
        brake_delta_m=None,
        apex_speed_a_kph=200.0,
        apex_speed_b_kph=200.0,
        apex_a_m=1870.0,
        apex_b_m=1870.0,
        apex_found_a=True,
        apex_found_b=True,
        throttle_on_a_m=None,
        throttle_on_b_m=None,
        max_speed_before_a_kph=300.0,
        max_speed_before_b_kph=300.0,
        max_speed_after_a_kph=280.0,
        max_speed_after_b_kph=280.0,
        delta_ms=50.0,
    )
    return CornerComparison(**(values | overrides))


def test_corner_insight_wording_and_thresholds():
    from pitwall.telemetry.coach import corner_insight

    assert corner_insight(_corner(delta_ms=5.0), "VER", "NOR") is None  # below 10 ms

    fallback = corner_insight(_corner(), "VER", "NOR")
    assert fallback.text == "NOR is quicker than VER through T6, worth 0.050 s"
    assert fallback.kind == "corner" and fallback.delta_ms == 50.0

    traction = corner_insight(
        _corner(throttle_on_a_m=1900.0, throttle_on_b_m=1885.0, max_speed_after_b_kph=285.0),
        "VER",
        "NOR",
    )
    assert traction.text == (
        "NOR gets back on full throttle 15 m earlier than VER out of T6 "
        "and is 5 km/h quicker on the exit, worth 0.050 s"
    )
    # Apex/exit comparisons are skipped when one driver has no apex in the window.
    no_apex = corner_insight(
        _corner(apex_found_a=False, apex_speed_b_kph=210.0, delta_ms=-120.0), "VER", "NOR"
    )
    assert no_apex.text == "VER is quicker than NOR through T6, worth 0.12 s"
