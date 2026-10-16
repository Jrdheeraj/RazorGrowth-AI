"""
Shared pytest fixtures for the RazorGrowth AI test suite.

Test database strategy:
  - Uses SQLite WAL mode with a named in-memory shared-cache database.
  - WAL (Write-Ahead Logging) allows concurrent readers/writers so the
    session-scoped db_session and the client's override_get_db can
    coexist without table locking.
  - JSONB columns are replaced with JSON at DDL time for SQLite compat.
  - The `client` fixture overrides FastAPI's get_db dependency, keeping
    production code unmodified.

All 16 Phase 1 tests pass because:
  - GET / and GET /api/health have no DB dependency.
  - GET /api/opportunities falls back to the in-memory growth engine
    when no merchants are present in the test DB.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Test-environment defaults (set BEFORE any backend import).
# Real environment variables take precedence over .env in pydantic-settings.
#
# AUTH_MODE=optional preserves pre-Phase-6 behaviour for the legacy suites:
# unauthenticated requests fall back to single-tenant development semantics.
# The Phase 6 security suite explicitly switches to AUTH_MODE=required where
# needed (see tests/test_auth_login.py fixtures).
# Production deployments are unaffected: code default is AUTH_MODE=required
# and validate_production_safety() refuses insecure production boots.
# ---------------------------------------------------------------------------
os.environ.setdefault("AUTH_MODE", "optional")
os.environ.setdefault("AUTH_ENABLE_REGISTRATION", "true")
os.environ.setdefault("AUTH_SECRET_KEY", "test-only-secret-key-do-not-use-in-production")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("APP_ENV", "testing")

# Ensure Razorpay is disabled by default for tests (override .env)
os.environ["RAZORPAY_ENABLED"] = "false"
os.environ["RAZORPAY_TEST_MODE"] = "false"
os.environ["REAL_TEST_INTEGRATION_ENABLED"] = "false"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = ""

# --------------------------------------------------------------------------- #
# External-execution + provider credentials MUST be forced, not defaulted.
# --------------------------------------------------------------------------- #
# A developer's real .env is loaded by pydantic-settings (core/config.py) and
# typically carries live Cloudflare / Google / Meta / Razorpay credentials with
# EXECUTION_ENABLED=true. Previously only the Razorpay family was neutralised,
# so a normal `pytest` run inherited live execution and live OAuth client ids
# and issued REAL authenticated calls to oauth2.googleapis.com and
# googleads.googleapis.com.
#
# These are assigned unconditionally so a populated .env cannot leak into the
# suite. Tests that genuinely need a credential inject it via monkeypatch and
# clear the settings cache for the duration of that test.
#
# Image generation is deliberately NOT disabled here: the Designer FLUX tests
# mock at the httpx boundary, and _no_live_llm below blanks the Cloudflare
# credential so the provider reports itself unavailable rather than contacted.
for _name, _value in (
    # No agent or executor may perform a real external write in tests.
    ("EXECUTION_ENABLED", "false"),
    # Marketing provider credentials.
    ("GOOGLE_OAUTH_CLIENT_ID", ""),
    ("GOOGLE_OAUTH_CLIENT_SECRET", ""),
    ("GOOGLE_OAUTH_REDIRECT_URI", ""),
    ("GOOGLE_ADS_DEVELOPER_TOKEN", ""),
    ("META_APP_ID", ""),
    ("META_APP_SECRET", ""),
    ("META_OAUTH_REDIRECT_URI", ""),
    ("RESEND_API_KEY", ""),
    ("RESEND_FROM_EMAIL", ""),
    # Razorpay keys, so nothing can authenticate against the live API.
    ("RAZORPAY_KEY_ID", ""),
    ("RAZORPAY_KEY_SECRET", ""),
):
    os.environ[_name] = _value

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from starlette.testclient import TestClient

from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app

# --------------------------------------------------------------------------- #
# SQLite shared-cache in-memory DB with WAL journal mode.
# WAL allows concurrent reads from multiple connections without locking.
# --------------------------------------------------------------------------- #
_TEST_DATABASE_URL = "sqlite:///file:testdb?mode=memory&cache=shared&uri=true&timeout=30"


def _make_test_engine():
    engine = create_engine(
        _TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    # Replace JSONB with JSON for SQLite compatibility at DDL time
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy import JSON

    @event.listens_for(Base.metadata, "before_create")
    def swap_jsonb_for_sqlite(target, connection, **kw):
        if connection.dialect.name == "sqlite":
            for table in target.tables.values():
                for col in table.columns:
                    if isinstance(col.type, JSONB):
                        col.type = JSON()

    return engine


_test_engine = _make_test_engine()
_TestSessionLocal = sessionmaker(
    bind=_test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@pytest.fixture(scope="session", autouse=True)
def _create_test_schema():
    """Create all tables once per test session; drop at teardown."""
    Base.metadata.create_all(bind=_test_engine)
    yield
    Base.metadata.drop_all(bind=_test_engine)


@pytest.fixture(scope="session", autouse=True)
def _no_live_llm():
    """Never let the test suite reach a real LLM provider.

    The repository ``.env`` carries real, working credentials. Without this
    guard the suite silently resolved the configured provider and issued LIVE
    chat-completion calls, so:

      * test results depended on the developer's provider quota and on whether
        a hosted model happened to be answering,
      * every run burned real tokens, and
      * a provider outage (or an exhausted daily allocation) turned into a
        wall of unrelated red tests.

    Only the CREDENTIAL variables are blanked. Provider and model *names* are
    left alone so the Settings defaults stay observable to the tests that
    assert them; with no credential present ``resolve_llm_provider()``
    returns ``None`` and the agents take their documented deterministic path.

    Session-scoped on purpose: this only needs to happen once, and adding a
    per-test ``get_settings.cache_clear()`` changes the settings-caching
    dynamics that unrelated tests depend on.

    Tests that DO exercise a provider set the variable themselves via
    ``monkeypatch`` and clear the settings cache, which overrides this for
    that test only.

    Image generation is deliberately NOT neutralised: the Designer FLUX path
    is mocked at the httpx boundary in its own tests, and the flag stays on so
    the "provider unavailable" branches stay reachable.
    """
    import os

    from backend.app.core.config import get_settings

    blanked = (
        "LLM_API_KEY",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
    )
    saved = {name: os.environ.get(name) for name in blanked}
    for name in blanked:
        os.environ[name] = ""
    get_settings.cache_clear()
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_settings.cache_clear()


@pytest.fixture(scope="function")
def db_session(_create_test_schema) -> Session:
    """
    Function-scoped DB session for model/repository tests.

    Each test gets a fresh transaction that is rolled back at teardown,
    keeping tests isolated without needing to truncate tables.
    """
    session = _TestSessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="session")
def client(_create_test_schema) -> TestClient:
    """
    Session-scoped HTTP test client.

    Overrides get_db so all FastAPI routes use the test SQLite engine.
    """
    def override_get_db():
        session = _TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()
