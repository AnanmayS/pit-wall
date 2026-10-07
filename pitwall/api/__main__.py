"""Start the API server: `uv run python -m pitwall.api [--host H] [--port P] [--reload]`."""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Pit Wall API")
    parser.add_argument("--host", default="127.0.0.1")
    # 8000 is used by DynamoDB Local in docker compose
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    args = parser.parse_args()
    uvicorn.run("pitwall.api.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
