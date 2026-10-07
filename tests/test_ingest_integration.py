"""Round-trip synthetic rows through ClickHouse (needs `docker compose up`)."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from pitwall.db.clickhouse import get_client, migrate
from pitwall.ingest import transform as tf
from pitwall.ingest.load import IngestResult, record_runs, write_frames
from tests.test_transform import make_laps, make_raw_telemetry

pytestmark = pytest.mark.integration

SEASON, ROUND, STYPE = 1999, 99, "R"  # never collides with real data
WHERE = f"season = {SEASON} AND round = {ROUND}"
TABLES = ("telemetry", "laps", "pit_stops", "ingest_runs")


@pytest.fixture()
def client():
    c = get_client()
    migrate(c)
    yield c
    for table in TABLES:
        c.command(f"DELETE FROM {table} WHERE {WHERE}")


def test_telemetry_and_laps_round_trip(client):
    tel = tf.normalize_telemetry(make_raw_telemetry(), SEASON, ROUND, STYPE)
    laps = tf.laps_frame(make_laps(), SEASON, ROUND, STYPE)
    pits = tf.pit_stops_frame(make_laps(), SEASON, ROUND, STYPE)
    frames = {"telemetry": tel, "laps": laps, "pit_stops": pits}

    rows, seconds = write_frames(client, frames, SEASON, ROUND, STYPE)
    assert rows == {"telemetry": 6, "laps": 8, "pit_stops": 1}
    # a second write must not duplicate telemetry (delete-then-insert)
    write_frames(client, {"telemetry": tel}, SEASON, ROUND, STYPE)
    assert client.command(f"SELECT count() FROM telemetry WHERE {WHERE}") == 6

    back = client.query_df(f"SELECT * FROM telemetry WHERE {WHERE} ORDER BY distance_m")
    assert list(back.columns) == list(tel.columns)
    assert back["session_ms"].tolist() == tel["session_ms"].tolist()
    assert back["brake"].tolist() == tel["brake"].tolist()
    assert back["source"].tolist() == tel["source"].tolist()

    lap_rows = client.query(
        f"SELECT driver, lap_number, lap_time_ms, sector1_ms, compound, position "
        f"FROM laps FINAL WHERE {WHERE} ORDER BY driver, lap_number"
    ).result_rows
    by_key = {(d, n): (lt, s1, comp, pos) for d, n, lt, s1, comp, pos in lap_rows}
    assert len(by_key) == 8
    assert by_key[("VER", 1)] == (90_123, None, "SOFT", 1)  # NaT sector -> NULL
    assert by_key[("VER", 4)][0] is None
    assert by_key[("VER", 5)][2] == "UNKNOWN"
    assert by_key[("HAM", 3)][3] is None

    stop = client.query(
        f"SELECT pit_lane_ms, compound_before, compound_after FROM pit_stops FINAL WHERE {WHERE}"
    ).result_rows
    assert stop == [(22_500, "SOFT", "HARD")]

    result = IngestResult(
        SEASON,
        ROUND,
        STYPE,
        started_at=datetime.now(UTC),
        rows=rows,
        fetch_seconds=1.0,
        transform_seconds=0.5,
        insert_seconds=seconds,
    )
    record_runs(client, result)
    runs = client.query_df(f"SELECT * FROM ingest_runs WHERE {WHERE}")
    assert sorted(runs["table"]) == ["laps", "pit_stops", "telemetry"]
    assert (runs["load_seconds"] == 1.5).all()
    assert isinstance(runs["started_at"].iloc[0], pd.Timestamp)
