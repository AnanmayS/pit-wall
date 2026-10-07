"""API tests with the ClickHouse query layer replaced by in-memory fakes (no database)."""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pitwall.api.app import create_app
from pitwall.telemetry import queries
from pitwall.telemetry.models import DriverSummary, SessionInfo
from tests.test_coach_align import corner_lap

LAPS = pd.DataFrame(
    {
        "driver": ["VER", "VER", "NOR", "NOR"],
        "lap_number": [3, 5, 4, 6],
        "lap_time_ms": [76_000, 75_500, 75_800, None],
        "deleted": [False, False, False, False],
    }
)
TELEMETRY = {
    ("VER", 5): corner_lap(brake_point_m=708.0, apex_kph=104.0, throttle_on_m=860.0),
    ("NOR", 4): corner_lap(brake_point_m=700.0, apex_kph=100.0, throttle_on_m=860.0),
}
EMPTY_TELEMETRY = pd.DataFrame(columns=list(queries.TELEMETRY_COLUMNS))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    def get_lap_telemetry(season, round, session_type, driver, lap_number, client=None):
        return TELEMETRY.get((driver, lap_number), EMPTY_TELEMETRY)

    monkeypatch.setattr(queries, "ping", lambda client=None: True)
    monkeypatch.setattr(
        queries,
        "get_session",
        lambda season, round, session_type, client=None: SessionInfo(
            season=season,
            round=round,
            session_type=session_type,
            event_name="Australian Grand Prix",
            country="Australia",
            location="Melbourne",
        ),
    )
    monkeypatch.setattr(queries, "get_lap_times", lambda *args, **kwargs: LAPS)
    monkeypatch.setattr(queries, "get_lap_telemetry", get_lap_telemetry)
    monkeypatch.setattr(
        queries,
        "get_corners",
        lambda season, round, client=None: pd.DataFrame({"distance_m": [800.0], "name": ["T1"]}),
    )
    monkeypatch.setattr(
        queries,
        "list_drivers",
        lambda season, round, session_type, client=None: [
            DriverSummary(
                driver="VER",
                driver_number=1,
                team="Red Bull Racing",
                laps=2,
                fastest_lap_number=5,
                fastest_lap_ms=75_500,
            )
        ],
    )
    return TestClient(create_app())


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "clickhouse": "up"}


def test_compare_shape_defaults_to_fastest_laps(client: TestClient):
    r = client.get(
        "/api/compare",
        params={
            "season": 2025,
            "round": 1,
            "session_type": "q",
            "driver_a": "ver",
            "driver_b": "NOR",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "meta",
        "total_delta_ms",
        "telemetry_delta_ms",
        "summary",
        "grid",
        "segments",
        "corners",
        "insights",
        "key_segments",
    }
    meta = body["meta"]
    assert (meta["driver_a"], meta["lap_a"], meta["driver_b"], meta["lap_b"]) == (
        "VER",
        5,
        "NOR",
        4,
    )
    assert meta["session_type"] == "Q"
    assert meta["event_name"] == "Australian Grand Prix"
    assert body["total_delta_ms"] == -300.0  # 75.500 - 75.800 from the laps table
    grid = body["grid"]
    assert set(grid) == {
        "distance_m",
        "delta_ms",
        "speed_a",
        "speed_b",
        "throttle_a",
        "throttle_b",
        "brake_a",
        "brake_b",
        "gear_a",
        "gear_b",
    }
    assert len({len(v) for v in grid.values()}) == 1
    assert len(grid["distance_m"]) <= 2000
    assert body["corners"][0]["name"] == "T1"
    assert body["corners"][0]["brake_delta_m"] == pytest.approx(8.0)
    insight = body["insights"][0]
    assert set(insight) == {"text", "corner", "delta_ms", "kind", "faster_driver"}
    assert insight["text"].startswith("VER brakes 8 m later than NOR into T1")


def test_compare_accepts_fastest_and_explicit_laps(client: TestClient):
    base = {"season": 2025, "round": 1, "session_type": "Q", "driver_a": "VER", "driver_b": "NOR"}
    r = client.get("/api/compare", params=base | {"lap_a": "fastest", "lap_b": "4"})
    assert r.status_code == 200, r.text
    assert (r.json()["meta"]["lap_a"], r.json()["meta"]["lap_b"]) == (5, 4)
    assert client.get("/api/compare", params=base | {"lap_a": "best"}).status_code == 422
    assert client.get("/api/compare", params=base | {"lap_b": "0"}).status_code == 422


def test_compare_missing_telemetry_is_404(client: TestClient):
    r = client.get(
        "/api/compare",
        params={
            "season": 2025,
            "round": 1,
            "session_type": "Q",
            "driver_a": "VER",
            "driver_b": "NOR",
            "lap_a": 3,
        },
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "No telemetry for VER lap 3 in 2025 round 1 Q"


def test_compare_degenerate_telemetry_is_404(client: TestClient, monkeypatch):
    stationary = TELEMETRY[("NOR", 4)].iloc[:5].assign(distance_m=0.0)
    monkeypatch.setitem(TELEMETRY, ("NOR", 4), stationary)
    r = client.get(
        "/api/compare",
        params={
            "season": 2025,
            "round": 1,
            "session_type": "Q",
            "driver_a": "VER",
            "driver_b": "NOR",
        },
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "No usable telemetry for NOR lap 4 in 2025 round 1 Q"


def test_compare_driver_without_timed_laps_is_404(client: TestClient):
    r = client.get(
        "/api/compare",
        params={
            "season": 2025,
            "round": 1,
            "session_type": "Q",
            "driver_a": "VER",
            "driver_b": "HAM",
        },
    )
    assert r.status_code == 404
    assert "HAM" in r.json()["detail"]


def test_compare_validates_input(client: TestClient):
    base = {"season": 2025, "round": 1, "session_type": "Q", "driver_a": "VER", "driver_b": "NOR"}
    assert client.get("/api/compare", params=base | {"session_type": "XX"}).status_code == 422
    assert client.get("/api/compare", params=base | {"driver_a": "VER1"}).status_code == 422
    assert client.get("/api/compare", params=base | {"step_m": 0}).status_code == 422


def test_drivers_endpoint(client: TestClient):
    r = client.get("/api/sessions/2025/1/Q/drivers")
    assert r.status_code == 200
    assert r.json()[0]["driver"] == "VER"
    assert client.get("/api/sessions/2025/1/ZZ/drivers").status_code == 422


def test_cors_allows_web_app(client: TestClient):
    r = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
