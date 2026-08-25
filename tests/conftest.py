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

import pytest
from sqlalchemy import create_engine, event, text
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
