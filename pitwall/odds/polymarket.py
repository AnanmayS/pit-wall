"""Polymarket F1 markets: discovery (Gamma API), parsing, calendar mapping, price history (CLOB).

API notes (verified 2026-10-06):
- Gamma `GET /events?tag_slug=f1` lists F1 events; each event embeds its binary markets. The
  `outcomes`, `outcomePrices` and `clobTokenIds` fields are JSON-encoded strings; the first CLOB
  token is the "Yes" outcome.
- CLOB `GET /prices-history` with `interval=max` returns an empty history for closed markets and only
  ~30 days for open ones. Explicit `startTs`/`endTs` windows work, but a window longer than 15 days is
  rejected with HTTP 400 ("interval is too long"), so full histories are fetched in 14-day windows.
- Event slugs are inconsistent: typos ("azerbijan", "brazlian"), no year on 2024/2025 events, "Italy
  Grand Prix" for the 2025 Emilia Romagna race, "Catalunya" for the 2026 Barcelona race. Rounds are
  therefore matched on the race date first and the name second.
- The `f1` tag also carries non-F1 events (an IndyCar race winner event), and race events contain
  placeholder markets ("Driver A".."Driver J", "Person A") alongside an "Other" market.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple

import httpx
from rapidfuzz import fuzz, process

log = logging.getLogger(__name__)

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"
F1_TAG = "f1"
MAX_WINDOW_S = 14 * 86_400  # CLOB rejects startTs..endTs windows longer than 15 days
DEFAULT_SLEEP_S = 0.2

MARKET_KINDS = (
    "season_champion",
    "constructors_champion",
    "race_winner",
    "race_podium",
    "race_pole",
    "other",
)
RACE_KINDS = frozenset({"race_winner", "race_podium", "race_pole"})
DRIVER_KINDS = frozenset({"season_champion", *RACE_KINDS})

# Special driver codes stored in pm_markets.driver.
OTHER = "OTHER"  # "any other driver" bucket market
PLACEHOLDER = "PLACEHOLDER"  # unlisted slot markets ("Driver A", "Person B"), never traded
UNKNOWN = "UNKNOWN"  # a name we could not map; always logged

# 2024-2026 grid (plus reserves who raced) -> FastF1 three-letter abbreviation.
DRIVER_NAMES: dict[str, str] = {
    "Max Verstappen": "VER",
    "Lando Norris": "NOR",
    "Oscar Piastri": "PIA",
    "Charles Leclerc": "LEC",
    "Lewis Hamilton": "HAM",
    "George Russell": "RUS",
    "Andrea Kimi Antonelli": "ANT",
    "Carlos Sainz": "SAI",
    "Alexander Albon": "ALB",
    "Fernando Alonso": "ALO",
    "Lance Stroll": "STR",
    "Pierre Gasly": "GAS",
    "Esteban Ocon": "OCO",
    "Oliver Bearman": "BEA",
    "Nico Hulkenberg": "HUL",
    "Gabriel Bortoleto": "BOR",
    "Yuki Tsunoda": "TSU",
    "Liam Lawson": "LAW",
    "Isack Hadjar": "HAD",
    "Franco Colapinto": "COL",
    "Jack Doohan": "DOO",
    "Sergio Perez": "PER",
    "Valtteri Bottas": "BOT",
    "Zhou Guanyu": "ZHO",
    "Kevin Magnussen": "MAG",
    "Daniel Ricciardo": "RIC",
    "Logan Sargeant": "SAR",
    "Arvid Lindblad": "LIN",
    "Luke Browning": "BRO",
    "Paul Aron": "ARO",
}
# Alternative spellings seen on Polymarket (normalized form -> code).
_DRIVER_ALIASES: dict[str, str] = {
    "kimi antonelli": "ANT",
    "andrea antonelli": "ANT",
    "alex albon": "ALB",
    "carlos sainz jr": "SAI",
    "guanyu zhou": "ZHO",
    "checo perez": "PER",
}

# Constructor names -> FastF1 TeamName (as stored in results.team).
TEAM_NAMES: dict[str, str] = {
    "mclaren": "McLaren",
    "ferrari": "Ferrari",
    "mercedes": "Mercedes",
    "red bull": "Red Bull Racing",
    "red bull racing": "Red Bull Racing",
    "aston martin": "Aston Martin",
    "alpine": "Alpine",
    "williams": "Williams",
    "racing bulls": "Racing Bulls",
    "rb": "Racing Bulls",
    "visa cash app rb": "Racing Bulls",
    "haas": "Haas F1 Team",
    "haas f1 team": "Haas F1 Team",
    "sauber": "Kick Sauber",
    "kick sauber": "Kick Sauber",
    "stake": "Kick Sauber",
    "audi": "Audi",
    "cadillac": "Cadillac",
}


# ----------------------------------------------------------------------------------------------
# HTTP


class PolymarketClient:
    """Thin httpx wrapper with timeouts, retry on 429/5xx/transport errors and a polite delay."""

    def __init__(
        self,
        *,
        timeout_s: float = 20.0,
        retries: int = 3,
        backoff_s: float = 1.0,
        sleep_s: float = DEFAULT_SLEEP_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.http = httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            headers={"User-Agent": "pitwall/0.1 (+research)"},
            transport=transport,
        )
        self.retries = retries
        self.backoff_s = backoff_s
        self.sleep_s = sleep_s
        self.calls = 0

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> PolymarketClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(self.backoff_s * 2 ** (attempt - 1))
            try:
                self.calls += 1
                r = self.http.get(url, params=params)
            except httpx.TransportError as e:
                last = e
                log.warning("GET %s failed (%s), attempt %d", url, e, attempt + 1)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = httpx.HTTPStatusError(
                    f"{r.status_code} for {url}", request=r.request, response=r
                )
                log.warning("GET %s -> %d, attempt %d", url, r.status_code, attempt + 1)
                continue
            r.raise_for_status()
            return r.json()
        assert last is not None
        raise last

    def pause(self) -> None:
        if self.sleep_s > 0:
            time.sleep(self.sleep_s)


# ----------------------------------------------------------------------------------------------
# Discovery


def discover_f1_events(
    closed: bool | None = None,
    *,
    client: PolymarketClient | None = None,
    page_size: int = 100,
    tag_slug: str = F1_TAG,
) -> list[dict[str, Any]]:
    """All Gamma events tagged `f1`, oldest first. closed=None fetches both open and closed."""
    own = client is None
    pm = client or PolymarketClient()
    try:
        states = [False, True] if closed is None else [closed]
        seen: set[str] = set()
        events: list[dict[str, Any]] = []
        for state in states:
            offset = 0
            while True:
                page = pm.get_json(
                    f"{GAMMA_URL}/events",
                    {
                        "tag_slug": tag_slug,
                        "closed": str(state).lower(),
                        "limit": page_size,
                        "offset": offset,
                        "order": "startDate",
                        "ascending": "true",
                    },
                )
                if not page:
                    break
                for ev in page:
                    key = str(ev.get("id") or ev.get("slug"))
                    if key not in seen:
                        seen.add(key)
                        events.append(ev)
                offset += len(page)
                if len(page) < page_size:
                    break
        return events
    finally:
        if own:
            pm.close()


# ----------------------------------------------------------------------------------------------
# Classification


class EventClass(NamedTuple):
    market_kind: str
    season: int | None
    race_name_guess: str | None


_YEAR_RE = re.compile(r"(?<!\d)(20\d\d)(?!\d)")
_SLUG_DATE_RE = re.compile(r"(20\d\d)-(\d\d)-(\d\d)$")
_GP_RE = re.compile(r"([A-Za-zÀ-ÿ'.\- ]+?\bGrand Prix)", re.IGNORECASE)
_NOT_F1 = ("indycar", "indy", "nascar", "motogp", "formula-e", "f2", "f3")
_PLACE_RE = re.compile(r"\b(2nd|3rd|4th|5th|\d+th)[- ]place\b")


def _norm(text: str) -> str:
    """Lowercase ASCII with punctuation turned into spaces."""
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _year(text: str) -> int | None:
    m = _YEAR_RE.search(text or "")
    return int(m.group(1)) if m else None


def race_name_from_title(title: str) -> str | None:
    """'F1 Canadian Grand Prix Winner' -> 'Canadian Grand Prix'."""
    t = re.sub(r"^\s*(?:F1|Formula 1)\s*[:\-]?\s*", "", title or "", flags=re.IGNORECASE)
    t = re.sub(r"\b20\d\d\b", "", t)
    m = _GP_RE.search(t)
    if not m:
        return None
    name = re.sub(r"\s+", " ", m.group(1)).strip(" -:")
    name = re.sub(r"^(?:the|will there be a .* during the)\s+", "", name, flags=re.IGNORECASE)
    return name or None


def _has(slug: str, title: str, *phrases: str) -> bool:
    """True if any hyphenated phrase occurs as whole words in the slug or the title."""
    s = f"-{slug}-"
    t = f" {_norm(title)} "
    return any(f"-{p}-" in s or f" {p.replace('-', ' ')} " in t for p in phrases)


def classify_event(slug: str, title: str) -> EventClass:
    """(market_kind, season, race_name_guess) from an event's slug and title.

    season comes from a year in the slug or title and is None when neither has one; callers fall
    back to the market questions and the event dates (see `resolve_season`).
    """
    s = (slug or "").lower()
    t = title or ""
    season = _year(s) or _year(t)

    if _has(s, t, *_NOT_F1):
        return EventClass("other", season, None)
    if _PLACE_RE.search(f"{s} {t.lower()}".replace("_", "-")) or _has(
        s, t, "ahead", "finish-ahead", "h2h", "head-to-head", "top-3", "top-5", "top-10"
    ):
        return EventClass("other", season, None)  # "Drivers Champion: 2nd Place", rivalries

    if not _has(s, t, "grand-prix") and re.search(r"champion", f"{s} {t.lower()}"):
        if _has(s, t, "constructors", "constructor", "constructors-championship"):
            return EventClass("constructors_champion", season, None)
        if _has(s, t, "drivers", "driver", "f1-champion", "world-champion"):
            return EventClass("season_champion", season, None)
        return EventClass("other", season, None)

    if not _has(s, t, "grand-prix"):
        return EventClass("other", season, None)
    race = race_name_from_title(t) or _race_name_from_slug(s)
    if _has(
        s,
        t,
        "sprint",
        "practice",
        "fastest-lap",
        "constructor",
        "safety-car",
        "red-flag",
        "take-place",
        "rain",
        "margin",
        "laps",
    ):
        return EventClass("other", season, race)
    if _has(s, t, "pole", "pole-position", "pole-winner"):
        return EventClass("race_pole", season, race)
    if _has(s, t, "podium"):
        return EventClass("race_podium", season, race)
    if _has(s, t, "winner", "driver-winner"):
        return EventClass("race_winner", season, race)
    return EventClass("other", season, race)


def _race_name_from_slug(slug: str) -> str | None:
    m = re.search(r"(?:f1-)?([a-z\-]+?)-grand-prix", slug)
    if not m:
        return None
    return m.group(1).replace("-", " ").title() + " Grand Prix"


def race_date_guess(event: dict[str, Any]) -> date | None:
    """Race (or session) date: the date suffix of newer slugs, else the event endDate.

    Newer events (late 2025 on) end a week after the race but carry the race date in the slug;
    older ones end on race day.
    """
    m = _SLUG_DATE_RE.search(event.get("slug") or "")
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    end = parse_ts(event.get("endDate"))
    return end.date() if end else None


def resolve_season(event: dict[str, Any], kind: str | None = None) -> int | None:
    """Season of an event: slug/title year, else the questions' year, else from its dates."""
    ec = classify_event(event.get("slug", ""), event.get("title", ""))
    if ec.season:
        return ec.season
    for m in event.get("markets") or []:
        y = _year(m.get("question", ""))
        if y:
            return y
    kind = kind or ec.market_kind
    if kind in RACE_KINDS:
        d = race_date_guess(event)
        return d.year if d else None
    end = parse_ts(event.get("endDate"))
    if end is None:
        return None
    # championship markets settle after the final race, sometimes months into the next year
    return end.year - 1 if end.month <= 4 else end.year


# ----------------------------------------------------------------------------------------------
# Market parsing


def parse_ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        out = json.loads(value)
    except (TypeError, ValueError):
        return []
    return out if isinstance(out, list) else []


_NORMALIZED_NAMES = {_norm(k): v for k, v in DRIVER_NAMES.items()}
_LAST_NAMES = {_norm(k).split()[-1]: v for k, v in DRIVER_NAMES.items()}
_PLACEHOLDER_RE = re.compile(r"^(driver|person|player|team)\s+[a-z]$")
_OTHER_RE = re.compile(r"^(other|field|any other( driver)?|another driver|someone else)$")


def driver_code(name: str, *, context: str = "") -> str:
    """Map a driver name as written on Polymarket to a FastF1 code (or OTHER/PLACEHOLDER/UNKNOWN).

    Exact full name, then alias, then last name, then fuzzy match (handles 'Hulkenburg',
    'George Russel', 'Carlos Sainz Jr.'). Unmapped names are logged and returned as UNKNOWN.
    """
    n = _norm(name)
    n = re.sub(r"\s+(jr|sr|ii|iii)$", "", n)
    if not n:
        log.warning("empty driver name (%s)", context)
        return UNKNOWN
    if _OTHER_RE.match(n):
        return OTHER
    if _PLACEHOLDER_RE.match(n):
        return PLACEHOLDER
    if n in _NORMALIZED_NAMES:
        return _NORMALIZED_NAMES[n]
    if n in _DRIVER_ALIASES:
        return _DRIVER_ALIASES[n]
    last = n.split()[-1]
    if last in _LAST_NAMES:
        return _LAST_NAMES[last]
    hit = process.extractOne(n, list(_NORMALIZED_NAMES), scorer=fuzz.WRatio, score_cutoff=88)
    if hit:
        return _NORMALIZED_NAMES[hit[0]]
    hit = process.extractOne(last, list(_LAST_NAMES), scorer=fuzz.ratio, score_cutoff=85)
    if hit:
        return _LAST_NAMES[hit[0]]
    log.warning("UNKNOWN driver name %r (%s)", name, context)
    return UNKNOWN


def team_name(name: str, *, context: str = "") -> str:
    """Constructor name -> FastF1 team name ('Mclaren Mastercard' -> 'McLaren'); '' if unknown."""
    n = _norm(name)
    if not n:
        return ""
    if re.match(r"^(other|another team|any other team|field)$", n):
        return OTHER
    if _PLACEHOLDER_RE.match(n):
        return PLACEHOLDER
    if n in TEAM_NAMES:
        return TEAM_NAMES[n]
    for key in sorted(TEAM_NAMES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", n):
            return TEAM_NAMES[key]
    log.warning("UNKNOWN team name %r (%s)", name, context)
    return UNKNOWN


_QUESTION_SUBJECT_RE = re.compile(r"^\s*will\s+(.+?)\s+(?:win|be|finish|get|take)\b", re.I)


def subject_of(market: dict[str, Any]) -> str:
    """The driver/team a market is about: groupItemTitle, else parsed from the question."""
    title = (market.get("groupItemTitle") or "").strip()
    if title:
        return title
    m = _QUESTION_SUBJECT_RE.match(market.get("question") or "")
    return m.group(1) if m else ""


def resolved_outcome(market: dict[str, Any]) -> int | None:
    """1 if Yes won, 0 if No won, None while open or if the market settled at a non 0/1 price."""
    if not market.get("closed"):
        return None
    prices = _json_list(market.get("outcomePrices"))
    outcomes = [str(o).lower() for o in _json_list(market.get("outcomes"))]
    if len(prices) < 2:
        return None
    try:
        p = [float(x) for x in prices]
    except (TypeError, ValueError):
        return None
    yes_idx = outcomes.index("yes") if "yes" in outcomes else 0
    if p[yes_idx] >= 0.99:
        return 1
    if p[yes_idx] <= 0.01:
        return 0
    return None


@dataclass
class MarketRecord:
    """One row of pm_markets."""

    market_id: str
    condition_id: str
    event_slug: str
    event_title: str
    question: str
    market_kind: str
    season: int
    round: int | None
    driver: str
    team: str
    yes_token_id: str
    created_at: datetime
    end_date: datetime
    closed: bool
    resolved_outcome: int | None
    # not stored; used for calendar mapping
    race_name_guess: str | None = field(default=None, compare=False)
    race_date: date | None = field(default=None, compare=False)

    def row(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("race_name_guess")
        d.pop("race_date")
        return d


EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def parse_market(event: dict[str, Any], market: dict[str, Any]) -> MarketRecord:
    """Normalize one Gamma market (with its parent event) into a pm_markets row."""
    slug = event.get("slug", "")
    ec = classify_event(slug, event.get("title", ""))
    kind = ec.market_kind
    season = resolve_season(event, kind) or _year(market.get("question", "")) or 0
    context = f"{slug} / {market.get('id')}"
    subject = subject_of(market)
    driver = team = ""
    if kind in DRIVER_KINDS:
        driver = driver_code(subject, context=context)
    elif kind == "constructors_champion":
        team = team_name(subject, context=context)
    tokens = _json_list(market.get("clobTokenIds"))
    outcomes = [str(o).lower() for o in _json_list(market.get("outcomes"))]
    yes_idx = outcomes.index("yes") if "yes" in outcomes else 0
    yes_token = str(tokens[yes_idx]) if len(tokens) > yes_idx else ""
    created = parse_ts(market.get("createdAt")) or parse_ts(event.get("startDate")) or EPOCH
    end = parse_ts(market.get("endDate")) or parse_ts(event.get("endDate")) or created
    return MarketRecord(
        market_id=str(market.get("id", "")),
        condition_id=str(market.get("conditionId") or ""),
        event_slug=slug,
        event_title=(event.get("title") or "").strip(),
        question=(market.get("question") or "").strip(),
        market_kind=kind,
        season=int(season),
        round=None,
        driver=driver,
        team=team,
        yes_token_id=yes_token,
        created_at=created,
        end_date=end,
        closed=bool(market.get("closed")),
        resolved_outcome=resolved_outcome(market),
        race_name_guess=ec.race_name_guess,
        race_date=race_date_guess(event) if kind in RACE_KINDS else None,
    )


def iter_market_records(events: Iterable[dict[str, Any]]) -> Iterator[MarketRecord]:
    for ev in events:
        for m in ev.get("markets") or []:
            if not m.get("id"):
                continue
            yield parse_market(ev, m)


# ----------------------------------------------------------------------------------------------
# Calendar mapping


@dataclass(frozen=True)
class CalendarRace:
    season: int
    round: int
    event_name: str
    country: str
    location: str
    race_date: date

    @property
    def words(self) -> set[str]:
        return set(_norm(f"{self.event_name} {self.country} {self.location}").split()) - _STOP


_STOP = {"grand", "prix", "gp", "f1", "formula", "the", "de", "of", "city"}
# Polymarket spellings that share no prefix with FastF1's event/country/location words.
_NAME_SYNONYMS = {
    "us": {"united", "states", "austin"},
    "usa": {"united", "states", "austin"},
    "catalunya": {"barcelona", "spain"},
    "brazilian": {"brazil", "paulo"},
    "brazlian": {"brazil", "paulo"},
    "mexican": {"mexico"},
    "emilia": {"imola"},
    "romagna": {"imola"},
}


def _name_score(guess: str | None, race: CalendarRace) -> float:
    """0..100 similarity between a Polymarket race name and a calendar event."""
    if not guess:
        return 0.0
    gw = set(_norm(guess).split()) - _STOP
    if not gw:
        return 0.0
    cw = race.words
    best = 0.0
    for w in gw:
        if _NAME_SYNONYMS.get(w, set()) & cw:
            return 100.0
        for c in cw:
            if w[:4] == c[:4] and len(w) >= 4:
                best = max(best, 90.0)
            best = max(best, float(fuzz.ratio(w, c)))
    return best


def race_round_for_market(
    season: int,
    race_name: str | None,
    race_date: date | None,
    calendar: Iterable[CalendarRace],
    *,
    window_days: int = 8,
    name_threshold: float = 75.0,
) -> int | None:
    """Round of the race an event is about, or None.

    Candidates are calendar races of the season within `window_days` of the event's race date; a
    name match wins, otherwise the nearest date (logged). The date gate keeps cancelled races (the
    April 2026 Bahrain event) and reused names (2025 "Italy Grand Prix" = Imola) from mapping onto
    the wrong round.
    """
    races = [r for r in calendar if r.season == season]
    if not races or race_date is None:
        return None
    near = [r for r in races if abs((r.race_date - race_date).days) <= window_days]
    if not near:
        return None
    named = [r for r in near if _name_score(race_name, r) >= name_threshold]
    pool = named or near
    best = min(pool, key=lambda r: abs((r.race_date - race_date).days))
    if not named:
        log.info(
            "round by date only: %r on %s -> R%d %s",
            race_name,
            race_date,
            best.round,
            best.event_name,
        )
    return best.round


def load_calendar(
    ch_client: Any | None, seasons: Iterable[int], *, use_fastf1: bool = True
) -> list[CalendarRace]:
    """Race calendar from ClickHouse `sessions` (R rows), completed with the FastF1 event schedule
    for rounds not ingested yet (future races, seasons not loaded)."""
    seasons = sorted({int(s) for s in seasons if s})
    out: dict[tuple[int, int], CalendarRace] = {}
    if ch_client is not None and seasons:
        rows = ch_client.query(
            "SELECT season, round, any(event_name), any(country), any(location), "
            "toDate(min(session_date)) FROM sessions FINAL "
            "WHERE session_type = 'R' AND season IN {seasons:Array(UInt16)} "
            "GROUP BY season, round",
            parameters={"seasons": seasons},
        ).result_rows
        for s, r, name, country, loc, d in rows:
            out[(int(s), int(r))] = CalendarRace(int(s), int(r), name, country, loc, d)
    if use_fastf1:
        for season in seasons:
            for race in _fastf1_calendar(season):
                out.setdefault((race.season, race.round), race)
    return sorted(out.values(), key=lambda r: (r.season, r.round))


def _fastf1_calendar(season: int) -> list[CalendarRace]:
    try:
        import fastf1
        import pandas as pd

        from pitwall.config import get_settings

        cache = get_settings().fastf1_cache_dir
        cache.mkdir(parents=True, exist_ok=True)
        fastf1.Cache.enable_cache(str(cache))
        sched = fastf1.get_event_schedule(season, include_testing=False)
    except Exception as e:  # network or FastF1 failure: mapping falls back to ClickHouse only
        log.warning("FastF1 schedule %d unavailable: %s", season, e)
        return []
    out = []
    for _, ev in sched.iterrows():
        rnd = int(ev["RoundNumber"])
        if rnd <= 0:
            continue
        when = ev.get("Session5DateUtc")
        if when is None or pd.isna(when):
            when = ev["EventDate"]
        out.append(
            CalendarRace(
                season,
                rnd,
                str(ev["EventName"]),
                str(ev["Country"]),
                str(ev["Location"]),
                pd.Timestamp(when).date(),
            )
        )
    return out


def assign_rounds(
    records: Iterable[MarketRecord], calendar: list[CalendarRace]
) -> tuple[int, list[str]]:
    """Set `round` on race-level records in place. Returns (events mapped, unmapped event slugs)."""
    by_event: dict[str, list[MarketRecord]] = {}
    for rec in records:
        if rec.market_kind in RACE_KINDS:
            by_event.setdefault(rec.event_slug, []).append(rec)
    mapped = 0
    unmapped: list[str] = []
    for slug, recs in by_event.items():
        r0 = recs[0]
        rnd = race_round_for_market(r0.season, r0.race_name_guess, r0.race_date, calendar)
        for rec in recs:
            rec.round = rnd
        if rnd is None:
            unmapped.append(slug)
            log.warning(
                "unmapped %s event %s (%r, %s, season %d)",
                r0.market_kind,
                slug,
                r0.race_name_guess,
                r0.race_date,
                r0.season,
            )
        else:
            mapped += 1
    return mapped, unmapped


# ----------------------------------------------------------------------------------------------
# Price history


def fetch_price_history(
    token_id: str,
    start_ts: int,
    end_ts: int,
    fidelity: int = 60,
    *,
    client: PolymarketClient | None = None,
    window_s: int = MAX_WINDOW_S,
    stop_after_empty: int = 2,
) -> list[tuple[int, float]]:
    """Yes-price history [(unix seconds, price)] for one CLOB token between start_ts and end_ts.

    Walks backwards from end_ts in windows of at most 14 days, de-duplicating on t. Stops at
    start_ts, or after `stop_after_empty` consecutive empty windows once data has been seen (the
    market did not exist yet).
    """
    if not token_id or end_ts <= start_ts:
        return []
    own = client is None
    pm = client or PolymarketClient()
    points: dict[int, float] = {}
    empty_run = 0
    try:
        hi = end_ts
        while hi > start_ts:
            lo = max(start_ts, hi - window_s)
            data = pm.get_json(
                f"{CLOB_URL}/prices-history",
                {"market": token_id, "startTs": lo, "endTs": hi, "fidelity": fidelity},
            )
            pm.pause()
            hist = (data or {}).get("history") or []
            for pt in hist:
                try:
                    t, p = int(pt["t"]), float(pt["p"])
                except (KeyError, TypeError, ValueError):
                    continue
                if start_ts <= t <= end_ts:
                    points[t] = p
            if hist:
                empty_run = 0
            else:
                empty_run += 1
                if points and empty_run >= stop_after_empty:
                    break
            hi = lo
        return sorted(points.items())
    finally:
        if own:
            pm.close()


def history_bounds(
    created_at: datetime,
    end_date: datetime,
    closed: bool,
    last_ts: datetime | None,
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """(start_ts, end_ts) to request for a market: after what is stored, up to now or settlement."""
    now = now or datetime.now(UTC)
    start = created_at - timedelta(hours=1)
    if last_ts is not None:
        start = max(start, last_ts + timedelta(seconds=1))
    end = min(now, end_date + timedelta(days=1)) if closed else now
    return int(start.timestamp()), int(end.timestamp())
