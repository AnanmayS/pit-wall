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
from pydantic import BaseModel, Field

from pitwall.telemetry import coach, queries
from pitwall.telemetry.models import (
    SESSION_TYPES,
    CompareResult,
    DriverSummary,
    LapSummary,
    SessionInfo,
)
from pitwall.whatif import store
from pitwall.whatif.models import ScenarioSpec
from pitwall.whatif.service import open_shared, run_or_cached

log = logging.getLogger(__name__)

CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

Season = Annotated[int, Path(ge=1950, le=2100)]
Round = Annotated[int, Path(ge=1, le=30)]
SessionTypePath = Annotated[str, Path(description=f"One of {', '.join(SESSION_TYPES)}")]
DriverCode = Annotated[str, Query(pattern=r"^[A-Za-z]{3}$", description="e.g. VER")]
LapParam = Annotated[
    str | None, Query(description="Lap number, or 'fastest' / omitted for the fastest lap")
]


def _session_type(value: str) -> str:
    """Normalise and validate a session type, raising 422 for unknown values."""
    upper = value.upper()
    if upper not in SESSION_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"session_type must be one of {', '.join(SESSION_TYPES)}, got {value!r}",
        )
    return upper


def _lap_number(value: str | None, name: str) -> int | None:
    """Parse a lap selector: None or "fastest" -> None, otherwise a lap number 1..255."""
    if value is None or value.strip().lower() in ("", "fastest"):
        return None
    if not value.strip().isdigit() or not 1 <= int(value) <= 255:
        raise HTTPException(
            status_code=422, detail=f"{name} must be a lap number or 'fastest', got {value!r}"
        )
    return int(value)


def create_app() -> FastAPI:
    """Build the API application."""
    app = FastAPI(title="Pit Wall API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST"],
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
    def drivers(season: Season, round: Round, session_type: SessionTypePath) -> list[DriverSummary]:
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
        lap_a: LapParam = None,
        lap_b: LapParam = None,
        step_m: Annotated[float, Query(ge=0.5, le=10.0)] = 1.0,
    ) -> CompareResult:
        return coach.compare_laps(
            season,
            round,
            _session_type(session_type),
            driver_a,
            driver_b,
            lap_a=_lap_number(lap_a, "lap_a"),
            lap_b=_lap_number(lap_b, "lap_b"),
            step_m=step_m,
        )

    # ---- What If (milestone 2) ----
    @app.post("/api/whatif")
    def whatif_run(spec: ScenarioSpec) -> dict:
        """Run a scenario (or return the cached result) and return it with its share id."""
        try:
            return run_or_cached(spec).to_dict()
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.get("/api/whatif/recent")
    def whatif_recent(
        season: Annotated[int, Query(ge=1950, le=2100)], round: Annotated[int, Query(ge=1, le=30)]
    ) -> list[dict]:
        return store.list_recent(season, round)

    @app.get("/api/whatif/{scenario_id}")
    def whatif_get(scenario_id: Annotated[str, Path(pattern=r"^[0-9A-Za-z]{8,16}$")]) -> dict:
        resp = open_shared(scenario_id)
        if resp is None:
            raise HTTPException(404, f"Unknown scenario {scenario_id}")
        return resp.to_dict()

    # ---- AI (milestone 2) ----
    class AskRequest(BaseModel):
        question: str = Field(min_length=3, max_length=500)
        effort: str = Field(default="medium", pattern="^(low|medium|high)$")

    @app.post("/api/ask")
    def ask_endpoint(req: AskRequest) -> dict:
        from pitwall.ai.ask import ask

        try:
            return ask(req.question, effort=req.effort).to_dict()
        except Exception as e:  # noqa: BLE001 - surface SDK/config errors as 503
            log.exception("ask failed")
            raise HTTPException(503, f"AI layer unavailable: {type(e).__name__}: {e}") from e

    return app


app = create_app()
