"""ClickHouse client helpers and schema migration."""

from __future__ import annotations

from pathlib import Path

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from pitwall.config import get_settings

DDL_PATH = Path(__file__).with_name("ddl.sql")


def get_client(database: str | None = None) -> Client:
    s = get_settings()
    return clickhouse_connect.get_client(
        host=s.clickhouse_host,
        port=s.clickhouse_port,
        username=s.clickhouse_user,
        password=s.clickhouse_password,
        database=database or s.clickhouse_database,
        # fail fast locally; retries are handled by the ingest loop
        connect_timeout=5,
        send_receive_timeout=300,
    )


def _strip_leading_comments(stmt: str) -> str:
    lines = stmt.strip().splitlines()
    while lines and (not lines[0].strip() or lines[0].strip().startswith("--")):
        lines.pop(0)
    return "\n".join(lines).strip()


def iter_statements(sql: str):
    """Split a DDL file into statements. A statement ends with ';' at the end of a line.

    Leading comment lines are stripped; inline comments inside a statement are kept
    (ClickHouse accepts them). Comment-only blocks are skipped.
    """
    buf: list[str] = []
    for line in sql.splitlines():
        buf.append(line)
        if line.strip().endswith(";"):
            stmt = _strip_leading_comments("\n".join(buf)).rstrip(";").strip()
            buf = []
            if stmt:
                yield stmt
    tail = _strip_leading_comments("\n".join(buf)).rstrip(";").strip()
    if tail:
        yield tail


def migrate(client: Client | None = None) -> list[str]:
    """Apply ddl.sql (all statements are idempotent: CREATE ... IF NOT EXISTS)."""
    s = get_settings()
    # the database may not exist yet; connect to `default` to create it
    boot = clickhouse_connect.get_client(
        host=s.clickhouse_host,
        port=s.clickhouse_port,
        username=s.clickhouse_user,
        password=s.clickhouse_password,
    )
    boot.command(f"CREATE DATABASE IF NOT EXISTS {s.clickhouse_database}")
    client = client or get_client()
    applied: list[str] = []
    for stmt in iter_statements(DDL_PATH.read_text()):
        client.command(stmt)
        applied.append(stmt.splitlines()[0][:80])
    return applied
