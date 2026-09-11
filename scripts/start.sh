#!/bin/sh
# ============================================================================
# RazorGrowth AI — backend container entrypoint
#
# Startup sequence (fail-fast, no silent skips, no arbitrary sleeps):
#
#   1. Wait for PostgreSQL to accept connections (bounded retry loop against
#      the DATABASE_URL host/port — Compose's dependency healthcheck already
#      gates container start; this is defence in depth).
#   2. alembic upgrade head          — idempotent schema migration
#   3. optional: python -m backend.app.data.seed
#        (only when SEED_DEMO_DATA=true; the seed itself is idempotent via
#         deterministic natural keys)
#   4. exec uvicorn backend.app.main:app — the FastAPI application
#
# Any failure exits the container with a clear error so `docker compose up`
# surfaces the problem instead of serving a broken app.
# ============================================================================
set -e

echo "[entrypoint] RazorGrowth AI backend starting…"

# ------------------------------------------------------------------ #
# 1. Wait for the database (bounded — no infinite hang, no blind sleep)
# ------------------------------------------------------------------ #
if [ -z "${DATABASE_URL:-}" ]; then
    echo "[entrypoint] FATAL: DATABASE_URL is not set. Refusing to start." >&2
    exit 1
fi

# Extract host and port from DATABASE_URL (works for postgres:// and
# postgresql:// schemes). Defaults: host=db, port=5432.
DB_HOST="$(printf '%s' "$DATABASE_URL" | sed -E 's|^[a-zA-Z0-9+]+://([^:/@]+):([^@]+)@([^:/]+)(:[0-9]+)?.*|\3|')"
DB_PORT="$(printf '%s' "$DATABASE_URL" | sed -E 's|^[a-zA-Z0-9+]+://([^:/@]+):([^@]+)@([^:/]+)(:[0-9]+)?.*|\4|')"
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT#:}"
DB_PORT="${DB_PORT:-5432}"

ATTEMPT=0
MAX_ATTEMPTS="${DB_WAIT_ATTEMPTS:-30}"
echo "[entrypoint] Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT} …"
until python - "$DB_HOST" "$DB_PORT" <<'PY' 2>/dev/null
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
with socket.socket() as s:
    s.settimeout(2)
    sys.exit(0 if s.connect_ex((host, port)) == 0 else 1)
PY
do
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -ge "$MAX_ATTEMPTS" ]; then
        echo "[entrypoint] FATAL: PostgreSQL at ${DB_HOST}:${DB_PORT} not reachable after ${MAX_ATTEMPTS} attempts." >&2
        exit 1
    fi
    sleep 1
done
echo "[entrypoint] PostgreSQL is accepting connections."

# ------------------------------------------------------------------ #
# 2. Migrations — Alembic is the single source of truth for the schema
# ------------------------------------------------------------------ #
echo "[entrypoint] Applying Alembic migrations (alembic upgrade head)…"
alembic upgrade head
echo "[entrypoint] Migrations applied. Current revision:"
alembic current || true

# ------------------------------------------------------------------ #
# 3. Optional bootstrap seed (off by default; opt-in via SEED_DEMO_DATA)
#    python -m backend.app.data.seed is idempotent (deterministic UUIDs)
# ------------------------------------------------------------------ #
if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
    echo "[entrypoint] SEED_DEMO_DATA=true — seeding deterministic demo dataset…"
    python -m backend.app.data.seed
    echo "[entrypoint] Seed complete."
else
    echo "[entrypoint] SEED_DEMO_DATA not set to 'true' — skipping demo seed (signup creates its own workspace)."
fi

# ------------------------------------------------------------------ #
# 4. Start FastAPI (foreground so the container lifecycle is uvicorn's)
# ------------------------------------------------------------------ #
echo "[entrypoint] Starting uvicorn on 0.0.0.0:8001…"
exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8001
