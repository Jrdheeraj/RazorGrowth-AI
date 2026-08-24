"""
Structured application logging configuration.

Call configure_logging() once at application startup.
Use get_logger(__name__) everywhere else.

Rules:
- Never log API secrets, passwords, or payment credentials.
- Never log full sensitive customer PII (email/phone in error paths).
- Log enough context to debug failures without exposing secrets.
"""
from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger with a structured format."""
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        stream=sys.stdout,
        force=True,
    )
    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)
