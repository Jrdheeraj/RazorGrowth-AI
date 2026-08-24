"""
SQLAlchemy engine factory.

Engines are expensive to create and must be shared across requests.
This module creates exactly one engine per process lifetime.

Do NOT import this at module level inside model files — only import
inside functions or via the session dependency to keep import order safe.
"""
from __future__ import annotations

from sqlalchemy import Engine, create_engine, event, text


def build_engine(database_url: str, echo: bool = False) -> Engine:
    """
    Create a SQLAlchemy engine with production-appropriate settings.

    Args:
        database_url: Full connection string, e.g.
            postgresql://user:pass@host:5432/dbname
        echo: If True, log all SQL statements (development only).
    """
    engine = create_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,       # detect stale connections
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,        # recycle connections every 30 min
    )
    return engine
