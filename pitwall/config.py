from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Values come from env vars or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ClickHouse
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "pitwall"
    clickhouse_password: str = "pitwall"
    clickhouse_database: str = "pitwall"

    # DynamoDB
    dynamodb_endpoint_url: str | None = "http://localhost:8000"
    aws_region: str = "us-east-1"
    pitwall_ddb_table: str = "pitwall"

    # FastF1
    fastf1_cache_dir: Path = Path("./data/fastf1-cache")

    # Claude
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
