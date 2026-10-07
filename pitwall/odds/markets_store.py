"""ClickHouse storage for Polymarket markets (pm_markets) and Yes-price history (pm_prices)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from clickhouse_connect.driver.client import Client

from pitwall.odds.polymarket import MarketRecord

MARKET_COLUMNS = [
    "market_id",
    "condition_id",
    "event_slug",
    "event_title",
    "question",
    "market_kind",
    "season",
    "round",
    "driver",
    "team",
    "yes_token_id",
    "created_at",
    "end_date",
    "closed",
    "resolved_outcome",
    "fetched_at",
]
PRICE_COLUMNS = ["market_id", "ts", "price", "fidelity_min"]


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def upsert_markets(client: Client, records: Iterable[MarketRecord]) -> int:
    """Insert (or replace, by market_id with the newest fetched_at) market rows."""
    now = datetime.now(UTC).replace(microsecond=0)
    rows: list[list[Any]] = []
    for rec in records:
        d = rec.row()
        d["created_at"] = _utc(d["created_at"])
        d["end_date"] = _utc(d["end_date"])
        d["fetched_at"] = now
        rows.append([d[c] for c in MARKET_COLUMNS])
    if rows:
        client.insert("pm_markets", rows, column_names=MARKET_COLUMNS)
    return len(rows)


def max_ts_by_market(
    client: Client, market_ids: Sequence[str] | None = None
) -> dict[str, datetime]:
    """Latest stored price timestamp (UTC) per market."""
    where = "WHERE market_id IN {ids:Array(String)}" if market_ids is not None else ""
    if market_ids is not None and not market_ids:
        return {}
    rows = client.query(
        f"SELECT market_id, max(ts) FROM pm_prices {where} GROUP BY market_id",
        parameters={"ids": list(market_ids or [])},
    ).result_rows
    return {str(m): _utc(ts) for m, ts in rows}


def insert_prices(
    client: Client,
    market_id: str,
    points: Iterable[tuple[int, float]],
    fidelity_min: int = 60,
    *,
    last_ts: datetime | None = None,
    known_last: bool = False,
) -> int:
    """Insert (unix seconds, price) points newer than what is stored for the market.

    Pass `last_ts` with known_last=True to skip the max(ts) lookup (bulk ingest already has it).
    """
    if not known_last:
        last_ts = max_ts_by_market(client, [market_id]).get(market_id)
    cutoff = int(last_ts.timestamp()) if last_ts is not None else None
    rows = [
        [market_id, datetime.fromtimestamp(t, UTC), float(p), int(fidelity_min)]
        for t, p in points
        if cutoff is None or t > cutoff
    ]
    if rows:
        client.insert("pm_prices", rows, column_names=PRICE_COLUMNS)
    return len(rows)


def load_markets(
    client: Client,
    season: int | None = None,
    kinds: Sequence[str] | None = None,
    *,
    closed: bool | None = None,
) -> list[dict[str, Any]]:
    """Stored markets (deduplicated with FINAL) as dicts, ordered by event then market."""
    cond: list[str] = []
    params: dict[str, Any] = {}
    if season is not None:
        cond.append("season = {season:UInt16}")
        params["season"] = int(season)
    if kinds:
        cond.append("market_kind IN {kinds:Array(String)}")
        params["kinds"] = list(kinds)
    if closed is not None:
        cond.append("closed = {closed:Bool}")
        params["closed"] = closed
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    res = client.query(
        f"SELECT {', '.join(MARKET_COLUMNS)} FROM pm_markets FINAL {where} "
        "ORDER BY season, market_kind, event_slug, market_id",
        parameters=params,
    )
    out = []
    for row in res.result_rows:
        d = dict(zip(res.column_names, row, strict=True))
        d["created_at"] = _utc(d["created_at"])
        d["end_date"] = _utc(d["end_date"])
        out.append(d)
    return out


def latest_prices(
    client: Client,
    season: int,
    kind: str,
    *,
    as_of: datetime | None = None,
    round: int | None = None,
) -> list[dict[str, Any]]:
    """Last Yes price (at or before `as_of`, default now) of every market of a season/kind.

    One dict per market: market_id, event_slug, round, driver, team, price, ts, resolved_outcome.
    Markets with no stored price are omitted.
    """
    params: dict[str, Any] = {"season": int(season), "kind": kind}
    cond = ["m.season = {season:UInt16}", "m.market_kind = {kind:String}"]
    ts_cond = ""
    if as_of is not None:
        ts_cond = "WHERE ts <= {as_of:DateTime('UTC')}"
        params["as_of"] = _utc(as_of)
    if round is not None:
        cond.append("m.round = {round:UInt8}")
        params["round"] = int(round)
    res = client.query(
        f"""
        SELECT m.market_id AS market_id, m.event_slug AS event_slug, m.round AS round,
               m.driver AS driver, m.team AS team, p.last_price AS price, p.last_ts AS ts,
               m.resolved_outcome AS resolved_outcome
        FROM (SELECT * FROM pm_markets FINAL) AS m
        INNER JOIN (
            SELECT market_id, argMax(price, ts) AS last_price, max(ts) AS last_ts
            FROM pm_prices {ts_cond} GROUP BY market_id
        ) AS p ON p.market_id = m.market_id
        WHERE {" AND ".join(cond)}
        ORDER BY event_slug, price DESC
        """,
        parameters=params,
    )
    out = []
    for row in res.result_rows:
        d = dict(zip(res.column_names, row, strict=True))
        d["price"] = float(d["price"])
        d["ts"] = _utc(d["ts"])
        out.append(d)
    return out


def price_at(client: Client, market_id: str, ts: datetime) -> float | None:
    """Last stored Yes price of a market at or before `ts` (None if there is none)."""
    rows = client.query(
        "SELECT argMax(price, ts), count() FROM pm_prices "
        "WHERE market_id = {m:String} AND ts <= {ts:DateTime('UTC')}",
        parameters={"m": market_id, "ts": _utc(ts)},
    ).result_rows
    if not rows or rows[0][1] == 0:
        return None
    return float(rows[0][0])
