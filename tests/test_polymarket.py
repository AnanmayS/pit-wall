"""Polymarket parsing, classification, driver mapping, calendar mapping and windowed history."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime

import httpx
import pytest

from pitwall.odds import polymarket as pm


@pytest.mark.parametrize(
    ("slug", "title", "kind", "season", "race"),
    [
        ("2026-f1-drivers-champion", "F1 Drivers' Champion", "season_champion", 2026, None),
        ("f1-drivers-champion", "F1 Drivers Champion", "season_champion", None, None),
        (
            "f1-constructors-champion",
            "F1 Constructors' Champion",
            "constructors_champion",
            None,
            None,
        ),
        (
            "f1-constructors-championship-winner",
            "F1 Constructors Champion",
            "constructors_champion",
            None,
            None,
        ),
        ("f1-drivers-champion-2nd-place", "F1 Drivers Champion: 2nd Place", "other", None, None),
        (
            "f1-singapore-grand-prix-winner-2026-10-11",
            "Singapore Grand Prix: Driver Winner",
            "race_winner",
            2026,
            "Singapore Grand Prix",
        ),
        (
            "italian-grand-prix-winner",
            "Italian Grand Prix Winner",
            "race_winner",
            None,
            "Italian Grand Prix",
        ),
        (
            "f1-canadian-grand-prix-winner",
            "F1 Canadian Grand Prix Winner ",
            "race_winner",
            None,
            "Canadian Grand Prix",
        ),
        (
            "f1-bahrain-grand-prix-winner-2026-10-04",
            "Bahrain Grand Prix: Driver Winner",
            "race_winner",
            2026,
            "Bahrain Grand Prix",
        ),
        (
            "f1-singapore-grand-prix-driver-podium-2026-10-11",
            "Singapore Grand Prix: Driver Podium Finish",
            "race_podium",
            2026,
            "Singapore Grand Prix",
        ),
        (
            "f1-singapore-grand-prix-driver-pole-position-2026-10-10",
            "Singapore Grand Prix: Driver Pole Position",
            "race_pole",
            2026,
            "Singapore Grand Prix",
        ),
        ("miami-grand-prix-pole-winner", "Miami Grand Prix: Pole Winner", "race_pole", None, None),
        # look-alikes that must not be race winners
        (
            "f1-singapore-grand-prix-sprint-winner-2026-10-10",
            "Singapore Grand Prix: Sprint Winner",
            "other",
            2026,
            None,
        ),
        (
            "f1-singapore-grand-prix-sprint-qualifying-pole-winner-2026-10-09",
            "Singapore Grand Prix: Sprint Qualifying Pole Winner",
            "other",
            2026,
            None,
        ),
        (
            "f1-singapore-grand-prix-constructor-pole-position-2026-10-10",
            "Singapore Grand Prix: Constructor Pole Position",
            "other",
            2026,
            None,
        ),
        (
            "f1-dutch-grand-prix-h2h-2026-08-23",
            "Dutch Grand Prix: Head-to-Head",
            "other",
            2026,
            None,
        ),
        (
            "f1-bahrain-grand-prix-safety-car-2026-10-04",
            "Will there be a safety car during the 2026 F1 Bahrain Grand Prix?",
            "other",
            2026,
            None,
        ),
        (
            "will-it-rain-during-the-bahrain-grand-prix",
            "Rain during the Bahrain Grand Prix?",
            "other",
            None,
            None,
        ),
        (
            "indycar-honda-indy-200-at-mid-ohio-winner-2026-07-05",
            "Honda Indy 200 at Mid-Ohio: Race Winner",
            "other",
            2026,
            None,
        ),
        (
            "f1-will-carlos-sainz-finish-ahead-of-fernando-alonso-in-the-2026-drivers-championship",
            "F1: Will Carlos Sainz finish ahead of Fernando Alonso in the 2026 Drivers' Championship?",
            "other",
            2026,
            None,
        ),
        (
            "will-lando-norris-win-3-grands-prix-in-2026",
            "Will Lando Norris win 3+ Grands Prix in 2026?",
            "other",
            2026,
            None,
        ),
    ],
)
def test_classify_event(slug, title, kind, season, race):
    ec = pm.classify_event(slug, title)
    assert ec.market_kind == kind
    assert ec.season == season
    if race is not None:
        assert ec.race_name_guess == race


def test_classify_event_unpacks_as_tuple():
    kind, season, race = pm.classify_event(
        "f1-bahrain-grand-prix-winner-2026-10-04", "Bahrain Grand Prix: Driver Winner"
    )
    assert (kind, season, race) == ("race_winner", 2026, "Bahrain Grand Prix")


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Lando Norris", "NOR"),
        ("Max Verstappen", "VER"),
        ("Andrea Kimi Antonelli", "ANT"),
        ("Kimi Antonelli", "ANT"),
        ("Andrea Antonelli", "ANT"),
        ("Carlos Sainz Jr.", "SAI"),
        ("Carlos Sainz ", "SAI"),
        ("Nico Hülkenberg", "HUL"),
        ("Nico Hulkenburg", "HUL"),  # typo seen on Polymarket
        ("George Russel ", "RUS"),  # typo seen on Polymarket
        ("Sergio Pérez", "PER"),
        ("Alex Albon", "ALB"),
        ("Piastri", "PIA"),
        ("Arvid Lindblad", "LIN"),
        ("Zhou Guanyu", "ZHO"),
        ("Other", pm.OTHER),
        ("Other ", pm.OTHER),
        ("Driver A", pm.PLACEHOLDER),
        ("Person D", pm.PLACEHOLDER),
    ],
)
def test_driver_code(name, code):
    assert pm.driver_code(name) == code


def test_driver_code_unknown_is_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="pitwall.odds.polymarket"):
        assert pm.driver_code("Alex Palou", context="test") == pm.UNKNOWN
    assert "Alex Palou" in caplog.text


@pytest.mark.parametrize(
    ("name", "team"),
    [
        ("Red Bull", "Red Bull Racing"),
        ("Red Bull Racing", "Red Bull Racing"),
        ("Mclaren Mastercard", "McLaren"),
        ("Tgr Haas", "Haas F1 Team"),
        ("Audi Revolut", "Audi"),
        ("Racing Bulls", "Racing Bulls"),
        ("Other", pm.OTHER),
    ],
)
def test_team_name(name, team):
    assert pm.team_name(name) == team


def _event(
    slug="f1-bahrain-grand-prix-winner-2026-10-04", title="Bahrain Grand Prix: Driver Winner"
):
    return {
        "slug": slug,
        "title": title,
        "startDate": "2026-09-26T11:30:00Z",
        "endDate": "2026-10-11T07:00:00Z",
        "markets": [],
    }


def _market(**kw):
    m = {
        "id": "1586671",
        "question": "Will Lando Norris win the 2026 F1 Bahrain Grand Prix?",
        "conditionId": "0xabc",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.31", "0.69"]',
        "clobTokenIds": '["111", "222"]',
        "createdAt": "2026-09-26T11:30:01.93Z",
        "endDate": "2026-10-11T07:00:00Z",
        "closed": False,
        "groupItemTitle": "Lando Norris",
    }
    m.update(kw)
    return m


def test_parse_market_open_race_winner():
    rec = pm.parse_market(_event(), _market())
    assert rec.market_id == "1586671"
    assert rec.market_kind == "race_winner"
    assert rec.season == 2026
    assert rec.driver == "NOR"
    assert rec.team == ""
    assert rec.yes_token_id == "111"
    assert rec.created_at == datetime(2026, 9, 26, 11, 30, 1, 930000, tzinfo=UTC)
    assert rec.closed is False
    assert rec.resolved_outcome is None
    assert rec.race_date == date(2026, 10, 4)
    assert rec.round is None
    assert "race_name_guess" not in rec.row()


def test_parse_market_resolution_and_question_fallback():
    won = pm.parse_market(
        _event(), _market(closed=True, outcomePrices='["1", "0"]', groupItemTitle=None)
    )
    lost = pm.parse_market(_event(), _market(closed=True, outcomePrices='["0", "1"]'))
    split = pm.parse_market(_event(), _market(closed=True, outcomePrices='["0.5", "0.5"]'))
    assert won.driver == "NOR"  # parsed from the question
    assert (won.resolved_outcome, lost.resolved_outcome, split.resolved_outcome) == (1, 0, None)


def test_parse_market_yes_token_follows_outcome_order():
    rec = pm.parse_market(_event(), _market(outcomes='["No", "Yes"]'))
    assert rec.yes_token_id == "222"


def test_season_from_question_when_slug_has_no_year():
    ev = _event(slug="f1-constructors-champion", title="F1 Constructors' Champion")
    ev["endDate"] = "2027-04-01T03:59:00Z"
    ev["markets"] = [_market(question="Will McLaren be the 2026 F1 Constructors' Champion?")]
    rec = pm.parse_market(ev, _market(groupItemTitle="McLaren"))
    assert rec.season == 2026
    assert rec.market_kind == "constructors_champion"
    assert rec.team == "McLaren"
    assert rec.driver == ""


def test_season_from_end_date_for_old_race_events():
    ev = _event(slug="italian-grand-prix-winner", title="Italian Grand Prix Winner")
    ev["endDate"] = "2024-09-01T12:00:00Z"
    rec = pm.parse_market(
        ev, _market(question="Will Charles Leclerc win the Italian Grand Prix?", groupItemTitle="")
    )
    assert rec.season == 2024
    assert rec.race_date == date(2024, 9, 1)
    assert rec.driver == "LEC"


CAL = [
    pm.CalendarRace(2025, 6, "Miami Grand Prix", "United States", "Miami", date(2025, 5, 4)),
    pm.CalendarRace(2025, 7, "Emilia Romagna Grand Prix", "Italy", "Imola", date(2025, 5, 18)),
    pm.CalendarRace(2025, 8, "Monaco Grand Prix", "Monaco", "Monaco", date(2025, 5, 25)),
    pm.CalendarRace(2025, 16, "Italian Grand Prix", "Italy", "Monza", date(2025, 9, 7)),
    pm.CalendarRace(2025, 21, "São Paulo Grand Prix", "Brazil", "São Paulo", date(2025, 11, 9)),
    pm.CalendarRace(2026, 7, "Barcelona Grand Prix", "Spain", "Barcelona", date(2026, 6, 14)),
    pm.CalendarRace(2026, 16, "Bahrain Grand Prix", "Bahrain", "Sakhir", date(2026, 10, 4)),
    pm.CalendarRace(
        2026, 17, "Singapore Grand Prix", "Singapore", "Marina Bay", date(2026, 10, 11)
    ),
]


@pytest.mark.parametrize(
    ("season", "name", "when", "rnd"),
    [
        (2026, "Bahrain Grand Prix", date(2026, 10, 4), 16),
        (2026, "Singapore Grand Prix", date(2026, 10, 11), 17),
        (2026, "Catalunya Grand Prix", date(2026, 6, 14), 7),  # Polymarket name != FastF1 name
        (2025, "Italy Grand Prix", date(2025, 5, 19), 7),  # 2025 "Italy" = Imola, not Monza
        (2025, "Italian Grand Prix", date(2025, 9, 8), 16),
        (2025, "Brazilian Grand Prix", date(2025, 11, 9), 21),
        (2025, "Miami Grand Prix", date(2025, 5, 4), 6),
        (2026, "Bahrain Grand Prix", date(2026, 4, 12), None),  # cancelled April race
        (2025, "Bahrain Grand Prix", None, None),
        (2024, "Bahrain Grand Prix", date(2024, 3, 2), None),  # season not in calendar
    ],
)
def test_race_round_for_market(season, name, when, rnd):
    assert pm.race_round_for_market(season, name, when, CAL) == rnd


def test_race_round_prefers_name_when_two_races_are_close():
    # an endDate a week after the race can sit between two back-to-back races
    assert pm.race_round_for_market(2025, "Monaco Grand Prix", date(2025, 5, 21), CAL) == 8
    assert pm.race_round_for_market(2025, "Italy Grand Prix", date(2025, 5, 21), CAL) == 7


def test_assign_rounds_marks_unmapped():
    ev_ok = _event()
    ev_bad = _event(slug="f1-bahrain-grand-prix-winner-2026-04-12")
    recs = [pm.parse_market(ev_ok, _market()), pm.parse_market(ev_bad, _market(id="2"))]
    mapped, unmapped = pm.assign_rounds(recs, CAL)
    assert mapped == 1
    assert unmapped == ["f1-bahrain-grand-prix-winner-2026-04-12"]
    assert [r.round for r in recs] == [16, None]


def _clob_transport(series: dict[int, float], max_window: int = 15 * 86_400, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params
        lo, hi = int(q["startTs"]), int(q["endTs"])
        if calls is not None:
            calls.append((lo, hi))
        if hi - lo > max_window:
            return httpx.Response(400, json={"error": "interval is too long"})
        hist = [{"t": t, "p": p} for t, p in sorted(series.items()) if lo <= t <= hi]
        return httpx.Response(200, json={"history": hist})

    return httpx.MockTransport(handler)


def test_fetch_price_history_walks_windows_and_dedupes():
    start = 1_700_000_000
    end = start + 40 * 86_400
    series = {start + h * 3600: round(h / 1000, 4) for h in range(0, 40 * 24 + 1)}
    calls: list[tuple[int, int]] = []
    client = pm.PolymarketClient(sleep_s=0, transport=_clob_transport(series, calls=calls))
    pts = pm.fetch_price_history("tok", start, end, client=client)
    assert pts == sorted(series.items())  # window edges overlap but every t appears once
    assert len(calls) == 3  # 40 days in 14-day windows
    assert all(hi - lo <= pm.MAX_WINDOW_S for lo, hi in calls)
    assert calls[0][1] == end  # walks backwards from the end


def test_fetch_price_history_stops_after_empty_windows_before_creation():
    start = 1_700_000_000
    end = start + 200 * 86_400
    first = end - 10 * 86_400  # data only in the last 10 days
    series = {t: 0.5 for t in range(first, end, 3600)}
    calls: list[tuple[int, int]] = []
    client = pm.PolymarketClient(sleep_s=0, transport=_clob_transport(series, calls=calls))
    pts = pm.fetch_price_history("tok", start, end, client=client)
    assert len(pts) == len(series)
    assert len(calls) == 3  # one window with data, then two empty ones


def test_client_retries_server_errors():
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=[{"id": "1", "slug": "x"}])

    client = pm.PolymarketClient(backoff_s=0, sleep_s=0, transport=httpx.MockTransport(handler))
    events = pm.discover_f1_events(False, client=client)
    assert [e["slug"] for e in events] == ["x"]
    assert attempts["n"] == 3


def test_discover_pages_until_short_page():
    pages = {0: [{"id": str(i), "slug": f"e{i}"} for i in range(2)], 2: [{"id": "2", "slug": "e2"}]}

    def handler(request):
        off = int(request.url.params["offset"])
        assert request.url.params["tag_slug"] == "f1"
        return httpx.Response(200, json=pages.get(off, []))

    client = pm.PolymarketClient(sleep_s=0, transport=httpx.MockTransport(handler))
    events = pm.discover_f1_events(True, client=client, page_size=2)
    assert [e["slug"] for e in events] == ["e0", "e1", "e2"]


def test_history_bounds_incremental_and_closed():
    created = datetime(2026, 9, 26, tzinfo=UTC)
    end = datetime(2026, 10, 11, tzinfo=UTC)
    now = datetime(2026, 10, 6, tzinfo=UTC)
    lo, hi = pm.history_bounds(created, end, False, None, now=now)
    assert hi == int(now.timestamp())
    assert lo == int(created.timestamp()) - 3600
    last = datetime(2026, 10, 1, tzinfo=UTC)
    lo, _ = pm.history_bounds(created, end, False, last, now=now)
    assert lo == int(last.timestamp()) + 1
    _, hi = pm.history_bounds(created, end, True, None, now=datetime(2027, 1, 1, tzinfo=UTC))
    assert hi == int(end.timestamp()) + 86_400


def test_json_encoded_fields_parse():
    assert pm._json_list('["Yes", "No"]') == ["Yes", "No"]
    assert pm._json_list(["a"]) == ["a"]
    assert pm._json_list("not json") == []
    assert pm._json_list(None) == []
    assert json.loads(_market()["clobTokenIds"])[0] == "111"


@pytest.mark.network
def test_gamma_live_drivers_champion_event():
    with pm.PolymarketClient() as client:
        data = client.get_json(f"{pm.GAMMA_URL}/events", {"slug": "2026-f1-drivers-champion"})
    assert data, "event not found"
    ev = data[0]
    recs = [pm.parse_market(ev, m) for m in ev["markets"]]
    assert {r.market_kind for r in recs} == {"season_champion"}
    assert {r.season for r in recs} == {2026}
    assert all(r.yes_token_id for r in recs)
    codes = {r.driver for r in recs}
    assert {"VER", "NOR", "PIA", "RUS"} <= codes
    assert pm.UNKNOWN not in codes
