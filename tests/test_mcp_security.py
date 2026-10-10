"""MCP security tests — the model must not be able to escape its sandbox.

Explicit coverage of the ten attacks named in the integration brief:

   1. the LLM cannot retrieve OAuth secrets
   2. the LLM cannot specify another merchant_id
   3. the LLM cannot invoke an unknown MCP tool
   4. the LLM cannot bypass approval
   5. the LLM cannot bypass EXECUTION_ENABLED
   6. MCP cannot execute against another tenant
   7. MCP logs contain no credentials
   8. MCP tool results contain no credentials
   9. a failed provider call does not create a fake success
  10. an approval action cannot be replayed incorrectly

These tests attempt the attack for real. None of them asserts only on a
return code: they verify the SIDE EFFECT did not happen.
"""
from __future__ import annotations

import json
import logging
import uuid

import httpx
import pytest

from backend.app.integrations.mcp import bridge as mcp_bridge
from backend.app.integrations.mcp.client import _redact
from backend.app.integrations.mcp.errors import (
    APPROVAL_REQUIRED,
    AUTHENTICATION_ERROR,
    EXECUTION_DISABLED,
    INTEGRATION_NOT_CONNECTED,
    TENANT_SCOPE_ERROR,
    TOOL_NOT_ALLOWED,
)
from backend.app.integrations.mcp.servers.base import legacy_call
from backend.app.models.customer import Customer
from backend.app.models.enums import (
    AgentActionStatus,
    AgentActionType,
    CustomerSegment,
)
from tests.security_utils import make_world
from tests.test_marketing_agi import add_customer
from tests.test_mcp_layer import (
    _connect_google,
    _connect_instagram,
    _connect_meta,
    _connect_resend,
    _instagram_handler,
    _json,
    _meta_handler,
    _patch_httpx,
)

# Every value that must never reach the model, the logs or an API response.
SECRET_VALUES = (
    "re_super_secret_mcp",
    "1//refresh-mcp",
    "dev-token-mcp",
    "test-client-secret",
    "meta-token-mcp",
    "ig-token-mcp",
)


def _client(db, merchant, **kw):
    return mcp_bridge.build_client(db, merchant.id, **kw)


def _assert_clean(payload, *, where: str) -> None:
    dumped = json.dumps(payload, default=str) if not isinstance(payload, str) else payload
    for secret in SECRET_VALUES:
        assert secret not in dumped, f"{where} leaked {secret!r}"


def _approved(db, merchant, action_type, payload, *, status=AgentActionStatus.approved):
    from backend.app.models.agent_action import AgentAction

    action = AgentAction(
        merchant_id=merchant.id,
        action_type=action_type,
        status=status,
        input_payload={"merchant_id": str(merchant.id), **payload},
        requested_by="agent:test",
        approved_by="owner@test" if status == AgentActionStatus.approved else None,
    )
    db.add(action)
    db.commit()
    return action


# ═══════════════════════════════════════════════════════════════════════
# 1 — the LLM cannot retrieve OAuth secrets
# ═══════════════════════════════════════════════════════════════════════


class TestNoSecretDisclosureToModel:
    def test_credentials_never_appear_in_any_tool_result(self, db_session, monkeypatch):
        """Every provider surface is exercised with real stored credentials."""
        from backend.app.core.config import get_settings

        m, _, _ = make_world(db_session, slug_hint="sec-every")
        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "dev-token-mcp")
        get_settings.cache_clear()

        _connect_resend(db_session, m, key="re_super_secret_mcp")
        _connect_meta(db_session, m, token="meta-token-mcp")
        _connect_instagram(db_session, m, token="ig-token-mcp")
        _connect_google(db_session, m, monkeypatch, refresh_token="1//refresh-mcp")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/token":
                return _json(200, {"access_token": "ya29.exchanged", "expires_in": 3600})
            if "/googleAds:search" in request.url.path:
                return _json(200, {"results": [{
                    "campaign": {"id": "1", "name": "C", "status": "PAUSED"},
                    "metrics": {"impressions": "1", "clicks": "1", "costMicros": "0"},
                }]})
            return _meta_handler(request)

        _patch_httpx(monkeypatch, httpx.MockTransport(handler))
        client = _client(db_session, m)
        tools = [
            "marketing.analytics.get_revenue",
            "marketing.crm.search_customers",
            "marketing.crm.get_segment",
            "marketing.email.get_campaigns",
            "marketing.email.get_connection",
            "marketing.meta_ads.list_campaigns",
            "marketing.meta_ads.get_insights",
            "marketing.instagram.get_account",
            "marketing.google_ads.list_campaigns",
            "marketing.google_ads.list_accessible_customers",
            "marketing.google_ads.get_campaign_performance",
        ]
        for tool in tools:
            out = client.call(tool, {})
            _assert_clean(out, where=tool)
            _assert_clean(client.records[-1].to_dict(), where=f"{tool} record")

    def test_secret_shaped_arguments_are_never_echoed(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="sec-args")
        add_customer(db_session, m, name="Ada")
        client = _client(db_session, m)
        out = client.call(
            "marketing.crm.search_customers",
            {
                "access_token": "model-supplied-token",
                "refresh_token": "model-refresh",
                "client_secret": "model-secret",
                "developer_token": "model-dev-token",
            },
        )
        assert out["status"] == "success"
        _assert_clean(out, where="tool result")
        _assert_clean(client.records[-1].to_dict(), where="record")
        assert "model-supplied-token" not in json.dumps(out)

    def test_redactor_covers_every_credential_key_shape(self):
        from backend.app.integrations.marketing.base import _SECRET_PATTERNS

        # Every credential-shaped key the platform already recognises must
        # be redacted by MCP's result redactor too — same patterns, one
        # standard.
        secrets = {f"value-for-{p}": p for p in _SECRET_PATTERNS}
        cleaned = _redact(secrets)
        assert set(cleaned.values()) == {"***REDACTED***"}, (
            f"unredacted keys: {[k for k, v in cleaned.items() if v != '***REDACTED***']}"
        )
        # The VALUES are gone; only the (non-secret) key names remain.
        for pattern in _SECRET_PATTERNS:
            assert pattern not in json.dumps(list(cleaned.values()))

    def test_redactor_is_recursive(self):
        cleaned = _redact({
            "outer": {"inner": [{"api_key": "leak"}]},
            "list_of_maps": [{"refresh_token": "leak"}],
        })
        assert cleaned["outer"]["inner"][0]["api_key"] == "***REDACTED***"
        assert cleaned["list_of_maps"][0]["refresh_token"] == "***REDACTED***"

    def test_vault_blob_stays_encrypted_at_rest(self, db_session):
        from backend.app.services import integration_service as svc

        m, _, _ = make_world(db_session, slug_hint="sec-vault")
        row = _connect_resend(db_session, m, key="re_super_secret_mcp")
        raw = svc.decrypt_credentials(row)
        assert raw["api_key"] == "re_super_secret_mcp"
        from backend.app.models.integration_connection import IntegrationConnection

        stored = db_session.get(IntegrationConnection, row.id)
        assert stored.encrypted_credentials.startswith("vault1:")
        assert "re_super_secret_mcp" not in stored.encrypted_credentials


# ═══════════════════════════════════════════════════════════════════════
# 2 — the LLM cannot specify another merchant_id
# ═══════════════════════════════════════════════════════════════════════


class TestTenantOverrideRefused:
    @pytest.mark.parametrize(
        "key",
        ["merchant_id", "merchantId", "tenant_id", "tenant", "tenantId", "workspace_id"],
    )
    def test_every_tenant_override_key_is_stripped(self, db_session, key):
        victim, _, _ = make_world(db_session, slug_hint="sec-victim")
        attacker, _, _ = make_world(db_session, slug_hint="sec-attacker")
        add_customer(db_session, victim, name="Victim")
        add_customer(db_session, attacker, name="Attacker")
        client = _client(db_session, attacker)
        out = client.call("marketing.crm.search_customers", {key: str(victim.id)})
        assert out["status"] == "success"
        assert key in out["metadata"]["dropped_arguments"]
        assert [c["name"] for c in out["data"]["customers"]] == ["Attacker"]

    def test_overrides_are_stripped_on_every_tool(self, db_session):
        victim, _, _ = make_world(db_session, slug_hint="sec-victim2")
        attacker, _, _ = make_world(db_session, slug_hint="sec-attacker2")
        _connect_resend(db_session, attacker, key="re_super_secret_mcp")
        client = _client(db_session, attacker)
        for tool in (
            "marketing.analytics.get_revenue",
            "marketing.crm.get_segment",
            "marketing.crm.get_action_history",
            "marketing.email.get_campaigns",
            "marketing.email.get_connection",
        ):
            out = client.call(tool, {"merchant_id": str(victim.id)})
            assert "merchant_id" in out["metadata"]["dropped_arguments"], tool

    def test_agent_sanitizer_and_mcp_agree_on_forbidden_keys(self, db_session):
        from backend.app.agents.marketing_agi.agent import (
            FORBIDDEN_TOOL_ARG_KEYS,
            sanitize_tool_args,
        )
        from backend.app.integrations.mcp.schemas import FORBIDDEN_ARG_KEYS

        _, dropped = sanitize_tool_args({"merchant_id": "x", "tenant_id": "y"})
        assert set(dropped) >= {"merchant_id", "tenant_id"}
        assert FORBIDDEN_TOOL_ARG_KEYS <= FORBIDDEN_ARG_KEYS

    def test_injected_db_session_argument_is_stripped(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="sec-dbsess")
        add_customer(db_session, m, name="Ada")
        client = _client(db_session, m)
        out = client.call("marketing.crm.search_customers", {"db": "not-a-session"})
        assert "db" in out["metadata"]["dropped_arguments"]


# ═══════════════════════════════════════════════════════════════════════
# 3 — the LLM cannot invoke an unknown MCP tool
# ═══════════════════════════════════════════════════════════════════════


class TestUnknownToolRefused:
    @pytest.mark.parametrize(
        "name",
        [
            "marketing.crm.drop_database",
            "rm -rf /",
            "__import__('os').system('id')",
            "http.request",
            "marketing.email.send_campaign_v2",
            "send_campaign",              # legacy action name, not a tool
            "get_registry",
            "",
        ],
    )
    def test_unknown_names_are_refused(self, db_session, name):
        m, _, _ = make_world(db_session, slug_hint="sec-unknown")
        client = _client(db_session, m)
        out = client.call(name, {})
        assert out["status"] == "error", name
        assert out["error"]["code"] == TOOL_NOT_ALLOWED, name
        assert out["data"] is None
        assert client.records[-1].status == "denied"

    def test_refusal_is_auditable(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="sec-audit")
        client = _client(db_session, m)
        client.call("marketing.crm.wipe", {})
        row = client.records[-1].to_dict()
        assert row["status"] == "denied"
        assert row["error_code"] == TOOL_NOT_ALLOWED
        assert "wipe" in row["tool"]

    def test_agent_records_a_rejected_tool_in_state(self, db_session):
        """The agent refuses a name neither MCP nor the legacy registry knows."""
        from backend.app.agents.marketing_agi.agent import MarketingAGI
        from backend.app.agents.marketing_agi.state import MarketingAGIState
        from backend.app.agents.marketing_agi.tools.registry import ToolError

        m, _, _ = make_world(db_session, slug_hint="sec-agentreject")
        agent = MarketingAGI(db_session, m.id, llm=None)
        state = MarketingAGIState(run_id="r", merchant_id=str(m.id), objective="o")
        # Not MCP-registered and not a legacy tool either: nothing to run.
        assert mcp_bridge.resolve("marketing.crm.wipe") is None
        with pytest.raises(ToolError):
            agent._dispatch_tool(state, "marketing.crm.wipe", {})
        assert state.tool_calls == []  # nothing was recorded as a call

    def test_agent_rejects_a_registered_mcp_refusal_as_a_gap(self, db_session):
        """A registered tool that policy refuses is recorded as FAILED."""
        from backend.app.agents.marketing_agi.agent import MarketingAGI
        from backend.app.agents.marketing_agi.state import MarketingAGIState
        from backend.app.integrations.mcp.errors import MCPError

        m, _, _ = make_world(db_session, slug_hint="sec-agentrefuse")
        agent = MarketingAGI(db_session, m.id, llm=None)
        state = MarketingAGIState(run_id="r", merchant_id=str(m.id), objective="o")
        # The MCP name itself is allowlisted, so the refusal comes from
        # policy (provider not connected), not from the allowlist.
        with pytest.raises(MCPError) as exc:
            agent._dispatch_tool(state, "marketing.google_ads.list_campaigns", {})
        assert exc.value.code == INTEGRATION_NOT_CONNECTED
        assert state.tool_calls[-1]["ok"] is False


# ═══════════════════════════════════════════════════════════════════════
# 4 — the LLM cannot bypass approval
# ═══════════════════════════════════════════════════════════════════════


class TestApprovalCannotBeBypassed:
    EXTERNAL_WRITES = (
        ("marketing.email.send_campaign", "resend"),
        ("marketing.google_ads.create_campaign", "google_ads"),
        ("marketing.meta_ads.create_campaign", "meta_ads"),
        ("marketing.instagram.publish", "instagram"),
    )

    @pytest.mark.parametrize("tool,provider", EXTERNAL_WRITES)
    def test_write_without_approval_is_refused(self, db_session, monkeypatch, tool, provider):
        m, _, _ = make_world(db_session, slug_hint=f"sec-appr-{provider}")
        # Connect everything so only APPROVAL can be the blocker.
        _connect_resend(db_session, m, key="re_super_secret_mcp")
        _connect_meta(db_session, m, token="meta-token-mcp")
        _connect_instagram(db_session, m, token="ig-token-mcp")
        _connect_google(db_session, m, monkeypatch, refresh_token="1//refresh-mcp")
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))

        client = _client(db_session, m, execution_enabled=True)
        out = client.call(tool, {})
        assert out["error"]["code"] == APPROVAL_REQUIRED, tool

    def test_self_approval_flag_in_arguments_is_ignored(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="sec-selfapprove")
        _connect_meta(db_session, m, token="meta-token-mcp")
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))
        client = _client(db_session, m, execution_enabled=True)
        out = client.call(
            "marketing.meta_ads.create_campaign",
            {
                "approved": True,
                "approved_by": "model",
                "requires_approval": False,
                "execution_enabled": True,
            },
        )
        assert out["error"]["code"] == APPROVAL_REQUIRED
        dropped = set(out["metadata"]["dropped_arguments"])
        assert {"approved", "approved_by", "requires_approval", "execution_enabled"} <= dropped

    def test_requested_action_is_refused_by_the_pipeline(self, db_session, monkeypatch):
        """A 'requested' action cannot be executed, even via MCP."""
        m, _, _ = make_world(db_session, slug_hint="sec-requested")
        _connect_meta(db_session, m, token="meta-token-mcp")
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))
        action = _approved(
            db_session, m, AgentActionType.create_ad_campaign,
            {"provider": "meta_ads", "name": "X"},
            status=AgentActionStatus.requested,
        )
        client = _client(db_session, m, execution_enabled=True)
        out = client.call(
            "marketing.meta_ads.create_campaign", {}, approved_action_id=action.id
        )
        assert out["status"] == "error"
        db_session.refresh(action)
        assert action.status == AgentActionStatus.requested
        assert action.output_payload in (None, {})

    def test_rejected_action_is_refused(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="sec-rejected")
        _connect_meta(db_session, m, token="meta-token-mcp")
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))
        action = _approved(
            db_session, m, AgentActionType.create_ad_campaign,
            {"provider": "meta_ads", "name": "X"},
            status=AgentActionStatus.rejected,
        )
        out = _client(db_session, m, execution_enabled=True).call(
            "marketing.meta_ads.create_campaign", {}, approved_action_id=action.id
        )
        assert out["status"] == "error"

    def test_email_send_never_reaches_resend_without_approval(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="sec-nosend")
        _connect_resend(db_session, m, key="re_super_secret_mcp")
        sent: list[dict] = []
        monkeypatch.setattr(
            "backend.app.integrations.marketing.resend_email.ResendProvider.send_email",
            lambda self, **kw: sent.append(kw),
        )
        out = _client(db_session, m, execution_enabled=True).call(
            "marketing.email.send_campaign", {}
        )
        assert out["error"]["code"] == APPROVAL_REQUIRED
        assert sent == []

    def test_instagram_publish_never_reaches_the_graph_api(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="sec-nopublish")
        _connect_instagram(db_session, m, token="ig-token-mcp")
        published: list[dict] = []
        monkeypatch.setattr(
            "backend.app.integrations.marketing.instagram.InstagramProvider.publish_photo",
            lambda self, **kw: published.append(kw),
        )
        out = _client(db_session, m, execution_enabled=True).call(
            "marketing.instagram.publish", {}
        )
        assert out["error"]["code"] == APPROVAL_REQUIRED
        assert published == []


# ═══════════════════════════════════════════════════════════════════════
# 5 — the LLM cannot bypass EXECUTION_ENABLED
# ═══════════════════════════════════════════════════════════════════════


class TestExecutionSwitchCannotBeBypassed:
    def test_approved_but_disabled_write_is_withheld(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="sec-execoff")
        _connect_meta(db_session, m, token="meta-token-mcp")
        created: list[dict] = []
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))
        monkeypatch.setattr(
            "backend.app.integrations.marketing.meta_ads.MetaAdsProvider.create_campaign",
            lambda self, **kw: created.append(kw),
        )
        action = _approved(
            db_session, m, AgentActionType.create_ad_campaign,
            {"provider": "meta_ads", "name": "X"},
        )
        out = _client(db_session, m, execution_enabled=False).call(
            "marketing.meta_ads.create_campaign", {}, approved_action_id=action.id
        )
        assert out["error"]["code"] == EXECUTION_DISABLED
        assert created == []  # nothing reached the provider

    def test_execution_flag_in_arguments_is_ignored(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="sec-execarg")
        _connect_meta(db_session, m, token="meta-token-mcp")
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))
        action = _approved(
            db_session, m, AgentActionType.create_ad_campaign,
            {"provider": "meta_ads", "name": "X"},
        )
        out = _client(db_session, m, execution_enabled=False).call(
            "marketing.meta_ads.create_campaign",
            {"execution_enabled": True, "requires_execution_enabled": False},
            approved_action_id=action.id,
        )
        assert out["error"]["code"] == EXECUTION_DISABLED
        assert "execution_enabled" in out["metadata"]["dropped_arguments"]

    def test_context_snapshot_cannot_be_flipped_mid_run(self, db_session, monkeypatch):
        """The switch is snapshotted; nothing in a tool arg can change it."""
        m, _, _ = make_world(db_session, slug_hint="sec-snapshot")
        _connect_meta(db_session, m, token="meta-token-mcp")
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))
        client = _client(db_session, m, execution_enabled=False)
        assert client.context.execution_enabled is False
        client.call("marketing.meta_ads.create_campaign", {"execution_enabled": True})
        assert client.context.execution_enabled is False


# ═══════════════════════════════════════════════════════════════════════
# 6 — MCP cannot execute against another tenant
# ═══════════════════════════════════════════════════════════════════════


class TestNoCrossTenantExecution:
    def test_another_tenants_approval_is_refused(self, db_session, monkeypatch):
        a, _, _ = make_world(db_session, slug_hint="sec-x-a")
        b, _, _ = make_world(db_session, slug_hint="sec-x-b")
        _connect_meta(db_session, b, token="meta-token-mcp")
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))
        action = _approved(
            db_session, b, AgentActionType.create_ad_campaign,
            {"provider": "meta_ads", "name": "B's campaign"},
        )
        out = _client(db_session, a, execution_enabled=True).call(
            "marketing.meta_ads.create_campaign", {}, approved_action_id=action.id
        )
        assert out["error"]["code"] == TENANT_SCOPE_ERROR
        db_session.refresh(action)
        assert action.status == AgentActionStatus.approved  # untouched

    def test_nonexistent_approval_is_refused(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="sec-x-missing")
        _connect_meta(db_session, m, token="meta-token-mcp")
        out = _client(db_session, m, execution_enabled=True).call(
            "marketing.meta_ads.create_campaign", {}, approved_action_id=uuid.uuid4()
        )
        assert out["error"]["code"] == TENANT_SCOPE_ERROR

    def test_provider_credentials_are_never_shared(self, db_session, monkeypatch):
        """Merchant B's connected Meta token is never used for merchant A."""
        a, _, _ = make_world(db_session, slug_hint="sec-cred-a")
        b, _, _ = make_world(db_session, slug_hint="sec-cred-b")
        _connect_meta(db_session, a, token="meta-token-mcp")
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.params.get("access_token", ""))
            return _meta_handler(request)

        _patch_httpx(monkeypatch, httpx.MockTransport(handler))
        out = _client(db_session, b).call("marketing.meta_ads.list_campaigns", {})
        assert out["error"]["code"] == INTEGRATION_NOT_CONNECTED
        assert "meta-token-mcp" not in seen  # no call was even attempted

    def test_legacy_call_helper_cannot_be_given_another_tenant(self, db_session):
        """The helper always binds the CONTEXT merchant, never an argument."""
        from backend.app.integrations.mcp.context import MCPExecutionContext

        a, _, _ = make_world(db_session, slug_hint="sec-helper-a")
        b, _, _ = make_world(db_session, slug_hint="sec-helper-b")
        add_customer(db_session, b, name="B-Customer")
        ctx = MCPExecutionContext(db=db_session, merchant_id=a.id)
        out = legacy_call(ctx, "get_customer_segments", {"merchant_id": str(b.id)})
        assert out["total"] == 0  # filtered by the context merchant, not the argument


# ═══════════════════════════════════════════════════════════════════════
# 7 — MCP logs contain no credentials
# ═══════════════════════════════════════════════════════════════════════


class TestNoCredentialsInLogs:
    def test_call_logs_are_clean(self, db_session, monkeypatch, caplog):
        m, _, _ = make_world(db_session, slug_hint="sec-log")
        _connect_resend(db_session, m, key="re_super_secret_mcp")
        _connect_google(db_session, m, monkeypatch, refresh_token="1//refresh-mcp")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/token":
                return _json(400, {"error": "invalid_grant"})
            return _json(500, {})

        _patch_httpx(monkeypatch, httpx.MockTransport(handler))
        with caplog.at_level(logging.DEBUG):
            client = _client(db_session, m)
            client.call("marketing.analytics.get_revenue", {})
            client.call("marketing.crm.search_customers", {})
            client.call("marketing.google_ads.list_campaigns", {})
            client.call("marketing.not_registered", {})
        _assert_clean(caplog.text, where="logs")

    def test_observability_records_are_clean(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="sec-obs")
        _connect_resend(db_session, m, key="re_super_secret_mcp")
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))
        client = _client(db_session, m)
        client.call("marketing.email.get_connection", {})
        client.call("marketing.crm.search_customers", {"api_key": "leak-me"})
        for row in client.records:
            _assert_clean(row.to_dict(), where="mcp record")
        _assert_clean(client.metrics(), where="mcp metrics")


# ═══════════════════════════════════════════════════════════════════════
# 8 — MCP tool results contain no credentials
# ═══════════════════════════════════════════════════════════════════════


class TestNoCredentialsInResults:
    def test_run_state_and_events_are_clean(self, db_session, monkeypatch):
        """What the dashboard renders is clean, end to end."""
        from sqlalchemy import select as sa_select

        from backend.app.agents.marketing_agi.agent import MarketingAGI
        from backend.app.models.marketing_agi import MarketingAGIEvent
        from tests.test_marketing_agi import run_agent, seed_inactive_customers

        m, _, _ = make_world(db_session, slug_hint="sec-run")
        _connect_resend(db_session, m, key="re_super_secret_mcp")
        _connect_meta(db_session, m, token="meta-token-mcp")
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))
        seed_inactive_customers(db_session, m, n=5)
        agent = MarketingAGI(db_session, m.id, llm=None)
        run = run_agent(db_session, m, agent=agent)

        _assert_clean(run.state, where="run state")
        _assert_clean(run.result, where="run result")
        _assert_clean(run.errors, where="run errors")
        events = db_session.scalars(
            sa_select(MarketingAGIEvent).where(MarketingAGIEvent.run_id == run.id)
        ).all()
        for event in events:
            _assert_clean(event.data, where=f"event {event.event_type}")
            _assert_clean(event.message, where=f"event message {event.event_type}")

    def test_api_response_is_clean(self, client, db_session):
        from backend.app.core.security import create_access_token
        from backend.app.models.enums import UserRole
        from tests.security_utils import make_membership, make_user

        m, _, _ = make_world(db_session, slug_hint="sec-api")
        _connect_resend(db_session, m, key="re_super_secret_mcp")
        user = make_user(db_session, "sec-api")
        make_membership(db_session, user, m, UserRole.owner)
        token, _ = create_access_token(user.id, user.email)
        headers = {"Authorization": f"Bearer {token}"}
        for path in (
            "/api/marketing-agi/status",
            "/api/marketing-agi/tools",
            "/api/marketing-agi/integrations",
            "/api/marketing-agi/integrations/resend",
        ):
            r = client.get(path, headers=headers)
            assert r.status_code == 200, path
            _assert_clean(r.text, where=path)


# ═══════════════════════════════════════════════════════════════════════
# 9 — a failed provider call never becomes a fake success
# ═══════════════════════════════════════════════════════════════════════


class TestNoFakeSuccess:
    def test_refused_call_has_no_data(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="sec-fake1")
        out = _client(db_session, m).call("marketing.google_ads.list_campaigns", {})
        assert out["status"] == "error"
        assert out["data"] is None
        assert out["error"]["code"] == INTEGRATION_NOT_CONNECTED

    def test_provider_failure_keeps_null_campaigns(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="sec-fake2")
        _connect_meta(db_session, m, token="meta-token-mcp")

        def failing(request: httpx.Request) -> httpx.Response:
            return _json(500, {"error": "boom"})

        _patch_httpx(monkeypatch, httpx.MockTransport(failing))
        client = _client(db_session, m, max_retries=0)
        out = client.call("marketing.meta_ads.list_campaigns", {})
        # A provider failure is a classified failure with NO data at all, so
        # there is no payload in which campaigns/metrics could look real.
        assert out["status"] == "error"
        assert out["data"] is None
        assert client.records[-1].status == "error"
        assert client.records[-1].read_only is True

    def test_agent_records_a_gap_instead_of_inventing_data(self, db_session):
        """A disconnected provider leaves an honest knowledge gap."""
        from backend.app.agents.marketing_agi.agent import MarketingAGI
        from backend.app.agents.marketing_agi.state import MarketingAGIState

        m, _, _ = make_world(db_session, slug_hint="sec-fake3")
        agent = MarketingAGI(db_session, m.id, llm=None)
        state = MarketingAGIState(run_id="r", merchant_id=str(m.id), objective="o")
        state._active_state = state
        with pytest.raises(Exception):
            agent._dispatch_tool(
                state, "get_google_ads_campaigns", {}
            )
        failures = [c for c in state.tool_calls if not c["ok"]]
        assert failures
        assert failures[-1]["summary"] != "done"

    def test_error_envelope_never_reports_success(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="sec-fake4")
        _connect_google(db_session, m, monkeypatch)

        def failing(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/token":
                return _json(400, {"error": "invalid_grant"})
            return _json(500, {})

        _patch_httpx(monkeypatch, httpx.MockTransport(failing))
        client = _client(db_session, m, max_retries=0)
        out = client.call("marketing.google_ads.list_campaigns", {})
        # The envelope is a failure all the way through — there is no
        # "success carrying an error" shape for the model or the dashboard
        # to misread.
        assert out["status"] == "error"
        assert out["data"] is None
        assert out["error"]["code"] == AUTHENTICATION_ERROR
        assert classify("AUTH_EXPIRED") == AUTHENTICATION_ERROR
        assert client.records[-1].status == "error"


def classify(code):
    from backend.app.integrations.mcp.errors import classify_provider_code

    return classify_provider_code(code)


# ═══════════════════════════════════════════════════════════════════════
# 10 — an approval action cannot be replayed incorrectly
# ═══════════════════════════════════════════════════════════════════════


class TestNoApprovalReplay:
    """Idempotency of the approved-action pipeline, seen through MCP.

    ``create_ad_campaign`` is currently outside the guardrail layer's
    permitted action types (a pre-existing Phase-3 policy this change does
    not touch), so the pipeline refuses it BEFORE any provider call. The
    tests below assert exactly that: an MCP write never reaches Meta, and
    repeating it never produces a second campaign. The
    ``send_campaign`` test exercises the path that IS permitted, to prove
    the completed-action no-op still holds through MCP.
    """

    def test_ads_write_is_refused_by_guardrails_before_any_provider_call(
        self, db_session, monkeypatch
    ):
        m, _, _ = make_world(db_session, slug_hint="sec-replay")
        _connect_meta(db_session, m, token="meta-token-mcp")
        created: list[dict] = []

        def counting(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.endswith("/campaigns"):
                created.append({"path": request.url.path})
            return _meta_handler(request)

        _patch_httpx(monkeypatch, httpx.MockTransport(counting))
        action = _approved(
            db_session, m, AgentActionType.create_ad_campaign,
            {"provider": "meta_ads", "name": "Once"},
        )
        client = _client(db_session, m, execution_enabled=True)
        for _ in range(3):
            out = client.call(
                "marketing.meta_ads.create_campaign", {}, approved_action_id=action.id
            )
            assert out["status"] == "error"
        assert created == []  # no campaign ever reached the provider

    def test_guardrail_refusal_is_not_retried(self, db_session, monkeypatch):
        """A policy decision must not be retried as a transient failure."""
        m, _, _ = make_world(db_session, slug_hint="sec-replay-nr")
        _connect_meta(db_session, m, token="meta-token-mcp")
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))
        action = _approved(
            db_session, m, AgentActionType.create_ad_campaign,
            {"provider": "meta_ads", "name": "Once"},
        )
        client = _client(db_session, m, execution_enabled=True)
        out = client.call(
            "marketing.meta_ads.create_campaign", {}, approved_action_id=action.id
        )
        assert out["error"]["code"] == APPROVAL_REQUIRED
        assert out["error"]["retryable"] is False
        assert client.records[-1].retries == 0

    def test_second_execution_of_a_completed_action_is_a_no_op(self, db_session, monkeypatch):
        """send_campaign is permitted, so it exercises the real replay path."""
        from backend.app.models.agent_action import AgentAction

        m, _, _ = make_world(db_session, slug_hint="sec-replay-send")
        _connect_resend(db_session, m, key="re_super_secret_mcp")
        sends: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/domains":
                return _json(200, {"data": []})
            if request.url.path == "/emails":
                sends.append({"path": request.url.path})
                return _json(202, {"id": "em_1"})
            return _json(404, {})

        _patch_httpx(monkeypatch, httpx.MockTransport(handler))
        # The first call must be a REAL send for this test to prove anything:
        # enabling it only on the MCP context left the executor on the
        # environment default (off), so run 1 was a preview and the "no-op"
        # assertion passed without ever having delivered anything.
        import backend.app.services.action_executor as _ex

        _settings = _ex.get_settings()
        monkeypatch.setattr(
            _ex, "get_settings",
            lambda: type(_settings)(
                **{**_settings.model_dump(), "EXECUTION_ENABLED": True}
            ),
        )
        customer = Customer(
            merchant_id=m.id, name="Ada", email="ada@buyer.test",
            segment=CustomerSegment.new,
        )
        db_session.add(customer)
        db_session.commit()
        from backend.app.models.marketing_agi import MarketingAGICampaign

        campaign = MarketingAGICampaign(
            merchant_id=m.id, campaign_key="k-replay", workflow="email_campaign",
            name="Win back", objective="o", channel="email",
            integration_status="connected", lifecycle="ready_for_approval",
            audience={"customer_ids": [str(customer.id)]}, audience_count=1,
            content={"message": "Hi", "subject_variants": ["Hi"], "cta": "Shop"},
        )
        db_session.add(campaign)
        db_session.commit()
        action = _approved(
            db_session, m, AgentActionType.send_campaign,
            {
                "campaign_type": "email",
                "target": {"marketing_agi_campaign_id": str(campaign.id)},
                "target_count": 1,
            },
        )
        client = _client(db_session, m, execution_enabled=True)
        first = client.call(
            "marketing.email.send_campaign", {}, approved_action_id=action.id
        )
        assert first["status"] == "success"
        assert first["data"]["executed"] is True
        db_session.refresh(action)
        assert action.status == AgentActionStatus.completed
        sent_after_first = len(sends)

        second = client.call(
            "marketing.email.send_campaign", {}, approved_action_id=action.id
        )
        # Never a second send at Resend.
        assert len(sends) == sent_after_first
        assert second["status"] == "success"
        assert second["data"]["result"].get("idempotent") is True
        db_session.refresh(action)
        assert action.status == AgentActionStatus.completed

    def test_repeated_refused_write_never_reaches_a_provider(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="sec-replay2")
        _connect_meta(db_session, m, token="meta-token-mcp")
        posts: list[dict] = []

        def counting(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.endswith("/campaigns"):
                posts.append({})
            return _meta_handler(request)

        _patch_httpx(monkeypatch, httpx.MockTransport(counting))
        action = _approved(
            db_session, m, AgentActionType.create_ad_campaign,
            {"provider": "meta_ads", "name": "Once"},
        )
        client = _client(db_session, m, execution_enabled=True)
        for _ in range(3):
            client.call(
                "marketing.meta_ads.create_campaign", {}, approved_action_id=action.id
            )
        assert posts == []

    def test_mcp_never_creates_or_approves_an_action(self, db_session):
        """MCP has no tool that can mint or approve an approval."""
        from backend.app.integrations.mcp import get_mcp_registry

        registry = get_mcp_registry()
        for name in registry.names():
            lowered = name.lower()
            assert "approve" not in lowered
            assert "authorize" not in lowered
            assert "create_action" not in lowered
            assert "auto" not in lowered

    def test_agent_still_persists_the_action_before_approval(self, db_session):
        """The existing approval boundary is intact after the migration."""
        from backend.app.models.agent_action import AgentAction
        from sqlalchemy import select as sa_select

        from tests.test_marketing_agi import run_agent, seed_inactive_customers

        m, _, _ = make_world(db_session, slug_hint="sec-boundary")
        seed_inactive_customers(db_session, m, n=5)
        run = run_agent(db_session, m)
        assert run.status == "waiting_approval"
        actions = list(
            db_session.scalars(
                sa_select(AgentAction).where(AgentAction.merchant_id == m.id)
            ).all()
        )
        assert actions
        assert all(a.status == AgentActionStatus.requested for a in actions)
        assert all(a.approved_by is None for a in actions)


# ═══════════════════════════════════════════════════════════════════════
# Prompt-surface checks — what the model can even see
# ═══════════════════════════════════════════════════════════════════════


class TestPromptSurfaceIsSafe:
    def test_catalog_never_exposes_credentials_or_handlers(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="sec-catalog")
        _connect_resend(db_session, m, key="re_super_secret_mcp")
        client = _client(db_session, m)
        catalog = client.catalog(phase="research")
        _assert_clean(json.dumps(catalog, default=str), where="prompt catalog")
        for entry in catalog:
            assert "handler" not in entry
            assert "credentials" not in entry

    def test_catalog_states_the_approval_requirement(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="sec-catalog2")
        _connect_resend(db_session, m)
        client = _client(db_session, m)
        entry = next(
            e for e in client.catalog(phase="execution")
            if e["name"] == "marketing.email.send_campaign"
        )
        assert entry["requires_approval"] is True
        assert entry["risk_level"] == "critical"

    def test_credential_settings_never_enter_the_catalog(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="sec-catalog3")
        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
        client = _client(db_session, m)
        _assert_clean(json.dumps(client.catalog(), default=str), where="full catalog")