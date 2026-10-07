"""Fetching sessions and schedules from FastF1 (with on-disk cache and retry/backoff)."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from datetime import UTC, datetime

import fastf1
import pandas as pd
import requests
from fastf1.core import Session
from fastf1.req import RateLimitExceededError

from pitwall.config import get_settings

log = logging.getLogger(__name__)

SESSION_TYPES = ("FP1", "FP2", "FP3", "Q", "SQ", "S", "R")
SPRINT_ONLY = {"S", "SQ"}

# Errors worth retrying: network hiccups and the FastF1 API rate limit.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    requests.exceptions.RequestException,
    RateLimitExceededError,
    ConnectionError,
    TimeoutError,
)

_cache_enabled = False


def enable_cache() -> None:
    """Point FastF1 at the configured on-disk cache (idempotent)."""
    global _cache_enabled
    if _cache_enabled:
        return
    cache_dir = get_settings().fastf1_cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache_dir))
    _cache_enabled = True


def _with_retries(fn, what: str, retries: int, backoff_s: float):
    """Call fn(), retrying transient errors with exponential backoff."""
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except TRANSIENT_ERRORS as exc:
            if attempt == retries:
                raise
            # rate limits reset slowly, so wait much longer for them
            base = 60.0 if isinstance(exc, RateLimitExceededError) else backoff_s
            delay = base * 2 ** (attempt - 1)
            log.warning(
                "%s failed (attempt %d/%d): %s; retrying in %.0fs",
                what,
                attempt,
                retries,
                exc,
                delay,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")


def load_session(
    season: int,
    round: int,
    session_type: str,
    *,
    telemetry: bool = True,
    retries: int = 3,
    backoff_s: float = 5.0,
) -> Session:
    """Load one FastF1 session (laps, weather, messages and optionally telemetry)."""
    session_type = session_type.upper()
    if session_type not in SESSION_TYPES:
        raise ValueError(f"unknown session type {session_type!r}; expected one of {SESSION_TYPES}")
    enable_cache()

    def _load() -> Session:
        session = fastf1.get_session(season, round, session_type)
        session.load(laps=True, telemetry=telemetry, weather=True, messages=True)
        # FastF1 logs (rather than raises) some load failures; touching laps surfaces them.
        _ = session.laps
        return session

    return _with_retries(
        _load, f"load {season} R{round} {session_type}", retries=retries, backoff_s=backoff_s
    )


def get_schedule(season: int, *, retries: int = 3) -> pd.DataFrame:
    """The season's event schedule without testing events."""
    enable_cache()
    return _with_retries(
        lambda: fastf1.get_event_schedule(season, include_testing=False),
        f"schedule {season}",
        retries=retries,
        backoff_s=5.0,
    )


def _session_date_utc(event: pd.Series, session_type: str) -> pd.Timestamp | None:
    """Find the UTC start time of `session_type` within a schedule row."""
    names = {
        "FP1": "Practice 1",
        "FP2": "Practice 2",
        "FP3": "Practice 3",
        "Q": "Qualifying",
        "SQ": "Sprint Qualifying",
        "S": "Sprint",
        "R": "Race",
    }
    wanted = names[session_type]
    for i in range(1, 6):
        if event.get(f"Session{i}") == wanted:
            value = event.get(f"Session{i}DateUtc")
            return None if pd.isna(value) else pd.Timestamp(value)
    return None


def sessions_from_schedule(
    schedule: pd.DataFrame,
    session_types: Iterable[str],
    now: datetime | None = None,
) -> list[tuple[int, str]]:
    """Pure helper behind season_sessions: (round, session_type) pairs that already happened."""
    now_ts = pd.Timestamp(now if now is not None else datetime.now(UTC))
    if now_ts.tzinfo is not None:
        now_ts = now_ts.tz_convert("UTC").tz_localize(None)  # compare as naive UTC
    wanted = [s.upper() for s in session_types]
    pairs: list[tuple[int, str]] = []
    for _, event in schedule.iterrows():
        rnd = int(event["RoundNumber"])
        if rnd <= 0:
            continue
        is_sprint = str(event.get("EventFormat", "")).startswith("sprint")
        for st in wanted:
            if st in SPRINT_ONLY and not is_sprint:
                continue
            date = _session_date_utc(event, st)
            if date is None:
                continue  # e.g. FP2/FP3 do not exist on sprint weekends
            if date.tzinfo is not None:
                date = date.tz_convert("UTC").tz_localize(None)
            if date > now_ts:
                continue
            pairs.append((rnd, st))
    return pairs


def season_sessions(
    season: int,
    session_types: Iterable[str] = ("R", "Q", "S", "SQ"),
) -> list[tuple[int, str]]:
    """Enumerate (round, session_type) pairs of a season that have already taken place.

    Sprint sessions (S, SQ) are only included for sprint weekends.
    """
    return sessions_from_schedule(get_schedule(season), session_types)
