"""Print a markdown summary of ingestion (rows per table, timings, totals) from ClickHouse.

Usage: uv run python benchmarks/ingest_report.py [SEASON]
"""

from __future__ import annotations

import sys

from pitwall.db.clickhouse import get_client
from pitwall.ingest.status import SESSION_TABLES, IngestStatus, collect_status


def _s(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def storage_rows(client, database: str) -> list[tuple[str, int, int, int]]:
    """(table, rows, compressed bytes, uncompressed bytes) of active parts per table."""
    return client.query(
        """
        SELECT table, sum(rows), sum(data_compressed_bytes), sum(data_uncompressed_bytes)
        FROM system.parts
        WHERE active AND database = {db:String}
        GROUP BY table ORDER BY sum(data_compressed_bytes) DESC
        """,
        parameters={"db": database},
    ).result_rows


def markdown(status: IngestStatus, storage: list[tuple[str, int, int, int]]) -> str:
    out: list[str] = []
    headers = ["session", *SESSION_TABLES, "fetch+transform s", "insert s", "total s"]
    out.append("| " + " | ".join(headers) + " |")
    out.append("|" + "|".join(["---"] + ["---:"] * (len(headers) - 1)) + "|")
    totals = dict.fromkeys(SESSION_TABLES, 0)
    load_total = insert_total = 0.0
    for s in status.sessions:
        for t in SESSION_TABLES:
            totals[t] += s.rows.get(t, 0)
        load_total += s.last_load_seconds or 0.0
        insert_total += s.last_insert_seconds or 0.0
        cells = [
            f"{s.season} R{s.round} {s.session_type}",
            *(f"{s.rows.get(t, 0):,}" for t in SESSION_TABLES),
            _s(s.last_load_seconds),
            _s(s.last_insert_seconds),
            _s(s.last_total_seconds),
        ]
        out.append("| " + " | ".join(cells) + " |")
    cells = [
        f"**total ({len(status.sessions)} sessions)**",
        *(f"**{totals[t]:,}**" for t in SESSION_TABLES),
        f"**{load_total:.1f}**",
        f"**{insert_total:.1f}**",
        f"**{load_total + insert_total:.1f}**",
    ]
    out.append("| " + " | ".join(cells) + " |")
    out.append("")
    out.append(f"- Total telemetry rows: {status.total_telemetry_rows:,}")
    out.append(
        f"- Seconds above are from the latest run of each session; all {status.total_runs} "
        f"recorded runs (re-ingests included) took {status.total_ingest_seconds:.1f} s."
    )
    if load_total + insert_total > 0:
        rate = totals["telemetry"] / (load_total + insert_total)
        out.append(f"- End-to-end throughput: {rate:,.0f} telemetry rows/s")
    if storage:
        out.append("")
        out.append("| table | rows (active parts) | compressed | uncompressed | ratio |")
        out.append("|---|---:|---:|---:|---:|")
        for table, rows, comp, raw in storage:
            ratio = f"{raw / comp:.1f}x" if comp else "-"
            out.append(
                f"| {table} | {rows:,} | {comp / 1e6:.1f} MB | {raw / 1e6:.1f} MB | {ratio} |"
            )
    return "\n".join(out)


def main() -> None:
    season = int(sys.argv[1]) if len(sys.argv) > 1 else None
    client = get_client()
    status = collect_status(client, season)
    print(markdown(status, storage_rows(client, client.database)))


if __name__ == "__main__":
    main()
