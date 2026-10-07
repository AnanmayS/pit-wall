"""Read-side summaries of what has been ingested (used by `pitwall ingest status` and benchmarks)."""

from __future__ import annotations

from dataclasses import dataclass, field

from clickhouse_connect.driver.client import Client

# Per-session tables shown in the status table; ReplacingMergeTree tables are counted with FINAL.
SESSION_TABLES = (
    "laps",
    "telemetry",
    "stints",
    "pit_stops",
    "weather",
    "track_status",
    "race_control",
    "results",
)
PLAIN_MERGETREE = {"telemetry"}

SessionKey = tuple[int, int, str]


@dataclass
class SessionStatus:
    season: int
    round: int
    session_type: str
    event_name: str
    rows: dict[str, int] = field(default_factory=dict)
    last_load_seconds: float | None = None  # fetch + transform of the latest run
    last_insert_seconds: float | None = None  # sum over tables of the latest run
    runs: int = 0

    @property
    def last_total_seconds(self) -> float | None:
        if self.last_load_seconds is None or self.last_insert_seconds is None:
            return None
        return self.last_load_seconds + self.last_insert_seconds


@dataclass
class IngestStatus:
    sessions: list[SessionStatus]
    total_telemetry_rows: int
    total_ingest_seconds: float  # every recorded run, re-ingests included
    total_runs: int


def _where(season: int | None) -> str:
    return f"WHERE season = {int(season)}" if season is not None else ""


def collect_status(client: Client, season: int | None = None) -> IngestStatus:
    """Sessions present in ClickHouse with per-table row counts and ingest timings."""
    where = _where(season)
    sessions: dict[SessionKey, SessionStatus] = {}
    for s, r, st, name in client.query(
        f"SELECT season, round, session_type, event_name FROM sessions FINAL {where} "
        "ORDER BY season, round, session_type"
    ).result_rows:
        sessions[(int(s), int(r), str(st))] = SessionStatus(int(s), int(r), str(st), str(name))

    for table in SESSION_TABLES:
        final = "" if table in PLAIN_MERGETREE else "FINAL"
        for s, r, st, n in client.query(
            f"SELECT season, round, session_type, count() FROM {table} {final} {where} "
            "GROUP BY season, round, session_type"
        ).result_rows:
            key = (int(s), int(r), str(st))
            if key in sessions:
                sessions[key].rows[table] = int(n)

    # ingest_runs: load_seconds is repeated on every table row of a run, insert_seconds is per table.
    runs = client.query(
        f"""
        SELECT season, round, session_type, started_at,
               any(load_seconds) AS load_s, sum(insert_seconds) AS insert_s
        FROM ingest_runs {where}
        GROUP BY season, round, session_type, started_at
        ORDER BY started_at
        """
    ).result_rows
    total_seconds = 0.0
    for s, r, st, _started, load_s, insert_s in runs:
        total_seconds += float(load_s) + float(insert_s)
        key = (int(s), int(r), str(st))
        if key in sessions:  # rows are ordered by started_at, so the last one wins
            sessions[key].last_load_seconds = float(load_s)
            sessions[key].last_insert_seconds = float(insert_s)
            sessions[key].runs += 1

    total_tel = int(client.command(f"SELECT count() FROM telemetry {where}"))
    return IngestStatus(
        sessions=list(sessions.values()),
        total_telemetry_rows=total_tel,
        total_ingest_seconds=total_seconds,
        total_runs=len(runs),
    )


def format_table(headers: list[str], rows: list[list[str]], left: int = 1) -> str:
    """Plain fixed-width text table: the first `left` columns left-aligned, the rest right."""
    widths = [
        max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)
    ]

    def fmt(cells: list[str]) -> str:
        return "  ".join(
            c.ljust(w) if i < left else c.rjust(w)
            for i, (c, w) in enumerate(zip(cells, widths, strict=True))
        )

    lines = [fmt(headers), "  ".join("-" * w for w in widths)]
    lines += [fmt(r) for r in rows]
    return "\n".join(lines)


def _fmt_s(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def status_text(status: IngestStatus) -> str:
    """Human-readable status report."""
    if not status.sessions:
        return "No sessions ingested."
    headers = ["session", "event", *SESSION_TABLES, "load_s", "insert_s", "total_s"]
    rows = []
    for s in status.sessions:
        rows.append(
            [
                f"{s.season} R{s.round:02d} {s.session_type}",
                s.event_name,
                *(f"{s.rows.get(t, 0):,}" for t in SESSION_TABLES),
                _fmt_s(s.last_load_seconds),
                _fmt_s(s.last_insert_seconds),
                _fmt_s(s.last_total_seconds),
            ]
        )
    summary = (
        f"\nsessions: {len(status.sessions)}"
        f"\ntotal telemetry rows: {status.total_telemetry_rows:,}"
        f"\ntotal ingest seconds (all {status.total_runs} recorded runs): "
        f"{status.total_ingest_seconds:.1f}"
    )
    return format_table(headers, rows, left=2) + summary
