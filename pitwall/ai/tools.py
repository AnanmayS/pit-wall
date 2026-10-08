"""Tool definitions for the AI layer. Each tool wraps a query or simulator function and returns a
JSON-serializable dict; the schemas are strict so inputs always validate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pitwall.db.clickhouse import get_client
from pitwall.telemetry import coach, queries
from pitwall.whatif.models import ScenarioSpec
from pitwall.whatif.service import run_or_cached

SESSION_TYPES = ["R", "Q", "S", "SQ", "FP1", "FP2", "FP3"]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[..., Any]

    def to_api(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "strict": True,
        }


def _schema(props: dict[str, dict]) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def _opt(t: str, desc: str, **extra) -> dict:
    return {"type": [t, "null"], "description": desc, **extra}


def _int(desc: str, **extra) -> dict:
    return {"type": "integer", "description": desc, **extra}


def _str(desc: str, **extra) -> dict:
    return {"type": "string", "description": desc, **extra}


def list_sessions(season: int) -> list[dict]:
    return [s.model_dump() for s in queries.list_sessions(season)]


def get_drivers(season: int) -> list[dict]:
    return sorted(
        queries.driver_names(season).values(), key=lambda d: str(d.get("last_name") or d["driver"])
    )


def compare_laps(season, round, session_type, driver_a, driver_b, lap_a=None, lap_b=None) -> dict:
    res = coach.compare_laps(
        season, round, session_type, driver_a, driver_b, lap_a=lap_a, lap_b=lap_b
    )
    out = res.model_dump()
    out.pop("grid", None)
    out.pop("segments", None)
    return out


def get_lap_times(season, round, session_type, driver, lap_from=None, lap_to=None) -> list[dict]:
    laps = queries.list_laps(season, round, session_type.upper(), driver.upper())
    rows = [lap.model_dump() for lap in laps]
    if lap_from is not None:
        rows = [r for r in rows if r["lap_number"] >= lap_from]
    if lap_to is not None:
        rows = [r for r in rows if r["lap_number"] <= lap_to]
    return rows


def get_results(season: int, round: int, session_type: str = "R") -> list[dict]:
    df = get_client().query_df(
        "SELECT driver, team, grid_position, position, classified_position, status, points, laps_completed "
        "FROM results FINAL WHERE season={s:UInt16} AND round={r:UInt8} AND session_type={t:String} ORDER BY position",
        parameters={"s": season, "r": round, "t": session_type.upper()},
    )
    return df.where(df.notna(), None).to_dict(orient="records")


def get_stints(season: int, round: int, driver: str | None = None) -> dict:
    p = {"s": season, "r": round, "d": (driver or "").upper()}
    extra = " AND driver={d:String}" if driver else ""
    c = get_client()
    stints = c.query_df(
        f"SELECT driver, stint, compound, start_lap, end_lap, laps, tyre_life_at_start FROM stints FINAL "
        f"WHERE season={{s:UInt16}} AND round={{r:UInt8}} AND session_type='R'{extra} ORDER BY driver, stint",
        parameters=p,
    )
    stops = c.query_df(
        f"SELECT driver, stop_number, lap_in, pit_lane_ms, compound_before, compound_after FROM pit_stops FINAL "
        f"WHERE season={{s:UInt16}} AND round={{r:UInt8}} AND session_type='R'{extra} ORDER BY driver, stop_number",
        parameters=p,
    )
    return {
        "stints": stints.to_dict(orient="records"),
        "pit_stops": stops.to_dict(orient="records"),
        "note": "pit_lane_ms is pit-entry to pit-exit; stops with compound_before == compound_after and "
        "pit_lane_ms under ~17000 under a safety car are drive-throughs, not tyre changes",
    }


def get_gaps(season: int, round: int, lap: int) -> list[dict]:
    """Gap to the leader at the end of `lap` (race), from lap start times."""
    df = get_client().query_df(
        """
        SELECT l.driver AS driver, l.position AS position, l.compound AS compound, l.tyre_life AS tyre_life,
               coalesce(n.next_start, l.lap_start_session_ms + l.lap_time_ms)
                 - (SELECT min(lap_start_session_ms) FROM laps FINAL
                    WHERE season={s:UInt16} AND round={r:UInt8} AND session_type='R' AND lap_number=1) AS race_time_ms
        FROM (SELECT driver, position, compound, tyre_life, lap_start_session_ms, lap_time_ms FROM laps FINAL
              WHERE season={s:UInt16} AND round={r:UInt8} AND session_type='R' AND lap_number={lap:UInt8}) AS l
        LEFT JOIN (SELECT driver, lap_start_session_ms AS next_start FROM laps FINAL
                   WHERE season={s:UInt16} AND round={r:UInt8} AND session_type='R' AND lap_number={lap:UInt8}+1) AS n
          ON n.driver = l.driver
        ORDER BY race_time_ms
        """,
        parameters={"s": season, "r": round, "lap": lap},
    )
    if df.empty:
        return []
    leader = df["race_time_ms"].min()
    df["gap_to_leader_ms"] = df["race_time_ms"] - leader
    df = df.where(df.notna(), None)
    return df.to_dict(orient="records")


def simulate_scenario(season, round, changes, branch_lap=None, n_runs=10_000) -> dict:
    spec = ScenarioSpec(
        season=season, round=round, changes=changes, branch_lap=branch_lap, n_runs=n_runs
    )
    resp = run_or_cached(spec)
    out = resp.to_dict()
    out["summary"] = [
        {k: v for k, v in row.items() if k != "position_probs"} for row in out["summary"][:12]
    ]
    return out


CHANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": [
                "pit_lap",
                "compound",
                "skip_stop",
                "extra_stop",
                "no_safety_car",
                "safety_car",
                "dnf",
            ],
            "description": "pit_lap: move the driver's next stop to `lap` (optionally with `compound`); "
            "compound: change the tyre fitted at remaining stop number `stop`; skip_stop: remove remaining stop `stop`; "
            "extra_stop: add a stop on `lap` with `compound`; no_safety_car: no safety cars after the branch; "
            "safety_car: force one on `lap`; dnf: retire the driver on `lap`",
        },
        "driver": _opt("string", "3-letter driver code; required for driver changes"),
        "lap": _opt("integer", "lap number for pit_lap / extra_stop / safety_car / dnf"),
        "stop": _opt("integer", "1-based remaining stop number for compound / skip_stop"),
        "compound": _opt(
            "string",
            "SOFT, MEDIUM, HARD, INTERMEDIATE or WET",
            enum=["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", None],
        ),
    },
    "required": ["type", "driver", "lap", "stop", "compound"],
    "additionalProperties": False,
}

TOOLS: list[Tool] = [
    Tool(
        "get_drivers",
        "Driver codes with full names, car numbers and teams for a season. Use it to turn codes into names.",
        _schema({"season": _int("Season year, e.g. 2025")}),
        get_drivers,
    ),
    Tool(
        "list_sessions",
        "List ingested sessions (round numbers, event names, session types) for a season.",
        _schema({"season": _int("Season year, e.g. 2025")}),
        list_sessions,
    ),
    Tool(
        "get_results",
        "Final classification for a session: finishing position, grid, status, points.",
        _schema(
            {
                "season": _int("season"),
                "round": _int("round number"),
                "session_type": _str("R, Q, S or SQ", enum=["R", "Q", "S", "SQ"]),
            }
        ),
        get_results,
    ),
    Tool(
        "compare_laps",
        "Telemetry Coach: align two drivers' laps by track distance and report where time is gained or lost "
        "(total delta, per-corner braking points, apex speeds, throttle-on points, ranked insights). "
        "lap_a/lap_b null = that driver's fastest lap. Positive delta_ms means driver_a is slower.",
        _schema(
            {
                "season": _int("season"),
                "round": _int("round number"),
                "session_type": _str("R, Q, S or SQ", enum=["R", "Q", "S", "SQ"]),
                "driver_a": _str("3-letter driver code"),
                "driver_b": _str("3-letter driver code"),
                "lap_a": _opt("integer", "lap number for driver_a, null for fastest"),
                "lap_b": _opt("integer", "lap number for driver_b, null for fastest"),
            }
        ),
        compare_laps,
    ),
    Tool(
        "get_lap_times",
        "Lap-by-lap times, compounds, tyre age, stint and position for one driver in a session.",
        _schema(
            {
                "season": _int("season"),
                "round": _int("round number"),
                "session_type": _str("R, Q, S or SQ", enum=["R", "Q", "S", "SQ"]),
                "driver": _str("3-letter driver code"),
                "lap_from": _opt("integer", "first lap to include, null for all"),
                "lap_to": _opt("integer", "last lap to include, null for all"),
            }
        ),
        get_lap_times,
    ),
    Tool(
        "get_stints",
        "Race stints (compound, start/end lap) and pit stops (lap, pit-lane time) for one driver or the field.",
        _schema(
            {
                "season": _int("season"),
                "round": _int("round number"),
                "driver": _opt("string", "3-letter code or null for everyone"),
            }
        ),
        get_stints,
    ),
    Tool(
        "get_gaps",
        "Running order and gap to the leader (ms) for every driver at the end of a given race lap.",
        _schema(
            {"season": _int("season"), "round": _int("round number"), "lap": _int("lap number")}
        ),
        get_gaps,
    ),
    Tool(
        "simulate_scenario",
        "What If: replay a real race to a branch lap, apply changes (pit laps, compounds, safety cars, DNFs) "
        "and simulate the rest of the race n_runs times. Returns finishing-position probabilities per driver "
        "and, for changed drivers, their actual result vs the counterfactual distribution. Results are cached.",
        _schema(
            {
                "season": _int("season"),
                "round": _int("round number"),
                "changes": {"type": "array", "items": CHANGE_SCHEMA, "minItems": 1, "maxItems": 10},
                "branch_lap": _opt("integer", "lap to simulate from; null = earliest change lap"),
                "n_runs": _int(
                    "Monte Carlo runs, 100-100000 (default 10000)", minimum=100, maximum=100000
                ),
            }
        ),
        simulate_scenario,
    ),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def execute(name: str, inputs: dict) -> tuple[Any, bool]:
    """Run a tool. Returns (result, is_error)."""
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return {"error": f"unknown tool {name}"}, True
    try:
        return tool.fn(**inputs), False
    except Exception as e:  # noqa: BLE001 - surfaced to the model as a tool error
        return {"error": f"{type(e).__name__}: {e}"}, True
