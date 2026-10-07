"""Unit tests for pitwall.ingest.transform using synthetic FastF1-shaped DataFrames."""

from __future__ import annotations

import re
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from pitwall.db.clickhouse import DDL_PATH, iter_statements
from pitwall.ingest import transform as tf
from pitwall.ingest.source import sessions_from_schedule


def TD(seconds: float = 0.0, milliseconds: float = 0.0) -> pd.Timedelta:  # noqa: N802
    """pd.Timedelta built from an explicit unit (keyword construction warns on numpy 2)."""
    return pd.Timedelta(seconds * 1000.0 + milliseconds, unit="ms")


def ddl_columns() -> dict[str, list[str]]:
    """Column names per table parsed from ddl.sql (ingested_at excluded: it has a DEFAULT)."""
    tables: dict[str, list[str]] = {}
    for stmt in iter_statements(DDL_PATH.read_text()):
        m = re.match(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*)\) ENGINE", stmt, re.S)
        if not m:
            continue
        cols = []
        for line in m.group(2).splitlines():
            line = line.split("--")[0].strip()
            cm = re.match(r"^(\w+)\s+\w", line)
            if cm and cm.group(1) != "ingested_at":
                cols.append(cm.group(1))
        tables[m.group(1)] = cols
    return tables


def make_laps() -> pd.DataFrame:
    """Two drivers. VER: 5 laps, one stop on lap 2 (SOFT -> HARD). HAM: 3 laps, a stop on
    lap 3 with no following out-lap (retired in the pits), so it must not become a stop."""
    nat = pd.NaT
    rows = [
        # driver, lap, stint, compound, tyre_life, pit_in, pit_out, lap_time
        ("VER", 1, 1, "SOFT", 1, nat, nat, TD(seconds=90.1234)),
        ("VER", 2, 1, "SOFT", 2, TD(seconds=200), nat, TD(seconds=95)),
        ("VER", 3, 2, "HARD", 1, nat, TD(seconds=222.5), TD(seconds=110)),
        ("VER", 4, 2, "HARD", 2, nat, nat, nat),
        ("VER", 5, 2, np.nan, 3, nat, nat, TD(seconds=89)),
        ("HAM", 1, 1, "MEDIUM", 4, nat, nat, TD(seconds=91)),
        ("HAM", 2, 1, "MEDIUM", 5, nat, nat, TD(seconds=92)),
        ("HAM", 3, 1, "MEDIUM", 6, TD(seconds=300), nat, nat),
    ]
    df = pd.DataFrame(
        rows,
        columns=[
            "Driver",
            "LapNumber",
            "Stint",
            "Compound",
            "TyreLife",
            "PitInTime",
            "PitOutTime",
            "LapTime",
        ],
    )
    n = len(df)
    df["LapNumber"] = df["LapNumber"].astype(float)  # FastF1 uses floats here
    df["Stint"] = df["Stint"].astype(float)
    df["TyreLife"] = df["TyreLife"].astype(float)
    df["DriverNumber"] = df["Driver"].map({"VER": "1", "HAM": "44"})
    df["Team"] = df["Driver"].map({"VER": "Red Bull Racing", "HAM": "Ferrari"})
    df["Time"] = pd.to_timedelta(np.arange(n) * 90, unit="s")
    df["LapStartTime"] = df["Time"]
    for c in ("Sector1Time", "Sector2Time", "Sector3Time"):
        df[c] = TD(seconds=30)
    df.loc[0, "Sector1Time"] = pd.NaT
    for c in ("SpeedI1", "SpeedI2", "SpeedFL", "SpeedST"):
        df[c] = 300.0
    df.loc[1, "SpeedFL"] = np.nan
    df["IsPersonalBest"] = pd.Series(
        [True, False, np.nan, False, False, True, False, False], dtype=object
    )
    df["FreshTyre"] = True
    df["TrackStatus"] = "1"
    df["Position"] = np.where(df["Driver"] == "VER", 1.0, 2.0)
    df.loc[7, "Position"] = np.nan
    df["Deleted"] = False
    df["IsAccurate"] = True
    return df


def make_raw_telemetry(n: int = 6) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "driver": "VER",
            "lap_number": 3,
            "SessionTime": pd.to_timedelta(np.arange(n) * 0.25 + 4000, unit="s"),
            "Distance": np.linspace(0, 50, n),
            "RelativeDistance": np.linspace(0, 0.01, n),
            "Speed": np.linspace(100, 120, n),
            "RPM": np.full(n, 11000.0),
            "nGear": np.full(n, 5),
            "Throttle": np.full(n, 100.0),
            "Brake": [False, True] * (n // 2),
            "DRS": np.full(n, 12),
            "X": np.arange(n, dtype=float),
            "Y": np.arange(n, dtype=float),
            "Z": np.zeros(n),
            "Source": ["car", "pos"] * (n // 2),
        }
    )


# --------------------------------------------------------------------------- schema contract


def test_schemas_match_ddl_columns_exactly():
    ddl = ddl_columns()
    assert set(ddl) - {"ingest_runs"} == set(tf.SCHEMAS)
    for table, cols in tf.SCHEMAS.items():
        assert list(cols) == ddl[table], table


def test_telemetry_columns_equal_ddl():
    df = tf.normalize_telemetry(make_raw_telemetry(), 2025, 1, "R")
    assert list(df.columns) == ddl_columns()["telemetry"]
    assert str(df["session_ms"].dtype) == "uint32"
    assert str(df["rpm"].dtype) == "uint16"
    assert str(df["gear"].dtype) == "uint8"
    assert df["brake"].dtype == bool
    assert df["session_ms"].iloc[1] == 4_000_250
    assert df["brake"].tolist() == [False, True] * 3


def test_empty_frames_have_ddl_columns():
    ddl = ddl_columns()
    for table in tf.SCHEMAS:
        assert list(tf.empty_frame(table).columns) == ddl[table]


# --------------------------------------------------------------------------- conversions


def test_timedelta_to_ms_with_nat():
    s = tf.timedelta_to_ms([TD(seconds=90.1234), pd.NaT, TD(milliseconds=1), TD(0)])
    assert s.dtype == "Int64"
    assert s.iloc[0] == 90_123
    assert s.iloc[1] is pd.NA
    assert s.iloc[2] == 1
    assert s.iloc[3] == 0


def test_ms_or_none():
    assert tf.ms_or_none(pd.NaT) is None
    assert tf.ms_or_none(None) is None
    assert tf.ms_or_none(TD(seconds=1.5)) == 1500


def test_conform_clamps_and_nulls():
    df = pd.DataFrame(
        {
            "season": [2025],
            "round": [1],
            "session_type": ["R"],
            "session_ms": [tf.timedelta_to_ms([TD(seconds=10)]).iloc[0]],
            "status": ["4"],
            "message": [None],
        }
    )
    out = tf.conform(df, "track_status")
    assert out.loc[0, "status"] == 4
    assert out.loc[0, "message"] == ""
    with pytest.raises(KeyError):
        tf.conform(df.drop(columns="status"), "track_status")


# --------------------------------------------------------------------------- laps / stints / pits


def test_laps_frame():
    df = tf.laps_frame(make_laps(), 2025, 1, "R")
    assert list(df.columns) == ddl_columns()["laps"]
    assert len(df) == 8
    ver1 = df.iloc[0]
    assert ver1["lap_time_ms"] == 90_123
    assert ver1["sector1_ms"] is pd.NA
    assert ver1["driver_number"] == 1
    assert df.loc[3, "lap_time_ms"] is pd.NA
    assert df.loc[4, "compound"] == "UNKNOWN"
    assert df.loc[1, "pit_in_session_ms"] == 200_000
    assert df.loc[2, "pit_out_session_ms"] == 222_500
    assert df.loc[1, "speed_fl"] is pd.NA
    assert df.loc[7, "position"] is pd.NA
    assert df["is_personal_best"].tolist() == [True, False, False, False, False, True, False, False]
    assert str(df["lap_time_ms"].dtype) == "UInt32"


def test_stints_frame():
    raw = tf.stints_frame(make_laps(), 2025, 1, "R")
    assert list(raw.columns) == ddl_columns()["stints"]
    df = raw.set_index(["driver", "stint"])
    assert len(df) == 3
    ver1, ver2, ham1 = df.loc[("VER", 1)], df.loc[("VER", 2)], df.loc[("HAM", 1)]
    assert (ver1["compound"], ver1["start_lap"], ver1["end_lap"], ver1["laps"]) == ("SOFT", 1, 2, 2)
    # lap 5 has a NaN compound; the stint takes the first known compound
    assert (ver2["compound"], ver2["start_lap"], ver2["end_lap"], ver2["laps"]) == ("HARD", 3, 5, 3)
    assert ver2["tyre_life_at_start"] == 1
    # HAM started on a used set
    assert ham1["tyre_life_at_start"] == 4


def test_pit_stops_frame():
    df = tf.pit_stops_frame(make_laps(), 2025, 1, "R")
    assert list(df.columns) == ddl_columns()["pit_stops"]
    # HAM's pit entry on his final lap has no out-lap and is dropped
    assert len(df) == 1
    stop = df.iloc[0]
    assert stop["driver"] == "VER"
    assert stop["stop_number"] == 1
    assert stop["lap_in"] == 2
    assert stop["pit_in_session_ms"] == 200_000
    assert stop["pit_out_session_ms"] == 222_500
    assert stop["pit_lane_ms"] == 22_500
    assert (stop["compound_before"], stop["compound_after"]) == ("SOFT", "HARD")


def test_pit_stop_numbers_increment_per_driver():
    laps = make_laps()
    # add a second VER stop: in on lap 4, out on lap 5
    laps.loc[3, "PitInTime"] = TD(seconds=400)
    laps.loc[4, "PitOutTime"] = TD(seconds=420)
    df = tf.pit_stops_frame(laps, 2025, 1, "R")
    ver = df[df["driver"] == "VER"]
    assert ver["stop_number"].tolist() == [1, 2]
    assert ver["lap_in"].tolist() == [2, 4]
    assert ver["pit_lane_ms"].tolist() == [22_500, 20_000]
    assert ver.iloc[1]["compound_after"] == "UNKNOWN"


def test_pit_stops_empty():
    laps = make_laps()
    laps["PitInTime"] = pd.NaT
    df = tf.pit_stops_frame(laps, 2025, 1, "R")
    assert df.empty
    assert list(df.columns) == ddl_columns()["pit_stops"]


# --------------------------------------------------------------------------- telemetry


def test_normalize_telemetry_drops_nan_rows_and_clamps():
    raw = make_raw_telemetry()
    raw.loc[1, "Distance"] = np.nan
    raw.loc[2, "SessionTime"] = pd.NaT
    raw.loc[3, "RPM"] = 70_000.0  # out of UInt16 range
    raw.loc[4, "nGear"] = -1
    df = tf.normalize_telemetry(raw, 2025, 1, "R")
    assert len(df) == 4
    assert df["rpm"].max() == 65_535
    assert df["gear"].min() == 0
    assert set(df["source"]) == {"car", "pos"}
    assert (df["season"] == 2025).all() and (df["session_type"] == "R").all()


def test_normalize_telemetry_numeric_brake():
    raw = make_raw_telemetry()
    raw["Brake"] = [0, 100, 0, 100, 0, 100]  # pre-2023 FastF1 style
    df = tf.normalize_telemetry(raw, 2025, 1, "R")
    assert df["brake"].tolist() == [False, True] * 3


# --------------------------------------------------------------------------- session-level tables


def test_results_frame_quali_times():
    results = pd.DataFrame(
        {
            "Abbreviation": ["NOR", "PIA"],
            "DriverNumber": ["4", "81"],
            "TeamName": ["McLaren", "McLaren"],
            "GridPosition": [np.nan, np.nan],
            "Position": [1.0, 2.0],
            "ClassifiedPosition": ["", ""],
            "Status": ["", ""],
            "Points": [np.nan, np.nan],
            "Laps": [np.nan, np.nan],
            "Q1": [TD(seconds=75.912), TD(seconds=76.0)],
            "Q2": [TD(seconds=75.415), pd.NaT],
            "Q3": [TD(seconds=75.096), pd.NaT],
        }
    )
    df = tf.results_frame(results, 2025, 1, "Q")
    assert list(df.columns) == ddl_columns()["results"]
    assert df.loc[0, "q3_ms"] == 75_096
    assert df.loc[1, "q2_ms"] is pd.NA
    assert df.loc[0, "grid_position"] is pd.NA
    assert df.loc[0, "points"] == 0.0


def test_race_control_frame_relative_to_t0():
    t0 = pd.Timestamp("2025-03-16 03:00:00")
    msgs = pd.DataFrame(
        {
            "Time": [pd.Timestamp("2025-03-16 03:10:00"), pd.Timestamp("2025-03-16 02:59:00")],
            "Category": ["Flag", "Other"],
            "Message": ["YELLOW IN TRACK SECTOR 3", "EARLY"],
            "Status": [None, None],
            "Flag": ["YELLOW", None],
            "Scope": ["Sector", None],
            "Sector": [3.0, np.nan],
            "RacingNumber": [None, "44"],
            "Lap": [1, 1],
        }
    )
    df = tf.race_control_frame(msgs, t0, 2025, 1, "R")
    assert list(df.columns) == ddl_columns()["race_control"]
    assert df.loc[0, "session_ms"] == 600_000
    assert df.loc[1, "session_ms"] == 0  # before t0 -> clamped
    assert df.loc[0, "sector"] == 3 and df.loc[1, "sector"] is pd.NA
    assert df.loc[1, "racing_number"] == 44 and df.loc[0, "racing_number"] is pd.NA
    assert df.loc[1, "flag"] == ""


def test_weather_and_track_status_frames():
    weather = pd.DataFrame(
        {
            "Time": [TD(seconds=7.776), TD(seconds=67.777)],
            "AirTemp": [15.8, 15.7],
            "Humidity": [80.0, 81.0],
            "Pressure": [1010.0, 1010.1],
            "Rainfall": [False, True],
            "TrackTemp": [20.0, 19.5],
            "WindDirection": [211, 273],
            "WindSpeed": [2.6, 2.6],
        }
    )
    w = tf.weather_frame(weather, 2025, 1, "R")
    assert list(w.columns) == ddl_columns()["weather"]
    assert w["session_ms"].tolist() == [7_776, 67_777]
    assert w["rainfall"].tolist() == [False, True]

    ts = pd.DataFrame({"Time": [TD(seconds=24.491)], "Status": ["4"], "Message": ["SCDeployed"]})
    t = tf.track_status_frame(ts, 2025, 1, "R")
    assert list(t.columns) == ddl_columns()["track_status"]
    assert (t.loc[0, "session_ms"], t.loc[0, "status"]) == (24_491, 4)


def test_corners_frame():
    corners = pd.DataFrame(
        {
            "X": [1.0, 2.0],
            "Y": [3.0, 4.0],
            "Number": [1, 1],
            "Letter": ["", "A"],
            "Angle": [10.0, 20.0],
            "Distance": [350.7, 400.0],
        }
    )
    df = tf.corners_frame(corners, 2025, 1)
    assert list(df.columns) == ddl_columns()["circuit_corners"]
    assert df["corner_letter"].tolist() == ["", "A"]


# --------------------------------------------------------------------------- schedule


def test_sessions_from_schedule_sprint_and_future_filtering():
    def ev(rnd, fmt, sessions):
        row = {"RoundNumber": rnd, "EventFormat": fmt}
        for i, (name, date) in enumerate(sessions, start=1):
            row[f"Session{i}"] = name
            row[f"Session{i}DateUtc"] = pd.Timestamp(date)
        return row

    schedule = pd.DataFrame(
        [
            ev(
                1,
                "conventional",
                [
                    ("Practice 1", "2025-03-14"),
                    ("Practice 2", "2025-03-14"),
                    ("Practice 3", "2025-03-15"),
                    ("Qualifying", "2025-03-15 05:00"),
                    ("Race", "2025-03-16 04:00"),
                ],
            ),
            ev(
                2,
                "sprint_qualifying",
                [
                    ("Practice 1", "2025-03-21"),
                    ("Sprint Qualifying", "2025-03-21 07:30"),
                    ("Sprint", "2025-03-22 03:00"),
                    ("Qualifying", "2025-03-22 07:00"),
                    ("Race", "2025-03-23 07:00"),
                ],
            ),
        ]
    )
    now = datetime(2025, 3, 22, 12, 0)
    pairs = sessions_from_schedule(schedule, ("R", "Q", "S", "SQ"), now=now)
    assert pairs == [(1, "R"), (1, "Q"), (2, "Q"), (2, "S"), (2, "SQ")]
