"""`pitwall odds ...`: Polymarket market discovery, price history ingest and listing."""

from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Annotated

import typer

odds_app = typer.Typer(help="Title Odds: Polymarket markets and prices.", no_args_is_help=True)
log = logging.getLogger("pitwall.odds")


def _logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("fastf1").setLevel(logging.WARNING)


def _csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


@odds_app.command("ingest-markets")
def ingest_markets_cmd(
    season: Annotated[int | None, typer.Option(help="Only events of this season.")] = None,
    include_closed: Annotated[
        bool, typer.Option("--include-closed", help="Also fetch closed (settled) events.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Discover Polymarket F1 events, parse their markets, map race events to rounds, store."""
    _logging(verbose)
    from pitwall.db.clickhouse import get_client
    from pitwall.odds import polymarket as pm
    from pitwall.odds.markets_store import upsert_markets

    t0 = time.perf_counter()
    with pm.PolymarketClient() as http:
        events = pm.discover_f1_events(None if include_closed else False, client=http)
    records = list(pm.iter_market_records(events))
    if season is not None:
        records = [r for r in records if r.season == season]
    ch = get_client()
    calendar = pm.load_calendar(ch, {r.season for r in records if r.market_kind in pm.RACE_KINDS})
    mapped, unmapped = pm.assign_rounds(records, calendar)
    n = upsert_markets(ch, records)

    events_by_kind: dict[str, set[str]] = {}
    for r in records:
        events_by_kind.setdefault(r.market_kind, set()).add(r.event_slug)
    markets_by_kind = Counter(r.market_kind for r in records)
    unknown = [r for r in records if r.driver == pm.UNKNOWN or r.team == pm.UNKNOWN]
    typer.echo(
        f"{len(events)} events fetched, {n} markets stored "
        f"({time.perf_counter() - t0:.1f}s, season={season or 'all'})"
    )
    for kind in pm.MARKET_KINDS:
        if kind in events_by_kind:
            typer.echo(
                f"  {kind:<22}{len(events_by_kind[kind]):>4} events {markets_by_kind[kind]:>6} markets"
            )
    typer.echo(f"race events mapped to a round: {mapped}, unmapped: {len(unmapped)}")
    for slug in unmapped:
        typer.echo(f"  unmapped: {slug}")
    if unknown:
        typer.echo(f"markets with an UNKNOWN driver/team: {len(unknown)}")
        for r in unknown[:20]:
            typer.echo(f"  {r.event_slug}: {r.question}")


@odds_app.command("ingest-prices")
def ingest_prices_cmd(
    season: Annotated[int | None, typer.Option(help="Only markets of this season.")] = None,
    kinds: Annotated[
        str, typer.Option(help="Comma-separated market kinds.")
    ] = "race_winner,season_champion",
    fidelity: Annotated[int, typer.Option(help="Minutes between price points.")] = 60,
    max_minutes: Annotated[
        float, typer.Option(help="Stop after this long and report what remains.")
    ] = 10.0,
    refresh_closed: Annotated[
        bool,
        typer.Option(help="Re-fetch closed markets that already have prices (normally skipped)."),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Fetch CLOB price history for stored markets, incrementally (only points newer than stored)."""
    _logging(verbose)
    from pitwall.db.clickhouse import get_client
    from pitwall.odds import polymarket as pm
    from pitwall.odds.markets_store import insert_prices, load_markets, max_ts_by_market

    ch = get_client()
    markets = [
        m
        for m in load_markets(ch, season, _csv(kinds))
        if m["yes_token_id"] and m["driver"] != pm.PLACEHOLDER and m["team"] != pm.PLACEHOLDER
    ]
    last = max_ts_by_market(ch, [m["market_id"] for m in markets])
    todo = [m for m in markets if refresh_closed or not (m["closed"] and m["market_id"] in last)]
    typer.echo(
        f"{len(markets)} markets ({kinds}, season={season or 'all'}); "
        f"{len(markets) - len(todo)} closed with prices already, {len(todo)} to fetch"
    )
    deadline = time.monotonic() + max_minutes * 60
    t0 = time.perf_counter()
    inserted = done = 0
    with pm.PolymarketClient() as http:
        for m in todo:
            if time.monotonic() > deadline:
                break
            lo, hi = pm.history_bounds(
                m["created_at"], m["end_date"], m["closed"], last.get(m["market_id"])
            )
            try:
                pts = pm.fetch_price_history(m["yes_token_id"], lo, hi, fidelity, client=http)
            except Exception as e:  # keep going; the market is retried on the next run
                log.warning("prices for %s (%s) failed: %s", m["market_id"], m["question"], e)
                continue
            inserted += insert_prices(
                ch,
                m["market_id"],
                pts,
                fidelity,
                last_ts=last.get(m["market_id"]),
                known_last=True,
            )
            done += 1
            if done % 50 == 0:
                log.info(
                    "%d/%d markets, %d points, %d calls", done, len(todo), inserted, http.calls
                )
        calls = http.calls
    remaining = len(todo) - done
    typer.echo(
        f"fetched {done} markets, inserted {inserted:,} price points, {calls} CLOB calls, "
        f"{time.perf_counter() - t0:.0f}s"
    )
    if remaining:
        typer.echo(f"stopped at the time budget: {remaining} markets remain (re-run to continue)")


@odds_app.command("markets")
def markets_cmd(
    season: Annotated[int | None, typer.Option(help="Only this season.")] = None,
    kind: Annotated[str | None, typer.Option(help="Only this market kind.")] = None,
) -> None:
    """List stored Polymarket events: kind, round, markets, price points, favourite."""
    from pitwall.db.clickhouse import get_client

    ch = get_client()
    cond = []
    params: dict[str, object] = {}
    if season is not None:
        cond.append("m.season = {season:UInt16}")
        params["season"] = season
    if kind:
        cond.append("m.market_kind = {kind:String}")
        params["kind"] = kind
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    rows = ch.query(
        f"""
        SELECT m.season, m.market_kind, m.event_slug, any(m.round) AS rnd, count() AS markets,
               min(m.closed) AS all_closed, sum(p.n) AS points,
               argMax(if(m.driver != '', m.driver, m.team), p.last_price) AS fav,
               max(p.last_price) AS fav_price,
               anyIf(if(m.driver != '', m.driver, m.team), m.resolved_outcome = 1) AS won
        FROM (SELECT * FROM pm_markets FINAL) AS m
        LEFT JOIN (
            SELECT market_id, count() AS n, argMax(price, ts) AS last_price
            FROM pm_prices GROUP BY market_id
        ) AS p ON p.market_id = m.market_id
        {where}
        GROUP BY m.season, m.market_kind, m.event_slug
        ORDER BY m.season, m.market_kind, rnd, m.event_slug
        """,
        parameters=params,
    ).result_rows
    header = (
        f"{'season':<7}{'kind':<23}{'rnd':>4}  {'event':<58}{'mkts':>5}{'points':>9}"
        f"  {'last fav':<14}{'won':<8}"
    )
    typer.echo(header)
    typer.echo("-" * len(header))
    for s, k, slug, rnd, n, all_closed, pts, fav, fav_p, won in rows:
        fav_s = f"{fav} {fav_p:.2f}" if pts else "-"
        typer.echo(
            f"{s:<7}{k:<23}{'' if rnd is None else rnd:>4}  {slug[:57]:<58}{n:>5}{pts or 0:>9,}"
            f"  {fav_s:<14}{won or ('-' if all_closed else 'open'):<8}"
        )
    typer.echo(f"{len(rows)} events")
