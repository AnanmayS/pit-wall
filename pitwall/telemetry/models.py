"""Pydantic models returned by the Telemetry Coach and the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SESSION_TYPES = ("FP1", "FP2", "FP3", "Q", "SQ", "S", "R")

InsightKind = Literal["straight", "braking", "apex", "traction", "exit", "corner"]


class SessionInfo(BaseModel):
    season: int
    round: int
    session_type: str
    event_name: str
    country: str
    location: str
    session_date: datetime | None = None


class DriverSummary(BaseModel):
    driver: str
    driver_number: int
    team: str
    laps: int
    fastest_lap_number: int | None = None
    fastest_lap_ms: int | None = None


class LapSummary(BaseModel):
    lap_number: int
    lap_time_ms: int | None = None
    sector1_ms: int | None = None
    sector2_ms: int | None = None
    sector3_ms: int | None = None
    stint: int
    compound: str
    tyre_life: int
    is_personal_best: bool
    is_accurate: bool
    deleted: bool
    pit_in: bool
    pit_out: bool
    track_status: str
    position: int | None = None


class CompareMeta(BaseModel):
    season: int
    round: int
    session_type: str
    event_name: str
    driver_a: str
    driver_b: str
    lap_a: int
    lap_b: int
    lap_time_a_ms: int | None
    lap_time_b_ms: int | None
    lap_length_m: float
    step_m: float
    raw_lap_length_a_m: float = Field(description="Integrated telemetry length of lap A")
    raw_lap_length_b_m: float = Field(description="Integrated telemetry length of lap B")


class CompareGrid(BaseModel):
    """Distance-aligned traces (downsampled for transport). delta_ms = time A - time B."""

    distance_m: list[float]
    delta_ms: list[float]
    speed_a: list[float]
    speed_b: list[float]
    throttle_a: list[float]
    throttle_b: list[float]
    brake_a: list[bool]
    brake_b: list[bool]
    gear_a: list[int]
    gear_b: list[int]


class SegmentDelta(BaseModel):
    """Time lost by A inside one corner segment (positive = A slower there)."""

    name: str
    start_m: float
    end_m: float
    delta_ms: float
    full_throttle_pct_a: float | None
    full_throttle_pct_b: float | None


class CornerComparison(BaseModel):
    name: str
    distance_m: float
    brake_point_a_m: float | None
    brake_point_b_m: float | None
    brake_delta_m: float | None = Field(
        description="brake_point_a - brake_point_b; positive = A brakes later"
    )
    apex_speed_a_kph: float
    apex_speed_b_kph: float
    apex_a_m: float
    apex_b_m: float
    apex_found_a: bool = Field(description="False if A's speed minimum is on the window edge")
    apex_found_b: bool = Field(description="False if B's speed minimum is on the window edge")
    throttle_on_a_m: float | None
    throttle_on_b_m: float | None
    max_speed_before_a_kph: float
    max_speed_before_b_kph: float
    max_speed_after_a_kph: float = Field(description="Top speed from the apex to segment end")
    max_speed_after_b_kph: float
    delta_ms: float = Field(description="Time lost by A in this corner's segment")


class Insight(BaseModel):
    text: str
    corner: str | None
    delta_ms: float = Field(description="Time lost by A (positive) or gained by A (negative)")
    kind: InsightKind
    faster_driver: str


class KeySegment(BaseModel):
    name: str
    start_m: float
    end_m: float
    delta_ms: float
    faster_driver: str
    text: str


class CompareResult(BaseModel):
    meta: CompareMeta
    total_delta_ms: float = Field(
        description="Lap time A - lap time B (official timing when available)"
    )
    telemetry_delta_ms: float = Field(description="delta_ms at the end of the aligned grid")
    summary: str
    grid: CompareGrid
    segments: list[SegmentDelta]
    corners: list[CornerComparison]
    insights: list[Insight]
    key_segments: list[KeySegment]
