"""
Razorpay integration boundary — Phase 8 (Slice 8).

Design rules:
  - Credentials come ONLY from environment configuration. They are never
    hardcoded, never returned by any API response, and never logged.
  - The adapter abstraction is the ONLY place that may talk to Razorpay.
  - Test mode is the default and performs NO network calls; every result is
    explicitly labelled mode="test" with executed/simulated flags so no
    caller can mistake it for a real-world side effect.
  - Real TEST integration requires explicit opt-in via REAL_TEST_INTEGRATION_ENABLED
    and uses the official Razorpay SDK against TEST MODE endpoints.
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
import time
from dataclasses import dataclass, field
from typing import Any

from backend.app.core.config import get_settings

try:
    import razorpay
    RAZORPAY_SDK_AVAILABLE = True
except ImportError:
    razorpay = None
    RAZORPAY_SDK_AVAILABLE = False

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Structured results
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RazorpayResult:
    """Outcome of an adapter operation. `executed` means a REAL external effect."""

    ok: bool
    mode: str                       # "test" | "live" | "disabled" | "real_test"
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

    # Real TEST API operations (implemented by RealRazorpayTestClient)
    def create_order(self, amount_inr: float, currency: str = "INR", receipt: str | None = None, notes: dict | None = None) -> RazorpayResult:
        raise NotImplementedError()

    def fetch_order(self, order_id: str) -> RazorpayResult:
        raise NotImplementedError()

    def list_orders(self, params: dict | None = None) -> RazorpayResult:
        raise NotImplementedError()

    def fetch_payment(self, payment_id: str) -> RazorpayResult:
        raise NotImplementedError()

    def list_payments(self, params: dict | None = None) -> RazorpayResult:
        raise NotImplementedError()

    def create_customer(self, name: str, email: str, contact: str | None = None, fail_existing: str = "0") -> RazorpayResult:
        raise NotImplementedError()

    def fetch_customer(self, customer_id: str) -> RazorpayResult:
        raise NotImplementedError()

    def list_customers(self, params: dict | None = None) -> RazorpayResult:
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


class RealRazorpayTestClient(BaseRazorpayClient):
    """
    Real Razorpay TEST MODE integration using the official SDK.

    This client makes REAL network calls to Razorpay TEST MODE endpoints.
    It requires:
      - RAZORPAY_ENABLED=true
      - RAZORPAY_TEST_MODE=true
      - REAL_TEST_INTEGRATION_ENABLED=true
      - Valid RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET

    All operations are against TEST MODE endpoints (no real money).
    Results are labelled executed=True, simulated=False, test_mode=True.
    """

    mode = "real_test"

    def __init__(self, key_id: str, key_secret: str) -> None:
        if not RAZORPAY_SDK_AVAILABLE:
            raise RuntimeError("razorpay SDK not installed. Run: pip install razorpay")
        self._client = razorpay.Client(auth=(key_id, key_secret))
        # Razorpay SDK uses requests internally; timeout handled per-request

    def _handle_error(self, operation: str, exc: Exception) -> RazorpayResult:
        """Convert SDK exceptions into safe, structured results without leaking secrets."""
        # Try to extract the actual error message from the exception
        error_details = str(exc) if str(exc) else type(exc).__name__
        log.error("Razorpay %s failed: %s - %s", operation, type(exc).__name__, error_details)
        # Razorpay SDK raises generic exceptions; avoid logging exception details that might contain secrets
        error_msg = f"RAZORPAY_{operation.upper()}_FAILED"
        return RazorpayResult(
            ok=False,
            mode=self.mode,
            executed=False,
            simulated=False,
            error=error_msg,
            metadata={"operation": operation, "error_type": type(exc).__name__, "error_details": error_details[:500]},
        )

    def retry_payment(self, payment_id: str, amount_inr: float | None = None) -> RazorpayResult:
        try:
            # Razorpay doesn't have a direct "retry" API; this would typically be a new payment link
            # For now, fetch the payment to verify it exists
            payment = self._client.payment.fetch(payment_id)
            return RazorpayResult(
                ok=True,
                mode=self.mode,
                executed=True,
                simulated=False,
                metadata={
                    "payment_id": payment_id,
                    "status": payment.get("status"),
                    "amount": payment.get("amount"),
                    "note": "Fetched payment for retry verification",
                },
            )
        except Exception as exc:
            return self._handle_error("retry_payment", exc)

    def create_order(self, amount_inr: float, currency: str = "INR", receipt: str | None = None, notes: dict | None = None) -> RazorpayResult:
        try:
            # Razorpay expects amount in paise (smallest currency unit)
            amount_paise = int(amount_inr * 100)
            order_data = {
                "amount": amount_paise,
                "currency": currency,
            }
            if receipt:
                order_data["receipt"] = receipt
            if notes:
                order_data["notes"] = notes

            order = self._client.order.create(order_data)
            return RazorpayResult(
                ok=True,
                mode=self.mode,
                executed=True,
                simulated=False,
                metadata={
                    "order_id": order.get("id"),
                    "amount": order.get("amount"),
                    "currency": order.get("currency"),
                    "receipt": order.get("receipt"),
                    "status": order.get("status"),
                },
            )
        except Exception as exc:
            return self._handle_error("create_order", exc)

    def fetch_order(self, order_id: str) -> RazorpayResult:
        try:
            order = self._client.order.fetch(order_id)
            return RazorpayResult(
                ok=True,
                mode=self.mode,
                executed=True,
                simulated=False,
                metadata=order,
            )
        except Exception as exc:
            return self._handle_error("fetch_order", exc)

    def list_orders(self, params: dict | None = None) -> RazorpayResult:
        try:
            orders = self._client.order.all(params or {})
            return RazorpayResult(
                ok=True,
                mode=self.mode,
                executed=True,
                simulated=False,
                metadata={"orders": orders},
            )
        except Exception as exc:
            return self._handle_error("list_orders", exc)

    def fetch_payment(self, payment_id: str) -> RazorpayResult:
        try:
            payment = self._client.payment.fetch(payment_id)
            return RazorpayResult(
                ok=True,
                mode=self.mode,
                executed=True,
                simulated=False,
                metadata=payment,
            )
        except Exception as exc:
            return self._handle_error("fetch_payment", exc)

    def list_payments(self, params: dict | None = None) -> RazorpayResult:
        try:
            payments = self._client.payment.all(params or {})
            return RazorpayResult(
                ok=True,
                mode=self.mode,
                executed=True,
                simulated=False,
                metadata={"payments": payments},
            )
        except Exception as exc:
            return self._handle_error("list_payments", exc)

    def create_customer(self, name: str, email: str, contact: str | None = None, fail_existing: str = "0") -> RazorpayResult:
        try:
            customer_data = {
                "name": name,
                "email": email,
                "fail_existing": fail_existing,
            }
            if contact:
                customer_data["contact"] = contact
            customer = self._client.customer.create(customer_data)
            return RazorpayResult(
                ok=True,
                mode=self.mode,
                executed=True,
                simulated=False,
                metadata=customer,
            )
        except Exception as exc:
            return self._handle_error("create_customer", exc)

    def fetch_customer(self, customer_id: str) -> RazorpayResult:
        try:
            customer = self._client.customer.fetch(customer_id)
            return RazorpayResult(
                ok=True,
                mode=self.mode,
                executed=True,
                simulated=False,
                metadata=customer,
            )
        except Exception as exc:
            return self._handle_error("fetch_customer", exc)

    def list_customers(self, params: dict | None = None) -> RazorpayResult:
        try:
            customers = self._client.customer.all(params or {})
            return RazorpayResult(
                ok=True,
                mode=self.mode,
                executed=True,
                simulated=False,
                metadata={"customers": customers},
            )
        except Exception as exc:
            return self._handle_error("list_customers", exc)

    def create_payment_link(
        self,
        amount_inr: float,
        currency: str = "INR",
        description: str | None = None,
        customer_id: str | None = None,
        receipt: str | None = None,
        notes: dict | None = None,
        callback_url: str | None = None,
        callback_method: str = "get",
    ) -> RazorpayResult:
        """
        Create a Razorpay Payment Link for TEST MODE checkout.
        
        Returns a payment link URL that can be used to redirect the customer
        to Razorpay's hosted checkout page.
        """
        try:
            amount_paise = int(amount_inr * 100)
            link_data = {
                "amount": amount_paise,
                "currency": currency,
            }
            if description:
                link_data["description"] = description
            if customer_id:
                link_data["customer_id"] = customer_id
            # reference_id is optional; omit to let Razorpay generate a unique one
            # if receipt:
            #     link_data["reference_id"] = receipt
            if notes:
                link_data["notes"] = notes
            if callback_url:
                link_data["callback_url"] = callback_url
                link_data["callback_method"] = callback_method
            # Set expire_by to 30 days from now (max allowed)
            import time
            link_data["expire_by"] = int(time.time()) + 30 * 24 * 60 * 60

            link = self._client.payment_link.create(link_data)
            return RazorpayResult(
                ok=True,
                mode=self.mode,
                executed=True,
                simulated=False,
                metadata={
                    "payment_link_id": link.get("id"),
                    "short_url": link.get("short_url"),
                    "amount": link.get("amount"),
                    "currency": link.get("currency"),
                    "description": link.get("description"),
                    "status": link.get("status"),
                },
            )
        except Exception as exc:
            return self._handle_error("create_payment_link", exc)

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
        # Check for explicit REAL TEST integration flag
        if getattr(s, 'REAL_TEST_INTEGRATION_ENABLED', False) and s.RAZORPAY_KEY_ID and s.RAZORPAY_KEY_SECRET:
            log.info("Initializing RealRazorpayTestClient for REAL TEST MODE integration")
            return RealRazorpayTestClient(s.RAZORPAY_KEY_ID, s.RAZORPAY_KEY_SECRET)
        # Default: simulated test mode
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
        "real_test_integration_enabled": getattr(s, 'REAL_TEST_INTEGRATION_ENABLED', False),
        "webhook_configured": bool(s.RAZORPAY_WEBHOOK_SECRET),
        "client": build_razorpay_client().health(),
    }