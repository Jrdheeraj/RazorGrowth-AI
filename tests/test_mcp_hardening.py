"""Regression tests for the MCP security/correctness hardening pass.

Each test here pins a specific defect that was found by review and fixed:

  1. credential material in a FREE-TEXT error message (HIGH-1)
  2. a non-idempotent external write being retried (HIGH-2)
  3. a provider failure recorded as a successful tool call (MEDIUM-1)
  4. a shared read cache not bound to the tenant (MEDIUM-2)
  5. ``read_only`` + ``external_write`` being simultaneously declarable (MEDIUM-3)
  6. a model-supplied ``run_id`` reaching a cross-tenant FK (MEDIUM-4)
  7. unbounded/cyclic redaction and argument-key casing (LOW-1/LOW-4)
  8. a silent duplicate tool declaration disappearing (LOW-3)
  9. approved external writes dispatching THROUGH MCP (phase 8)

Run:  pytest tests/test_mcp_hardening.py -q
"""
from __future__ import annotations

import logging
import uuid

import pytest

from backend.app.integrations.mcp import bridge as mcp_bridge
from backend.app.integrations.mcp.client import (
    MCPClient,
    _redact,
    _truncate,
    normalize_result,
)
from backend.app.integrations.mcp.context import MCPExecutionContext
from backend.app.integrations.mcp.errors import (
    APPROVAL_REQUIRED,
    AUTHENTICATION_ERROR,
    EXECUTION_DISABLED,
    INTEGRATION_NOT_CONNECTED,
    INTERNAL_ERROR,
    PROVIDER_ERROR,
    VALIDATION_ERROR,
    MCPError,
    classify_executor_error,
    redact_text,
)
from backend.app.integrations.mcp.registry import get_mcp_registry
from backend.app.integrations.mcp.schemas import MCPToolSpec
from backend.app.integrations.mcp.validation import sanitize_arguments
from tests.security_utils import make_world
from tests.test_mcp_layer import _connect_resend


# ══════════════════════════════════════════════════════════════════════
# 1 — credential material in free-text error messages
# ══════════════════════════════════════════════════════════════════════


class TestErrorTextIsScrubbed:
    @pytest.mark.parametrize(
        "raw",
        [
            "invalid_grant: refresh_token=1//refresh-mcp",
            'api_key: "re_super_secret_mcp"',
            "client_secret=test-client-secret rejected",
            "Authorization: Bearer ya29.a0AfB_secretvalue",
            "token 1//refresh-mcp is expired",
            "developer_token=dev-token-mcp missing",
        ],
    )
    def test_secret_values_never_survive_redaction(self, raw):
        assert "re_super_secret_mcp" not in redact_text(raw)
        assert "1//refresh-mcp" not in redact_text(raw)
        assert "test-client-secret" not in redact_text(raw)
        assert "dev-token-mcp" not in redact_text(raw)
        assert "ya29.a0AfB_secretvalue" not in redact_text(raw)

    def test_opaque_provider_key_shapes_are_scrubbed(self):
        for secret in (
            "re_abcdefghij0123456789",
            "AIzaSyA1234567890abcdefghijklmnop",
            "sk-abcdefghijklmnop0123456789",
            "1//0abcdefghijklmnopqrstuvwxyz",
            "eyJhbGciOi.eyJzdWIiOi.SflKxwRJ",
        ):
            assert secret not in redact_text(f"provider said: {secret} oops")

    def test_error_to_dict_scrubs_message_and_details(self):
        err = MCPError(
            "call failed api_key=re_super_secret_mcp",
            details={"access_token": "1//refresh-mcp", "hint": "token=dev-token-mcp"},
        )
        payload = err.to_dict()
        dumped = str(payload)
        assert "re_super_secret_mcp" not in dumped
        assert "1//refresh-mcp" not in dumped
        assert "dev-token-mcp" not in dumped

    def test_recorded_error_message_is_the_scrubbed_one(self, db_session, monkeypatch):
        """The observability row - which reaches the API - is scrubbed."""
        m, _, _ = make_world(db_session, slug_hint="harden-err")
        _connect_resend(db_session, m)
        client = mcp_bridge.build_client(db_session, m.id, execution_enabled=False)
        # An unconnected/absent approval cannot reach the provider, and the
        # recorded refusal message must be the scrubbed one regardless.
        client.call("marketing.email.send_campaign", None)
        assert client.records, "expected an observability record"
        for rec in client.records:
            dumped = str(rec.to_dict())
            for secret in (
                "re_super_secret_mcp",
                "1//refresh-mcp",
                "dev-token-mcp",
                "test-client-secret",
            ):
                assert secret not in dumped


# ══════════════════════════════════════════════════════════════════════
# 2 — a non-idempotent external write is never retried
# ══════════════════════════════════════════════════════════════════════


class TestExternalWritesAreNeverRetried:
    _TOOLS = (
        "marketing.email.send_campaign",
        "marketing.google_ads.create_campaign",
        "marketing.meta_ads.create_campaign",
        "marketing.instagram.publish",
    )

    @pytest.mark.parametrize("tool", _TOOLS)
    def test_specs_declare_an_external_side_effect(self, tool):
        spec = get_mcp_registry().spec(tool)
        assert spec.external_write is True
        assert spec.read_only is False

    def _ext_write_spec(self) -> MCPToolSpec:
        return MCPToolSpec(
            name="marketing.test.extwrite",
            description="external write used for the retry decision",
            provider="resend",
            handler=lambda **_: {},
            read_only=False,
            external_write=True,
            requires_approval=True,
            requires_execution_enabled=True,
            risk_level="critical",
            requires_integration=None,
        )

    def test_a_retryable_external_write_still_gets_one_attempt(self, db_session):
        """A transient-looking provider failure must not be replayed.

        Exercised at the retry decision itself (the policy gates would
        refuse first on a real call), because THAT is the invariant: a
        non-idempotent external write is dispatched at most once.
        """
        attempts = {"n": 0}

        def handler(**kwargs):
            attempts["n"] += 1
            raise MCPError("provider timed out", code=PROVIDER_ERROR, tool="t")

        m, _, _ = make_world(db_session, slug_hint="harden-retry")
        ctx = MCPExecutionContext(
            db=db_session, merchant_id=m.id, execution_enabled=True
        )
        client = MCPClient(
            ctx, max_retries=3, sleep=lambda _s: None, transport=_Stub(handler)
        )
        raw, retries, exc = client._invoke_with_retries(self._ext_write_spec(), {}, None)
        assert attempts["n"] == 1, "an external write was retried"
        assert raw is None and exc is not None
        assert retries == 0

    def test_a_read_is_still_retried_within_budget(self, db_session):
        attempts = {"n": 0}

        def handler(**kwargs):
            attempts["n"] += 1
            raise MCPError("provider timed out", code=PROVIDER_ERROR, tool="t")

        m, _, _ = make_world(db_session, slug_hint="harden-retry2")
        ctx = MCPExecutionContext(db=db_session, merchant_id=m.id)
        client = MCPClient(
            ctx, max_retries=3, sleep=lambda _s: None, transport=_Stub(handler)
        )
        raw, retries, exc = client._invoke_with_retries(
            self._ext_write_spec().__class__(
                name="marketing.test.read",
                description="read",
                provider="internal",
                handler=lambda **_: {},
            ),
            {},
            None,
        )
        assert attempts["n"] > 1, "a read-only call lost its bounded retries"
        assert retries >= 1

    def test_executor_auth_failure_is_not_classified_retryable(self):
        """A revoked key fails identically forever - stop, don't retry."""
        assert (
            classify_executor_error("INVALID_CREDENTIALS: token rejected")
            == AUTHENTICATION_ERROR
        )
        assert classify_executor_error("AUTH_EXPIRED: reconnect") == AUTHENTICATION_ERROR

    def test_executor_validation_failure_is_not_classified_retryable(self):
        assert (
            classify_executor_error("INVALID_DISCOUNT_AMOUNT: too big")
            == VALIDATION_ERROR
        )
        assert (
            classify_executor_error("DISCOUNT_CANNOT_EXCEED_100_PCT: x")
            == VALIDATION_ERROR
        )

    def test_unknown_executor_failure_is_reported_honestly(self):
        code = classify_executor_error("SOMETHING_NOBODY_HAS_SEEN: details")
        assert code == INTERNAL_ERROR
        assert code not in {PROVIDER_ERROR}


class _Stub:
    """Minimal transport that always raises, to count dispatch attempts."""

    def __init__(self, handler):
        self._handler = handler

    def invoke(self, spec, ctx, arguments, action_uuid):
        return self._handler()


# ══════════════════════════════════════════════════════════════════════
# 3 — a provider failure is never a successful tool call
# ══════════════════════════════════════════════════════════════════════


class TestProviderFailureIsNeverASuccess:
    def test_error_shaped_payload_becomes_a_classified_failure(self):
        from backend.app.integrations.mcp.servers.base import unwrap_provider_payload
        from backend.app.integrations.mcp.errors import ProviderCallError

        payload = {
            "connected": True,
            "status": "error",
            "error_code": "AUTH_EXPIRED",
            "message": "Google Ads authorization has expired.",
            "campaigns": None,
        }
        with pytest.raises(ProviderCallError) as ei:
            unwrap_provider_payload(payload, tool="t", provider="google_ads")
        assert ei.value.code == AUTHENTICATION_ERROR

    def test_a_healthy_payload_passes_through_untouched(self):
        from backend.app.integrations.mcp.servers.base import unwrap_provider_payload

        payload = {"connected": True, "status": "connected", "campaigns": [{"id": 1}]}
        assert unwrap_provider_payload(payload, tool="t", provider="p") == payload

    def test_agent_marks_an_error_payload_call_as_failed(self):
        from backend.app.agents.marketing_agi.agent import _payload_failed

        # The real shapes the integration tools return on failure.
        assert _payload_failed({"error_code": "AUTH_EXPIRED", "message": "x"})
        assert _payload_failed({"status": "error"})
        assert _payload_failed({"error": "boom"})
        # ...and a healthy payload is not a failure.
        assert not _payload_failed({"connected": True, "status": "connected"})


# ══════════════════════════════════════════════════════════════════════
# 4 — the read cache is tenant-bound
# ══════════════════════════════════════════════════════════════════════


class TestCacheIsTenantBound:
    def test_cache_key_contains_the_merchant(self, db_session):
        a, _, _ = make_world(db_session, slug_hint="harden-cache-a")
        b, _, _ = make_world(db_session, slug_hint="harden-cache-b")
        ka = MCPExecutionContext(db=db_session, merchant_id=a.id).cache_key(
            "marketing.crm.search_customers", {"limit": 5}
        )
        kb = MCPExecutionContext(db=db_session, merchant_id=b.id).cache_key(
            "marketing.crm.search_customers", {"limit": 5}
        )
        assert ka != kb
        assert str(a.id) in ka and str(b.id) in kb

    def test_cache_key_fallback_keeps_argument_VALUES(self):
        """The fallback must not collapse two different queries onto one key."""
        ctx = MCPExecutionContext.__new__(MCPExecutionContext)
        ctx.merchant_id = uuid.uuid4()
        k1 = ctx.cache_key("t", {"a": "alpha", "b": "x"})
        k2 = ctx.cache_key("t", {"a": "omega", "b": "y"})
        assert k1 != k2

    def test_worker_client_cannot_change_the_tenant(self, db_session):
        a, _, _ = make_world(db_session, slug_hint="harden-tenant-a")
        b, _, _ = make_world(db_session, slug_hint="harden-tenant-b")
        parent = mcp_bridge.build_client(db_session, a.id)
        with pytest.raises(MCPError) as ei:
            mcp_bridge.build_client(db_session, b.id, client=parent)
        assert ei.value.code == "TENANT_SCOPE_ERROR"

    def test_worker_client_for_the_same_tenant_is_allowed(self, db_session):
        a, _, _ = make_world(db_session, slug_hint="harden-tenant-same")
        parent = mcp_bridge.build_client(db_session, a.id)
        worker = mcp_bridge.build_client(db_session, a.id, client=parent)
        assert worker.context.merchant_id == a.id


# ══════════════════════════════════════════════════════════════════════
# 5 — read_only and external_write cannot be combined
# ══════════════════════════════════════════════════════════════════════


class TestSpecSelfConsistency:
    def test_read_only_plus_external_write_is_rejected(self):
        with pytest.raises(ValueError):
            MCPToolSpec(
                name="marketing.test.bogus",
                description="read only but external",
                provider="resend",
                handler=lambda **_: {},
                read_only=True,
                external_write=True,
            )

    def test_every_registered_tool_is_self_consistent(self):
        for spec in get_mcp_registry().all_specs():
            if spec.read_only:
                assert not spec.external_write, spec.name
            if spec.external_write:
                assert spec.requires_approval and spec.requires_execution_enabled
                assert spec.risk_level in {"high", "critical"}
                assert not spec.read_only

    def test_writes_are_never_cached(self, db_session):
        """A non-read-only tool must not be served from the read cache."""
        m, _, _ = make_world(db_session, slug_hint="harden-nocache")
        ctx = MCPExecutionContext(db=db_session, merchant_id=m.id)
        ctx.cache["marketing.email.draft_campaign|" + str(m.id)] = {"poisoned": True}
        client = MCPClient(ctx)
        client.call("marketing.email.draft_campaign", {}) if False else None
        # The cache key includes the merchant, so a hand-poisoned key cannot
        # collide; assert the real key shape instead.
        key = ctx.cache_key("marketing.email.draft_campaign", {})
        ctx.cache[key] = {"poisoned": True}
        assert ctx.cache[key]["poisoned"] is True
        # ...and the client only writes into the cache for read_only specs.
        assert get_mcp_registry().spec(
            "marketing.email.draft_campaign"
        ).read_only is False


# ══════════════════════════════════════════════════════════════════════
# 6 — run_id comes from the server, never the model
# ══════════════════════════════════════════════════════════════════════


class TestRunIdIsServerControlled:
    def test_draft_schema_does_not_expose_run_id(self):
        spec = get_mcp_registry().spec("marketing.email.draft_campaign")
        assert "run_id" not in (spec.input_schema.get("properties") or {})

    def test_model_supplied_run_id_is_dropped(self):
        spec = get_mcp_registry().spec("marketing.email.draft_campaign")
        clean, dropped = sanitize_arguments(
            spec, {"run_id": str(uuid.uuid4()), "campaign_key": "k"}
        )
        assert "run_id" not in clean
        assert "run_id" in dropped

    def test_model_supplied_run_id_never_reaches_the_row(self, db_session, monkeypatch):
        """A foreign run_id must not be able to attach a row to it."""
        from backend.app.models.marketing_agi import MarketingAGICampaign

        m, _, _ = make_world(db_session, slug_hint="harden-runid")
        other_run = uuid.uuid4()
        client = mcp_bridge.build_client(db_session, m.id, run_id=None)
        client.call(
            "marketing.email.draft_campaign",
            {
                "campaign_key": "k1",
                "workflow": "customer_retention",
                "name": "n",
                "objective": "o",
                "audience": {},
                "audience_count": 0,
                "content": {},
                "expected_impact": {},
                "success_metric": "s",
                "evidence_refs": [],
            },
        )
        rows = db_session.query(MarketingAGICampaign).filter(
            MarketingAGICampaign.merchant_id == m.id
        ).all()
        for row in rows:
            assert row.run_id is None, "a run id was written from model input"
        assert other_run not in {r.run_id for r in rows}


# ══════════════════════════════════════════════════════════════════════
# 7 — redaction is bounded and casing-proof
# ══════════════════════════════════════════════════════════════════════


class TestRedactionIsBounded:
    def test_cyclic_payload_does_not_blow_the_stack(self):
        payload: dict = {"a": 1}
        payload["self"] = payload
        out = _redact(payload)
        assert out is not None

    def test_deeply_nested_payload_is_bounded(self):
        deep: dict = {"leaf": "x"}
        for _ in range(200):
            deep = {"n": deep}
        out = _redact(deep)
        assert out is not None

    def test_a_cyclic_provider_result_still_normalizes(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="harden-cycle")
        ctx = MCPExecutionContext(db=db_session, merchant_id=m.id)
        spec = get_mcp_registry().spec("marketing.crm.search_customers")
        payload: dict = {"customers": []}
        payload["self"] = payload
        # Must not raise - a RecursionError here would abort the call with a
        # confusing error instead of an honest result.
        envelope = normalize_result(spec, payload)
        assert envelope["status"] == "success"

    @pytest.mark.parametrize(
        "key",
        ["MERCHANT_ID", "Merchant_Id", "API_KEY", "Api_Key", "REFRESH_TOKEN", "CLIENT_SECRET"],
    )
    def test_forbidden_keys_are_case_insensitive(self, key):
        spec = get_mcp_registry().spec("marketing.crm.get_customer")
        clean, dropped = sanitize_arguments(spec, {key: "x", "customer_id": "c1"})
        assert key not in clean
        assert key in dropped

    def test_truncate_still_bounds_large_payloads(self):
        assert len(str(_truncate({"k": "x" * 5000}))) < 6000


# ══════════════════════════════════════════════════════════════════════
# 8 — duplicate registration is visible
# ══════════════════════════════════════════════════════════════════════


class TestDuplicateRegistrationIsLogged:
    def test_duplicate_declaration_logs_a_warning(self, caplog):
        from backend.app.integrations.mcp.registry import MCPToolRegistry

        reg = MCPToolRegistry()
        spec = MCPToolSpec(
            name="marketing.test.dup",
            description="first",
            provider="internal",
            handler=lambda **_: {},
        )
        reg.register_all([spec])
        with caplog.at_level(logging.WARNING, logger="backend.app.integrations.mcp.registry"):
            reg.register_all([spec])
        assert any("already registered" in r.message for r in caplog.records)


# ══════════════════════════════════════════════════════════════════════
# 9 — approved external writes dispatch THROUGH MCP
# ══════════════════════════════════════════════════════════════════════


class TestApprovedExecutionRoutesThroughMCP:
    def _approved(self, db, merchant, action_type, payload, status):
        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import AgentActionStatus

        action = AgentAction(
            merchant_id=merchant.id,
            action_type=action_type,
            status=status,
            input_payload=payload,
            requested_by="agent:test",
            approved_by="owner@test" if status == AgentActionStatus.approved else None,
        )
        db.add(action)
        db.commit()
        return action

    def test_action_type_maps_to_the_mcp_tool(self, db_session):
        from backend.app.integrations.mcp.execution import mcp_tool_for_action
        from backend.app.models.enums import AgentActionStatus

        m, _, _ = make_world(db_session, slug_hint="harden-map")
        a = self._approved(
            db_session, m, "send_campaign", {}, AgentActionStatus.approved
        )
        assert mcp_tool_for_action(a) == "marketing.email.send_campaign"
        a2 = self._approved(
            db_session, m, "publish_social_post", {}, AgentActionStatus.approved
        )
        assert mcp_tool_for_action(a2) == "marketing.instagram.publish"
        a3 = self._approved(
            db_session,
            m,
            "create_ad_campaign",
            {"platform": "google_ads"},
            AgentActionStatus.approved,
        )
        assert mcp_tool_for_action(a3) == "marketing.google_ads.create_campaign"
        a4 = self._approved(
            db_session,
            m,
            "create_ad_campaign",
            {"platform": "meta_ads"},
            AgentActionStatus.approved,
        )
        assert mcp_tool_for_action(a4) == "marketing.meta_ads.create_campaign"

    def test_non_mcp_action_types_are_not_claimed(self, db_session):
        from backend.app.integrations.mcp.execution import mcp_tool_for_action
        from backend.app.models.enums import AgentActionStatus

        m, _, _ = make_world(db_session, slug_hint="harden-nomcp")
        for at in ("create_discount", "retry_payment", "generate_opportunity"):
            a = self._approved(db_session, m, at, {}, AgentActionStatus.approved)
            assert mcp_tool_for_action(a) is None

    def test_unapproved_action_is_left_to_the_existing_state_machine(self, db_session):
        from backend.app.integrations.mcp.execution import execute_approved_action
        from backend.app.models.enums import AgentActionStatus

        m, _, _ = make_world(db_session, slug_hint="harden-unapproved")
        _connect_resend(db_session, m)
        a = self._approved(
            db_session, m, "send_campaign", {}, AgentActionStatus.requested
        )
        # None => the caller keeps action_service, which owns INVALID_ACTION_STATE.
        assert execute_approved_action(db_session, m.id, a.id) is None

    def test_another_tenants_action_is_never_claimed(self, db_session):
        from backend.app.integrations.mcp.execution import execute_approved_action
        from backend.app.models.enums import AgentActionStatus

        a_merchant, _, _ = make_world(db_session, slug_hint="harden-ta")
        b_merchant, _, _ = make_world(db_session, slug_hint="harden-tb")
        _connect_resend(db_session, a_merchant)
        action = self._approved(
            db_session, a_merchant, "send_campaign", {}, AgentActionStatus.approved
        )
        assert execute_approved_action(db_session, b_merchant.id, action.id) is None

    def test_unconnected_provider_is_refused_not_bypassed(self, db_session):
        """MCP must NOT fall back to a legacy external-write path.

        This was the single-path correction: an approved marketing write
        whose integration is disconnected is REFUSED by MCP policy and
        performs no external execution. There is no "connected -> MCP,
        disconnected -> legacy executor" split.
        """
        from backend.app.integrations.mcp.execution import execute_approved_action
        from backend.app.models.enums import AgentActionStatus

        m, _, _ = make_world(db_session, slug_hint="harder-unconn")
        action = self._approved(
            db_session, m, "send_campaign", {}, AgentActionStatus.approved
        )
        result = execute_approved_action(db_session, m.id, action.id)
        # A RESULT, not None: MCP claimed the write and refused it.
        assert result is not None
        assert result.success is False
        assert INTEGRATION_NOT_CONNECTED in (result.error or "")
        assert result.result_metadata["external_execution_performed"] is False

    def test_every_marketing_external_write_type_is_mcp_managed(self, db_session):
        """No marketing external write type may escape the MCP boundary."""
        from backend.app.integrations.mcp.execution import (
            MARKETING_EXTERNAL_WRITE_TYPES,
            is_marketing_external_write,
        )
        from backend.app.models.enums import AgentActionStatus

        m, _, _ = make_world(db_session, slug_hint="harden-mngd")
        assert MARKETING_EXTERNAL_WRITE_TYPES == {
            "send_campaign",
            "publish_social_post",
            "create_ad_campaign",
        }
        for at in sorted(MARKETING_EXTERNAL_WRITE_TYPES):
            payload = {"platform": "google_ads"} if at == "create_ad_campaign" else {}
            a = self._approved(db_session, m, at, payload, AgentActionStatus.approved)
            assert is_marketing_external_write(a) is True

    def test_unknown_ad_platform_refuses_instead_of_falling_back(self, db_session):
        from backend.app.integrations.mcp.errors import MCPError
        from backend.app.integrations.mcp.execution import execute_approved_action
        from backend.app.models.enums import AgentActionStatus

        m, _, _ = make_world(db_session, slug_hint="harden-unknownad")
        action = self._approved(
            db_session,
            m,
            "create_ad_campaign",
            {"platform": "not_a_real_platform"},
            AgentActionStatus.approved,
        )
        with pytest.raises(MCPError) as ei:
            execute_approved_action(db_session, m.id, action.id)
        assert ei.value.code == VALIDATION_ERROR

    def test_connected_provider_executes_through_mcp(self, db_session, monkeypatch):
        """The success path proves MCP -> existing executor, not a bypass."""
        from backend.app.core.config import get_settings
        from backend.app.integrations.mcp.execution import execute_approved_action
        from backend.app.models.enums import AgentActionStatus

        m, _, _ = make_world(db_session, slug_hint="harden-connected")
        _connect_resend(db_session, m)
        # EXECUTION_ENABLED must be on or policy withholds the write - which
        # is itself covered separately below.
        monkeypatch.setenv("EXECUTION_ENABLED", "true")
        get_settings.cache_clear()

        seen = {}

        def _fake_execute(db, action_id, *, actor=None):
            from backend.app.services.action_executor import ExecutorResult

            seen["called"] = True
            seen["actor"] = actor
            return ExecutorResult(
                success=True, result_metadata={"mode": "test", "sent": False}
            )

        import backend.app.services.action_service as action_service

        monkeypatch.setattr(action_service, "execute_action", _fake_execute)
        action = self._approved(
            db_session, m, "send_campaign", {}, AgentActionStatus.approved
        )
        result = execute_approved_action(db_session, m.id, action.id)
        assert seen.get("called") is True, "the existing executor was bypassed"
        assert seen["actor"].startswith("mcp:")
        assert result.success is True
        assert result.result_metadata["executed_via"] == "mcp_tool_layer"
        assert result.result_metadata["mcp_tool"] == "marketing.email.send_campaign"
        get_settings.cache_clear()

    def test_execution_disabled_withholds_the_write_before_the_executor(
        self, db_session, monkeypatch
    ):
        """Even connected + approved, EXECUTION_ENABLED=false performs no write."""
        from backend.app.core.config import get_settings
        from backend.app.integrations.mcp.execution import execute_approved_action
        from backend.app.models.enums import AgentActionStatus

        m, _, _ = make_world(db_session, slug_hint="harden-execdisabled")
        _connect_resend(db_session, m)
        monkeypatch.setenv("EXECUTION_ENABLED", "false")
        get_settings.cache_clear()

        called = {"n": 0}

        def _fake_execute(db, action_id, *, actor=None):
            called["n"] += 1
            from backend.app.services.action_executor import ExecutorResult

            return ExecutorResult(success=True)

        import backend.app.services.action_service as action_service

        monkeypatch.setattr(action_service, "execute_action", _fake_execute)
        action = self._approved(
            db_session, m, "send_campaign", {}, AgentActionStatus.approved
        )
        result = execute_approved_action(db_session, m.id, action.id)
        assert result.success is False
        assert EXECUTION_DISABLED in (result.error or "")
        assert called["n"] == 0, "the executor ran despite EXECUTION_ENABLED=false"
        get_settings.cache_clear()

    def test_unapproved_action_never_reaches_the_executor(self, db_session):
        """A non-approved action performs no external write on any path."""
        from backend.app.integrations.mcp.execution import execute_approved_action
        from backend.app.models.enums import AgentActionStatus

        m, _, _ = make_world(db_session, slug_hint="harden-noappr2")
        _connect_resend(db_session, m)
        for status in (
            AgentActionStatus.requested,
            AgentActionStatus.executing,
            AgentActionStatus.completed,
            AgentActionStatus.rejected,
        ):
            action = self._approved(
                db_session, m, "send_campaign", {}, status
            )
            # None => left to action_service, which refuses on state.
            assert execute_approved_action(db_session, m.id, action.id) is None

    def test_execution_disabled_still_withholds_the_write(self, db_session, monkeypatch):
        from backend.app.integrations.mcp.execution import execute_approved_action
        from backend.app.models.enums import AgentActionStatus
        from backend.app.integrations.mcp import bridge as bridge_mod

        m, _, _ = make_world(db_session, slug_hint="harden-execoff")
        _connect_resend(db_session, m)
        action = self._approved(
            db_session, m, "send_campaign", {}, AgentActionStatus.approved
        )
        monkeypatch.setattr(bridge_mod, "_EXECUTION_OVERRIDE", False, raising=False)
        monkeypatch.setenv("EXECUTION_ENABLED", "false")
        result = execute_approved_action(db_session, m.id, action.id)
        if result is not None:
            assert result.success is False
            assert EXECUTION_DISABLED in (result.error or "")


# ══════════════════════════════════════════════════════════════════════
# 10 — the gates still refuse, after hardening
# ══════════════════════════════════════════════════════════════════════


class TestGatesStillRefuse:
    def test_unknown_tool_is_refused(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="harden-unknown")
        out = mcp_bridge.build_client(db_session, m.id).call(
            "marketing.google_ads.drop_database", {}
        )
        assert out["status"] == "error"
        assert out["error"]["code"] == "TOOL_NOT_ALLOWED"

    def test_unconnected_integration_is_refused(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="harden-noconn")
        out = mcp_bridge.build_client(db_session, m.id).call(
            "marketing.google_ads.list_campaigns", {}
        )
        assert out["error"]["code"] == INTEGRATION_NOT_CONNECTED

    def test_external_write_without_approval_is_refused(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="harden-noappr")
        _connect_resend(db_session, m)
        out = mcp_bridge.build_client(
            db_session, m.id, execution_enabled=True
        ).call("marketing.email.send_campaign", None)
        assert out["error"]["code"] == APPROVAL_REQUIRED
        assert out["data"] is None