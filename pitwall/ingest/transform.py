"""Turn a loaded FastF1 session into DataFrames that match pitwall/db/ddl.sql exactly.

The heavy lifting lives in functions that take plain pandas DataFrames with FastF1 column
names (``laps_frame``, ``stints_frame``, ``pit_stops_frame``, ``normalize_telemetry``, ...),
so they can be unit tested without FastF1 objects or network access. Thin wrappers
(``telemetry_frame``, ``sessions_frame``, ``transform_session``) pull the inputs out of a
``fastf1.core.Session``.

Conventions: durations and session times become integer milliseconds; NaT becomes NULL
(pandas ``<NA>`` in a nullable integer column). Column order and dtypes come from SCHEMAS.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ClickHouse type -> pandas dtype. Nullable(...) maps to pandas nullable extension dtypes.
# `ingested_at` columns are omitted on purpose: ClickHouse fills them with DEFAULT now().
_KEY = {"season": "uint16", "round": "uint8", "session_type": "object"}

SCHEMAS: dict[str, dict[str, str]] = {
    "sessions": {
        **_KEY,
        "event_name": "object",
        "country": "object",
        "location": "object",
        "event_format": "object",
        "session_date": "datetime64[ns]",
        "total_laps": "UInt8",
        "circuit_rotation": "float32",
        "fastf1_version": "object",
    },
    "laps": {
        **_KEY,
        "driver": "object",
        "driver_number": "uint8",
        "team": "object",
        "lap_number": "uint8",
        "stint": "uint8",
        "lap_time_ms": "UInt32",
        "sector1_ms": "UInt32",
        "sector2_ms": "UInt32",
        "sector3_ms": "UInt32",
        "lap_start_session_ms": "UInt32",
        "pit_in_session_ms": "UInt32",
        "pit_out_session_ms": "UInt32",
        "compound": "object",
        "tyre_life": "uint8",
        "fresh_tyre": "bool",
        "track_status": "object",
        "position": "UInt8",
        "speed_i1": "Float32",
        "speed_i2": "Float32",
        "speed_fl": "Float32",
        "speed_st": "Float32",
        "is_personal_best": "bool",
        "is_accurate": "bool",
        "deleted": "bool",
    },
    "telemetry": {
        **_KEY,
        "driver": "object",
        "lap_number": "uint8",
        "session_ms": "uint32",
        "distance_m": "float32",
        "rel_distance": "float32",
        "speed_kph": "float32",
        "rpm": "uint16",
        "gear": "uint8",
        "throttle_pct": "float32",
        "brake": "bool",
        "drs": "uint8",
        "x": "float32",
        "y": "float32",
        "z": "float32",
        "source": "object",
    },
    "stints": {
        **_KEY,
        "driver": "object",
        "stint": "uint8",
        "compound": "object",
        "start_lap": "uint8",
        "end_lap": "uint8",
        "laps": "uint8",
        "tyre_life_at_start": "uint8",
    },
    "pit_stops": {
        **_KEY,
        "driver": "object",
        "stop_number": "uint8",
        "lap_in": "uint8",
        "pit_in_session_ms": "uint32",
        "pit_out_session_ms": "uint32",
        "pit_lane_ms": "uint32",
        "compound_before": "object",
        "compound_after": "object",
    },
    "weather": {
        **_KEY,
        "session_ms": "uint32",
        "air_temp_c": "float32",
        "track_temp_c": "float32",
        "humidity_pct": "float32",
        "pressure_mbar": "float32",
        "rainfall": "bool",
        "wind_dir_deg": "uint16",
        "wind_speed_ms": "float32",
    },
    "track_status": {
        **_KEY,
        "session_ms": "uint32",
        "status": "uint8",
        "message": "object",
    },
    "race_control": {
        **_KEY,
        "session_ms": "uint32",
        "lap": "UInt8",
        "category": "object",
        "flag": "object",
        "scope": "object",
        "sector": "UInt8",
        "racing_number": "UInt8",
        "message": "object",
    },
    "results": {
        **_KEY,
        "driver": "object",
        "driver_number": "uint8",
        "team": "object",
        "grid_position": "UInt8",
        "position": "UInt8",
        "classified_position": "object",
        "status": "object",
        "points": "float32",
        "laps_completed": "UInt8",
        "q1_ms": "UInt32",
        "q2_ms": "UInt32",
        "q3_ms": "UInt32",
    },
    "drivers": {
        **_KEY,
        "driver": "object",
        "driver_number": "uint8",
        "full_name": "object",
        "first_name": "object",
        "last_name": "object",
        "team": "object",
        "country_code": "object",
    },
    "circuit_corners": {
        "season": "uint16",
        "round": "uint8",
        "corner_number": "uint8",
        "corner_letter": "object",
        "distance_m": "float32",
        "angle_deg": "float32",
        "x": "float32",
        "y": "float32",
    },
}

# Inclusive value ranges for the unsigned/narrow integer types, used to clamp before casting.
_INT_RANGES = {
    "uint8": (0, 255),
    "uint16": (0, 65_535),
    "uint32": (0, 4_294_967_295),
    "UInt8": (0, 255),
    "UInt32": (0, 4_294_967_295),
}


# --------------------------------------------------------------------------- helpers


def timedelta_to_ms(values: Any) -> pd.Series:
    """Timedeltas -> nullable Int64 milliseconds (rounded). NaT becomes <NA>."""
    td = pd.to_timedelta(pd.Series(values))
    ms = (td.dt.total_seconds() * 1000.0).round()
    return ms.astype("Int64")


def ms_or_none(value: Any) -> int | None:
    """Scalar version of timedelta_to_ms: NaT/None -> None."""
    if value is None or pd.isna(value):
        return None
    return int(round(pd.Timedelta(value).total_seconds() * 1000.0))


def _clean_str(values: pd.Series, default: str = "") -> pd.Series:
    """Strings with NaN/None replaced by `default`."""
    return values.astype(object).where(values.notna(), default).astype(str)


def _to_bool(values: pd.Series) -> pd.Series:
    """Booleans with NaN/None treated as False (FastF1 uses object dtype with NaN here)."""
    if values.dtype == bool:
        return values
    return values.astype(object).where(values.notna(), False).map(bool).astype(bool)


def _numeric(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce")


def conform(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """Select the table's columns in DDL order and cast each to the matching pandas dtype.

    Integers are clamped to the column's range so clickhouse-connect never overflows;
    non-nullable numeric columns get 0 for missing values.
    """
    schema = SCHEMAS[table]
    missing = [c for c in schema if c not in df.columns]
    if missing:
        raise KeyError(f"{table}: missing columns {missing}")
    out = pd.DataFrame(index=df.index)
    for col, dtype in schema.items():
        s = df[col]
        if dtype == "object":
            out[col] = _clean_str(s)
        elif dtype == "bool":
            out[col] = _to_bool(s)
        elif dtype.startswith("datetime64"):
            ts = pd.to_datetime(s, utc=True).dt.tz_localize(None)
            out[col] = ts.astype(dtype)
        elif dtype in _INT_RANGES:
            lo, hi = _INT_RANGES[dtype]
            num = _numeric(s).round().clip(lo, hi)
            if dtype[0].isupper():  # nullable
                out[col] = num.astype("Int64").astype(dtype)
            else:
                out[col] = num.fillna(0).astype("int64").astype(dtype)
        elif dtype == "Float32":
            out[col] = _numeric(s).astype("Float32")
        elif dtype == "float32":
            out[col] = _numeric(s).fillna(0.0).astype("float32")
        else:
            raise ValueError(f"unhandled dtype {dtype} for {table}.{col}")
    return out.reset_index(drop=True)


def empty_frame(table: str) -> pd.DataFrame:
    """A zero-row frame with the table's columns and dtypes."""
    return pd.DataFrame({c: pd.Series(dtype=d) for c, d in SCHEMAS[table].items()})


def _with_key(df: pd.DataFrame, season: int, round: int, session_type: str | None) -> pd.DataFrame:
    df = df.copy()
    df["season"] = season
    df["round"] = round
    if session_type is not None:
        df["session_type"] = session_type
    return df


# --------------------------------------------------------------------------- laps, stints, pits


def laps_frame(laps: pd.DataFrame, season: int, round: int, session_type: str) -> pd.DataFrame:
    """FastF1 laps -> `laps` table rows. Laps without a lap number are dropped."""
    laps = pd.DataFrame(laps)
    laps = laps[laps["LapNumber"].notna() & laps["Driver"].notna()]
    if laps.empty:
        return empty_frame("laps")
    df = pd.DataFrame(
        {
            "driver": laps["Driver"],
            "driver_number": _numeric(laps["DriverNumber"]),
            "team": laps["Team"],
            "lap_number": laps["LapNumber"],
            "stint": laps["Stint"],
            "lap_time_ms": timedelta_to_ms(laps["LapTime"]).values,
            "sector1_ms": timedelta_to_ms(laps["Sector1Time"]).values,
            "sector2_ms": timedelta_to_ms(laps["Sector2Time"]).values,
            "sector3_ms": timedelta_to_ms(laps["Sector3Time"]).values,
            "lap_start_session_ms": timedelta_to_ms(laps["LapStartTime"]).values,
            "pit_in_session_ms": timedelta_to_ms(laps["PitInTime"]).values,
            "pit_out_session_ms": timedelta_to_ms(laps["PitOutTime"]).values,
            "compound": laps["Compound"].where(laps["Compound"].notna(), "UNKNOWN"),
            "tyre_life": laps["TyreLife"],
            "fresh_tyre": laps["FreshTyre"],
            "track_status": laps["TrackStatus"],
            "position": laps["Position"],
            "speed_i1": laps["SpeedI1"],
            "speed_i2": laps["SpeedI2"],
            "speed_fl": laps["SpeedFL"],
            "speed_st": laps["SpeedST"],
            "is_personal_best": laps["IsPersonalBest"],
            "is_accurate": laps["IsAccurate"],
            "deleted": laps["Deleted"] if "Deleted" in laps else False,
        },
        index=laps.index,
    )
    return conform(_with_key(df, season, round, session_type), "laps")


def _compound(value: Any) -> str:
    return "UNKNOWN" if value is None or pd.isna(value) or value == "" else str(value)


def stints_frame(laps: pd.DataFrame, season: int, round: int, session_type: str) -> pd.DataFrame:
    """One row per (driver, stint): compound, first/last lap, lap count, tyre life at start."""
    laps = pd.DataFrame(laps)
    laps = laps[laps["LapNumber"].notna() & laps["Stint"].notna() & laps["Driver"].notna()]
    if laps.empty:
        return empty_frame("stints")
    rows = []
    for (driver, stint), g in laps.sort_values("LapNumber").groupby(["Driver", "Stint"]):
        first = g.iloc[0]
        known = g["Compound"].dropna()
        rows.append(
            {
                "driver": driver,
                "stint": stint,
                "compound": _compound(known.iloc[0] if len(known) else None),
                "start_lap": g["LapNumber"].min(),
                "end_lap": g["LapNumber"].max(),
                "laps": len(g),
                "tyre_life_at_start": first["TyreLife"],
            }
        )
    return conform(_with_key(pd.DataFrame(rows), season, round, session_type), "stints")


def pit_stops_frame(laps: pd.DataFrame, season: int, round: int, session_type: str) -> pd.DataFrame:
    """Pit stops derived from laps.

    A stop is a lap with PitInTime set; the matching pit exit is the PitOutTime of the driver's
    next lap. Stops without a following out-lap (retired in the pits, end of session) or with a
    non-positive pit lane time are skipped. stop_number counts 1, 2, ... per driver.
    """
    laps = pd.DataFrame(laps)
    laps = laps[laps["LapNumber"].notna() & laps["Driver"].notna()]
    rows = []
    for driver, g in laps.sort_values("LapNumber").groupby("Driver"):
        g = g.reset_index(drop=True)
        stop_number = 0
        for i in range(len(g) - 1):
            pit_in = ms_or_none(g.at[i, "PitInTime"])
            if pit_in is None:
                continue
            pit_out = ms_or_none(g.at[i + 1, "PitOutTime"])
            if pit_out is None or pit_out <= pit_in:
                continue
            stop_number += 1
            rows.append(
                {
                    "driver": driver,
                    "stop_number": stop_number,
                    "lap_in": g.at[i, "LapNumber"],
                    "pit_in_session_ms": pit_in,
                    "pit_out_session_ms": pit_out,
                    "pit_lane_ms": pit_out - pit_in,
                    "compound_before": _compound(g.at[i, "Compound"]),
                    "compound_after": _compound(g.at[i + 1, "Compound"]),
                }
            )
    if not rows:
        return empty_frame("pit_stops")
    return conform(_with_key(pd.DataFrame(rows), season, round, session_type), "pit_stops")


# --------------------------------------------------------------------------- telemetry

# FastF1 telemetry columns we keep, and their DDL names.
TELEMETRY_COLUMNS = {
    "SessionTime": "session_ms",
    "Distance": "distance_m",
    "RelativeDistance": "rel_distance",
    "Speed": "speed_kph",
    "RPM": "rpm",
    "nGear": "gear",
    "Throttle": "throttle_pct",
    "Brake": "brake",
    "DRS": "drs",
    "X": "x",
    "Y": "y",
    "Z": "z",
    "Source": "source",
}


def normalize_telemetry(
    raw: pd.DataFrame, season: int, round: int, session_type: str
) -> pd.DataFrame:
    """Concatenated per-lap FastF1 telemetry (plus `driver`, `lap_number`) -> `telemetry` rows.

    Rows without a distance or session time are dropped; everything else is cast to the DDL
    types (clamped to range, missing numeric values -> 0).
    """
    if raw.empty:
        return empty_frame("telemetry")
    raw = raw[raw["Distance"].notna() & raw["SessionTime"].notna()]
    df = raw.rename(columns=TELEMETRY_COLUMNS)
    df["session_ms"] = timedelta_to_ms(raw["SessionTime"]).values
    # FastF1 stores Brake as bool (recent data) or 0..100 (older data); anything > 0 is braking.
    df["brake"] = _numeric(raw["Brake"].astype(float)).fillna(0) > 0
    return conform(_with_key(df, season, round, session_type), "telemetry")


def lap_telemetry(lap: Any, *, driver_ahead: bool = False) -> pd.DataFrame:
    """Merged car + position telemetry for one FastF1 lap.

    Equivalent to ``lap.get_telemetry()`` but, unless ``driver_ahead`` is set, it skips the
    DriverAhead computation, which dominates get_telemetry's runtime and is not stored.
    """
    if driver_ahead:
        return lap.get_telemetry()
    pos = lap.get_pos_data(pad=1, pad_side="both")
    car = lap.get_car_data(pad=1, pad_side="both").add_distance().add_relative_distance()
    return pos.merge_channels(car).slice_by_lap(lap, interpolate_edges=True)


@dataclass
class TelemetryStats:
    laps_total: int = 0
    laps_ok: int = 0
    laps_skipped: int = 0
    skipped: list[tuple[str, int, str]] = field(default_factory=list)  # (driver, lap, reason)


def collect_telemetry(laps: Any) -> tuple[pd.DataFrame, TelemetryStats]:
    """Iterate every lap of a FastF1 Laps object and concatenate its telemetry once.

    Laps whose telemetry cannot be built (missing car/position data) are skipped and counted.
    """
    keep = list(TELEMETRY_COLUMNS)
    parts: list[pd.DataFrame] = []
    stats = TelemetryStats()
    for driver in pd.unique(laps["Driver"].dropna()):
        driver_laps = laps.pick_drivers(driver)
        for _, lap in driver_laps.iterrows():
            if pd.isna(lap["LapNumber"]):
                continue
            stats.laps_total += 1
            lap_number = int(lap["LapNumber"])
            try:
                tel = lap_telemetry(lap)
            except Exception as exc:  # FastF1 raises a variety of errors for missing data
                stats.laps_skipped += 1
                stats.skipped.append((str(driver), lap_number, type(exc).__name__))
                continue
            if tel is None or len(tel) == 0:
                stats.laps_skipped += 1
                stats.skipped.append((str(driver), lap_number, "empty"))
                continue
            part = pd.DataFrame(tel)[keep]
            part.insert(0, "driver", str(driver))
            part.insert(1, "lap_number", lap_number)
            parts.append(part)
            stats.laps_ok += 1
    raw = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=keep)
    return raw, stats


def telemetry_frame(
    session: Any, season: int, round: int, session_type: str
) -> tuple[pd.DataFrame, TelemetryStats]:
    """All drivers' per-lap telemetry for a loaded session, in DDL shape."""
    raw, stats = collect_telemetry(session.laps)
    if raw.empty:
        return empty_frame("telemetry"), stats
    return normalize_telemetry(raw, season, round, session_type), stats


# --------------------------------------------------------------------------- session-level tables


def weather_frame(
    weather: pd.DataFrame, season: int, round: int, session_type: str
) -> pd.DataFrame:
    if weather is None or len(weather) == 0:
        return empty_frame("weather")
    w = pd.DataFrame(weather)
    w = w[w["Time"].notna()]
    df = pd.DataFrame(
        {
            "session_ms": timedelta_to_ms(w["Time"]).values,
            "air_temp_c": w["AirTemp"].values,
            "track_temp_c": w["TrackTemp"].values,
            "humidity_pct": w["Humidity"].values,
            "pressure_mbar": w["Pressure"].values,
            "rainfall": w["Rainfall"].values,
            "wind_dir_deg": w["WindDirection"].values,
            "wind_speed_ms": w["WindSpeed"].values,
        }
    )
    return conform(_with_key(df, season, round, session_type), "weather")


def track_status_frame(
    track_status: pd.DataFrame, season: int, round: int, session_type: str
) -> pd.DataFrame:
    if track_status is None or len(track_status) == 0:
        return empty_frame("track_status")
    t = pd.DataFrame(track_status)
    t = t[t["Time"].notna()]
    df = pd.DataFrame(
        {
            "session_ms": timedelta_to_ms(t["Time"]).values,
            "status": _numeric(t["Status"]).values,
            "message": t["Message"].values,
        }
    )
    return conform(_with_key(df, season, round, session_type), "track_status")


def race_control_frame(
    messages: pd.DataFrame,
    t0_date: Any,
    season: int,
    round: int,
    session_type: str,
) -> pd.DataFrame:
    """Race control messages. FastF1 gives absolute timestamps here, so session_ms is
    computed against the session's t0_date; messages before t0 are clamped to 0."""
    if messages is None or len(messages) == 0:
        return empty_frame("race_control")
    m = pd.DataFrame(messages)
    m = m[m["Time"].notna()]
    since_t0 = pd.to_datetime(m["Time"]) - pd.Timestamp(t0_date)
    df = pd.DataFrame(
        {
            "session_ms": timedelta_to_ms(since_t0).clip(lower=0).values,
            "lap": _numeric(m["Lap"]).values,
            "category": m["Category"].values,
            "flag": m["Flag"].values,
            "scope": m["Scope"].values,
            "sector": _numeric(m["Sector"]).values,
            "racing_number": _numeric(m["RacingNumber"]).values,
            "message": m["Message"].values,
        }
    )
    return conform(_with_key(df, season, round, session_type), "race_control")


def results_frame(
    results: pd.DataFrame, season: int, round: int, session_type: str
) -> pd.DataFrame:
    if results is None or len(results) == 0:
        return empty_frame("results")
    r = pd.DataFrame(results)
    r = r[r["Abbreviation"].notna() & (r["Abbreviation"].astype(str) != "")]
    df = pd.DataFrame(
        {
            "driver": r["Abbreviation"].values,
            "driver_number": _numeric(r["DriverNumber"]).values,
            "team": r["TeamName"].values,
            "grid_position": _numeric(r["GridPosition"]).values,
            "position": _numeric(r["Position"]).values,
            "classified_position": r["ClassifiedPosition"].values,
            "status": r["Status"].values,
            "points": _numeric(r["Points"]).values,
            "laps_completed": _numeric(r["Laps"]).values,
            "q1_ms": timedelta_to_ms(r["Q1"]).values,
            "q2_ms": timedelta_to_ms(r["Q2"]).values,
            "q3_ms": timedelta_to_ms(r["Q3"]).values,
        }
    )
    return conform(_with_key(df, season, round, session_type), "results")


def drivers_frame(
    results: pd.DataFrame, season: int, round: int, session_type: str
) -> pd.DataFrame:
    """Driver identity rows (code, number, names, team) from a session's results."""
    if results is None or len(results) == 0:
        return empty_frame("drivers")
    r = pd.DataFrame(results)
    r = r[r["Abbreviation"].notna() & (r["Abbreviation"].astype(str) != "")]

    def col(name: str) -> pd.Series:
        return (
            r[name].fillna("").astype(str) if name in r else pd.Series([""] * len(r), index=r.index)
        )

    df = pd.DataFrame(
        {
            "driver": r["Abbreviation"].values,
            "driver_number": _numeric(r["DriverNumber"]).values,
            "full_name": col("FullName").values,
            "first_name": col("FirstName").values,
            "last_name": col("LastName").values,
            "team": col("TeamName").values,
            "country_code": col("CountryCode").values,
        }
    )
    return conform(_with_key(df, season, round, session_type), "drivers")


def corners_frame(corners: pd.DataFrame | None, season: int, round: int) -> pd.DataFrame:
    if corners is None or len(corners) == 0:
        return empty_frame("circuit_corners")
    c = pd.DataFrame(corners)
    df = pd.DataFrame(
        {
            "corner_number": c["Number"].values,
            "corner_letter": c["Letter"].values,
            "distance_m": c["Distance"].values,
            "angle_deg": c["Angle"].values,
            "x": c["X"].values,
            "y": c["Y"].values,
        }
    )
    return conform(_with_key(df, season, round, None), "circuit_corners")


def sessions_frame(
    session: Any,
    season: int,
    round: int,
    session_type: str,
    *,
    circuit_rotation: float = 0.0,
    fastf1_version: str = "",
) -> pd.DataFrame:
    """The one-row `sessions` dimension record."""
    event = session.event
    try:
        total_laps = session.total_laps  # only meaningful for races/sprints
    except Exception:
        total_laps = None
    df = pd.DataFrame(
        [
            {
                "event_name": event.get("EventName", ""),
                "country": event.get("Country", ""),
                "location": event.get("Location", ""),
                "event_format": event.get("EventFormat", ""),
                "session_date": session.date,
                "total_laps": np.nan if total_laps is None else total_laps,
                "circuit_rotation": circuit_rotation,
                "fastf1_version": fastf1_version,
            }
        ]
    )
    return conform(_with_key(df, season, round, session_type), "sessions")


# --------------------------------------------------------------------------- orchestration


def _t0_date(session, laps: pd.DataFrame):
    """Absolute timestamp of session time zero.

    FastF1 only computes `session.t0_date` when car data is loaded. Without telemetry it is derived
    from any lap that has both an absolute (`LapStartDate`) and a session-relative (`LapStartTime`)
    start, which agree with FastF1's own value to the millisecond.
    """
    try:
        t0 = session.t0_date
        if t0 is not None and not pd.isna(t0):
            return t0
    except Exception:  # noqa: BLE001 - fastf1 raises DataNotLoadedError here
        pass
    if "LapStartDate" in laps and "LapStartTime" in laps:
        both = laps.dropna(subset=["LapStartDate", "LapStartTime"])
        if not both.empty:
            row = both.iloc[0]
            return pd.Timestamp(row["LapStartDate"]) - pd.Timedelta(row["LapStartTime"])
    return pd.Timestamp(session.date)


def transform_session(
    session: Any,
    season: int,
    round: int,
    session_type: str,
    *,
    telemetry: bool = True,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Build every table's DataFrame for a loaded session.

    Returns ``(frames, notes)``: ``frames`` is keyed by ClickHouse table name (``telemetry`` is
    omitted when ``telemetry=False``); ``notes`` holds per-table warnings such as skipped laps.
    """
    import fastf1

    notes: dict[str, Any] = {}
    laps = pd.DataFrame(session.laps)

    rotation = 0.0
    corners = None
    try:
        info = session.get_circuit_info()
        if info is not None:
            rotation = float(info.rotation)
            corners = info.corners
    except Exception as exc:  # circuit info needs position data; not fatal
        notes["circuit_corners"] = f"circuit info unavailable: {exc}"
        log.warning("circuit info unavailable for %s R%s %s: %s", season, round, session_type, exc)

    frames: dict[str, pd.DataFrame] = {
        "sessions": sessions_frame(
            session,
            season,
            round,
            session_type,
            circuit_rotation=rotation,
            fastf1_version=fastf1.__version__,
        ),
        "laps": laps_frame(laps, season, round, session_type),
        "stints": stints_frame(laps, season, round, session_type),
        "pit_stops": pit_stops_frame(laps, season, round, session_type),
        "weather": weather_frame(session.weather_data, season, round, session_type),
        "track_status": track_status_frame(session.track_status, season, round, session_type),
        "race_control": race_control_frame(
            session.race_control_messages, _t0_date(session, laps), season, round, session_type
        ),
        "results": results_frame(session.results, season, round, session_type),
        "drivers": drivers_frame(session.results, season, round, session_type),
        "circuit_corners": corners_frame(corners, season, round),
    }

    if telemetry:
        tel, stats = telemetry_frame(session, season, round, session_type)
        frames["telemetry"] = tel
        notes["telemetry"] = {
            "laps_total": stats.laps_total,
            "laps_ok": stats.laps_ok,
            "laps_skipped": stats.laps_skipped,
            "skipped_sample": stats.skipped[:20],
        }
        if stats.laps_skipped:
            log.warning("telemetry: skipped %d of %d laps", stats.laps_skipped, stats.laps_total)
    return frames, notes
