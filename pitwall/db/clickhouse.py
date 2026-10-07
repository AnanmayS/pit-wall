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


def iter_statements(sql: str):
    """Split a DDL file into statements. Statements end with ';' on their own line.

    Comments ("-- ...") are kept inside statements because ClickHouse accepts them.
    """
    buf: list[str] = []
    for line in sql.splitlines():
        buf.append(line)
        if line.strip().endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            buf = []
            # skip comment-only blocks
            if any(not ln.strip().startswith("--") and ln.strip() for ln in stmt.splitlines()):
                yield stmt
    tail = "\n".join(buf).strip()
    if tail and any(not ln.strip().startswith("--") and ln.strip() for ln in tail.splitlines()):
        yield tail.rstrip(";")


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
