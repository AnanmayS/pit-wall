"""Write transformed session frames to ClickHouse and record each load in `ingest_runs`."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import fastf1
import pandas as pd
from clickhouse_connect.driver.client import Client

from pitwall.db.clickhouse import get_client
from pitwall.ingest.source import load_session, season_sessions
from pitwall.ingest.transform import transform_session

log = logging.getLogger(__name__)

TELEMETRY_CHUNK_ROWS = 500_000

# `sessions` goes last: a row there means every other table of the session was written,
# which is what ingest_season's skip_existing relies on.
INSERT_ORDER = (
    "telemetry",
    "laps",
    "stints",
    "pit_stops",
    "weather",
    "track_status",
    "race_control",
    "results",
    "drivers",
    "circuit_corners",
    "sessions",
)


@dataclass
class IngestResult:
    """What one session ingest did and how long each step took."""

    season: int
    round: int
    session_type: str
    started_at: datetime
    rows: dict[str, int] = field(default_factory=dict)
    fetch_seconds: float = 0.0
    transform_seconds: float = 0.0
    insert_seconds: dict[str, float] = field(default_factory=dict)
    total_seconds: float = 0.0
    notes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def load_seconds(self) -> float:
        """FastF1 fetch + transform time (the `load_seconds` column of ingest_runs)."""
        return self.fetch_seconds + self.transform_seconds

    @property
    def label(self) -> str:
        return f"{self.season} R{self.round} {self.session_type}"


def _session_filter(season: int, round: int, session_type: str) -> str:
    return f"season = {int(season)} AND round = {int(round)} AND session_type = '{session_type}'"


def delete_session_telemetry(client: Client, season: int, round: int, session_type: str) -> int:
    """Remove a session's telemetry so a re-ingest does not duplicate it.

    Uses a lightweight DELETE scoped to the session. DROP PARTITION is not an option because
    the partition key is (season, round) and would also drop the weekend's other sessions.
    Returns the number of rows that were present.
    """
    where = _session_filter(season, round, session_type)
    existing = int(client.command(f"SELECT count() FROM telemetry WHERE {where}"))
    if existing:
        log.info("telemetry: deleting %d existing rows for %s", existing, where)
        client.command(f"DELETE FROM telemetry WHERE {where}")
    return existing


def insert_frame(
    client: Client, table: str, df: pd.DataFrame, chunk_rows: int | None = None
) -> None:
    """Insert a DataFrame, optionally in fixed-size chunks."""
    if df.empty:
        return
    step = chunk_rows or len(df)
    for start in range(0, len(df), step):
        client.insert_df(table, df.iloc[start : start + step])


def record_runs(client: Client, result: IngestResult) -> None:
    """One ingest_runs row per table written for this session."""
    rows = [
        [
            result.season,
            result.round,
            result.session_type,
            table,
            result.rows[table],
            result.load_seconds,
            result.insert_seconds.get(table, 0.0),
            result.started_at,
            fastf1.__version__,
        ]
        for table in result.rows
    ]
    client.insert(
        "ingest_runs",
        rows,
        column_names=[
            "season",
            "round",
            "session_type",
            "table",
            "rows",
            "load_seconds",
            "insert_seconds",
            "started_at",
            "fastf1_version",
        ],
    )


def write_frames(
    client: Client,
    frames: dict[str, pd.DataFrame],
    season: int,
    round: int,
    session_type: str,
) -> tuple[dict[str, int], dict[str, float]]:
    """Insert every frame (telemetry made idempotent first). Returns rows and seconds per table."""
    rows: dict[str, int] = {}
    seconds: dict[str, float] = {}
    for table in INSERT_ORDER:
        if table not in frames:
            continue
        df = frames[table]
        t0 = time.perf_counter()
        if table == "telemetry":
            delete_session_telemetry(client, season, round, session_type)
            insert_frame(client, table, df, chunk_rows=TELEMETRY_CHUNK_ROWS)
        else:
            insert_frame(client, table, df)
        seconds[table] = time.perf_counter() - t0
        rows[table] = len(df)
        log.info("%-15s %9d rows  %6.2fs", table, len(df), seconds[table])
    return rows, seconds


def ingest_session(
    season: int,
    round: int,
    session_type: str,
    *,
    telemetry: bool = True,
    client: Client | None = None,
) -> IngestResult:
    """Fetch one session from FastF1, transform it and write it to ClickHouse."""
    session_type = session_type.upper()
    result = IngestResult(season, round, session_type, started_at=datetime.now(UTC))
    t_start = time.perf_counter()
    log.info("%s: loading from FastF1 (telemetry=%s)", result.label, telemetry)

    session = load_session(season, round, session_type, telemetry=telemetry)
    result.fetch_seconds = time.perf_counter() - t_start
    log.info("%s: loaded in %.1fs, transforming", result.label, result.fetch_seconds)

    t0 = time.perf_counter()
    frames, notes = transform_session(session, season, round, session_type, telemetry=telemetry)
    result.transform_seconds = time.perf_counter() - t0
    result.notes = notes
    log.info("%s: transformed in %.1fs, inserting", result.label, result.transform_seconds)

    client = client or get_client()
    result.rows, result.insert_seconds = write_frames(client, frames, season, round, session_type)
    record_runs(client, result)

    result.total_seconds = time.perf_counter() - t_start
    log.info(
        "%s: done in %.1fs (fetch %.1fs, transform %.1fs, insert %.1fs)",
        result.label,
        result.total_seconds,
        result.fetch_seconds,
        result.transform_seconds,
        sum(result.insert_seconds.values()),
    )
    return result


def existing_sessions(client: Client, season: int) -> set[tuple[int, str]]:
    """(round, session_type) pairs already present in the `sessions` table."""
    rows = client.query(
        "SELECT DISTINCT round, session_type FROM sessions FINAL WHERE season = {s:UInt16}",
        parameters={"s": season},
    ).result_rows
    return {(int(r), str(st)) for r, st in rows}


def ingest_season(
    season: int,
    session_types: Iterable[str] = ("R", "Q", "S", "SQ"),
    *,
    telemetry: bool = True,
    skip_existing: bool = True,
    client: Client | None = None,
) -> list[IngestResult]:
    """Ingest every completed session of a season, sequentially (FastF1 is rate limited).

    A failing session is logged and recorded with `error` set; the loop continues.
    """
    client = client or get_client()
    pairs = season_sessions(season, tuple(session_types))
    done = existing_sessions(client, season) if skip_existing else set()
    todo = [p for p in pairs if p not in done]
    log.info(
        "season %d: %d sessions scheduled so far, %d already ingested, %d to do",
        season,
        len(pairs),
        len(pairs) - len(todo),
        len(todo),
    )
    results: list[IngestResult] = []
    for i, (rnd, st) in enumerate(todo, start=1):
        log.info("[%d/%d] %d R%d %s", i, len(todo), season, rnd, st)
        try:
            results.append(ingest_session(season, rnd, st, telemetry=telemetry, client=client))
        except Exception as exc:
            log.exception("%d R%d %s failed", season, rnd, st)
            failed = IngestResult(season, rnd, st, started_at=datetime.now(UTC))
            failed.error = f"{type(exc).__name__}: {exc}"
            results.append(failed)
    return results
