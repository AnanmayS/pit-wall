"""Race-state track map: where every car was on the circuit at the start of a given lap.

Used by the What If page to show the field at the branch lap. The path is the leader's lap
resampled by distance (same as the Coach map); each car is the telemetry sample closest in session
time to the moment the leader started the lap.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

from pitwall.telemetry import queries
from pitwall.telemetry.align import downsample_indices, resample_to_distance
from pitwall.telemetry.models import TrackCorner, TrackMap

MAX_POINTS = 1500


class CarOnTrack(BaseModel):
    driver: str
    team: str
    position: int | None
    lap_number: int
    distance_m: float
    x: float
    y: float
    gap_to_leader_ms: int
    compound: str
    tyre_life: int
    in_pit: bool


class RaceStateMap(BaseModel):
    season: int
    round: int
    lap: int
    leader: str
    session_ms: int
    track: TrackMap
    cars: list[CarOnTrack]


def race_state_map(season: int, round_no: int, lap: int, client=None) -> RaceStateMap | None:
    client = queries._client(client)
    p = {"s": season, "r": round_no, "lap": lap}
    leader = client.query_df(
        "SELECT driver, lap_start_session_ms FROM laps FINAL WHERE season={s:UInt16} AND round={r:UInt8} "
        "AND session_type='R' AND lap_number={lap:UInt8} AND position=1 LIMIT 1",
        parameters=p,
    )
    if leader.empty or pd.isna(leader["lap_start_session_ms"].iloc[0]):
        return None
    leader_code = str(leader["driver"].iloc[0])
    t0 = int(leader["lap_start_session_ms"].iloc[0])
    path_tel = queries.get_lap_telemetry(season, round_no, "R", leader_code, lap, client)
    if path_tel.empty or path_tel["distance_m"].nunique() < 10:
        return None
    grid = resample_to_distance(path_tel, 1.0)
    idx = downsample_indices(len(grid), MAX_POINTS)
    xs, ys, ds = (grid[c].to_numpy(dtype=np.float64) for c in ("x", "y", "distance_m"))
    corners_df = queries.get_corners(season, round_no, client)
    corners = []
    for r in corners_df.itertuples():
        d = float(r.distance_m)
        cx = (
            float(r.x)
            if "x" in corners_df and pd.notna(r.x) and float(r.x) != 0.0
            else float(np.interp(d, ds, xs))
        )
        cy = (
            float(r.y)
            if "y" in corners_df and pd.notna(r.y) and float(r.y) != 0.0
            else float(np.interp(d, ds, ys))
        )
        corners.append(
            TrackCorner(name=str(r.name), distance_m=round(d, 1), x=round(cx, 1), y=round(cy, 1))
        )
    track = TrackMap(
        x=np.round(xs[idx], 1).tolist(),
        y=np.round(ys[idx], 1).tolist(),
        rotation_deg=queries.get_circuit_rotation(season, round_no, client),
        corners=corners,
    )
    # every car's nearest sample to t0, looking at the laps around `lap` (lapped cars are behind)
    cars = client.query_df(
        """
        SELECT t.driver AS driver, argMin(t.x, abs(toInt64(t.session_ms) - {t0:Int64})) AS x,
               argMin(t.y, abs(toInt64(t.session_ms) - {t0:Int64})) AS y,
               argMin(t.distance_m, abs(toInt64(t.session_ms) - {t0:Int64})) AS distance_m,
               argMin(t.lap_number, abs(toInt64(t.session_ms) - {t0:Int64})) AS lap_number,
               min(abs(toInt64(t.session_ms) - {t0:Int64})) AS dt_ms
        FROM telemetry AS t
        WHERE t.season={s:UInt16} AND t.round={r:UInt8} AND t.session_type='R'
          AND t.lap_number BETWEEN greatest(1, {lap:UInt8} - 3) AND {lap:UInt8} + 1
        GROUP BY t.driver
        HAVING dt_ms < 5000
        """,
        parameters=p | {"t0": t0},
    )
    laps = client.query_df(
        """
        SELECT driver, team, position, compound, tyre_life, lap_start_session_ms, pit_in_session_ms, pit_out_session_ms
        FROM laps FINAL WHERE season={s:UInt16} AND round={r:UInt8} AND session_type='R' AND lap_number={lap:UInt8}
        """,
        parameters=p,
    ).set_index("driver")
    leader_lap_ms = client.query(
        "SELECT lap_time_ms FROM laps FINAL WHERE season={s:UInt16} AND round={r:UInt8} AND session_type='R' "
        "AND lap_number={lap:UInt8} AND driver={d:String}",
        parameters=p | {"d": leader_code},
    ).result_rows
    leader_lap_ms = int(leader_lap_ms[0][0]) if leader_lap_ms and leader_lap_ms[0][0] else 90_000
    rows: list[CarOnTrack] = []
    for c in cars.itertuples():
        info = laps.loc[c.driver] if c.driver in laps.index else None
        start = (
            int(info["lap_start_session_ms"])
            if info is not None and pd.notna(info["lap_start_session_ms"])
            else None
        )
        if start is not None:
            # time behind the leader = how much later this car starts the same lap
            gap = max(0, start - t0)
        else:
            # no row for this lap (retired or lapped out): distance-based approximation
            gap = (
                int((ds[-1] - float(c.distance_m)) / max(ds[-1], 1.0) * leader_lap_ms)
                + leader_lap_ms
            )
        laps_behind = int(gap // leader_lap_ms)
        in_pit = False
        if info is not None:
            pin, pout = info["pit_in_session_ms"], info["pit_out_session_ms"]
            in_pit = (pd.notna(pin) and int(pin) <= t0) or (pd.notna(pout) and int(pout) >= t0)
        rows.append(
            CarOnTrack(
                driver=str(c.driver),
                team=str(info["team"]) if info is not None else "",
                position=int(info["position"])
                if info is not None and pd.notna(info["position"])
                else None,
                lap_number=lap - laps_behind,
                distance_m=round(float(c.distance_m), 1),
                x=round(float(c.x), 1),
                y=round(float(c.y), 1),
                gap_to_leader_ms=int(gap),
                compound=str(info["compound"]) if info is not None else "UNKNOWN",
                tyre_life=int(info["tyre_life"])
                if info is not None and pd.notna(info["tyre_life"])
                else 0,
                in_pit=bool(in_pit),
            )
        )
    # running order at the lap start = order of gap (FastF1's per-lap Position is the end-of-lap
    # classification, which differs for cars that pit during the lap)
    rows.sort(key=lambda r: r.gap_to_leader_ms)
    for i, r in enumerate(rows, start=1):
        r.position = i
    return RaceStateMap(
        season=season,
        round=round_no,
        lap=lap,
        leader=leader_code,
        session_ms=t0,
        track=track,
        cars=rows,
    )
