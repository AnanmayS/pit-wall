"""ClickHouse reads for the Telemetry Coach.

All user input goes through server-side query parameters ({name:Type}); nothing is formatted
into SQL strings. Every function accepts an optional `client` (tests, benchmarks); by default a
per-thread client is reused, because clickhouse-connect clients must not be shared by threads
that query concurrently (FastAPI runs sync endpoints in a thread pool).
"""

from __future__ import annotations

import threading
from typing import Any

import pandas as pd
from clickhouse_connect.driver.client import Client

from pitwall.db.clickhouse import get_client
from pitwall.telemetry.align import corner_name
from pitwall.telemetry.models import DriverSummary, LapSummary, SessionInfo

_local = threading.local()

TELEMETRY_COLUMNS = (
    "session_ms",
    "distance_m",
    "rel_distance",
    "speed_kph",
    "throttle_pct",
    "brake",
    "gear",
    "drs",
    "x",
    "y",
)

LAP_TELEMETRY_SQL = f"""
SELECT {", ".join(TELEMETRY_COLUMNS)}
FROM telemetry
WHERE season = {{season:UInt16}}
  AND round = {{round:UInt8}}
  AND session_type = {{session_type:String}}
  AND driver = {{driver:String}}
  AND lap_number = {{lap_number:UInt8}}
ORDER BY distance_m
"""

_SESSION_FILTER = """
WHERE season = {season:UInt16}
  AND round = {round:UInt8}
  AND session_type = {session_type:String}
"""


def client_for_thread() -> Client:
    """A ClickHouse client owned by the calling thread (created on first use)."""
    client = getattr(_local, "client", None)
    if client is None:
        client = get_client()
        _local.client = client
    return client


def _client(client: Client | None) -> Client:
    return client if client is not None else client_for_thread()


def _session_params(season: int, round: int, session_type: str) -> dict[str, Any]:
    return {"season": season, "round": round, "session_type": session_type.upper()}


def _none_if_null(value: Any) -> Any:
    return None if value is None or pd.isna(value) else value


def _query_df(
    client: Client | None, sql: str, parameters: dict[str, Any], columns: tuple[str, ...]
) -> pd.DataFrame:
    """query_df that keeps the expected columns when the result is empty."""
    df = _client(client).query_df(sql, parameters=parameters)
    return df if not df.empty else pd.DataFrame(columns=list(columns))


def ping(client: Client | None = None) -> bool:
    """True if ClickHouse answers a trivial query."""
    try:
        return _client(client).command("SELECT 1") == 1
    except Exception:  # health checks report failures, they do not raise
        return False


def list_sessions(season: int, client: Client | None = None) -> list[SessionInfo]:
    """Ingested sessions of a season, in calendar order."""
    df = _client(client).query_df(
        """
        SELECT season, round, session_type, event_name, country, location, session_date
        FROM sessions FINAL
        WHERE season = {season:UInt16}
        ORDER BY round, session_date
        """,
        parameters={"season": season},
    )
    return [
        SessionInfo(
            season=int(r.season),
            round=int(r.round),
            session_type=str(r.session_type),
            event_name=str(r.event_name),
            country=str(r.country),
            location=str(r.location),
            session_date=_none_if_null(r.session_date),
        )
        for r in df.itertuples(index=False)
    ]


def get_session(
    season: int, round: int, session_type: str, client: Client | None = None
) -> SessionInfo | None:
    """One session's metadata, or None when it was not ingested."""
    df = _client(client).query_df(
        "SELECT season, round, session_type, event_name, country, location, session_date "
        "FROM sessions FINAL" + _SESSION_FILTER + "LIMIT 1",
        parameters=_session_params(season, round, session_type),
    )
    if df.empty:
        return None
    r = df.iloc[0]
    return SessionInfo(
        season=int(r.season),
        round=int(r["round"]),
        session_type=str(r.session_type),
        event_name=str(r.event_name),
        country=str(r.country),
        location=str(r.location),
        session_date=_none_if_null(r.session_date),
    )


def list_drivers(
    season: int, round: int, session_type: str, client: Client | None = None
) -> list[DriverSummary]:
    """Drivers in a session with lap counts and their fastest valid (not deleted) lap."""
    df = _client(client).query_df(
        """
        SELECT
            driver,
            any(driver_number) AS driver_number,
            any(team) AS team,
            count() AS laps,
            minIf(lap_time_ms, lap_time_ms IS NOT NULL AND NOT deleted) AS fastest_lap_ms,
            argMinIf(lap_number, lap_time_ms, lap_time_ms IS NOT NULL AND NOT deleted)
                AS fastest_lap_number
        FROM laps FINAL
        """
        + _SESSION_FILTER
        + """
        GROUP BY driver
        ORDER BY isNull(fastest_lap_ms), fastest_lap_ms, driver
        """,
        parameters=_session_params(season, round, session_type),
    )
    drivers = []
    for r in df.itertuples(index=False):
        fastest_ms = _none_if_null(r.fastest_lap_ms)
        drivers.append(
            DriverSummary(
                driver=str(r.driver),
                driver_number=int(r.driver_number),
                team=str(r.team),
                laps=int(r.laps),
                fastest_lap_ms=None if fastest_ms is None else int(fastest_ms),
                fastest_lap_number=None if fastest_ms is None else int(r.fastest_lap_number),
            )
        )
    return drivers


def list_laps(
    season: int, round: int, session_type: str, driver: str, client: Client | None = None
) -> list[LapSummary]:
    """All laps of one driver in a session."""
    params = _session_params(season, round, session_type) | {"driver": driver.upper()}
    df = _client(client).query_df(
        """
        SELECT lap_number, lap_time_ms, sector1_ms, sector2_ms, sector3_ms, stint, compound,
               tyre_life, is_personal_best, is_accurate, deleted,
               pit_in_session_ms IS NOT NULL AS pit_in,
               pit_out_session_ms IS NOT NULL AS pit_out,
               track_status, position
        FROM laps FINAL
        """
        + _SESSION_FILTER
        + """
          AND driver = {driver:String}
        ORDER BY lap_number
        """,
        parameters=params,
    )
    laps = []
    for r in df.to_dict(orient="records"):
        for key in ("lap_time_ms", "sector1_ms", "sector2_ms", "sector3_ms", "position"):
            value = _none_if_null(r[key])
            r[key] = None if value is None else int(value)
        laps.append(LapSummary(**r))
    return laps


def get_lap_times(
    season: int,
    round: int,
    session_type: str,
    drivers: list[str],
    client: Client | None = None,
) -> pd.DataFrame:
    """Columns driver, lap_number, lap_time_ms (nullable), deleted for the given drivers."""
    params = _session_params(season, round, session_type) | {
        "drivers": [d.upper() for d in drivers]
    }
    return _query_df(
        client,
        "SELECT driver, lap_number, lap_time_ms, deleted FROM laps FINAL"
        + _SESSION_FILTER
        + "AND driver IN {drivers:Array(String)} ORDER BY driver, lap_number",
        params,
        ("driver", "lap_number", "lap_time_ms", "deleted"),
    )


def fastest_lap_number(
    season: int, round: int, session_type: str, driver: str, client: Client | None = None
) -> int | None:
    """Lap number of the driver's fastest timed, not-deleted lap (None if there is none)."""
    params = _session_params(season, round, session_type) | {"driver": driver.upper()}
    result = _client(client).query(
        "SELECT lap_number FROM laps FINAL"
        + _SESSION_FILTER
        + """
          AND driver = {driver:String}
          AND lap_time_ms IS NOT NULL
          AND NOT deleted
        ORDER BY lap_time_ms, lap_number
        LIMIT 1
        """,
        parameters=params,
    )
    return int(result.result_rows[0][0]) if result.result_rows else None


def lap_telemetry_params(
    season: int, round: int, session_type: str, driver: str, lap_number: int
) -> dict[str, Any]:
    """Query parameters for LAP_TELEMETRY_SQL."""
    return _session_params(season, round, session_type) | {
        "driver": driver.upper(),
        "lap_number": lap_number,
    }


def get_lap_telemetry(
    season: int,
    round: int,
    session_type: str,
    driver: str,
    lap_number: int,
    client: Client | None = None,
) -> pd.DataFrame:
    """One lap's telemetry ordered by distance (a single primary-key range read)."""
    return _query_df(
        client,
        LAP_TELEMETRY_SQL,
        lap_telemetry_params(season, round, session_type, driver, lap_number),
        TELEMETRY_COLUMNS,
    )


def get_corners(season: int, round: int, client: Client | None = None) -> pd.DataFrame:
    """Corner markers (corner_number, corner_letter, distance_m, name) ordered by distance."""
    df = _query_df(
        client,
        """
        SELECT corner_number, corner_letter, distance_m, x, y
        FROM circuit_corners FINAL
        WHERE season = {season:UInt16} AND round = {round:UInt8}
        ORDER BY distance_m
        """,
        {"season": season, "round": round},
        ("corner_number", "corner_letter", "distance_m", "x", "y"),
    )
    df["name"] = [
        corner_name(n, letter)
        for n, letter in zip(df["corner_number"], df["corner_letter"], strict=True)
    ]
    return df


def get_circuit_rotation(season: int, round: int, client: Client | None = None) -> float:
    """Circuit rotation (degrees) FastF1 uses to draw the track map upright; 0 if unknown."""
    rows = (
        _client(client)
        .query(
            "SELECT any(circuit_rotation) FROM sessions FINAL WHERE season={s:UInt16} AND round={r:UInt8}",
            parameters={"s": season, "r": round},
        )
        .result_rows
    )
    return float(rows[0][0]) if rows and rows[0][0] is not None else 0.0


def driver_names(season: int, client: Client | None = None) -> dict[str, dict[str, Any]]:
    """code -> {full_name, first_name, last_name, driver_number, team} for a season (latest session wins)."""
    res = _client(client).query(
        """
        SELECT driver, argMax(full_name, (round, session_type)) AS full_name,
               argMax(first_name, (round, session_type)) AS first_name,
               argMax(last_name, (round, session_type)) AS last_name,
               argMax(driver_number, (round, session_type)) AS driver_number,
               argMax(team, (round, session_type)) AS team,
               argMax(country_code, (round, session_type)) AS country_code
        FROM drivers FINAL WHERE season={s:UInt16} GROUP BY driver
        """,
        parameters={"s": season},
    )
    out: dict[str, dict[str, Any]] = {}
    for row in res.result_rows:
        d = dict(zip(res.column_names, row, strict=True))
        if not d.get("full_name"):
            d["full_name"] = d["driver"]
        out[str(d["driver"])] = d
    return out
