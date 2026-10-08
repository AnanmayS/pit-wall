"""Our forecast next to Polymarket's prices, for the odds page."""

from __future__ import annotations

from typing import Any

import pandas as pd

from pitwall.db.clickhouse import get_client
from pitwall.odds import markets_store
from pitwall.odds.scoring import implied_probs

SKIP = {"PLACEHOLDER", "OTHER", "UNKNOWN", ""}


def _latest_forecast(
    client, season: int, kind: str
) -> tuple[dict[str, float], str | None, int | None]:
    df = client.query_df(
        "SELECT driver, round, probability, as_of FROM forecasts FINAL WHERE season={s:UInt16} AND kind={k:String} "
        "AND as_of = (SELECT max(as_of) FROM forecasts WHERE season={s:UInt16} AND kind={k:String})",
        parameters={"s": season, "k": kind},
    )
    if df.empty:
        return {}, None, None
    rnd = df["round"].dropna()
    return (
        {str(r.driver): float(r.probability) for r in df.itertuples()},
        str(df["as_of"].iloc[0]),
        int(rnd.iloc[0]) if not rnd.empty else None,
    )


def _market_now(
    client, season: int, kind: str, round: int | None = None
) -> tuple[dict[str, float], dict[str, float], str | None]:
    rows = [
        r
        for r in markets_store.latest_prices(client, season, kind, round=round)
        if r.get("driver") not in SKIP and r.get("resolved_outcome") is None
    ]
    if not rows:
        return {}, {}, None
    raw = {str(r["driver"]): float(r["price"]) for r in rows}
    probs = implied_probs(raw)["probs"]
    ts = max(r["ts"] for r in rows)
    return probs, raw, ts.isoformat(timespec="minutes")


def _market_history(client, season: int, drivers: list[str]) -> list[dict[str, Any]]:
    """Daily normalised title probability per driver from the champion markets."""
    if not drivers:
        return []
    df = client.query_df(
        """
        SELECT toDate(p.ts) AS day, m.driver AS driver, argMax(p.price, p.ts) AS price
        FROM pm_prices AS p
        INNER JOIN (SELECT market_id, driver FROM pm_markets FINAL
                    WHERE season={s:UInt16} AND market_kind='season_champion') AS m ON m.market_id = p.market_id
        GROUP BY day, driver ORDER BY day
        """,
        parameters={"s": season},
    )
    if df.empty:
        return []
    out = []
    for day, g in df.groupby("day", sort=True):
        raw = {str(r.driver): float(r.price) for r in g.itertuples() if str(r.driver) not in SKIP}
        probs = implied_probs(raw)["probs"] if raw else {}
        out.append({"date": str(pd.Timestamp(day).date())} | {d: probs.get(d) for d in drivers})
    return out


def market_comparison(season: int, client=None, top: int = 8) -> dict[str, Any]:
    client = client or get_client()
    ours_title, as_of, _ = _latest_forecast(client, season, "title")
    ours_next, _, next_round = _latest_forecast(client, season, "race_win")
    m_title, m_title_raw, m_title_ts = _market_now(client, season, "season_champion")
    m_next, m_next_raw, m_next_ts = (
        _market_now(client, season, "race_winner", next_round) if next_round else ({}, {}, None)
    )

    def rows(ours: dict[str, float], market: dict[str, float], raw: dict[str, float]) -> list[dict]:
        drivers = set(ours) | set(market)
        out = []
        for d in drivers:
            o, m = ours.get(d), market.get(d)
            out.append(
                {
                    "driver": d,
                    "ours": o,
                    "market": m,
                    "market_raw": raw.get(d),
                    "diff": (o - m) if o is not None and m is not None else None,
                }
            )
        out.sort(key=lambda r: -max(r["ours"] or 0.0, r["market"] or 0.0))
        return out

    title_rows = rows(ours_title, m_title, m_title_raw)
    top_codes = [r["driver"] for r in title_rows[:top]]
    ours_hist = client.query_df(
        "SELECT as_of, after_round, driver, probability FROM forecasts FINAL WHERE season={s:UInt16} AND kind='title' ORDER BY as_of",
        parameters={"s": season},
    )
    ours_points = []
    for as_of_ts, g in ours_hist.groupby("as_of", sort=True):
        ours_points.append(
            {
                "date": str(pd.Timestamp(as_of_ts).date()),
                "as_of": str(as_of_ts),
                "after_round": int(g["after_round"].iloc[0]),
            }
            | {
                str(r.driver): float(r.probability)
                for r in g.itertuples()
                if str(r.driver) in top_codes
            }
        )
    return {
        "season": season,
        "forecast_as_of": as_of,
        "market_name": "Polymarket",
        "title": {"market_as_of": m_title_ts, "rows": title_rows},
        "next_race": {
            "round": next_round,
            "market_as_of": m_next_ts,
            "rows": rows(ours_next, m_next, m_next_raw),
        },
        "history": {
            "series": top_codes,
            "market": _market_history(client, season, top_codes),
            "ours": ours_points,
        },
    }
