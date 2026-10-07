.PHONY: setup up down test lint ingest-season bench

setup:            ## create venv + install (uv)
	uv sync --extra dev

up:               ## start ClickHouse + DynamoDB Local
	docker compose up -d --wait

down:
	docker compose down

test:             ## unit tests (no services needed)
	uv run pytest -q

test-all:         ## unit + integration (needs `make up`)
	uv run pytest -q -m "not network"

lint:
	uv run ruff check . && uv run ruff format --check .

fmt:
	uv run ruff format . && uv run ruff check --fix .

migrate:          ## apply ClickHouse DDL
	uv run pitwall db migrate

ingest-season:    ## e.g. make ingest-season SEASON=2025
	uv run pitwall ingest season $(SEASON)
