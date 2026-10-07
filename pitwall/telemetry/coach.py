"""Telemetry Coach: compare two laps by distance and explain where time is gained or lost.

Sign convention (same as align.delta_time): every `delta_ms` is "time lost by driver A", so a
positive value means A is slower (behind) and a negative value means A is faster.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pitwall.telemetry import queries
from pitwall.telemetry.align import (
    CornerMetrics,
    Segment,
    corner_metrics,
    delta_time,
    downsample_indices,
    resample_to_distance,
    scale_distance,
    segment_by_corners,
    value_at,
)
from pitwall.telemetry.models import (
    CompareGrid,
    CompareMeta,
    CompareResult,
    CornerComparison,
    Insight,
    KeySegment,
    SegmentDelta,
)

MAX_GRID_POINTS = 2000
BRAKE_WINDOW_M = 300.0  # how far before a corner to look for the braking onset
EXIT_WINDOW_M = 200.0  # how far after a corner to look for the apex / throttle application

# Smallest differences worth putting into words.
MIN_INSIGHT_DELTA_MS = 10.0
MIN_BRAKE_DIFF_M = 5.0
MIN_APEX_DIFF_KPH = 2.0
MIN_THROTTLE_DIFF_M = 10.0
MIN_APPROACH_DIFF_KPH = 3.0
KEY_SEGMENTS = 3


class LapNotFoundError(LookupError):
    """The requested lap (or its telemetry) is not in the database."""


def compare_laps(
    season: int,
    round: int,
    session_type: str,
    driver_a: str,
    driver_b: str,
    lap_a: int | None = None,
    lap_b: int | None = None,
    step_m: float = 1.0,
    normalize_length: bool = True,
) -> CompareResult:
    """Compare two laps from ClickHouse. lap=None means that driver's fastest valid lap."""
    session_type = session_type.upper()
    driver_a, driver_b = driver_a.upper(), driver_b.upper()
    where = f"{season} round {round} {session_type}"

    session = queries.get_session(season, round, session_type)
    lap_times = queries.get_lap_times(season, round, session_type, [driver_a, driver_b])
    lap_a = lap_a if lap_a is not None else _fastest_lap(lap_times, driver_a)
    lap_b = lap_b if lap_b is not None else _fastest_lap(lap_times, driver_b)
    if lap_a is None:
        raise LapNotFoundError(f"No timed laps for {driver_a} in {where}")
    if lap_b is None:
        raise LapNotFoundError(f"No timed laps for {driver_b} in {where}")

    tel_a = queries.get_lap_telemetry(season, round, session_type, driver_a, lap_a)
    tel_b = queries.get_lap_telemetry(season, round, session_type, driver_b, lap_b)
    for driver, lap, tel in ((driver_a, lap_a, tel_a), (driver_b, lap_b, tel_b)):
        if len(tel) < 2:
            raise LapNotFoundError(f"No telemetry for {driver} lap {lap} in {where}")

    return build_comparison(
        tel_a,
        tel_b,
        queries.get_corners(season, round),
        season=season,
        round=round,
        session_type=session_type,
        event_name=session.event_name if session else "",
        driver_a=driver_a,
        driver_b=driver_b,
        lap_a=lap_a,
        lap_b=lap_b,
        lap_time_a_ms=_lap_time(lap_times, driver_a, lap_a),
        lap_time_b_ms=_lap_time(lap_times, driver_b, lap_b),
        step_m=step_m,
        normalize_length=normalize_length,
    )


def build_comparison(
    tel_a: pd.DataFrame,
    tel_b: pd.DataFrame,
    corners: pd.DataFrame,
    *,
    season: int,
    round: int,
    session_type: str,
    event_name: str,
    driver_a: str,
    driver_b: str,
    lap_a: int,
    lap_b: int,
    lap_time_a_ms: int | None,
    lap_time_b_ms: int | None,
    step_m: float = 1.0,
    normalize_length: bool = True,
) -> CompareResult:
    """Pure part of compare_laps: telemetry frames + corner table in, CompareResult out.

    With normalize_length=True both laps are linearly rescaled to the mean of their integrated
    lengths before resampling, so distance drift does not misalign the end of the lap.
    Otherwise the comparison is truncated to the shorter lap.
    """
    raw_len_a = float(tel_a["distance_m"].max())
    raw_len_b = float(tel_b["distance_m"].max())
    if normalize_length:
        reference_m = (raw_len_a + raw_len_b) / 2.0
        tel_a = scale_distance(tel_a, reference_m)
        tel_b = scale_distance(tel_b, reference_m)

    grid_a = resample_to_distance(tel_a, step_m)
    grid_b = resample_to_distance(tel_b, step_m)
    delta = delta_time(grid_a, grid_b)
    grid_a = grid_a.iloc[: len(delta)].reset_index(drop=True)
    grid_b = grid_b.iloc[: len(delta)].reset_index(drop=True)
    lap_length_m = float(delta["distance_m"].iloc[-1])
    telemetry_delta_ms = float(delta["delta_ms"].iloc[-1])

    if lap_time_a_ms is not None and lap_time_b_ms is not None:
        total_delta_ms = float(lap_time_a_ms - lap_time_b_ms)
    else:
        total_delta_ms = telemetry_delta_ms

    segments = segment_by_corners(
        corners["distance_m"].astype(float).tolist(),
        lap_length_m,
        names=corners["name"].astype(str).tolist(),
    )
    segment_deltas, corner_rows = _compare_corners(segments, grid_a, grid_b, delta)

    insights = [
        insight
        for row in corner_rows
        if (insight := corner_insight(row, driver_a, driver_b)) is not None
    ]
    insights.sort(key=lambda i: (-abs(i.delta_ms), i.corner or ""))

    meta = CompareMeta(
        season=season,
        round=round,
        session_type=session_type,
        event_name=event_name,
        driver_a=driver_a,
        driver_b=driver_b,
        lap_a=lap_a,
        lap_b=lap_b,
        lap_time_a_ms=lap_time_a_ms,
        lap_time_b_ms=lap_time_b_ms,
        lap_length_m=round_to(lap_length_m, 1),
        step_m=step_m,
        raw_lap_length_a_m=round_to(raw_len_a, 1),
        raw_lap_length_b_m=round_to(raw_len_b, 1),
    )
    return CompareResult(
        meta=meta,
        total_delta_ms=round_to(total_delta_ms, 1),
        telemetry_delta_ms=round_to(telemetry_delta_ms, 1),
        summary=lap_summary(meta, total_delta_ms),
        grid=_transport_grid(grid_a, grid_b, delta),
        segments=segment_deltas,
        corners=corner_rows,
        insights=insights,
        key_segments=key_segments(segment_deltas, driver_a, driver_b),
    )


def _compare_corners(
    segments: list[Segment],
    grid_a: pd.DataFrame,
    grid_b: pd.DataFrame,
    delta: pd.DataFrame,
) -> tuple[list[SegmentDelta], list[CornerComparison]]:
    """Per-segment time deltas and per-corner metrics for both drivers."""
    segment_deltas: list[SegmentDelta] = []
    corner_rows: list[CornerComparison] = []
    for i, seg in enumerate(segments):
        # Keep the search windows from reaching into the neighbouring corners.
        prev_gap = seg.corner_distance_m - (segments[i - 1].corner_distance_m if i else 0.0)
        next_gap = (
            segments[i + 1].corner_distance_m - seg.corner_distance_m
            if i + 1 < len(segments)
            else EXIT_WINDOW_M
        )
        before = min(BRAKE_WINDOW_M, prev_gap)
        after = min(EXIT_WINDOW_M, next_gap)

        def metrics(grid: pd.DataFrame, seg: Segment = seg) -> CornerMetrics:
            return corner_metrics(
                grid, seg.corner_distance_m, before, after, seg.start_m, seg.end_m
            )

        ma, mb = metrics(grid_a), metrics(grid_b)
        seg_delta = value_at(delta, "delta_ms", seg.end_m) - value_at(delta, "delta_ms", seg.start_m)

        segment_deltas.append(
            SegmentDelta(
                name=seg.name,
                start_m=round_to(seg.start_m, 1),
                end_m=round_to(seg.end_m, 1),
                delta_ms=round_to(seg_delta, 1),
                full_throttle_pct_a=round_to(ma.full_throttle_pct, 1),
                full_throttle_pct_b=round_to(mb.full_throttle_pct, 1),
            )
        )
        brake_delta = (
            ma.brake_point_m - mb.brake_point_m
            if ma.brake_point_m is not None and mb.brake_point_m is not None
            else None
        )
        corner_rows.append(
            CornerComparison(
                name=seg.name,
                distance_m=round_to(seg.corner_distance_m, 1),
                brake_point_a_m=round_to(ma.brake_point_m, 1),
                brake_point_b_m=round_to(mb.brake_point_m, 1),
                brake_delta_m=round_to(brake_delta, 1),
                apex_speed_a_kph=round_to(ma.min_speed_kph, 1),
                apex_speed_b_kph=round_to(mb.min_speed_kph, 1),
                apex_a_m=round_to(ma.min_speed_m, 1),
                apex_b_m=round_to(mb.min_speed_m, 1),
                throttle_on_a_m=round_to(ma.throttle_on_m, 1),
                throttle_on_b_m=round_to(mb.throttle_on_m, 1),
                max_speed_before_a_kph=round_to(ma.max_speed_before_kph, 1),
                max_speed_before_b_kph=round_to(mb.max_speed_before_kph, 1),
                delta_ms=round_to(seg_delta, 1),
            )
        )
    return segment_deltas, corner_rows


def corner_insight(c: CornerComparison, driver_a: str, driver_b: str) -> Insight | None:
    """One sentence on why the faster driver gained time in this corner (None if negligible).

    Differences are stated from the faster driver's point of view. Up to three reasons are kept
    (the largest relative to their thresholds) and written in track order: approach, braking,
    apex, exit. `kind` is the most significant reason.
    """
    if abs(c.delta_ms) < MIN_INSIGHT_DELTA_MS:
        return None
    a_faster = c.delta_ms < 0
    fast, slow = (driver_a, driver_b) if a_faster else (driver_b, driver_a)

    def pick(a_value: float | None, b_value: float | None) -> tuple[float | None, float | None]:
        return (a_value, b_value) if a_faster else (b_value, a_value)

    # (kind, gain in natural units, threshold, full clause with names, short clause)
    reasons: list[tuple[str, float, float, str, str]] = []

    approach_fast, approach_slow = pick(c.max_speed_before_a_kph, c.max_speed_before_b_kph)
    kph = round(approach_fast - approach_slow)
    reasons.append(
        (
            "straight",
            approach_fast - approach_slow,
            MIN_APPROACH_DIFF_KPH,
            f"is {kph} km/h quicker than {slow} on the approach to {c.name}",
            f"is {kph} km/h quicker on the approach",
        )
    )
    brake_fast, brake_slow = pick(c.brake_point_a_m, c.brake_point_b_m)
    if brake_fast is not None and brake_slow is not None:
        metres = round(brake_fast - brake_slow)
        reasons.append(
            (
                "braking",
                brake_fast - brake_slow,
                MIN_BRAKE_DIFF_M,
                f"brakes {metres} m later than {slow} into {c.name}",
                f"brakes {metres} m later",
            )
        )
    apex_fast, apex_slow = pick(c.apex_speed_a_kph, c.apex_speed_b_kph)
    kph = round(apex_fast - apex_slow)
    reasons.append(
        (
            "apex",
            apex_fast - apex_slow,
            MIN_APEX_DIFF_KPH,
            f"carries {kph} km/h more than {slow} through {c.name}",
            f"carries {kph} km/h more through the apex",
        )
    )
    on_fast, on_slow = pick(c.throttle_on_a_m, c.throttle_on_b_m)
    if on_fast is not None and on_slow is not None:
        metres = round(on_slow - on_fast)
        reasons.append(
            (
                "traction",
                on_slow - on_fast,
                MIN_THROTTLE_DIFF_M,
                f"gets back on full throttle {metres} m earlier than {slow} out of {c.name}",
                f"gets back on full throttle {metres} m earlier on exit",
            )
        )

    track_order = [r[0] for r in reasons]
    significant = [r for r in reasons if r[1] >= r[2]]
    strongest = sorted(significant, key=lambda r: -r[1] / r[2])[:3]
    chosen = sorted(strongest, key=lambda r: track_order.index(r[0]))

    worth = format_seconds(c.delta_ms)
    if not chosen:
        text = f"{fast} is quicker than {slow} through {c.name}, worth {worth} s"
        kind = "corner"
    else:
        clauses = [chosen[0][3]] + [r[4] for r in chosen[1:]]
        if len(clauses) == 1:
            body = clauses[0]
        else:
            body = ", ".join(clauses[:-1]) + " and " + clauses[-1]
        text = f"{fast} {body}, worth {worth} s"
        kind = strongest[0][0]
    return Insight(
        text=text, corner=c.name, delta_ms=c.delta_ms, kind=kind, faster_driver=fast
    )


def key_segments(
    segments: list[SegmentDelta], driver_a: str, driver_b: str, count: int = KEY_SEGMENTS
) -> list[KeySegment]:
    """The `count` segments with the largest absolute time difference, biggest first."""
    ranked = sorted(segments, key=lambda s: (-abs(s.delta_ms), s.start_m))[:count]
    out = []
    for s in ranked:
        fast, slow = (driver_a, driver_b) if s.delta_ms < 0 else (driver_b, driver_a)
        text = (
            f"{fast} gains {format_seconds(s.delta_ms)} s on {slow} in the {s.name} segment "
            f"({round(s.start_m)}-{round(s.end_m)} m)"
        )
        out.append(
            KeySegment(
                name=s.name,
                start_m=s.start_m,
                end_m=s.end_m,
                delta_ms=s.delta_ms,
                faster_driver=fast,
                text=text,
            )
        )
    return out


def lap_summary(meta: CompareMeta, total_delta_ms: float) -> str:
    """One-line headline, e.g. "VER (lap 18, 1:15.096) is 0.084 s faster than NOR (...)"."""
    a = f"{meta.driver_a} (lap {meta.lap_a}{_lap_time_suffix(meta.lap_time_a_ms)})"
    b = f"{meta.driver_b} (lap {meta.lap_b}{_lap_time_suffix(meta.lap_time_b_ms)})"
    if abs(total_delta_ms) < 0.5:
        return f"{a} and {b} are level on lap time"
    if total_delta_ms < 0:
        return f"{a} is {format_seconds(total_delta_ms, 3)} s faster than {b}"
    return f"{b} is {format_seconds(total_delta_ms, 3)} s faster than {a}"


def format_seconds(delta_ms: float, decimals: int | None = None) -> str:
    """|delta| in seconds: 2 dp from 0.1 s up, 3 dp below (or a fixed number of decimals)."""
    seconds = abs(delta_ms) / 1000.0
    if decimals is None:
        decimals = 2 if seconds >= 0.1 else 3
    return f"{seconds:.{decimals}f}"


def format_lap_time(ms: int) -> str:
    """Milliseconds to m:ss.sss."""
    minutes, rest = divmod(int(ms), 60_000)
    return f"{minutes}:{rest / 1000:06.3f}"


def round_to(value: float | None, decimals: int) -> float | None:
    """round() that passes None through and returns plain floats."""
    return None if value is None else round(float(value), decimals)


def _lap_time_suffix(ms: int | None) -> str:
    return "" if ms is None else f", {format_lap_time(ms)}"


def _fastest_lap(lap_times: pd.DataFrame, driver: str) -> int | None:
    """Fastest timed, not-deleted lap of a driver (ties go to the earlier lap)."""
    laps = lap_times[(lap_times["driver"] == driver) & lap_times["lap_time_ms"].notna()]
    laps = laps[~laps["deleted"].astype(bool)]
    if laps.empty:
        return None
    best = laps.sort_values(["lap_time_ms", "lap_number"], kind="stable").iloc[0]
    return int(best["lap_number"])


def _lap_time(lap_times: pd.DataFrame, driver: str, lap: int) -> int | None:
    rows = lap_times[(lap_times["driver"] == driver) & (lap_times["lap_number"] == lap)]
    if rows.empty or pd.isna(rows["lap_time_ms"].iloc[0]):
        return None
    return int(rows["lap_time_ms"].iloc[0])


def _transport_grid(grid_a: pd.DataFrame, grid_b: pd.DataFrame, delta: pd.DataFrame) -> CompareGrid:
    """Downsample the aligned traces to at most MAX_GRID_POINTS rows for the API."""
    idx = downsample_indices(len(delta), MAX_GRID_POINTS)

    def floats(series: pd.Series, decimals: int = 1) -> list[float]:
        return np.round(series.to_numpy(dtype=np.float64)[idx], decimals).tolist()

    return CompareGrid(
        distance_m=floats(delta["distance_m"]),
        delta_ms=floats(delta["delta_ms"]),
        speed_a=floats(grid_a["speed_kph"]),
        speed_b=floats(grid_b["speed_kph"]),
        throttle_a=floats(grid_a["throttle_pct"]),
        throttle_b=floats(grid_b["throttle_pct"]),
        brake_a=grid_a["brake"].to_numpy(dtype=bool)[idx].tolist(),
        brake_b=grid_b["brake"].to_numpy(dtype=bool)[idx].tolist(),
        gear_a=grid_a["gear"].to_numpy(dtype=np.int64)[idx].tolist(),
        gear_b=grid_b["gear"].to_numpy(dtype=np.int64)[idx].tolist(),
    )
