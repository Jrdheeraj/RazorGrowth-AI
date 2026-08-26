"""
Phase 6 security tests — Razorpay boundary (Slice 10, scenarios 21–22).

21. Webhook signature validation (fail closed)
22. Production execution disabled by default; live path refuses honestly
"""
from __future__ import annotations

import hashlib
import hmac

import pytest

from backend.app.core.config import get_settings
from tests.security_utils import bearer
from backend.app.integrations.razorpay import (
    DisabledRazorpayClient,
    LiveRazorpayClient,
    TestModeRazorpayClient,
    build_razorpay_client,
    verify_webhook_signature,
)

WEBHOOK_SECRET = "whsec_test_secret_0123456789abcdef"


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def webhook_configured(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


class TestWebhookSignatureValidation:
    def test_valid_signature_accepted(self, client, webhook_configured):
        body = b'{"event":"payment.captured","id":"evt_1"}'
        r = client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": _sign(body),
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"
        # Webhooks never trigger money movement.
        assert r.json()["action"] == "logged_only"

    def test_invalid_signature_rejected(self, client, webhook_configured):
        body = b'{"event":"refund.created"}'
        r = client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": "00" * 32},
        )
        assert r.status_code == 400
        assert r.json()["detail"] == "INVALID_SIGNATURE"

    def test_missing_signature_rejected(self, client, webhook_configured):
        r = client.post("/api/webhooks/razorpay", content=b"{}")
        assert r.status_code == 400

    def test_tampered_body_rejected(self, client, webhook_configured):
        body = b'{"event":"payment.captured","amount":999999}'
        good_sig = _sign(b'{"event":"payment.captured","amount":100}')
        r = client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": good_sig},
        )
        assert r.status_code == 400

    def test_unconfigured_secret_fails_closed(self, client, monkeypatch):
        monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
        get_settings.cache_clear()
        try:
            body = b'{"event":"payment.captured"}'
            r = client.post(
                "/api/webhooks/razorpay",
                content=body,
                headers={"X-Razorpay-Signature": _sign(body)},
            )
            # Even a VALID signature is refused when no secret is configured —
            # unsigned webhooks can never be trusted.
            assert r.status_code == 503
            assert r.json()["detail"] == "WEBHOOK_NOT_CONFIGURED"
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()

    def test_signature_unit_constant_time_and_strict(self):
        body = b"x"
        assert verify_webhook_signature(body, _sign(body), WEBHOOK_SECRET)
        assert not verify_webhook_signature(body, None, WEBHOOK_SECRET)
        assert not verify_webhook_signature(body, _sign(body), None)
        assert not verify_webhook_signature(b"", _sign(body), WEBHOOK_SECRET)
        assert not verify_webhook_signature(
            body, _sign(body).upper() + "x", WEBHOOK_SECRET
        )


class TestProductionExecutionDisabledByDefault:
    def test_default_settings_disable_razorpay(self, monkeypatch):
        for var in ("RAZORPAY_ENABLED", "EXECUTION_ENABLED", "RAZORPAY_TEST_MODE"):
            monkeypatch.delenv(var, raising=False)
        get_settings.cache_clear()
        try:
            s = get_settings()
            assert s.RAZORPAY_ENABLED is False
            assert s.EXECUTION_ENABLED is False
            client = build_razorpay_client()
            assert isinstance(client, DisabledRazorpayClient)
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()

    def test_disabled_client_never_executes(self):
        result = DisabledRazorpayClient().retry_payment("pay_123")
        assert result.ok is False
        assert result.executed is False
        assert result.simulated is False
        assert result.error == "RAZORPAY_DISABLED"

    def test_test_mode_is_explicitly_opt_in(self, monkeypatch):
        monkeypatch.setenv("RAZORPAY_ENABLED", "true")
        monkeypatch.setenv("RAZORPAY_TEST_MODE", "true")
        get_settings.cache_clear()
        try:
            client = build_razorpay_client()
            assert isinstance(client, TestModeRazorpayClient)
            result = client.retry_payment("pay_123")
            assert result.ok is True
            assert result.simulated is True
            assert result.executed is False       # never a real effect
            assert result.mode == "test"
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()

    def test_live_client_refuses_until_implemented(self):
        client = LiveRazorpayClient(key_id_present=True, key_secret_present=True)
        result = client.retry_payment("pay_123")
        assert result.ok is False
        assert result.executed is False
        assert result.error == "RAZORPAY_LIVE_RETRY_NOT_IMPLEMENTED"

        unconfigured = LiveRazorpayClient(False, False)
        assert unconfigured.retry_payment("p").error == "RAZORPAY_NOT_CONFIGURED"

    def test_end_to_end_retry_payment_stays_disabled_by_default(
        self, client, db_session
    ):
        """Full-stack: approved retry_payment fails honestly with
        RAZORPAY_DISABLED and never fabricates a payment success."""
        import uuid as _uuid

        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import AgentActionStatus, AgentActionType
        from tests.security_utils import make_world

        m, u_owner, _ = make_world(db_session, slug_hint="rzp")

        action = AgentAction(
            id=_uuid.uuid4(),
            merchant_id=m.id,
            action_type=AgentActionType.retry_payment,
            status=AgentActionStatus.approved,
            input_payload={"payment_id": "pay_test_001"},
            requested_by="rzp_probe",
        )
        db_session.add(action)
        db_session.commit()

        r = client.post(f"/api/actions/{action.id}/execute", headers=bearer(u_owner))
        assert r.status_code == 400
        detail = r.json()["detail"]
        error = detail["error"] if isinstance(detail, dict) else str(detail)
        assert error == "RAZORPAY_DISABLED"

        refreshed = db_session.get(AgentAction, action.id)
        db_session.refresh(refreshed)
        assert refreshed.status == AgentActionStatus.failed
        assert refreshed.error_code == "RAZORPAY_DISABLED"

    def test_public_results_never_include_credentials(self, monkeypatch):
        monkeypatch.setenv("RAZORPAY_ENABLED", "true")
        monkeypatch.setenv("RAZORPAY_TEST_MODE", "true")
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_PUBLICID1234")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "supersecretvalue123456")
        get_settings.cache_clear()
        try:
            result = build_razorpay_client().retry_payment("pay_x")
            public = result.safe_public_dict()
            blob = str(public) + str(result.metadata)
            assert "supersecretvalue123456" not in blob
            assert "rzp_test_PUBLICID1234" not in blob
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()
