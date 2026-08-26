"""
Razorpay integration boundary — Phase 8 (Slice 8).

Design rules:
  - Credentials come ONLY from environment configuration. They are never
    hardcoded, never returned by any API response, and never logged.
  - The adapter abstraction is the ONLY place that may talk to Razorpay.
  - Test mode is the default and performs NO network calls; every result is
    explicitly labelled mode="test" with executed/simulated flags so no
    caller can mistake it for a real-world side effect.
  - Live execution requires BOTH EXECUTION_ENABLED and RAZORPAY_ENABLED to
    be explicitly true AND a configured key pair — and even then the live
    client refuses unimplemented operations honestly instead of faking
    success. Real-money movement stays disabled by default everywhere.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from backend.app.core.config import get_settings

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Structured results
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RazorpayResult:
    """Outcome of an adapter operation. `executed` means a REAL external effect."""

    ok: bool
    mode: str                       # "test" | "live" | "disabled"
    executed: bool                  # True ONLY for real external side effects
    simulated: bool                 # True for deterministic test-mode outcomes
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def safe_public_dict(self) -> dict[str, Any]:
        """
        Client-safe projection. Never includes credentials or signatures.
        """
        return {
            "ok": self.ok,
            "mode": self.mode,
            "executed": self.executed,
            "simulated": self.simulated,
            "error": self.error,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Webhook signature validation (independent of execution mode)
# ─────────────────────────────────────────────────────────────────────────────


def verify_webhook_signature(body: bytes, signature: str | None, secret: str | None) -> bool:
    """
    Validate Razorpay's X-Razorpay-Signature header:

        hex(HMAC_SHA256(webhook_secret, raw_body)) == signature

    Constant-time comparison. Any missing/short input fails closed.
    """
    if not signature or not secret or not body:
        return False
    try:
        expected = hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
    except Exception:  # pragma: no cover - defensive
        return False
    return hmac.compare_digest(expected, signature.strip().lower())


# ─────────────────────────────────────────────────────────────────────────────
# Adapter abstraction
# ─────────────────────────────────────────────────────────────────────────────


class BaseRazorpayClient:
    """All Razorpay interactions must go through this interface."""

    mode: str = "abstract"

    def retry_payment(self, payment_id: str, amount_inr: float | None = None) -> RazorpayResult:
        raise NotImplementedError()

    def health(self) -> dict[str, Any]:
        """Configuration visibility WITHOUT ever exposing secrets."""
        return {"mode": self.mode, "configured": True}


class DisabledRazorpayClient(BaseRazorpayClient):
    """
    Default state: RAZORPAY_ENABLED=false. Every operation returns an honest
    non-success — a fake payment success is NEVER produced.
    """

    mode = "disabled"

    def retry_payment(self, payment_id: str, amount_inr: float | None = None) -> RazorpayResult:
        return RazorpayResult(
            ok=False,
            mode=self.mode,
            executed=False,
            simulated=False,
            error="RAZORPAY_DISABLED",
            metadata={
                "payment_id": payment_id,
                "razorpay_enabled": False,
                "note": "Real Razorpay execution is disabled "
                "(RAZORPAY_ENABLED=false). Nothing was charged or retried.",
            },
        )

    def health(self) -> dict[str, Any]:
        return {"mode": self.mode, "configured": False}


class TestModeRazorpayClient(BaseRazorpayClient):
    """
    Explicit test mode (RAZORPAY_TEST_MODE=true).

    Deterministic simulation only: no network calls, no credentials needed.
    Results are always labelled simulated=True / executed=False.
    """

    mode = "test"

    def retry_payment(self, payment_id: str, amount_inr: float | None = None) -> RazorpayResult:
        attempt_id = f"test_retry_{secrets.token_hex(8)}"
        log.info(
            "Razorpay TEST-mode simulated retry. payment=%s attempt=%s",
            payment_id, attempt_id,
        )
        return RazorpayResult(
            ok=True,
            mode=self.mode,
            executed=False,
            simulated=True,
            error=None,
            metadata={
                "payment_id": payment_id,
                "attempt_id": attempt_id,
                "note": "Test mode — simulated outcome, no external call made",
            },
        )

    def health(self) -> dict[str, Any]:
        return {"mode": self.mode, "configured": True}


class LiveRazorpayClient(BaseRazorpayClient):
    """
    Real-money client scaffold.

    Deliberately NOT implemented in this phase: returning fabricated success
    here would create fake financial reality. When implemented it must use
    the official SDK, run behind EXECUTION_ENABLED+RAZORPAY_ENABLED, and be
    reviewed against guardrails. Until then it refuses honestly.
    """

    mode = "live"

    def __init__(self, key_id_present: bool, key_secret_present: bool) -> None:
        self._key_configured = key_id_present and key_secret_present

    def retry_payment(self, payment_id: str, amount_inr: float | None = None) -> RazorpayResult:
        if not self._key_configured:
            return RazorpayResult(
                ok=False, mode=self.mode, executed=False, simulated=False,
                error="RAZORPAY_NOT_CONFIGURED",
                metadata={"payment_id": payment_id},
            )
        return RazorpayResult(
            ok=False, mode=self.mode, executed=False, simulated=False,
            error="RAZORPAY_LIVE_RETRY_NOT_IMPLEMENTED",
            metadata={"payment_id": payment_id},
        )

    def health(self) -> dict[str, Any]:
        # Never expose whether keys are present beyond a boolean.
        return {"mode": self.mode, "configured": self._key_configured}


def build_razorpay_client() -> BaseRazorpayClient:
    """Factory selecting the adapter strictly from environment configuration."""
    s = get_settings()
    if not s.RAZORPAY_ENABLED:
        return DisabledRazorpayClient()
    if s.RAZORPAY_TEST_MODE:
        return TestModeRazorpayClient()
    return LiveRazorpayClient(
        key_id_present=bool(s.RAZORPAY_KEY_ID),
        key_secret_present=bool(s.RAZORPAY_KEY_SECRET),
    )


def razorpay_health() -> dict[str, Any]:
    """Safe configuration summary for diagnostics (no secrets)."""
    s = get_settings()
    return {
        "razorpay_enabled": s.RAZORPAY_ENABLED,
        "test_mode": s.RAZORPAY_TEST_MODE,
        "webhook_configured": bool(s.RAZORPAY_WEBHOOK_SECRET),
        "client": build_razorpay_client().health(),
    }
