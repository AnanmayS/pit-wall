"""Telemetry Coach against a live ClickHouse with 2025 round 1 ingested (skipped otherwise)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

SEASON, ROUND = 2025, 1


def _drivers_or_skip(session_type: str):
    from pitwall.telemetry import queries

    try:
        drivers = queries.list_drivers(SEASON, ROUND, session_type)
    except Exception as exc:  # ClickHouse down or schema missing
        pytest.skip(f"ClickHouse unavailable: {exc}")
    with_laps = [d for d in drivers if d.fastest_lap_number is not None]
    if len(with_laps) < 2:
        pytest.skip(f"{SEASON} round {ROUND} {session_type} not ingested")
    return with_laps


@pytest.mark.parametrize("session_type", ["Q", "R"])
def test_compare_fastest_laps_of_top_two(session_type: str):
    from pitwall.telemetry import queries
    from pitwall.telemetry.coach import compare_laps

    drivers = _drivers_or_skip(session_type)
    a, b = drivers[0], drivers[1]
    tel = queries.get_lap_telemetry(SEASON, ROUND, session_type, a.driver, a.fastest_lap_number)
    if tel.empty:
        pytest.skip("telemetry not ingested yet")

    result = compare_laps(SEASON, ROUND, session_type, a.driver, b.driver)
    assert result.meta.lap_a == a.fastest_lap_number
    assert result.meta.lap_b == b.fastest_lap_number
    assert 3000 < result.meta.lap_length_m < 8000
    assert len(result.grid.distance_m) <= 2000
    # The telemetry-integrated delta should agree with official timing within a few tenths.
    assert abs(result.telemetry_delta_ms - result.total_delta_ms) < 500
    if result.segments:
        assert sum(s.delta_ms for s in result.segments) == pytest.approx(
            result.telemetry_delta_ms, abs=1.0
        )
