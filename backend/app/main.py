"""
RazorGrowth AI — FastAPI application entry point.

Run from the project root:
    uvicorn backend.app.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging, get_logger
from backend.app.core.errors import unhandled_exception_handler

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database connection pool at startup."""
    settings = get_settings()
    configure_logging("DEBUG" if settings.APP_ENV == "development" else "INFO")
    log.info("Starting RazorGrowth AI [%s]", settings.APP_ENV)

    from backend.app.db.engine import build_engine
    from backend.app.db.session import init_db

    engine = build_engine(
        settings.DATABASE_URL,
        echo=(settings.APP_ENV == "development"),
    )
    init_db(engine)
    log.info("Database connection pool initialised.")
    yield
    log.info("Shutting down.")


app = FastAPI(
    title="RazorGrowth AI",
    version="0.2.0",
    description="AI Growth & Agentic Commerce platform for Razorpay merchants.",
    lifespan=lifespan,
)

# ------------------------------------------------------------------ #
# Routers
# ------------------------------------------------------------------ #
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.opportunities import router as opportunities_router
from backend.app.api.routes.merchants import router as merchants_router
from backend.app.api.routes.products import router as products_router
from backend.app.api.routes.customers import router as customers_router
from backend.app.api.routes.orders import router as orders_router
from backend.app.api.routes.payments import router as payments_router
from backend.app.api.routes.ai import router as ai_router
from backend.app.api.routes.actions import router as actions_router
# Phase 5 — Agentic Growth Intelligence
from backend.app.api.routes.agents import router as agents_router
from backend.app.api.routes.radar import router as radar_router
from backend.app.api.routes.phase5 import (
    insights_router,
    customer_insights_router,
    simulations_router,
    experiments_router,
    memory_router,
    brief_router,
)

app.include_router(health_router, prefix="/api")
app.include_router(opportunities_router, prefix="/api")
app.include_router(merchants_router, prefix="/api")
app.include_router(products_router, prefix="/api")
app.include_router(customers_router, prefix="/api")
app.include_router(orders_router, prefix="/api")
app.include_router(payments_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(actions_router, prefix="/api")
# Phase 5 routes (each declared WITHOUT /api here — prefix added exactly once)
app.include_router(agents_router, prefix="/api")
app.include_router(radar_router, prefix="/api")
app.include_router(insights_router, prefix="/api")
app.include_router(customer_insights_router, prefix="/api")
app.include_router(simulations_router, prefix="/api")
app.include_router(experiments_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(brief_router, prefix="/api")


@app.get("/")
def root() -> dict:
    """Root endpoint — basic service identity."""
    settings = get_settings()
    return {
        "name": settings.APP_NAME,
        "status": "running",
        "version": settings.APP_VERSION,
    }


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc: Exception) -> JSONResponse:
    """Catch-all — delegates to the centralised error handler."""
    return await unhandled_exception_handler(request, exc)
