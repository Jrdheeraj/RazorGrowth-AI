"""
RazorGrowth AI — FastAPI application entry point.

Run from the project root:
    uvicorn backend.app.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging, get_logger
from backend.app.core.errors import unhandled_exception_handler
from backend.app.core.middleware import SecurityHeadersMiddleware, RequestCorrelationMiddleware, validate_production_safety

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database connection pool at startup."""
    settings = get_settings()
    configure_logging("DEBUG" if settings.APP_ENV == "development" else "INFO")
    from backend.app.core.logfilter import install_secret_redaction

    install_secret_redaction()
    validate_production_safety()

    log.info(
        "Starting RazorGrowth AI [%s] auth_mode=%s execution=%s razorpay=%s",
        settings.APP_ENV,
        settings.AUTH_MODE,
        "enabled" if settings.EXECUTION_ENABLED else "disabled",
        "test" if settings.RAZORPAY_TEST_MODE and settings.RAZORPAY_ENABLED
        else ("enabled" if settings.RAZORPAY_ENABLED else "disabled"),
    )

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


def _build_app() -> FastAPI:
    settings = get_settings()
    return FastAPI(
        title="RazorGrowth AI",
        version="0.6.0",
        description=(
            "AI Growth & Agentic Commerce platform for Razorpay merchants. "
            "Authenticated, tenant-isolated, human-in-the-loop."
        ),
        lifespan=lifespan,
        # Interactive docs are disabled in production by default (ENABLE_DOCS).
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )


app = _build_app()

# ------------------------------------------------------------------ #
# HTTP hardening (order matters: outermost first)
# ------------------------------------------------------------------ #
app.add_middleware(RequestCorrelationMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

_settings = get_settings()
if _settings.trusted_host_list and _settings.trusted_host_list != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_settings.trusted_host_list)

_cors_origins = _settings.cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=bool(_cors_origins),
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
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
# Phase 6 — Authentication & security
from backend.app.api.routes.auth import router as auth_router
from backend.app.api.routes.webhooks import router as webhooks_router
# Phase 7 — Recommendations & Approvals
from backend.app.api.routes.recommendations import router as recommendations_router
# Phase F — Agent Debate
from backend.app.api.routes.debate import router as debate_router
# Phase M — Analytics
from backend.app.api.routes.analytics import router as analytics_router

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
# Phase 6 routes
app.include_router(auth_router, prefix="/api")
app.include_router(webhooks_router, prefix="/api")
# Phase 7 routes
app.include_router(recommendations_router, prefix="/api")
# Phase F routes
app.include_router(debate_router, prefix="/api")
# Phase M routes
app.include_router(analytics_router, prefix="/api")


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
