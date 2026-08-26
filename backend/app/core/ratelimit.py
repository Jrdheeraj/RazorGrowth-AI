"""
Lightweight sliding-window rate limiter — Phase 9 hardening.

In-memory, per-process, keyed by (bucket, client IP). Suitable for the
single-process deployments this project targets; horizontal deployments
should front it with a gateway-level limiter (documented in docs/PHASE_6).

No external dependencies. Never logs request bodies or credentials.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import HTTPException, Request

from backend.app.core.config import get_settings


def client_ip(request: Request) -> str:
    """Best-effort client identity for rate limiting (never validated)."""
    return request.client.host if request.client else "unknown"


@dataclass
class _Window:
    hits: deque[float]


class RateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, _Window] = {}
        self._lock = threading.Lock()

    def check(self, bucket: str, key: str, limit: int, window_seconds: int) -> None:
        """
        Record one hit and raise 429 when the bucket is over its limit.
        """
        settings = get_settings()
        if not settings.RATE_LIMIT_ENABLED:
            return

        now = time.monotonic()
        k = f"{bucket}:{key}"
        with self._lock:
            win = self._windows.setdefault(k, _Window(deque()))
            cutoff = now - window_seconds
            while win.hits and win.hits[0] < cutoff:
                win.hits.popleft()
            if len(win.hits) >= limit:
                retry_after = max(1, int(window_seconds - (now - win.hits[0])))
                raise HTTPException(
                    status_code=429,
                    detail="RATE_LIMIT_EXCEEDED",
                    headers={"Retry-After": str(retry_after)},
                )
            win.hits.append(now)

            # Opportunistic cleanup so idle buckets cannot grow unbounded.
            if len(self._windows) > 10_000:
                stale = [
                    sk for sk, w in self._windows.items()
                    if not w.hits or w.hits[-1] < cutoff
                ]
                for sk in stale:
                    del self._windows[sk]


limiter = RateLimiter()


def enforce_auth_rate_limit(request: Request) -> None:
    """Dependency for credential endpoints — strict limits."""
    s = get_settings()
    limiter.check("auth", client_ip(request), s.RATE_LIMIT_AUTH_REQUESTS,
                  s.RATE_LIMIT_AUTH_WINDOW_SECONDS)


def enforce_webhook_rate_limit(request: Request) -> None:
    """Dependency for signature-authenticated webhook endpoints."""
    s = get_settings()
    limiter.check("webhook", client_ip(request), s.RATE_LIMIT_WEBHOOK_REQUESTS,
                  s.RATE_LIMIT_WEBHOOK_WINDOW_SECONDS)
