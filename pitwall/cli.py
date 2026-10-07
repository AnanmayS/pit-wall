"""Command line entry point: `pitwall db ...` and `pitwall ingest ...`."""

from __future__ import annotations

import logging
from typing import Annotated

import typer

app = typer.Typer(help="Pit Wall: F1 telemetry, simulation and odds.", no_args_is_help=True)
db_app = typer.Typer(help="ClickHouse schema management.", no_args_is_help=True)
ingest_app = typer.Typer(help="Load FastF1 sessions into ClickHouse.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    import fastf1

    fastf1.set_log_level("WARNING")  # FastF1's INFO output is very chatty


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply pitwall/db/ddl.sql (idempotent)."""
    from pitwall.db.clickhouse import migrate

    for stmt in migrate():
        typer.echo(f"ok  {stmt}")


@ingest_app.command("session")
def ingest_session_cmd(
    season: int,
    round: int,
    session_type: Annotated[str, typer.Argument(help="FP1, FP2, FP3, Q, SQ, S or R")],
    telemetry: Annotated[bool, typer.Option(help="Also ingest per-lap telemetry.")] = True,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Ingest one session, e.g. `pitwall ingest session 2025 1 R`."""
    _setup_logging(verbose)
    from pitwall.ingest.load import ingest_session

    result = ingest_session(season, round, session_type, telemetry=telemetry)
    typer.echo(
        f"{result.label}: {sum(result.rows.values()):,} rows in {result.total_seconds:.1f}s "
        f"(fetch {result.fetch_seconds:.1f}s, transform {result.transform_seconds:.1f}s, "
        f"insert {sum(result.insert_seconds.values()):.1f}s)"
    )
    for table, n in result.rows.items():
        typer.echo(f"  {table:<16}{n:>10,}")
    tel = result.notes.get("telemetry")
    if tel:
        typer.echo(
            f"  telemetry laps: {tel['laps_ok']} ok, {tel['laps_skipped']} skipped "
            f"of {tel['laps_total']}"
        )


@ingest_app.command("season")
def ingest_season_cmd(
    season: int,
    sessions: Annotated[
        str, typer.Option(help="Comma-separated session types, e.g. R,Q,S,SQ")
    ] = "R,Q,S,SQ",
    telemetry: Annotated[bool, typer.Option(help="Also ingest per-lap telemetry.")] = True,
    skip_existing: Annotated[
        bool, typer.Option(help="Skip sessions already present in the sessions table.")
    ] = True,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Ingest every completed session of a season (sequentially)."""
    _setup_logging(verbose)
    from pitwall.ingest.load import ingest_season

    types = [s.strip().upper() for s in sessions.split(",") if s.strip()]
    results = ingest_season(season, types, telemetry=telemetry, skip_existing=skip_existing)
    ok = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]
    typer.echo(
        f"ingested {len(ok)} sessions, {sum(sum(r.rows.values()) for r in ok):,} rows, "
        f"{sum(r.total_seconds for r in ok):.1f}s"
    )
    for r in failed:
        typer.echo(f"FAILED {r.label}: {r.error}", err=True)
    if failed:
        raise typer.Exit(code=1)


@ingest_app.command("status")
def ingest_status_cmd(
    season: Annotated[int | None, typer.Argument(help="Limit to one season.")] = None,
) -> None:
    """Show ingested sessions, row counts per table and ingest timings."""
    from pitwall.db.clickhouse import get_client
    from pitwall.ingest.status import collect_status, status_text

    typer.echo(status_text(collect_status(get_client(), season)))


if __name__ == "__main__":
    app()
