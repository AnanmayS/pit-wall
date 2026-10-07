"""Distance-based lap alignment and corner metrics (pure NumPy/pandas, no database access).

Conventions used throughout this module:

* Distances are metres from the lap start line; times are milliseconds since the first sample
  of the lap ("elapsed time").
* A "grid" is the output of `resample_to_distance`: one row per `step_m` metres, starting at 0.
* `delta_ms = time_a_ms - time_b_ms`. A POSITIVE delta means driver A reached that point of the
  lap LATER than driver B, i.e. A is behind / slower up to there. A delta that grows across a
  stretch of track means A lost time there; one that shrinks means A gained time.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Throttle at or above this value counts as "full throttle".
FULL_THROTTLE_PCT = 90.0
# Brake-off gaps shorter than this are treated as one braking zone (sensor flicker, re-applies).
BRAKE_MERGE_GAP_M = 20.0

GRID_COLUMNS = [
    "distance_m",
    "time_ms",
    "speed_kph",
    "throttle_pct",
    "brake",
    "gear",
    "drs",
    "x",
    "y",
]
_INTERPOLATED = ("speed_kph", "throttle_pct")
_STEPPED = ("brake", "gear", "drs")


@dataclass(frozen=True)
class Segment:
    """A stretch of the lap attributed to one corner: [start_m, end_m)."""

    name: str
    corner_distance_m: float
    start_m: float
    end_m: float


@dataclass(frozen=True)
class CornerMetrics:
    """How one driver took one corner. Distances are on the lap's distance grid."""

    corner_distance_m: float
    brake_point_m: float | None  # first braking onset in the approach window; None = no braking
    min_speed_kph: float  # apex speed
    min_speed_m: float  # apex position
    throttle_on_m: float | None  # first point after the apex at >= FULL_THROTTLE_PCT
    max_speed_before_kph: float  # top speed on the approach (window start .. apex)
    max_speed_after_kph: float  # top speed on the exit (apex .. segment end or window end)
    apex_found: bool = True  # False when speed is lowest at the window edge (no real apex)
    full_throttle_pct: float | None = None  # share of the segment's distance at full throttle
    segment_time_ms: float | None = None  # time spent in the segment


def corner_name(number: int, letter: str | None = None) -> str:
    """Display name of a corner, e.g. corner_name(4, "A") -> "T4A"."""
    return f"T{int(number)}{(letter or '').strip().upper()}"


def resample_to_distance(tel: pd.DataFrame, step_m: float = 1.0) -> pd.DataFrame:
    """Resample one lap's telemetry onto a uniform distance grid 0, step, 2*step, ... <= lap length.

    Elapsed time (session_ms minus the first sample's session_ms), speed and throttle are linearly
    interpolated; brake, gear and drs are step-sampled (value of the nearest previous sample).
    Duplicate distances keep their first (earliest) sample, and time is forced to be
    non-decreasing.
    Grid points before the first sample take the first sample's values.
    """
    if step_m <= 0:
        raise ValueError("step_m must be positive")
    # Sorting by (distance, time) makes "keep first" of a duplicate distance the earliest sample.
    df = tel.dropna(subset=["distance_m", "session_ms"]).sort_values(
        ["distance_m", "session_ms"], kind="stable"
    )
    if len(df) < 2:
        raise ValueError("need at least two telemetry samples to resample a lap")

    distance_raw = df["distance_m"].to_numpy(dtype=np.float64)
    distance, first_idx = np.unique(distance_raw, return_index=True)  # sorted, keeps first
    if len(distance) < 2:
        raise ValueError("telemetry has fewer than two distinct distances")

    session_ms = df["session_ms"].to_numpy(dtype=np.float64)[first_idx]
    elapsed_ms = np.maximum.accumulate(session_ms - session_ms[0])

    lap_length_m = float(distance[-1])
    n_points = int(np.floor(lap_length_m / step_m + 1e-9)) + 1
    grid = np.arange(n_points, dtype=np.float64) * step_m

    out: dict[str, np.ndarray] = {
        "distance_m": grid,
        "time_ms": np.interp(grid, distance, elapsed_ms),
    }
    for col in _INTERPOLATED + ("x", "y"):
        if col not in df:
            out[col] = np.zeros(n_points)  # position channels are optional (synthetic tests)
            continue
        values = df[col].astype("float64").ffill().bfill().fillna(0.0).to_numpy()[first_idx]
        out[col] = np.interp(grid, distance, values)

    prev_idx = np.clip(np.searchsorted(distance, grid, side="right") - 1, 0, len(distance) - 1)
    out["brake"] = df["brake"].fillna(False).to_numpy(dtype=bool)[first_idx][prev_idx]
    for col in ("gear", "drs"):
        values = df[col].fillna(0).to_numpy(dtype=np.int64)[first_idx]
        out[col] = values[prev_idx]
    return pd.DataFrame(out, columns=GRID_COLUMNS)


def scale_distance(tel: pd.DataFrame, target_length_m: float) -> pd.DataFrame:
    """Return a copy of a lap's telemetry with distance_m linearly rescaled to target_length_m.

    Used to put two laps whose integrated lengths differ slightly (racing line, integration drift)
    onto the same track length before resampling.
    """
    out = tel.copy()
    length = float(out["distance_m"].max())
    if length > 0:
        out["distance_m"] = out["distance_m"].astype("float64") * (target_length_m / length)
    return out


def delta_time(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """Time delta between two resampled laps on their common grid.

    Both inputs must come from `resample_to_distance` with the same step. The result is truncated
    to the shorter lap. Columns: distance_m, time_a_ms, time_b_ms, delta_ms, where
    delta_ms = time_a_ms - time_b_ms (positive = A is behind / slower at that point).
    """
    n = min(len(a), len(b))
    dist_a = a["distance_m"].to_numpy()[:n]
    dist_b = b["distance_m"].to_numpy()[:n]
    if not np.allclose(dist_a, dist_b):
        raise ValueError("laps were resampled with different steps; resample both with one step_m")
    time_a = a["time_ms"].to_numpy()[:n]
    time_b = b["time_ms"].to_numpy()[:n]
    return pd.DataFrame(
        {
            "distance_m": dist_a,
            "time_a_ms": time_a,
            "time_b_ms": time_b,
            "delta_ms": time_a - time_b,
        }
    )


def segment_by_corners(
    corner_distances: list[float],
    lap_length_m: float,
    names: list[str] | None = None,
) -> list[Segment]:
    """Split the lap into one segment per corner, cutting at midpoints between consecutive corners.

    The first segment (turn 1) starts at 0, so it owns the run from the start line; the last
    corner's segment runs to the end of the lap, so it owns the final straight. Corners outside
    [0, lap_length_m] are dropped. `names` defaults to "T1", "T2", ... in distance order
    (numbered before off-lap corners are dropped).
    """
    if names is not None and len(names) != len(corner_distances):
        raise ValueError("names must have the same length as corner_distances")
    if names is None:
        ordered = sorted(float(d) for d in corner_distances)
        pairs = [(d, f"T{i + 1}") for i, d in enumerate(ordered)]
    else:
        pairs = sorted(
            ((float(d), label) for d, label in zip(corner_distances, names, strict=True)),
            key=lambda p: p[0],
        )
    pairs = [(d, label) for d, label in pairs if 0.0 <= d <= lap_length_m]
    if not pairs:
        return []

    distances = np.array([d for d, _ in pairs])
    midpoints = (distances[:-1] + distances[1:]) / 2.0
    starts = np.concatenate([[0.0], midpoints])
    ends = np.concatenate([midpoints, [lap_length_m]])
    return [
        Segment(name=label, corner_distance_m=d, start_m=float(s), end_m=float(e))
        for (d, label), s, e in zip(pairs, starts, ends, strict=True)
    ]


def value_at(grid: pd.DataFrame, column: str, distance_m: float) -> float:
    """Linearly interpolate one grid column at an arbitrary distance."""
    return float(np.interp(distance_m, grid["distance_m"].to_numpy(), grid[column].to_numpy()))


def corner_metrics(
    grid: pd.DataFrame,
    corner_distance_m: float,
    window_before_m: float = 300.0,
    window_after_m: float = 200.0,
    segment_start_m: float | None = None,
    segment_end_m: float | None = None,
) -> CornerMetrics:
    """Braking, apex and traction metrics of one driver for one corner.

    * brake_point_m: start of the main braking zone, i.e. the first False->True brake transition
      of the longest braking zone that starts in [corner - window_before, corner]. Zones split by
      gaps shorter than BRAKE_MERGE_GAP_M count as one, so a short dab of the brake before or
      after the real zone is ignored. Braking already under way when the window opens belongs to
      an earlier corner and is not counted; with no braking zone the result is None.
    * apex: minimum speed in [corner - window_before, corner + window_after], clipped to the
      segment bounds when given (so a neighbouring corner's apex is not picked up). apex_found is
      False when the minimum sits on the window edge, i.e. the car is still slowing down or
      speeding up there and has no apex of its own inside the window.
    * throttle_on_m: first point after the apex with throttle >= FULL_THROTTLE_PCT, searched up to
      corner + window_after. None when there is no apex or the driver never lifted.
    * max_speed_before_kph: top speed between the window start and the apex.
    * max_speed_after_kph: top speed between the apex and the segment end (or window end).
    * full_throttle_pct / segment_time_ms: only when segment bounds are given.
    """
    dist = grid["distance_m"].to_numpy()
    speed = grid["speed_kph"].to_numpy()
    throttle = grid["throttle_pct"].to_numpy()
    brake = grid["brake"].to_numpy(dtype=bool)

    win_start = corner_distance_m - window_before_m
    win_end = corner_distance_m + window_after_m

    brake_point = _main_brake_onset(dist, brake, win_start, corner_distance_m)

    apex_lo = win_start if segment_start_m is None else max(win_start, segment_start_m)
    apex_hi = win_end if segment_end_m is None else min(win_end, segment_end_m)
    apex_mask = (dist >= apex_lo) & (dist <= apex_hi)
    if not apex_mask.any():  # corner beyond the grid: fall back to the nearest point
        apex_mask = np.zeros_like(brake)
        apex_mask[int(np.argmin(np.abs(dist - corner_distance_m)))] = True
    apex_candidates = np.flatnonzero(apex_mask)
    apex_pos = int(np.argmin(speed[apex_candidates]))
    apex_idx = int(apex_candidates[apex_pos])
    apex_m = float(dist[apex_idx])
    apex_found = 0 < apex_pos < len(apex_candidates) - 1

    lifted = bool((throttle[apex_candidates[: apex_pos + 1]] < FULL_THROTTLE_PCT).any())
    throttle_on: float | None = None
    if apex_found and lifted:
        after_apex = (dist >= apex_m) & (dist <= win_end) & (throttle >= FULL_THROTTLE_PCT)
        on_idx = np.flatnonzero(after_apex)
        throttle_on = float(dist[on_idx[0]]) if on_idx.size else None

    approach = (dist >= win_start) & (dist <= apex_m)
    max_before = float(speed[approach].max()) if approach.any() else float(speed[apex_idx])
    exit_end = win_end if segment_end_m is None else segment_end_m
    exit_mask = (dist >= apex_m) & (dist <= exit_end)
    max_after = float(speed[exit_mask].max()) if exit_mask.any() else float(speed[apex_idx])

    full_pct: float | None = None
    seg_time: float | None = None
    if segment_start_m is not None and segment_end_m is not None:
        seg_mask = (dist >= segment_start_m) & (dist < segment_end_m)
        if seg_mask.any():
            full_pct = float((throttle[seg_mask] >= FULL_THROTTLE_PCT).mean() * 100.0)
        seg_time = value_at(grid, "time_ms", segment_end_m) - value_at(
            grid, "time_ms", segment_start_m
        )

    return CornerMetrics(
        corner_distance_m=float(corner_distance_m),
        brake_point_m=brake_point,
        min_speed_kph=float(speed[apex_idx]),
        min_speed_m=apex_m,
        throttle_on_m=throttle_on,
        max_speed_before_kph=max_before,
        max_speed_after_kph=max_after,
        apex_found=apex_found,
        full_throttle_pct=full_pct,
        segment_time_ms=seg_time,
    )


def braking_zones(dist: np.ndarray, brake: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(start, end) distances of braking zones, merging zones separated by short gaps."""
    padded = np.concatenate([[False], brake, [False]]).astype(np.int8)
    edges = np.diff(padded)
    starts = np.flatnonzero(edges == 1)  # index of the first braking sample
    ends = np.flatnonzero(edges == -1) - 1  # index of the last braking sample
    if starts.size == 0:
        return np.empty(0), np.empty(0)
    start_m, end_m = dist[starts], dist[ends]
    # A zone continues the previous one when the gap between them is short.
    joins = np.concatenate([[False], (start_m[1:] - end_m[:-1]) < BRAKE_MERGE_GAP_M])
    keep_start = ~joins
    keep_end = np.concatenate([keep_start[1:], [True]])
    return start_m[keep_start], end_m[keep_end]


def _main_brake_onset(
    dist: np.ndarray, brake: np.ndarray, window_start_m: float, window_end_m: float
) -> float | None:
    """Start of the longest braking zone that begins inside [window_start_m, window_end_m]."""
    starts, ends = braking_zones(dist, brake)
    inside = (starts >= window_start_m) & (starts <= window_end_m)
    if not inside.any():
        return None
    lengths = np.where(inside, ends - starts, -1.0)
    return float(starts[int(np.argmax(lengths))])


def downsample_indices(n: int, max_points: int = 2000) -> np.ndarray:
    """Evenly strided row indices (always including the last row) so that len <= max_points."""
    if n <= max_points:
        return np.arange(n)
    stride = int(np.ceil((n - 1) / (max_points - 1)))
    idx = np.arange(0, n, stride)
    if idx[-1] != n - 1:
        idx = np.append(idx[: max_points - 1], n - 1)
    return idx
