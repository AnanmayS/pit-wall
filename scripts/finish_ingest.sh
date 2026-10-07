#!/usr/bin/env bash
# Re-run season ingests until every session is present, sleeping between attempts to respect
# FastF1's 500 calls/hour limit. Usage: scripts/finish_ingest.sh
set -u
cd "$(dirname "$0")/.."
need() { uv run python - "$1" <<'PY'
import sys
from pitwall.db.clickhouse import get_client
from pitwall.ingest.source import season_sessions
season = int(sys.argv[1])
have = {(r[0], r[1]) for r in get_client().query("SELECT round, session_type FROM sessions FINAL WHERE season=%d" % season).result_rows}
want = {(rnd, st) for rnd, st in season_sessions(season)}
print(len(want - have))
PY
}
for attempt in $(seq 1 12); do
  missing=$(need 2025)
  echo "$(date '+%H:%M:%S') 2025 missing sessions: $missing"
  [ "$missing" = "0" ] && break
  uv run pitwall ingest season 2025 || true
  [ "$(need 2025)" = "0" ] && break
  echo "$(date '+%H:%M:%S') sleeping 20 min for the FastF1 rate-limit window"; sleep 1200
done
for attempt in $(seq 1 8); do
  missing=$(need 2026)
  echo "$(date '+%H:%M:%S') 2026 missing sessions: $missing"
  [ "$missing" = "0" ] && break
  uv run pitwall ingest season 2026 --no-telemetry || true
  [ "$(need 2026)" = "0" ] && break
  echo "$(date '+%H:%M:%S') sleeping 20 min"; sleep 1200
done
echo "INGEST CHAIN DONE"
