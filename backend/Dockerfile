# ============================================================================
# RazorGrowth AI — backend image
#
# Runs the FastAPI application, applies Alembic migrations on startup, and
# (optionally) seeds the deterministic demo dataset. See scripts/start.sh for
# the exact startup order.
#
# Build context MUST be the repository root (docker-compose.yml already
# sets it) so that backend/, migrations/, alembic.ini and requirements.txt
# are all available inside the image.
# ============================================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ---- System packages -------------------------------------------------------
# libpq5 is the PostgreSQL client library runtime required by psycopg2-binary
# wheels (pulled in for reliability across glibc versions); curl is used by
# the container healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# ---- Python dependencies ---------------------------------------------------
# requirements.txt lives at the repository root (build context root).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Application code ------------------------------------------------------
# alembic.ini + migrations/ are needed for startup migrations; backend/ holds
# the app itself. Copying explicit paths keeps the image lean and avoids
# shipping local .env secrets into the image.
COPY alembic.ini .
COPY migrations/ ./migrations/
COPY backend/ ./backend/
COPY scripts/start.sh ./scripts/start.sh

RUN chmod +x scripts/start.sh \
    && python -m compileall -q backend migrations

# Non-root runtime user
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8001/api/health || exit 1

ENTRYPOINT ["/app/scripts/start.sh"]
