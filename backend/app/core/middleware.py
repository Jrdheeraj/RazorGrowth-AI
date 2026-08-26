"""
HTTP hardening middleware & production safety checks — Phase 9.

- SecurityHeadersMiddleware: adds defensive headers to every response.
  HSTS is added only in production (TLS terminates at the reverse proxy).
- validate_production_safety(): called from app lifespan. Refuses to boot
  production with insecure configuration, naming the violated requirement
  without ever echoing secret values.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI

from backend.app.core.config import get_settings


class SecurityHeadersMiddleware:
    def __init__(self, app: FastAPI) -> None:
        self.app = app

    async def __call__(
        self, scope: dict, receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                existing = {k.lower() for k, _ in headers}
                additions: list[tuple[bytes, bytes]] = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-permitted-cross-domain-policies", b"none"),
                    (b"cache-control", b"no-store"),
                ]
                if get_settings().is_production:
                    additions.append(
                        (
                            b"strict-transport-security",
                            b"max-age=63072000; includeSubDomains",
                        )
                    )
                for name, value in additions:
                    if name not in existing:
                        headers.append((name, value))
            await send(message)

        await self.app(scope, receive, send_with_headers)


def validate_production_safety() -> None:
    """
    Fail-fast checks for APP_ENV=production.

    An insecure default must never reach production. Raises RuntimeError
    naming the violated requirements (never echoing secret values).
    """
    s = get_settings()
    if not s.is_production:
        return

    problems: list[str] = []
    if len(s.AUTH_SECRET_KEY) < 32:
        problems.append("AUTH_SECRET_KEY must be set to at least 32 characters")
    if s.AUTH_MODE != "required":
        problems.append("AUTH_MODE must be 'required' in production")
    if "*" in s.trusted_host_list:
        problems.append("TRUSTED_HOSTS must list explicit hostnames in production")
    if problems:
        raise RuntimeError(
            "Refusing to start in production due to unsafe configuration: "
            + "; ".join(problems)
        )
