"""
Secret-safe logging — Phase 9 hardening.

Installs a logging Filter on the root logger that redacts the VALUES of
configured secrets (AUTH_SECRET_KEY, LLM_API_KEY, GROQ_API_KEY,
RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET, RAZORPAY_KEY_ID) should they
ever appear in a log record. Defence in depth: application code must never
log secrets in the first place.
"""
from __future__ import annotations

import logging

from backend.app.core.config import get_settings

_REDACTED = "***REDACTED***"
_SECRET_ENV_KEYS = (
    "AUTH_SECRET_KEY",
    "LLM_API_KEY",
    "GROQ_API_KEY",
    "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET",
)


class SecretRedactingFilter(logging.Filter):
    """Replace configured secret values wherever they appear in log output."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets: set[str] = set()
        self._refresh()

    def _refresh(self) -> None:
        settings = get_settings()
        found: set[str] = set()
        for name in _SECRET_ENV_KEYS:
            value = getattr(settings, name, "") or ""
            if len(value) >= 8:
                found.add(value)
        # Key IDs are semi-public but still scrubbed from logs.
        key_id = getattr(settings, "RAZORPAY_KEY_ID", "") or ""
        if len(key_id) >= 8:
            found.add(key_id)
        self._secrets = found

    def _scrub(self, value: object) -> object:
        if not isinstance(value, str) or not self._secrets:
            return value
        out = value
        for secret in self._secrets:
            if secret in out:
                out = out.replace(secret, _REDACTED)
        return out

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub(v) for k, v in record.args.items()}
            else:
                record.args = tuple(
                    self._scrub(a) for a in (
                        record.args if isinstance(record.args, tuple)
                        else (record.args,)
                    )
                )
        return True


def install_secret_redaction() -> None:
    """Attach the redacting filter to every existing handler + root logger."""
    f = SecretRedactingFilter()
    root = logging.getLogger()
    root.addFilter(f)
    for handler in root.handlers:
        handler.addFilter(f)
