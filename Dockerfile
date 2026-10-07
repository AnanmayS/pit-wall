# API image: FastAPI + simulator. Build: docker build -t pitwall-api . ; Run: docker run -p 8080:8080 --env-file .env pitwall-api
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY pitwall ./pitwall
RUN uv sync --frozen --no-dev
EXPOSE 8080
CMD ["uv", "run", "--no-sync", "uvicorn", "pitwall.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
