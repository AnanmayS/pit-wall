"""Print a markdown summary of stored Polymarket data: markets, price points, coverage, round mapping.

Usage: uv run python benchmarks/polymarket_report.py
"""

from __future__ import annotations

from pitwall.db.clickhouse import get_client

RACE_KINDS = ("race_winner", "race_podium", "race_pole")


def _table(headers: list[str], rows: list[list[object]], align: str = "") -> str:
    align = align or "l" + "r" * (len(headers) - 1)
    out = ["| " + " | ".join(headers) + " |"]
    out.append("|" + "|".join("---:" if a == "r" else "---" for a in align) + "|")
    for r in rows:
        out.append("| " + " | ".join("-" if v is None else str(v) for v in r) + " |")
    return "\n".join(out)


def _fmt_ts(ts) -> str | None:
    return None if ts is None else ts.strftime("%Y-%m-%d %H:%M")


def main() -> None:
    ch = get_client()
    parts: list[str] = ["# Polymarket data", ""]

    rows = ch.query(
        """
        SELECT m.season, m.market_kind, uniqExact(m.event_slug) AS events, count() AS markets,
               countIf(m.closed) AS closed, countIf(p.n > 0) AS with_prices,
               sum(p.n) AS points,
               if(countIf(p.n > 0) = 0, NULL, minIf(p.first_ts, p.n > 0)) AS first_ts,
               if(countIf(p.n > 0) = 0, NULL, maxIf(p.last_ts, p.n > 0)) AS last_ts
        FROM (SELECT * FROM pm_markets FINAL) AS m
        LEFT JOIN (
            SELECT market_id, count() AS n, min(ts) AS first_ts, max(ts) AS last_ts
            FROM pm_prices GROUP BY market_id
        ) AS p ON p.market_id = m.market_id
        GROUP BY m.season, m.market_kind
        ORDER BY m.season, m.market_kind
        """
    ).result_rows
    parts += ["## Markets and price points by season and kind", ""]
    parts.append(
        _table(
            [
                "season",
                "kind",
                "events",
                "markets",
                "closed",
                "with prices",
                "price points",
                "earliest",
                "latest",
            ],
            [
                [s, k, e, f"{m:,}", f"{c:,}", f"{w:,}", f"{p:,}", _fmt_ts(a), _fmt_ts(b)]
                for s, k, e, m, c, w, p, a, b in rows
            ],
            "llrrrrrll",
        )
    )

    tot_markets, tot_points, first, last, markets_with = ch.query(
        """
        SELECT (SELECT count() FROM pm_markets FINAL), count(), min(ts), max(ts),
               uniqExact(market_id)
        FROM pm_prices
        """
    ).result_rows[0]
    parts += [
        "",
        f"Total: {tot_markets:,} markets stored, {tot_points:,} price points across "
        f"{markets_with:,} markets, {_fmt_ts(first) if tot_points else '-'} .. "
        f"{_fmt_ts(last) if tot_points else '-'} UTC.",
        "",
    ]

    rows = ch.query(
        """
        SELECT season, market_kind,
               uniqExactIf(event_slug, round IS NOT NULL) AS mapped,
               uniqExactIf(event_slug, round IS NULL) AS unmapped,
               arrayStringConcat(groupUniqArrayIf(event_slug, round IS NULL), ', ') AS which
        FROM pm_markets FINAL
        WHERE market_kind IN {kinds:Array(String)}
        GROUP BY season, market_kind
        ORDER BY season, market_kind
        """,
        parameters={"kinds": list(RACE_KINDS)},
    ).result_rows
    parts += ["## Race events mapped to a calendar round", ""]
    parts.append(
        _table(
            ["season", "kind", "mapped", "unmapped", "unmapped events"],
            [[s, k, m, u, w or ""] for s, k, m, u, w in rows],
            "llrrl",
        )
    )

    rows = ch.query(
        """
        SELECT season, uniqExact(event_slug) AS events,
               uniqExactIf(event_slug, closed) AS closed_events,
               countIf(resolved_outcome = 1) AS winners_known
        FROM pm_markets FINAL
        WHERE market_kind = 'race_winner' AND round IS NOT NULL
        GROUP BY season ORDER BY season
        """
    ).result_rows
    parts += ["", "## Race-winner backtest coverage (mapped events)", ""]
    parts.append(
        _table(
            ["season", "events", "closed", "resolved Yes markets"],
            [list(r) for r in rows],
        )
    )

    rows = ch.query(
        """
        SELECT driver, count() FROM pm_markets FINAL
        WHERE driver IN ('UNKNOWN', 'PLACEHOLDER', 'OTHER') GROUP BY driver ORDER BY driver
        """
    ).result_rows
    parts += ["", "Special driver codes: " + ", ".join(f"{d} {n}" for d, n in rows) + "."]
    print("\n".join(parts))


if __name__ == "__main__":
    main()
