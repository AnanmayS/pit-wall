"""Round-trip synthetic Polymarket rows through ClickHouse (needs `docker compose up`).

Uses season 1999 and market ids prefixed `it1999-` so it never touches real data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pitwall.db.clickhouse import get_client, migrate
from pitwall.odds.markets_store import (
    insert_prices,
    latest_prices,
    load_markets,
    max_ts_by_market,
    price_at,
    upsert_markets,
)
from pitwall.odds.polymarket import MarketRecord
from pitwall.odds.scoring import implied_probs

pytestmark = pytest.mark.integration

SEASON = 1999
PREFIX = "it1999-"
T0 = datetime(1999, 3, 1, tzinfo=UTC)


@pytest.fixture()
def client():
    c = get_client()
    migrate(c)
    yield c
    c.command(f"DELETE FROM pm_prices WHERE startsWith(market_id, '{PREFIX}')")
    c.command(f"DELETE FROM pm_markets WHERE season = {SEASON}")


def _rec(i: int, driver: str, *, closed=False, outcome=None, round=1) -> MarketRecord:
    return MarketRecord(
        market_id=f"{PREFIX}{i}",
        condition_id=f"0x{i}",
        event_slug="f1-test-grand-prix-winner-1999-03-07",
        event_title="Test Grand Prix: Driver Winner",
        question=f"Will {driver} win the 1999 F1 Test Grand Prix?",
        market_kind="race_winner",
        season=SEASON,
        round=round,
        driver=driver,
        team="",
        yes_token_id=f"tok{i}",
        created_at=T0,
        end_date=T0 + timedelta(days=7),
        closed=closed,
        resolved_outcome=outcome,
    )


def test_markets_and_prices_round_trip(client):
    recs = [_rec(1, "VER"), _rec(2, "NOR"), _rec(3, "OTHER", round=None)]
    assert upsert_markets(client, recs) == 3
    # re-upsert with the market settled: FINAL keeps one row per market_id, the newest
    recs[0] = _rec(1, "VER", closed=True, outcome=1)
    upsert_markets(client, recs[:1])

    stored = load_markets(client, SEASON, ["race_winner"])
    assert [m["market_id"] for m in stored] == [f"{PREFIX}{i}" for i in (1, 2, 3)]
    by_id = {m["market_id"]: m for m in stored}
    assert by_id[f"{PREFIX}1"]["closed"] is True
    assert by_id[f"{PREFIX}1"]["resolved_outcome"] == 1
    assert by_id[f"{PREFIX}2"]["resolved_outcome"] is None
    assert by_id[f"{PREFIX}3"]["round"] is None
    assert by_id[f"{PREFIX}2"]["created_at"] == T0

    base = int(T0.timestamp())
    pts1 = [(base + h * 3600, 0.40 + h / 100) for h in range(5)]
    pts2 = [(base + h * 3600, 0.30) for h in range(5)]
    assert insert_prices(client, f"{PREFIX}1", pts1, 60) == 5
    assert insert_prices(client, f"{PREFIX}2", pts2, 60) == 5
    # incremental: only points after the stored max(ts) are inserted
    more = [*pts1, (base + 5 * 3600, 0.50)]
    assert insert_prices(client, f"{PREFIX}1", more, 60) == 1

    last = max_ts_by_market(client, [f"{PREFIX}1", f"{PREFIX}2", f"{PREFIX}3"])
    assert last == {
        f"{PREFIX}1": T0 + timedelta(hours=5),
        f"{PREFIX}2": T0 + timedelta(hours=4),
    }

    assert price_at(client, f"{PREFIX}1", T0 + timedelta(hours=2, minutes=30)) == pytest.approx(
        0.42
    )
    assert price_at(client, f"{PREFIX}1", T0 - timedelta(hours=1)) is None

    latest = latest_prices(client, SEASON, "race_winner")
    assert {d["driver"]: round(d["price"], 4) for d in latest} == {"VER": 0.5, "NOR": 0.3}
    as_of = latest_prices(client, SEASON, "race_winner", as_of=T0 + timedelta(hours=1), round=1)
    probs = implied_probs({d["driver"]: d["price"] for d in as_of})["probs"]
    assert probs["VER"] == pytest.approx(0.41 / 0.71, rel=1e-5)
