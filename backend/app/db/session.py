"""
Session factory and FastAPI database dependency.

Usage in a route:
    from fastapi import Depends
    from sqlalchemy.orm import Session
    from backend.app.db.session import get_db

    def my_route(db: Session = Depends(get_db)):
        ...
"""
from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    pass

# Module-level references — set once at application startup via init_db()
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_db(engine: Engine) -> None:
    """
    Bind the session factory to the given engine.

    Must be called once at application startup before any request is served.
    """
    global _engine, _SessionLocal
    _engine = engine
    _SessionLocal = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,  # avoid implicit lazy-loads after commit
    )


def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        raise RuntimeError(
            "Database not initialised. Call init_db() before using sessions."
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency — yields a SQLAlchemy Session.

    The session is always closed in the finally block regardless of whether
    the request succeeds or raises. Callers are responsible for commit/rollback.
    """
    factory = get_session_factory()
    db: Session = factory()
    try:
        yield db
    finally:
        db.close()
