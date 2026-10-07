"""FastAPI application for the Telemetry Coach.

Run with `uv run python -m pitwall.api` or `uv run uvicorn pitwall.api.app:app --port 8080`.
Endpoints are plain `def` functions: FastAPI runs them in its thread pool, and the query layer
keeps one ClickHouse client per thread.
"""

from __future__ import annotations

import logging
from typing import Annotated

from clickhouse_connect.driver.exceptions import ClickHouseError
from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pitwall.telemetry import coach, queries
from pitwall.telemetry.models import (
    SESSION_TYPES,
    CompareResult,
    DriverSummary,
    LapSummary,
    SessionInfo,
)

log = logging.getLogger(__name__)

CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

Season = Annotated[int, Path(ge=1950, le=2100)]
Round = Annotated[int, Path(ge=1, le=30)]
SessionTypePath = Annotated[str, Path(description=f"One of {', '.join(SESSION_TYPES)}")]
DriverCode = Annotated[str, Query(pattern=r"^[A-Za-z]{3}$", description="e.g. VER")]


def _session_type(value: str) -> str:
    """Normalise and validate a session type, raising 422 for unknown values."""
    upper = value.upper()
    if upper not in SESSION_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"session_type must be one of {', '.join(SESSION_TYPES)}, got {value!r}",
        )
    return upper


def create_app() -> FastAPI:
    """Build the API application."""
    app = FastAPI(title="Pit Wall API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.exception_handler(coach.LapNotFoundError)
    def lap_not_found(_: Request, exc: coach.LapNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ClickHouseError)
    def clickhouse_error(_: Request, exc: ClickHouseError) -> JSONResponse:
        log.exception("ClickHouse query failed", exc_info=exc)
        return JSONResponse(status_code=503, content={"detail": "Telemetry database unavailable"})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        clickhouse_ok = queries.ping()
        return {"status": "ok", "clickhouse": "up" if clickhouse_ok else "down"}

    @app.get("/api/sessions", response_model=list[SessionInfo])
    def sessions(season: Annotated[int, Query(ge=1950, le=2100)]) -> list[SessionInfo]:
        return queries.list_sessions(season)

    @app.get(
        "/api/sessions/{season}/{round}/{session_type}/drivers",
        response_model=list[DriverSummary],
    )
    def drivers(
        season: Season, round: Round, session_type: SessionTypePath
    ) -> list[DriverSummary]:
        st = _session_type(session_type)
        result = queries.list_drivers(season, round, st)
        if not result:
            raise HTTPException(404, f"No laps found for {season} round {round} {st}")
        return result

    @app.get(
        "/api/sessions/{season}/{round}/{session_type}/laps",
        response_model=list[LapSummary],
    )
    def laps(
        season: Season, round: Round, session_type: SessionTypePath, driver: DriverCode
    ) -> list[LapSummary]:
        st = _session_type(session_type)
        result = queries.list_laps(season, round, st, driver.upper())
        if not result:
            raise HTTPException(404, f"No laps for {driver.upper()} in {season} round {round} {st}")
        return result

    @app.get("/api/compare", response_model=CompareResult)
    def compare(
        season: Annotated[int, Query(ge=1950, le=2100)],
        round: Annotated[int, Query(ge=1, le=30)],
        session_type: str,
        driver_a: DriverCode,
        driver_b: DriverCode,
        lap_a: Annotated[int | None, Query(ge=1, le=255)] = None,
        lap_b: Annotated[int | None, Query(ge=1, le=255)] = None,
        step_m: Annotated[float, Query(ge=0.5, le=10.0)] = 1.0,
    ) -> CompareResult:
        return coach.compare_laps(
            season,
            round,
            _session_type(session_type),
            driver_a,
            driver_b,
            lap_a=lap_a,
            lap_b=lap_b,
            step_m=step_m,
        )

    return app


app = create_app()
