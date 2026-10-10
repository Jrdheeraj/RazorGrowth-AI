"""Email campaign execution — policy, preview truthfulness and provider path.

WHY THIS SUITE
--------------
`EXECUTION_DISABLED` was reported against
``marketing.email.send_campaign``. The refusal itself is CORRECT — it is the
execution gate doing its job. What was wrong is everything around it:

  1. three different interpretations of ``EXECUTION_ENABLED``
     (always-block in MCP policy, production-only in action_service,
     always-block in the executor) could drift apart;
  2. a withheld send returned ``success=True`` with ``sent=False``, so the
     action pipeline recorded an unsent campaign as a COMPLETED action — a
     preview that reads as a delivery;
  3. recipients were used with no validation and no consent/opt-out check;
  4. the campaign row was only advanced on success, so a failed or withheld
     campaign kept advertising itself as sendable;
  5. a "delivered" style status was implied where the provider only ever
     reports ACCEPTANCE.

These tests pin the corrected behaviour. Every provider call is mocked —
no test ever contacts Resend or sends mail.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from backend.app.models.agent_action import AgentAction
from backend.app.models.customer import Customer
from backend.app.models.enums import (
    AgentActionStatus,
    AgentActionType,
    CustomerSegment,
)
from backend.app.models.marketing_agi import MarketingAGICampaign
from backend.app.services import action_service
from backend.app.services.action_executor import (
    ExecutorResult,
    execute_approved_action,
    get_executor,
)
from backend.app.services.action_service import _was_preview_only


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _json_response(status: int, payload: dict):
    import json

    return httpx.Response(
        status, content=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )


def _resend_transport(
    *, email_id: str = "em_1", send_status: int = 202, verify_status: int = 200
) -> httpx.MockTransport:
    """Mock Resend. Records nothing real; returns the provider's own shape."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/domains":
            return _json_response(
                verify_status, {"data": [{"id": "d1", "name": "acme.test", "status": "verified"}]}
            )
        assert request.url.path == "/emails", request.url.path
        return _json_response(send_status, {"id": email_id})

    return httpx.MockTransport(handler)


_REAL_CLIENT = httpx.Client


def _install_transport(monkeypatch, transport: httpx.MockTransport) -> None:
    """Route every httpx.Client through `transport`.

    Captures the genuine httpx.Client ONCE. Re-wrapping an already-patched
    Client made the first transport override the second, so a later install
    silently had no effect.
    """
    def patched(*a, **k):
        return _REAL_CLIENT(*a, **{**k, "transport": transport})

    monkeypatch.setattr(httpx, "Client", patched)


def _settings_with(monkeypatch, **overrides):
    """Patch the executor's settings view with explicit overrides.

    The concrete settings object is captured BEFORE patching — reading
    ``ex.get_settings()`` inside the replacement would call the replacement.
    """
    import backend.app.services.action_executor as ex

    concrete = ex.get_settings()
    patched = type(concrete)(**{**concrete.model_dump(), **overrides})
    monkeypatch.setattr(ex, "get_settings", lambda: patched)
    return patched


def _campaign(db, merchant, customers, *, name="Win back"):
    camp = MarketingAGICampaign(
        merchant_id=merchant.id,
        campaign_key=f"k-{uuid.uuid4().hex[:8]}",
        workflow="email_campaign",
        name=name,
        objective="Bring lapsed buyers back",
        channel="email",
        integration_status="draft_only",
        lifecycle="ready_for_approval",
        audience={"customer_ids": [str(c.id) for c in customers]},
        audience_count=len(customers),
        content={"message": "Hello", "subject_variants": ["Hi"], "cta": "Shop"},
    )
    db.add(camp)
    db.commit()
    return camp


def _approved_action(db, merchant, campaign, *, status=AgentActionStatus.approved):
    action = AgentAction(
        merchant_id=merchant.id,
        action_type=AgentActionType.send_campaign,
        status=status,
        input_payload={
            "merchant_id": str(merchant.id),
            "campaign_type": "email",
            "target": {"marketing_agi_campaign_id": str(campaign.id)},
            "target_count": campaign.audience_count,
        },
        requested_by="agent:test",
        approved_by="owner@test",
    )
    db.add(action)
    db.commit()
    return action


def _customer(db, merchant, email="buyer@shop.test", **kw):
    c = Customer(merchant_id=merchant.id, name="Buyer", email=email,
                 segment=CustomerSegment.churned, **kw)
    db.add(c)
    db.commit()
    return c


@pytest.fixture()
def world(db_session):
    from tests.security_utils import make_world

    m, u, mem = make_world(db_session, slug_hint="mail")
    return m, u


# --------------------------------------------------------------------------- #
# 1. One authoritative execution policy
# --------------------------------------------------------------------------- #


class TestExecutionPolicyIsAuthoritative:
    def test_every_gate_reads_the_same_resolver(self):
        """No module may re-derive EXECUTION_ENABLED on its own."""
        from backend.app.core.execution_policy import external_execution_state

        state = external_execution_state()
        assert isinstance(state.enabled, bool)
        assert state.reason  # always explains itself

    def test_resolver_reports_disabled_with_remediation(self):
        from backend.app.core.execution_policy import external_execution_state

        state = external_execution_state(enabled=False)
        assert state.enabled is False
        assert "EXECUTION_ENABLED" in state.reason

    def test_resolver_reports_enabled(self):
        from backend.app.core.execution_policy import external_execution_state

        state = external_execution_state(enabled=True)
        assert state.enabled is True
        assert state.reason == ""

    def test_policy_and_service_agree_for_the_same_setting(self, monkeypatch):
        """MCP policy and the action service must not disagree."""
        from backend.app.core.execution_policy import external_execution_state

        for enabled in (True, False):
            monkeypatch.setenv("EXECUTION_ENABLED", "true" if enabled else "false")
            from backend.app.core.config import get_settings

            get_settings.cache_clear()
            assert external_execution_state(enabled=True).enabled is True
            assert external_execution_state().enabled is enabled
            get_settings.cache_clear()

    def test_malformed_value_is_treated_as_disabled(self, monkeypatch):
        """A typo must fail closed, never open."""
        from backend.app.core.execution_policy import external_execution_state

        for raw in ("", "maybe", "1.5", "yes please"):
            state = external_execution_state(raw_value=raw)
            assert state.enabled is False, f"{raw!r} must not enable execution"


# --------------------------------------------------------------------------- #
# 2. Execution disabled → explicit preview, provider NEVER called
# --------------------------------------------------------------------------- #


class TestPreviewOnlyWhenDisabled:
    def test_disabled_returns_preview_and_calls_no_provider(
        self, db_session, monkeypatch, world
    ):
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        called = {"n": 0}

        def handler(request):  # pragma: no cover - must never run
            called["n"] += 1
            raise AssertionError("provider must not be contacted when disabled")

        _install_transport(monkeypatch, httpx.MockTransport(handler))
        _settings_with(
            monkeypatch,
            EXECUTION_ENABLED=False,
            RESEND_API_KEY="re_key",
            RESEND_FROM_EMAIL="brand@acme.test",
        )

        res = execute_approved_action(action, db_session)
        assert res.success is True, "a preview is a successful *preview*, not a send"
        assert res.result_metadata["sent"] is False
        assert res.result_metadata["delivery_status"] == "preview_only"
        assert res.result_metadata["blocking_reason"] == "EXECUTION_DISABLED"
        assert called["n"] == 0

    def test_preview_is_recorded_without_claiming_a_delivery(
        self, db_session, monkeypatch, world
    ):
        """A withheld send must never be recorded as a delivery."""
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        _settings_with(monkeypatch, EXECUTION_ENABLED=False,
                       RESEND_API_KEY="re_key", RESEND_FROM_EMAIL="brand@acme.test")

        result = action_service.execute_action(db_session, action.id, actor="owner@test")
        db_session.refresh(action)

        meta = dict(action.output_payload or {})
        assert meta.get("sent") is False, "an unsent campaign must not record a send"
        assert meta.get("delivery_status") == "preview_only"
        assert meta.get("blocking_reason") == "EXECUTION_DISABLED"

        # And it must still be retryable once execution is enabled.
        assert _was_preview_only(action) is True

    def test_preview_becomes_a_real_send_when_execution_is_enabled(
        self, db_session, monkeypatch, world
    ):
        """The whole point: enabling execution lets the campaign actually go."""
        merchant, _user = world
        cust = _customer(db_session, merchant, "ada@buyer.test")
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        # 1) Disabled → preview.
        _settings_with(monkeypatch, EXECUTION_ENABLED=False,
                       RESEND_API_KEY="re_live", RESEND_FROM_EMAIL="brand@acme.test")
        action_service.execute_action(db_session, action.id, actor="owner@test")
        db_session.refresh(action)
        assert (action.output_payload or {}).get("sent") is False

        # 2) Operator enables execution and retries the SAME action.
        sends = {"n": 0}
        base = _resend_transport(email_id="em_after")

        def counting(request):
            if request.url.path == "/emails":
                sends["n"] += 1
            return base.handle_request(request)

        _install_transport(monkeypatch, httpx.MockTransport(counting))
        _settings_with(monkeypatch, EXECUTION_ENABLED=True,
                       RESEND_API_KEY="re_live", RESEND_FROM_EMAIL="brand@acme.test")
        r2 = action_service.execute_action(db_session, action.id, actor="owner@test")
        db_session.refresh(action)

        assert sends["n"] == 1, "the retry must actually reach the provider"
        assert (action.output_payload or {}).get("sent") is True
        assert (action.output_payload or {}).get("email_id") == "em_after"
        db_session.refresh(camp)
        assert camp.integration_status == "sent"

    def test_campaign_is_marked_preview_only(self, db_session, monkeypatch, world):
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        _settings_with(monkeypatch, EXECUTION_ENABLED=False,
                       RESEND_API_KEY="re_key", RESEND_FROM_EMAIL="brand@acme.test")
        action_service.execute_action(db_session, action.id, actor="owner@test")

        db_session.refresh(camp)
        assert camp.integration_status == "preview_only"
        assert camp.integration_status != "sent", (
            "a campaign that was never delivered must not be marked sent"
        )
        assert camp.lifecycle == "completed", (
            "lifecycle keeps mirroring the action status (existing contract)"
        )

    def test_missing_credentials_are_a_configuration_error(
        self, db_session, monkeypatch, world
    ):
        """No key / no sender is reported honestly, not as a silent preview."""
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        _settings_with(monkeypatch, EXECUTION_ENABLED=True,
                       RESEND_API_KEY="", RESEND_FROM_EMAIL="")

        res = execute_approved_action(action, db_session)
        assert res.success is True  # still a preview, but labelled
        assert res.result_metadata["blocking_reason"] == "PROVIDER_CONFIG_MISSING"
        assert res.result_metadata["sent"] is False


# --------------------------------------------------------------------------- #
# 3. Execution enabled + approved → real provider integration
# --------------------------------------------------------------------------- #


class TestLiveSendWhenEnabled:
    def test_enabled_approved_campaign_reaches_the_provider(
        self, db_session, monkeypatch, world
    ):
        merchant, _user = world
        cust = _customer(db_session, merchant, "ada@buyer.test")
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        _install_transport(monkeypatch, _resend_transport(email_id="em_live_1"))
        _settings_with(monkeypatch, EXECUTION_ENABLED=True,
                       RESEND_API_KEY="re_live", RESEND_FROM_EMAIL="brand@acme.test")

        res = execute_approved_action(action, db_session)
        assert res.success is True, res.error
        assert res.result_metadata["sent"] is True
        assert res.result_metadata["email_id"] == "em_live_1"
        # The provider only ACCEPTS mail; we never claim delivery.
        assert res.result_metadata["delivery_status"] == "accepted_by_provider"

        db_session.refresh(camp)
        assert camp.integration_status == "sent"
        assert camp.lifecycle == "completed"

    def test_approval_is_still_required_when_enabled(self, db_session, monkeypatch, world):
        """Turning execution on must NOT remove the human gate."""
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(
            db_session, merchant, camp, status=AgentActionStatus.requested
        )

        _install_transport(monkeypatch, _resend_transport())
        _settings_with(monkeypatch, EXECUTION_ENABLED=True,
                       RESEND_API_KEY="re_live", RESEND_FROM_EMAIL="brand@acme.test")

        # Through the real pipeline: the state machine, not the raw executor.
        result = action_service.execute_action(db_session, action.id, actor="owner@test")
        assert result.success is False
        assert "INVALID_ACTION_STATE" in (result.error or "")
        db_session.refresh(action)
        assert action.status == AgentActionStatus.requested

    def test_unapproved_action_cannot_execute_even_when_enabled(
        self, db_session, monkeypatch, world
    ):
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(
            db_session, merchant, camp, status=AgentActionStatus.requested
        )
        _settings_with(monkeypatch, EXECUTION_ENABLED=True,
                       RESEND_API_KEY="re_live", RESEND_FROM_EMAIL="brand@acme.test")

        result = action_service.execute_action(db_session, action.id, actor="x")
        assert result.success is False
        db_session.refresh(action)
        assert action.status == AgentActionStatus.requested


# --------------------------------------------------------------------------- #
# 4. Provider failures never become fake success
# --------------------------------------------------------------------------- #


class TestProviderFailuresAreTruthful:
    def _enabled(self, monkeypatch, transport):
        _install_transport(monkeypatch, transport)
        _settings_with(monkeypatch, EXECUTION_ENABLED=True,
                       RESEND_API_KEY="re_live", RESEND_FROM_EMAIL="brand@acme.test")

    def test_provider_authentication_failure_is_recorded(
        self, db_session, monkeypatch, world
    ):
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        self._enabled(monkeypatch, _resend_transport(verify_status=401))

        res = execute_approved_action(action, db_session)
        assert res.success is False, "an auth failure must not read as success"
        assert res.error and "INVALID_CREDENTIALS" in res.error

        db_session.refresh(camp)
        assert camp.integration_status == "failed"

    def test_provider_rejection_is_not_a_delivery(self, db_session, monkeypatch, world):
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        self._enabled(monkeypatch, _resend_transport(send_status=422))

        res = execute_approved_action(action, db_session)
        assert res.success is False
        db_session.refresh(camp)
        assert camp.integration_status != "sent"

    def test_rate_limit_is_classified(self, db_session, monkeypatch, world):
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        self._enabled(monkeypatch, _resend_transport(send_status=429))

        res = execute_approved_action(action, db_session)
        assert res.success is False
        assert "RATE_LIMITED" in (res.error or "")

    def test_network_timeout_is_surfaced(self, db_session, monkeypatch, world):
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        def boom(request):
            raise httpx.ConnectTimeout("provider unreachable")

        self._enabled(monkeypatch, httpx.MockTransport(boom))

        res = execute_approved_action(action, db_session)
        assert res.success is False
        assert res.error


# --------------------------------------------------------------------------- #
# 5. Idempotency — a retry must not send twice
# --------------------------------------------------------------------------- #


class TestIdempotency:
    def test_duplicate_execute_sends_only_once(self, db_session, monkeypatch, world):
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        sends = {"n": 0}
        base = _resend_transport(email_id="em_once")

        def counting(request):
            if request.url.path == "/emails":
                sends["n"] += 1
            return base.handle_request(request)

        _install_transport(monkeypatch, httpx.MockTransport(counting))
        _settings_with(monkeypatch, EXECUTION_ENABLED=True,
                       RESEND_API_KEY="re_live", RESEND_FROM_EMAIL="brand@acme.test")

        action_service.execute_action(db_session, action.id, actor="o")
        db_session.commit()
        action_service.execute_action(db_session, action.id, actor="o")
        db_session.commit()

        assert sends["n"] == 1, "a retry must not deliver a second email"

    def test_rejected_action_is_never_sent(self, db_session, monkeypatch, world):
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(
            db_session, merchant, camp, status=AgentActionStatus.rejected
        )
        sends = {"n": 0}

        def counting(request):
            if request.url.path == "/emails":
                sends["n"] += 1
            return _json_response(200, {"data": []})

        _install_transport(monkeypatch, httpx.MockTransport(counting))
        _settings_with(monkeypatch, EXECUTION_ENABLED=True,
                       RESEND_API_KEY="re_live", RESEND_FROM_EMAIL="brand@acme.test")

        res = action_service.execute_action(db_session, action.id, actor="owner@test")
        assert res.success is False
        assert sends["n"] == 0


# --------------------------------------------------------------------------- #
# 6. Recipient validation + consent / suppression
# --------------------------------------------------------------------------- #


class TestRecipientSafety:
    def _enabled(self, monkeypatch):
        _install_transport(monkeypatch, _resend_transport())
        _settings_with(monkeypatch, EXECUTION_ENABLED=True,
                       RESEND_API_KEY="re_live", RESEND_FROM_EMAIL="brand@acme.test")

    def test_empty_audience_blocks_sending(self, db_session, monkeypatch, world):
        merchant, _user = world
        camp = MarketingAGICampaign(
            merchant_id=merchant.id, campaign_key="k-empty", workflow="email_campaign",
            name="Empty", objective="o", channel="email",
            integration_status="draft_only", lifecycle="ready_for_approval",
            audience={"customer_ids": []}, audience_count=0,
            content={"message": "Hi", "subject_variants": ["Hi"]},
        )
        db_session.add(camp)
        db_session.commit()
        action = _approved_action(db_session, merchant, camp)

        self._enabled(monkeypatch)
        res = execute_approved_action(action, db_session)
        assert res.success is False
        assert "UNRESOLVABLE_AUDIENCE" in (res.error or "")

    def test_invalid_email_addresses_are_filtered_out(
        self, db_session, monkeypatch, world
    ):
        merchant, _user = world
        good = _customer(db_session, merchant, "good@shop.test")
        bad = _customer(db_session, merchant, "not-an-email")
        camp = _campaign(db_session, merchant, [good, bad])
        action = _approved_action(db_session, merchant, camp)

        self._enabled(monkeypatch)
        res = execute_approved_action(action, db_session)
        assert res.success is True
        assert res.result_metadata["target_count"] == 1, (
            "an invalid address must not be handed to the provider"
        )
        assert res.result_metadata.get("skipped_recipients")

    def test_unsubscribed_recipient_is_excluded(self, db_session, monkeypatch, world):
        merchant, _user = world
        opted_out = _customer(db_session, merchant, "out@shop.test",
                              email_opt_out=True)
        still_in = _customer(db_session, merchant, "in@shop.test")
        camp = _campaign(db_session, merchant, [opted_out, still_in])
        action = _approved_action(db_session, merchant, camp)

        self._enabled(monkeypatch)
        res = execute_approved_action(action, db_session)
        assert res.success is True
        assert res.result_metadata["target_count"] == 1
        assert res.result_metadata["skipped_unsubscribed"] == 1

    def test_a_fully_unsubscribed_audience_is_blocked(self, db_session, monkeypatch, world):
        merchant, _user = world
        only = _customer(db_session, merchant, "out@shop.test", email_opt_out=True)
        camp = _campaign(db_session, merchant, [only])
        action = _approved_action(db_session, merchant, camp)

        self._enabled(monkeypatch)
        res = execute_approved_action(action, db_session)
        assert res.success is False
        assert "UNSUBSCRIBED" in (res.error or "") or "UNRESOLVABLE_AUDIENCE" in (res.error or "")

    def test_recipient_limit_is_enforced(self, db_session, monkeypatch, world):
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        self._enabled(monkeypatch)
        _settings_with(monkeypatch, EXECUTION_ENABLED=True,
                       RESEND_API_KEY="re_live", RESEND_FROM_EMAIL="brand@acme.test",
                       CAMPAIGN_MAX_TARGET=0)

        res = execute_approved_action(action, db_session)
        assert res.success is False
        assert "CAMPAIGN_TARGET_EXCEEDS_LIMIT" in (res.error or "")


# --------------------------------------------------------------------------- #
# 7. MCP gate still refuses when disabled, with actionable remediation
# --------------------------------------------------------------------------- #


class TestMCPRefusal:
    def _ctx(self, db_session, merchant, *, enabled: bool):
        from backend.app.integrations.mcp.context import MCPExecutionContext

        return MCPExecutionContext(
            db=db_session, merchant_id=merchant.id, execution_enabled=enabled
        )

    def _spec(self):
        from backend.app.integrations.mcp.servers.email import TOOLS
        from backend.app.integrations.mcp.errors import ExecutionDisabledError

        spec = next(t for t in TOOLS() if t.name == "marketing.email.send_campaign")
        return spec, ExecutionDisabledError

    def test_disabled_refuses_with_remediation(self, db_session, monkeypatch, world):
        from backend.app.integrations.mcp import policy as mcp_policy

        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        spec, ExecutionDisabledError = self._spec()
        ctx = self._ctx(db_session, merchant, enabled=False)
        monkeypatch.setattr(mcp_policy, "assert_integration_connected", lambda *a, **k: None)

        with pytest.raises(ExecutionDisabledError) as exc:
            mcp_policy.enforce(ctx, spec, approved_action_id=action.id)
        assert "EXECUTION_ENABLED" in exc.value.message
        # The refusal must tell the operator what to actually do.
        assert "EXECUTION_ENABLED=true" in exc.value.message

    def test_enabled_and_approved_passes_the_gate(self, db_session, monkeypatch, world):
        from backend.app.integrations.mcp import policy as mcp_policy

        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        spec, _ = self._spec()
        ctx = self._ctx(db_session, merchant, enabled=True)
        monkeypatch.setattr(mcp_policy, "assert_integration_connected", lambda *a, **k: None)

        mcp_policy.enforce(ctx, spec, approved_action_id=action.id)

    def test_missing_approval_is_refused_even_when_enabled(self, db_session, monkeypatch, world):
        from backend.app.integrations.mcp import policy as mcp_policy
        from backend.app.integrations.mcp.errors import ApprovalRequiredError

        merchant, _user = world
        spec, _ = self._spec()
        ctx = self._ctx(db_session, merchant, enabled=True)
        monkeypatch.setattr(mcp_policy, "assert_integration_connected", lambda *a, **k: None)

        with pytest.raises(ApprovalRequiredError):
            mcp_policy.enforce(ctx, spec, approved_action_id=None)


# --------------------------------------------------------------------------- #
# 8. Secrets must never leak
# --------------------------------------------------------------------------- #


class TestNoSecretLeakage:
    def test_preview_metadata_carries_no_credentials(self, db_session, monkeypatch, world):
        merchant, _user = world
        cust = _customer(db_session, merchant)
        camp = _campaign(db_session, merchant, [cust])
        action = _approved_action(db_session, merchant, camp)

        _settings_with(monkeypatch, EXECUTION_ENABLED=False,
                       RESEND_API_KEY="re_super_secret", RESEND_FROM_EMAIL="b@acme.test")
        res = execute_approved_action(action, db_session)

        blob = repr(res.result_metadata)
        assert "re_super_secret" not in blob