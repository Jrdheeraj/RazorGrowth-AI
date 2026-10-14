"""MCP tool connectivity layer — unit, policy and integration coverage.

Covers the layers the migration added, without changing any existing
behaviour:

  discovery       phase-scoped catalog, allowlists, legacy aliases
  schemas         input validation, normalization, redaction, truncation
  policy          unknown tool, tenant scope, integration, approval,
                  EXECUTION_ENABLED gating — in the declared order
  clients         retries, Retry-After, timeouts, provider errors,
                  degraded providers, per-run read cache
  observability   one safe record per call; no secrets anywhere
  integration     the Marketing Agent's tools now run through MCP; the
                  agentic RAG loop and a full cycle still behave exactly
                  as before

Every external provider call is mocked at the HTTP boundary — no test here
fabricates a "connected" provider by pretending.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from backend.app.core import credential_vault as vault
from backend.app.integrations.mcp import bridge as mcp_bridge
from backend.app.integrations.mcp import policy as mcp_policy
from backend.app.integrations.mcp.client import (
    MCPClient,
    MCPToolCallRecord,
    normalize_result,
)
from backend.app.integrations.mcp.context import MCPExecutionContext
from backend.app.integrations.mcp.domains import capability_domain
from backend.app.integrations.mcp.errors import (
    APPROVAL_REQUIRED,
    AUTHENTICATION_ERROR,
    AUTHORIZATION_ERROR,
    CONFIGURATION_ERROR,
    EXECUTION_DISABLED,
    INTEGRATION_NOT_CONNECTED,
    PROVIDER_ERROR,
    RATE_LIMITED,
    TENANT_SCOPE_ERROR,
    TIMEOUT,
    TOOL_NOT_ALLOWED,
    VALIDATION_ERROR,
    MCPError,
    ProviderCallError,
    classify_provider_code,
)
from backend.app.integrations.mcp.observability import MCPLedger
from backend.app.integrations.mcp.registry import get_mcp_registry
from backend.app.integrations.mcp.schemas import MCPToolSpec
from backend.app.integrations.mcp.servers.base import legacy_call
from backend.app.models.customer import Customer
from backend.app.models.enums import CustomerSegment
from backend.app.services import integration_service as svc
from tests.security_utils import make_world
from tests.test_marketing_agi import (
    add_customer,
    run_agent,
    seed_inactive_customers,
    start_run_row,
)

# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _client(db, merchant, **kw) -> MCPClient:
    """MCP client bound to one authenticated merchant."""
    return mcp_bridge.build_client(db, merchant.id, **kw)


def _json(status: int, payload: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        headers=headers or {},
        request=httpx.Request("GET", "https://mock.local/"),
    )


def _patch_httpx(monkeypatch, transport: httpx.MockTransport) -> None:
    """Route every httpx.Client through a mock transport.

    Needed for provider READS: the stored connection is real, but the API
    call it authorises is mocked at the HTTP boundary so no test needs
    credentials or network access.
    """
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )


def _resend_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/domains":
        return _json(200, {"data": [{"id": "d1", "name": "acme.test", "status": "verified"}]})
    return _json(404, {"message": "not found"})


def _connect_resend(db, merchant, key: str = "re_test_mcp_key"):
    """Connect Resend for this merchant using the REAL connection service."""
    row, result = svc.connect_resend(
        db,
        merchant.id,
        actor="owner@test",
        api_key=key,
        from_email="brand@acme.test",
        from_name="Acme",
        transport=httpx.MockTransport(_resend_handler),
    )
    assert row is not None and result.ok
    return row


def _meta_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/me/adaccounts"):
        return _json(200, {"data": [{"id": "act_1001", "name": "Acme Ads", "account_status": 1}]})
    if request.url.path.endswith("/campaigns") and request.method == "GET":
        return _json(200, {"data": [
            {"id": "camp_9", "name": "Spring", "status": "PAUSED", "objective": "OUTCOME_TRAFFIC"}
        ]})
    if request.url.path.endswith("/campaigns"):
        return _json(200, {"id": "camp_new"})
    if request.url.path.endswith("/insights"):
        return _json(200, {"data": [{"impressions": "10", "clicks": "2", "spend": "5.00"}]})
    return _json(404, {})


def _connect_meta(db, merchant, token: str = "meta-token-mcp"):
    row, result = svc.connect_token(
        db,
        merchant.id,
        actor="owner@test",
        provider="meta_ads",
        access_token=token,
        transport=httpx.MockTransport(_meta_handler),
    )
    assert row is not None and result.ok
    return row


def _instagram_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/me/accounts"):
        return _json(200, {"data": [{
            "id": "page_1",
            "name": "Acme",
            "instagram_business_account": {"id": "ig_7", "username": "acme_brand"},
        }]})
    if request.url.path.endswith("/media"):
        return _json(200, {"id": "container_1"})
    if request.url.path.endswith("/media_publish"):
        return _json(200, {"id": "media_1"})
    return _json(404, {})


def _connect_instagram(db, merchant, token: str = "ig-token-mcp"):
    row, result = svc.connect_token(
        db,
        merchant.id,
        actor="owner@test",
        provider="instagram",
        access_token=token,
        transport=httpx.MockTransport(_instagram_handler),
    )
    assert row is not None and result.ok
    return row


def _connect_google(db, merchant, monkeypatch, refresh_token: str = "1//refresh-mcp"):
    """Store a real encrypted Google Ads connection row."""
    from backend.app.core.config import get_settings

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "dev-token-mcp")
    get_settings.cache_clear()
    row = svc._upsert_row(
        db,
        merchant.id,
        "google_ads",
        status="connected",
        account_id="111",
        account_name="Acme Ads",
        creds={"refresh_token": refresh_token, "developer_token": "dev-token-mcp"},
        metadata={"customer_id": "111"},
        last_error=None,
        verified=True,
    )
    db.commit()
    return row


# ═══════════════════════════════════════════════════════════════════════
# Discovery + registry
# ═══════════════════════════════════════════════════════════════════════


class TestMCPRegistry:
    def test_all_tool_names_are_namespaced_and_stable(self):
        from backend.app.integrations.mcp.domains import DOMAINS

        registry = get_mcp_registry()
        names = registry.names()
        assert names == sorted(names)
        for name in names:
            # Every tool lives in a REGISTERED capability domain. The
            # registry now holds more than one namespace (marketing plus the
            # Product Agent's commerce / analytics / product_intelligence),
            # so the invariant is "known domain prefix", not "the marketing
            # one". Channel servers keep the 3-segment
            # `domain.<server>.<tool>` shape; a domain-namespaced server uses
            # `domain.<tool>` and is served by the internal server.
            parts = name.split(".")
            assert parts[0] in DOMAINS, name
            assert len(parts) >= 2, name
            if parts[0] == "marketing":
                assert len(parts) >= 3, name

    def test_every_provider_surface_is_exposed(self):
        names = set(get_mcp_registry().names())
        # Internal CRM + analytics.
        assert {"marketing.crm.search_customers", "marketing.crm.get_customer",
                "marketing.crm.get_segment"} <= names
        assert {"marketing.analytics.get_revenue", "marketing.analytics.get_orders",
                "marketing.analytics.get_failed_payments",
                "marketing.analytics.get_customer_retention"} <= names
        # External providers.
        assert "marketing.email.send_campaign" in names
        assert {"marketing.google_ads.list_campaigns",
                "marketing.google_ads.create_campaign"} <= names
        assert {"marketing.meta_ads.list_campaigns",
                "marketing.meta_ads.create_campaign"} <= names
        assert {"marketing.instagram.get_account",
                "marketing.instagram.publish"} <= names

    def test_legacy_tool_names_resolve_to_mcp(self):
        registry = get_mcp_registry()
        assert registry.spec("find_customers").name == "marketing.crm.search_customers"
        assert registry.spec("get_business_overview").name == "marketing.analytics.get_revenue"
        assert registry.spec("get_google_ads_campaigns").name == (
            "marketing.google_ads.list_campaigns"
        )
        assert registry.spec("get_social_performance").name == (
            "marketing.instagram.get_account"
        )

    def test_bridge_resolves_legacy_names_only(self):
        assert mcp_bridge.resolve("get_failed_payment_analytics") == (
            "marketing.analytics.get_failed_payments"
        )
        assert mcp_bridge.is_mcp_tool("recall_memory") is True
        # An orchestration pseudo-tool is not an MCP data tool.
        assert mcp_bridge.resolve("verifier") is None

    def test_phase_catalogs_are_scoped(self):
        registry = get_mcp_registry()
        observe = {c["name"] for c in registry.catalog(phase="observe")}
        execution = {c["name"] for c in registry.catalog(phase="execution")}
        assert "marketing.analytics.get_revenue" in observe
        # The execution phase exposes ONLY external writes.
        assert execution == {
            "marketing.email.send_campaign",
            "marketing.google_ads.create_campaign",
            "marketing.meta_ads.create_campaign",
            "marketing.instagram.publish",
        }
        assert all(
            not get_mcp_registry().spec(n).read_only for n in execution
        )

    def test_write_tools_excluded_from_read_only_catalog(self):
        names = {
            c["name"]
            for c in get_mcp_registry().catalog(include_write=False)
        }
        assert "marketing.email.draft_campaign" not in names
        assert "marketing.analytics.get_revenue" in names

    def test_catalog_entry_never_leaks_the_handler(self):
        for entry in get_mcp_registry().catalog():
            assert "handler" not in entry
            assert set(entry) == {
                "name", "description", "domain", "capability_domain",
                "provider", "phase",
                "read_only", "requires_approval", "requires_integration",
                "risk_level", "timeout_seconds", "max_retries",
                "input_schema",
            }
            assert entry["domain"] == entry["name"].split(".", 1)[0]
            assert entry["capability_domain"] == capability_domain(entry["name"])
            assert entry["timeout_seconds"] > 0
            assert entry["max_retries"] >= 0

    def test_allowlists_partition_the_registry(self):
        sets = mcp_policy.allowlists()
        names = set(get_mcp_registry().names())
        assert sets["read"] | sets["write"] == names
        assert not (sets["read"] & sets["write"])
        assert sets["internal"] | sets["external"] == names
        assert sets["approval_required"] <= sets["write"]

    def test_external_writes_are_approval_gated(self):
        registry = get_mcp_registry()
        for name in mcp_policy.allowlists()["approval_required"]:
            spec = registry.spec(name)
            assert spec.read_only is False
            assert spec.requires_approval is True
            assert spec.requires_execution_enabled is True
            assert spec.risk_level in {"high", "critical"}

    def test_spec_rejects_an_ungated_external_write(self):
        # An external side effect must be claimed explicitly (external_write
        # defaults to False), and claiming it without the approval +
        # execution guardrails is a declaration error.
        with pytest.raises(ValueError):
            MCPToolSpec(
                name="marketing.test.ungated",
                description="write without approval",
                provider="resend",
                handler=lambda **_: {},
                read_only=False,
                external_write=True,
                requires_approval=False,
                requires_execution_enabled=True,
                risk_level="high",
            )

    def test_spec_rejects_a_read_only_tool_claiming_an_external_write(self):
        # read_only gates BOTH the approval gate (policy returns early) and
        # the read cache. A spec claiming both would be an ungated, cacheable
        # external write, so the combination must be unrepresentable.
        with pytest.raises(ValueError):
            MCPToolSpec(
                name="marketing.test.readonlywrite",
                description="read-only but claims an external write",
                provider="resend",
                handler=lambda **_: {},
                read_only=True,
                external_write=True,
            )

    def test_external_write_must_be_opted_into(self):
        """A write with no external side effect needs no approval gate."""
        spec = MCPToolSpec(
            name="marketing.test.localwrite",
            description="local draft write",
            provider="internal",
            handler=lambda **_: {},
            read_only=False,
        )
        assert spec.external_write is False
        assert spec.requires_approval is False

    def test_spec_rejects_non_namespaced_name(self):
        with pytest.raises(ValueError):
            MCPToolSpec(
                name="naked_tool",
                description="no namespace",
                provider="internal",
                handler=lambda **_: {},
            )


# ═══════════════════════════════════════════════════════════════════════
# Allowlist enforcement
# ═══════════════════════════════════════════════════════════════════════


class TestAllowlist:
    def test_unknown_tool_is_refused_and_recorded(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-unknown")
        client = _client(db_session, m)
        out = client.call("marketing.crm.drop_everything", {})
        assert out["status"] == "error"
        assert out["error"]["code"] == TOOL_NOT_ALLOWED
        assert out["data"] is None
        assert client.records[-1].status == "denied"

    def test_llm_cannot_call_a_non_mcp_name(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-raw")
        client = _client(db_session, m)
        out = client.call("os.system", {"cmd": "rm -rf /"})
        assert out["status"] == "error"
        assert out["error"]["code"] == TOOL_NOT_ALLOWED

    def test_unregistered_legacy_tool_is_refused(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-nolegacy")
        client = _client(db_session, m)
        out = client.call("drop_all_tables", {})
        assert out["error"]["code"] == TOOL_NOT_ALLOWED


# ═══════════════════════════════════════════════════════════════════════
# Schema validation
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaValidation:
    def test_missing_required_argument(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-req")
        add_customer(db_session, m, name="Ada")
        client = _client(db_session, m)
        out = client.call("marketing.crm.get_customer", {})
        assert out["error"]["code"] == VALIDATION_ERROR
        assert "customer_id" in out["error"]["message"]

    def test_wrong_type_is_refused(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-type")
        client = _client(db_session, m)
        out = client.call(
            "marketing.crm.search_customers", {"min_orders": "lots"}
        )
        assert out["error"]["code"] == VALIDATION_ERROR

    def test_out_of_range_is_refused(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-range")
        client = _client(db_session, m)
        out = client.call("marketing.analytics.get_orders", {"window_days": 99999})
        assert out["error"]["code"] == VALIDATION_ERROR

    def test_unknown_argument_is_stripped_and_reported(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-extra")
        add_customer(db_session, m, name="Ada")
        client = _client(db_session, m)
        out = client.call("marketing.analytics.get_orders", {"nonsense": 1})
        assert out["status"] == "success"
        assert out["metadata"]["dropped_arguments"] == ["nonsense"]

    def test_defaults_are_applied(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-default")
        client = _client(db_session, m)
        out = client.call("marketing.analytics.get_revenue", {})
        assert out["status"] == "success"
        assert out["data"]["window_days"] == 90

    def test_read_tools_run_against_real_tenant_data(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-read")
        add_customer(db_session, m, name="Ada", total_orders=3, total_spend="1500")
        client = _client(db_session, m)
        segments = client.call("marketing.crm.get_segment", {})
        assert segments["status"] == "success"
        assert segments["data"]["total"] == 1
        found = client.call(
            "marketing.crm.search_customers", {"min_orders": 2}
        )
        assert found["data"]["audience_count"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Tenant isolation
# ═══════════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    def test_model_supplied_merchant_id_is_stripped(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-tenant1")
        other, _, _ = make_world(db_session, slug_hint="mcp-tenant2")
        add_customer(db_session, m, name="Mine")
        add_customer(db_session, other, name="Theirs")
        client = _client(db_session, m)
        out = client.call(
            "marketing.crm.search_customers",
            {"merchant_id": str(other.id)},
        )
        assert out["status"] == "success"
        assert out["metadata"]["dropped_arguments"] == ["merchant_id"]
        names = [c["name"] for c in out["data"]["customers"]]
        assert names == ["Mine"]  # never the other workspace's customer

    def test_credential_arguments_are_stripped(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-creds")
        add_customer(db_session, m, name="Ada")
        client = _client(db_session, m)
        out = client.call(
            "marketing.crm.search_customers",
            {"access_token": "stolen", "api_key": "stolen", "client_secret": "s"},
        )
        assert out["status"] == "success"
        dropped = set(out["metadata"]["dropped_arguments"])
        assert {"access_token", "api_key", "client_secret"} <= dropped
        assert "stolen" not in str(out)

    def test_context_without_merchant_is_refused(self, db_session):
        """A context that never bound a merchant cannot invoke anything."""
        ctx = MCPExecutionContext(db=db_session, merchant_id=None)  # type: ignore[arg-type]
        client = MCPClient(ctx)
        out = client.call("marketing.analytics.get_revenue", {})
        assert out["error"]["code"] == TENANT_SCOPE_ERROR

    def test_two_workspaces_never_see_each_others_data(self, db_session):
        a, _, _ = make_world(db_session, slug_hint="mcp-a")
        b, _, _ = make_world(db_session, slug_hint="mcp-b")
        add_customer(db_session, a, name="A-Only")
        add_customer(db_session, b, name="B-Only")
        for merchant, expected in ((a, "A-Only"), (b, "B-Only")):
            out = _client(db_session, merchant).call(
                "marketing.crm.search_customers", {}
            )
            assert [c["name"] for c in out["data"]["customers"]] == [expected]

    def test_cached_result_is_tenant_bound(self, db_session):
        a, _, _ = make_world(db_session, slug_hint="mcp-ca")
        b, _, _ = make_world(db_session, slug_hint="mcp-cb")
        add_customer(db_session, a, name="A-Only")
        first = _client(db_session, a).call("marketing.crm.get_segment", {})
        assert first["data"]["total"] == 1
        # A fresh client for a different merchant must not see the cache.
        second = _client(db_session, b).call("marketing.crm.get_segment", {})
        assert second["data"]["total"] == 0

    def test_run_cache_is_not_shared_between_runs(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-runcache")
        add_customer(db_session, m, name="Ada")
        client = _client(db_session, m)
        first = client.call("marketing.crm.get_segment", {})
        assert first["metadata"]["cache_hit"] is False
        second = client.call("marketing.crm.get_segment", {})
        assert second["metadata"]["cache_hit"] is True
        client.clear_run_state()
        third = client.call("marketing.crm.get_segment", {})
        assert third["metadata"]["cache_hit"] is False


# ═══════════════════════════════════════════════════════════════════════
# Approval + execution gates
# ═══════════════════════════════════════════════════════════════════════


class TestApprovalAndExecutionGates:
    def test_external_write_refused_without_approval(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-noapprov")
        _connect_meta(db_session, m)
        client = _client(db_session, m, execution_enabled=True)
        out = client.call("marketing.meta_ads.create_campaign", {})
        assert out["status"] == "error"
        assert out["error"]["code"] == APPROVAL_REQUIRED
        assert out["error"]["retryable"] is False

    def test_external_write_refused_when_execution_disabled(self, db_session):
        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import AgentActionStatus, AgentActionType

        m, _, _ = make_world(db_session, slug_hint="mcp-noexec")
        _connect_meta(db_session, m)
        action = AgentAction(
            merchant_id=m.id,
            action_type=AgentActionType.create_ad_campaign,
            status=AgentActionStatus.approved,
            input_payload={
                "merchant_id": str(m.id),
                "provider": "meta_ads",
                "name": "Spring",
                "objective": "OUTCOME_TRAFFIC",
            },
            requested_by="agent:test",
            approved_by="owner@test",
        )
        db_session.add(action)
        db_session.commit()
        client = _client(db_session, m, execution_enabled=False)
        out = client.call(
            "marketing.meta_ads.create_campaign", {}, approved_action_id=action.id
        )
        assert out["error"]["code"] == EXECUTION_DISABLED

    def test_approved_action_of_another_tenant_is_refused(self, db_session):
        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import AgentActionStatus, AgentActionType

        a, _, _ = make_world(db_session, slug_hint="mcp-own-a")
        b, _, _ = make_world(db_session, slug_hint="mcp-own-b")
        _connect_meta(db_session, b)
        action = AgentAction(
            merchant_id=b.id,
            action_type=AgentActionType.create_ad_campaign,
            status=AgentActionStatus.approved,
            input_payload={"merchant_id": str(b.id), "provider": "meta_ads", "name": "X"},
            requested_by="agent:test",
            approved_by="owner@test",
        )
        db_session.add(action)
        db_session.commit()
        client = _client(db_session, a, execution_enabled=True)
        out = client.call(
            "marketing.meta_ads.create_campaign", {}, approved_action_id=action.id
        )
        assert out["error"]["code"] == TENANT_SCOPE_ERROR

    def test_unapproved_action_cannot_be_executed_through_mcp(self, db_session):
        """The MCP write tool delegates to the action pipeline, which
        refuses a 'requested' action — approval cannot be bypassed."""
        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import AgentActionStatus, AgentActionType

        m, _, _ = make_world(db_session, slug_hint="mcp-requested")
        _connect_meta(db_session, m)
        action = AgentAction(
            merchant_id=m.id,
            action_type=AgentActionType.create_ad_campaign,
            status=AgentActionStatus.requested,
            input_payload={"merchant_id": str(m.id), "provider": "meta_ads", "name": "X"},
            requested_by="agent:MarketingAGI",
        )
        db_session.add(action)
        db_session.commit()
        client = _client(db_session, m, execution_enabled=True)
        out = client.call(
            "marketing.meta_ads.create_campaign", {}, approved_action_id=action.id
        )
        assert out["status"] == "error"
        # The action was refused by the existing pipeline, not executed.
        db_session.refresh(action)
        assert action.status != AgentActionStatus.completed

    def test_email_send_is_gated_before_any_provider_call(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="mcp-emailgate")
        _connect_resend(db_session, m)
        called = []
        monkeypatch.setattr(
            "backend.app.integrations.marketing.resend_email.ResendProvider.send_email",
            lambda self, **kw: called.append(kw) or None,
        )
        client = _client(db_session, m, execution_enabled=True)
        out = client.call("marketing.email.send_campaign", {})
        assert out["error"]["code"] == APPROVAL_REQUIRED
        assert called == []  # nothing reached Resend

    def test_instagram_publish_is_gated(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-iggate")
        _connect_instagram(db_session, m)
        client = _client(db_session, m, execution_enabled=True)
        out = client.call("marketing.instagram.publish", {})
        assert out["error"]["code"] == APPROVAL_REQUIRED

    def test_google_create_is_gated(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="mcp-gogate")
        _connect_google(db_session, m, monkeypatch)
        client = _client(db_session, m, execution_enabled=True)
        out = client.call("marketing.google_ads.create_campaign", {})
        assert out["error"]["code"] == APPROVAL_REQUIRED

    def test_local_draft_write_needs_no_approval(self, db_session):
        """Persisting a draft has no external side effect, so the
        pre-existing approval boundary is unchanged."""
        m, _, _ = make_world(db_session, slug_hint="mcp-draft")
        client = _client(db_session, m)
        out = client.call(
            "marketing.email.draft_campaign",
            {
                "campaign_key": "k-mcp-1",
                "workflow": "customer_win_back",
                "name": "Win back",
                "objective": "reactivate",
                "audience": {"criteria": {"min_orders": 1}},
                "audience_count": 1,
                "content": {"message": "Hi"},
                "expected_impact": {"rationale": "test"},
                "success_metric": "purchases",
                "evidence_refs": ["e1"],
            },
        )
        assert out["status"] == "success"
        assert out["data"]["created"] is True
        spec = get_mcp_registry().spec("marketing.email.draft_campaign")
        assert spec.read_only is False
        assert spec.external_write is False
        assert spec.requires_approval is False

    def test_draft_write_is_never_cached(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-draftcache")
        client = _client(db_session, m)
        payload = {
            "campaign_key": "k-mcp-2",
            "workflow": "customer_win_back",
            "name": "Win back",
            "objective": "reactivate",
            "audience": {},
            "audience_count": 0,
            "content": {"message": "Hi"},
            "expected_impact": {},
            "success_metric": "purchases",
            "evidence_refs": [],
        }
        first = client.call("marketing.email.draft_campaign", payload)
        second = client.call("marketing.email.draft_campaign", payload)
        # Duplicate prevention is the DB's job for a write; MCP must not
        # serve it from cache.
        assert second["metadata"]["cache_hit"] is False
        assert second["data"]["status"] == "duplicate_prevented"
        assert first["data"]["campaign_id"] == second["data"]["campaign_id"]


# ═══════════════════════════════════════════════════════════════════════
# Integration connection behaviour
# ═══════════════════════════════════════════════════════════════════════


class TestConnectedProviders:
    def test_disconnected_provider_is_refused_not_faked(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-disconnected")
        client = _client(db_session, m)
        for tool in (
            "marketing.google_ads.list_campaigns",
            "marketing.meta_ads.list_campaigns",
            "marketing.instagram.get_account",
            "marketing.email.get_connection",
        ):
            out = client.call(tool, {})
            assert out["status"] == "error", tool
            assert out["error"]["code"] == INTEGRATION_NOT_CONNECTED
            assert out["data"] is None

    def test_disconnected_provider_is_absent_from_the_prompt_catalog(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-catalog")
        client = _client(db_session, m)
        names = {c["name"] for c in client.catalog(phase="research")}
        assert "marketing.google_ads.list_campaigns" not in names
        assert "marketing.meta_ads.create_campaign" not in names
        # But it stays in the execution allowlist — filtering never removes
        # a capability, only the prompt entry.
        assert "marketing.google_ads.create_campaign" in mcp_policy.allowlists()["write"]

    def test_connected_provider_appears_in_the_catalog(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-catconn")
        _connect_meta(db_session, m)
        client = _client(db_session, m)
        names = {c["name"] for c in client.catalog(phase="research")}
        assert "marketing.meta_ads.list_campaigns" in names
        assert "marketing.meta_ads.get_insights" in names
        assert "marketing.google_ads.list_campaigns" not in names

    def test_meta_campaigns_read_live_through_mcp(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="mcp-metalive")
        _connect_meta(db_session, m)
        _patch_httpx(monkeypatch, httpx.MockTransport(_meta_handler))
        client = _client(db_session, m)
        out = client.call("marketing.meta_ads.list_campaigns", {})
        assert out["status"] == "success"
        assert out["data"]["connected"] is True
        assert out["data"]["campaigns"][0]["name"] == "Spring"
        insights = client.call("marketing.meta_ads.get_insights", {})
        assert insights["data"]["insights"][0]["clicks"] == "2"

    def test_instagram_account_read_live_through_mcp(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="mcp-iglive")
        _connect_instagram(db_session, m)
        _patch_httpx(monkeypatch, httpx.MockTransport(_instagram_handler))
        client = _client(db_session, m)
        out = client.call("marketing.instagram.get_account", {})
        assert out["status"] == "success"
        assert out["data"]["account"]["username"] == "acme_brand"
        # Engagement metrics stay honestly unavailable.
        assert "impressions" in out["data"]["metrics_unavailable"]

    def test_email_connection_read_never_returns_the_key(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-resendread")
        _connect_resend(db_session, m, key="re_super_secret_mcp")
        client = _client(db_session, m)
        out = client.call("marketing.email.get_connection", {})
        assert out["status"] == "success"
        assert out["data"]["from_email"] == "brand@acme.test"
        assert "re_super_secret_mcp" not in str(out)

    def test_google_ads_read_uses_stored_encrypted_credentials(
        self, db_session, monkeypatch
    ):
        m, _, _ = make_world(db_session, slug_hint="mcp-google")
        _connect_google(db_session, m, monkeypatch)
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/token":
                seen["auth"] = request.headers.get("authorization", "")
                return _json(200, {"access_token": "ya29.mcp", "expires_in": 3600})
            if "/googleAds:search" in request.url.path:
                seen["developer_token"] = request.headers.get("developer-token", "")
                return _json(200, {"results": [{
                    "campaign": {"id": "7", "name": "Spring", "status": "PAUSED"},
                    "metrics": {"impressions": "100", "clicks": "5", "costMicros": "250000"},
                }]})
            return _json(404, {})

        _patch_httpx(monkeypatch, httpx.MockTransport(handler))
        client = _client(db_session, m)
        out = client.call("marketing.google_ads.list_campaigns", {})
        assert out["status"] == "success"
        assert out["data"]["campaigns"][0]["name"] == "Spring"
        # The refresh token stayed in the vault; only the exchanged access
        # token reached the provider.
        assert "1//refresh-mcp" not in seen.get("auth", "")
        assert seen.get("developer_token") == "dev-token-mcp"
        # ...and never appears in the result the model sees.
        assert "1//refresh-mcp" not in str(out)
        assert "ya29.mcp" not in str(out)

    def test_google_read_failure_is_honest_not_fake_success(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="mcp-googfail")
        _connect_google(db_session, m, monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/token":
                return _json(400, {"error": "invalid_grant"})
            return _json(500, {})

        _patch_httpx(monkeypatch, httpx.MockTransport(handler))
        client = _client(db_session, m, max_retries=0)
        out = client.call("marketing.google_ads.list_campaigns", {})
        # The failure is a real MCP failure, not a successful call carrying an
        # error-shaped payload: nothing was invented, and the record/event/
        # degraded-provider set all see it as a failure.
        assert out["status"] == "error"
        assert out["data"] is None
        # The adapter's own AUTH_EXPIRED code is classified (not re-labelled)
        # for the agent's reasoning.
        assert out["error"]["code"] == AUTHENTICATION_ERROR
        assert classify_provider_code("AUTH_EXPIRED") == AUTHENTICATION_ERROR
        # Never fabricated, and never a success on the observability record.
        assert out["data"] is None
        assert client.records[-1].status == "error"
        assert "google_ads" in client.context.degraded_providers


# ═══════════════════════════════════════════════════════════════════════
# Error classification
# ═══════════════════════════════════════════════════════════════════════


class TestErrorClassification:
    @pytest.mark.parametrize(
        "provider_code,expected",
        [
            ("INVALID_CREDENTIALS", AUTHENTICATION_ERROR),
            ("AUTH_EXPIRED", AUTHENTICATION_ERROR),
            ("INSUFFICIENT_PERMISSIONS", "AUTHORIZATION_ERROR"),
            ("RATE_LIMITED", RATE_LIMITED),
            ("TIMEOUT", TIMEOUT),
            ("NETWORK_ERROR", "PROVIDER_ERROR"),
            ("NOT_CONNECTED", INTEGRATION_NOT_CONNECTED),
            ("MISSING_CONFIGURATION", "CONFIGURATION_ERROR"),
            ("SOMETHING_NEW", "PROVIDER_ERROR"),
            (None, "PROVIDER_ERROR"),
        ],
    )
    def test_provider_codes_map_onto_the_taxonomy(self, provider_code, expected):
        assert classify_provider_code(provider_code) == expected

    def test_unknown_code_never_maps_to_success(self):
        for code in ("OK", "SUCCESS", "true", ""):
            assert classify_provider_code(code) == "PROVIDER_ERROR"

    def test_every_error_code_is_in_the_declared_set(self):
        from backend.app.integrations.mcp.errors import ERROR_CODES

        assert {
            AUTHENTICATION_ERROR, AUTHORIZATION_ERROR, RATE_LIMITED, TIMEOUT,
            PROVIDER_ERROR, VALIDATION_ERROR, INTEGRATION_NOT_CONNECTED,
            APPROVAL_REQUIRED, EXECUTION_DISABLED, TENANT_SCOPE_ERROR,
            TOOL_NOT_ALLOWED, CONFIGURATION_ERROR,
        } <= ERROR_CODES

    @staticmethod
    def _patch_handler(monkeypatch, tool_name: str, handler) -> None:
        """Swap one tool's handler without touching the frozen spec.

        The registry stays intact (the tool is still allowlisted); only the
        behaviour under test changes, so policy/envelope code runs for real.
        """
        from backend.app.integrations.mcp import registry as registry_mod

        patched = MCPToolSpec(
            name=tool_name,
            description="test double",
            provider="internal",
            handler=handler,
            input_schema=get_mcp_registry().spec(tool_name).input_schema,
            output_schema={"type": "object"},
        )
        # monkeypatch.setitem restores the real spec afterwards, so one test's
        # double can never leak into the next one.
        monkeypatch.setitem(registry_mod._REGISTRY._specs, tool_name, patched)

    def test_rate_limit_is_retried_with_bounded_backoff(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="mcp-retry")
        sleeps: list[float] = []
        calls = {"n": 0}

        def flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ProviderCallError(
                    "rate limited", provider_code="RATE_LIMITED", retry_after=99.0,
                    tool="marketing.crm.get_segment", provider="internal",
                )
            return {"segments": [], "total": 0}

        self._patch_handler(monkeypatch, "marketing.crm.get_segment", flaky)
        client = MCPClient(
            _client(db_session, m).context, max_retries=2,
            sleep=lambda s: sleeps.append(s),
        )
        out = client.call("marketing.crm.get_segment", {})
        assert out["status"] == "success"
        assert out["metadata"]["retries"] == 1
        # Retry-After honoured but hard-capped: no long blocking chain.
        assert sleeps and max(sleeps) <= 5.0

    def test_retries_are_bounded_and_then_reported(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="mcp-retrycap")
        calls = {"n": 0}

        def always(**kwargs):
            calls["n"] += 1
            raise ProviderCallError(
                "still limited", provider_code="RATE_LIMITED",
                tool="marketing.crm.get_segment", provider="internal",
            )

        self._patch_handler(monkeypatch, "marketing.crm.get_segment", always)
        bounded = MCPClient(
            _client(db_session, m).context, max_retries=2, sleep=lambda s: None
        )
        out = bounded.call("marketing.crm.get_segment", {})
        assert out["status"] == "error"
        assert out["error"]["code"] == RATE_LIMITED
        assert out["error"]["retryable"] is True
        assert calls["n"] == 3  # 1 attempt + exactly 2 retries

    def test_non_transient_failure_is_not_retried(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="mcp-noretry")
        calls = {"n": 0}

        def authfail(**kwargs):
            calls["n"] += 1
            raise ProviderCallError(
                "bad token", provider_code="AUTH_EXPIRED",
                tool="marketing.crm.get_segment", provider="internal",
            )

        self._patch_handler(monkeypatch, "marketing.crm.get_segment", authfail)
        out = _client(db_session, m).call("marketing.crm.get_segment", {})
        assert out["error"]["code"] == AUTHENTICATION_ERROR
        assert calls["n"] == 1  # no point retrying an auth failure

    def test_timeout_is_classified(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="mcp-timeout")

        def slow(**kwargs):
            raise ProviderCallError(
                "no response", provider_code="TIMEOUT",
                tool="marketing.crm.get_segment", provider="internal",
            )

        self._patch_handler(monkeypatch, "marketing.crm.get_segment", slow)
        out = _client(db_session, m).call("marketing.crm.get_segment", {})
        assert out["error"]["code"] == TIMEOUT

    def test_handler_crash_becomes_an_honest_failure(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="mcp-crash")

        def boom(**kwargs):
            raise RuntimeError("segment store exploded")

        self._patch_handler(monkeypatch, "marketing.crm.get_segment", boom)
        out = _client(db_session, m).call("marketing.crm.get_segment", {})
        assert out["status"] == "error"
        assert out["data"] is None
        assert "RuntimeError" in out["error"]["message"]

    def test_failed_provider_is_marked_degraded(self, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="mcp-degraded")

        def broken(**kwargs):
            raise ProviderCallError(
                "gone", provider_code="NETWORK_ERROR",
                tool="marketing.crm.get_segment", provider="internal",
            )

        self._patch_handler(monkeypatch, "marketing.crm.get_segment", broken)
        client = _client(db_session, m)
        out = client.call("marketing.crm.get_segment", {})
        assert out["status"] == "error"
        assert client.context.is_degraded("internal") is True
        assert "internal" in client.metrics()["degraded_providers"]

    def test_error_envelope_is_never_success_shaped(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-honesty")
        client = _client(db_session, m)
        out = client.call("marketing.google_ads.list_campaigns", {})
        assert out["status"] != "success"
        assert out["data"] is None
        assert out["error"]["message"]
        assert client.records[-1].status == "denied"


# ═══════════════════════════════════════════════════════════════════════
# Caching + normalization
# ═══════════════════════════════════════════════════════════════════════


class TestCachingAndNormalization:
    def test_identical_read_is_served_from_cache(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-cache1")
        add_customer(db_session, m, name="Ada")
        client = _client(db_session, m)
        first = client.call("marketing.crm.search_customers", {"min_orders": 1})
        second = client.call("marketing.crm.search_customers", {"min_orders": 1})
        assert first["metadata"]["cache_hit"] is False
        assert second["metadata"]["cache_hit"] is True
        assert second["data"] == first["data"]
        metrics = client.metrics()
        assert metrics["mcp_cache_hits"] == 1
        assert metrics["mcp_cache_misses"] == 1

    def test_different_arguments_are_not_cached_together(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-cache2")
        add_customer(db_session, m, name="Ada")
        client = _client(db_session, m)
        a = client.call("marketing.crm.search_customers", {"min_orders": 0})
        b = client.call("marketing.crm.search_customers", {"min_orders": 1})
        assert a["metadata"]["cache_hit"] is False
        assert b["metadata"]["cache_hit"] is False

    def test_cache_can_be_bypassed_for_a_fresh_read(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-cache3")
        add_customer(db_session, m, name="Ada")
        client = _client(db_session, m)
        client.call("marketing.crm.search_customers", {})
        fresh = client.call(
            "marketing.crm.search_customers", {}, use_cache=False
        )
        assert fresh["metadata"]["cache_hit"] is False

    def test_normalized_envelope_shape(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-env")
        add_customer(db_session, m, name="Ada")
        out = _client(db_session, m).call("marketing.crm.get_segment", {})
        assert set(out) >= {"tool", "status", "data", "metadata"}
        meta = out["metadata"]
        assert meta["provider"] == "internal"
        assert meta["tenant_scoped"] is True
        assert meta["read_only"] is True
        assert meta["risk_level"] == "low"

    def test_large_lists_are_summarized_not_dumped(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-trunc")
        for i in range(40):
            add_customer(db_session, m, name=f"C{i}", total_orders=1)
        out = _client(db_session, m).call("marketing.crm.search_customers", {})
        customers = out["data"]["customers"]
        # Bounded for the LLM, and it says so rather than silently cutting.
        assert isinstance(customers, dict)
        assert customers["_truncated"] is True
        assert customers["total_items"] == 40
        assert len(customers["items"]) == 25

    def test_normalizer_redacts_secret_shaped_keys(self, db_session):
        from backend.app.integrations.marketing.base import _SECRET_PATTERNS
        from backend.app.integrations.mcp.client import _redact

        payload = {
            "access_token": "leak",
            "nested": {"api_key": "leak", "safe": "ok"},
            "list": [{"refresh_token": "leak"}],
        }
        cleaned = _redact(payload)
        assert cleaned["access_token"] == "***REDACTED***"
        assert cleaned["nested"]["api_key"] == "***REDACTED***"
        assert cleaned["nested"]["safe"] == "ok"
        assert cleaned["list"][0]["refresh_token"] == "***REDACTED***"
        assert "leak" not in str(cleaned)

    def test_normalize_result_declares_the_tool(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-norm")
        spec = get_mcp_registry().spec("marketing.analytics.get_revenue")
        envelope = normalize_result(spec, {"total_revenue_inr": 10.0})
        assert envelope["tool"] == spec.name
        assert envelope["status"] == "success"


# ═══════════════════════════════════════════════════════════════════════
# Observability
# ═══════════════════════════════════════════════════════════════════════


class TestObservability:
    def test_every_call_produces_one_record(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-obs1")
        add_customer(db_session, m, name="Ada")
        client = _client(db_session, m)
        client.call("marketing.crm.get_segment", {})
        client.call("marketing.google_ads.list_campaigns", {})
        client.call("marketing.not.registered", {})
        assert [r.status for r in client.records] == ["success", "denied", "denied"]
        assert all(r.duration_ms >= 0 for r in client.records)
        assert client.records[1].error_code == INTEGRATION_NOT_CONNECTED

    def test_record_projection_has_no_credentials(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-obs2")
        _connect_resend(db_session, m, key="re_obs_secret")
        client = _client(db_session, m)
        client.call(
            "marketing.crm.search_customers",
            {"access_token": "leak", "merchant_id": str(m.id)},
        )
        row = client.records[-1].to_dict()
        dumped = str(row)
        assert "leak" not in dumped
        assert "re_obs_secret" not in dumped
        assert set(row) == {
            "tool", "server", "domain", "provider", "status", "read_only",
            "requires_approval", "risk_level", "duration_ms", "error_code",
            "error_message", "cached", "retries", "summary", "args",
            "run_id", "started_at", "approval_state", "phase",
            "analysis_cycle_id",
        }
        # Observability context is present and safe (no secrets by construction).
        assert row["domain"] == "marketing"
        assert row["started_at"]
        assert row["approval_state"] == "not_applicable"

    def test_ledger_forwards_records_and_survives_a_broken_sink(self):
        ledger = MCPLedger()
        ledger.bind(lambda record: (_ for _ in ()).throw(RuntimeError("sink")))
        record = MCPToolCallRecord(
            tool="marketing.analytics.get_revenue", server="analytics",
            provider="internal", status="success", read_only=True,
            requires_approval=False, risk_level="low",
        )
        ledger.record(record)  # must not raise
        assert ledger.records == [record]
        assert ledger.as_rows()[0]["tool"] == "marketing.analytics.get_revenue"

    def test_metrics_report_run_level_counters(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-metrics")
        add_customer(db_session, m, name="Ada")
        client = _client(db_session, m)
        client.call("marketing.crm.get_segment", {})
        client.call("marketing.crm.get_segment", {})
        metrics = client.metrics()
        assert metrics["mcp_calls"] == 2
        assert metrics["mcp_cache_hits"] == 1
        assert metrics["mcp_total_ms"] >= 0


# ═══════════════════════════════════════════════════════════════════════
# Reuse of the existing implementations
# ═══════════════════════════════════════════════════════════════════════


class TestExistingImplementationsReused:
    def test_internal_tool_goes_through_the_legacy_registry(self, db_session):
        """MCP adapts the existing tool rather than reimplementing it."""
        from backend.app.agents.marketing_agi.tools.registry import (
            MarketingToolRegistry,
        )

        m, _, _ = make_world(db_session, slug_hint="mcp-reuse")
        add_customer(db_session, m, name="Ada", total_orders=2)
        seen: list[str] = []
        real_call = MarketingToolRegistry.call

        def spy(self, ctx, name, params):
            seen.append(name)
            return real_call(self, ctx, name, params)

        original = MarketingToolRegistry.call
        MarketingToolRegistry.call = spy  # type: ignore[method-assign]
        try:
            out = _client(db_session, m).call(
                "marketing.crm.search_customers", {"min_orders": 1}
            )
        finally:
            MarketingToolRegistry.call = original  # type: ignore[method-assign]
        assert out["status"] == "success"
        assert "find_customers" in seen

    def test_legacy_call_helper_binds_the_same_tenant(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-helper")
        add_customer(db_session, m, name="Ada")
        ctx = MCPExecutionContext(db=db_session, merchant_id=m.id)
        out = legacy_call(ctx, "get_customer_segments")
        assert out["total"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Agent integration (agentic RAG + LLM provider untouched)
# ═══════════════════════════════════════════════════════════════════════


class TestAgentIntegration:
    def test_agent_tools_run_through_mcp(self, db_session):
        from backend.app.agents.marketing_agi.agent import MarketingAGI

        m = make_world(db_session, slug_hint="mcp-agent")[0]
        seed_inactive_customers(db_session, m, n=5)
        agent = MarketingAGI(db_session, m.id, llm=None)
        run = run_agent(db_session, m, agent=agent)
        assert run.status == "waiting_approval"
        assert len(agent._mcp.records) > 0
        assert all(r.provider in {"internal", "resend", "google_ads", "meta_ads", "instagram"}
                   for r in agent._mcp.records)

    def test_mcp_calls_are_recorded_on_run_state(self, db_session):
        from backend.app.agents.marketing_agi.agent import MarketingAGI

        m = make_world(db_session, slug_hint="mcp-agentstate")[0]
        seed_inactive_customers(db_session, m, n=5)
        agent = MarketingAGI(db_session, m.id, llm=None)
        run = run_agent(db_session, m, agent=agent)
        state = run.state or {}
        assert state["mcp_calls"]
        row = state["mcp_calls"][0]
        assert row["tool"].startswith("marketing.")
        assert row["status"] in {"success", "error", "denied"}
        assert row["tenant_scoped"] if "tenant_scoped" in row else True

    def test_mcp_activity_emits_real_events(self, db_session):
        from backend.app.agents.marketing_agi.agent import MarketingAGI
        from backend.app.models.marketing_agi import MarketingAGIEvent
        from sqlalchemy import select as sa_select

        m = make_world(db_session, slug_hint="mcp-agentevents")[0]
        seed_inactive_customers(db_session, m, n=5)
        agent = MarketingAGI(db_session, m.id, llm=None)
        run = run_agent(db_session, m, agent=agent)
        events = list(
            db_session.scalars(
                sa_select(MarketingAGIEvent).where(
                    MarketingAGIEvent.run_id == run.id,
                    MarketingAGIEvent.event_type == "mcp_tool_call",
                )
            ).all()
        )
        assert events, "MCP calls must appear in the live activity stream"
        assert all(e.data["tool"].startswith("marketing.") for e in events)

    def test_agentic_rag_uses_mcp(self, db_session):
        from backend.app.agents.marketing_agi.rag import AgenticRAG
        from backend.app.agents.marketing_agi.state import MarketingAGIState
        from backend.app.agents.marketing_agi.tools.registry import (
            ToolContext,
            get_registry,
        )

        m = make_world(db_session, slug_hint="mcp-rag")[0]
        add_customer(db_session, m, name="Ada", total_orders=2, total_spend="500")
        client = _client(db_session, m)
        rag = AgenticRAG(
            ToolContext(db=db_session, merchant_id=m.id),
            get_registry(),
            llm=None,
            invoke=lambda name, params: mcp_bridge.mcp_invoke(client, name, params),
        )
        result = rag.research("Which customers stopped buying?")
        assert result.outcomes, "RAG must retrieve through MCP"
        assert result.evidence_statements
        assert client.records, "the RAG retrieval must be observable"

    def test_rag_without_mcp_still_works(self, db_session):
        """The MCP seam is optional — RAG keeps its original path."""
        from backend.app.agents.marketing_agi.rag import AgenticRAG
        from backend.app.agents.marketing_agi.tools.registry import (
            ToolContext,
            get_registry,
        )

        m = make_world(db_session, slug_hint="mcp-ragnomcp")[0]
        add_customer(db_session, m, name="Ada", total_orders=2, total_spend="500")
        rag = AgenticRAG(
            ToolContext(db=db_session, merchant_id=m.id),
            get_registry(),
            llm=None,
        )
        result = rag.research("Which customers stopped buying?")
        assert result.outcomes

    def test_prompt_catalogs_are_phase_scoped_and_small(self, db_session):
        from backend.app.agents.marketing_agi.agent import MarketingAGI

        m = make_world(db_session, slug_hint="mcp-prompt")[0]
        agent = MarketingAGI(db_session, m.id, llm=None)
        research = agent._mcp_prompt_catalog(phase="research")
        names = {c["name"] for c in research}
        assert "marketing.analytics.get_failed_payments" in names
        # External writes never appear in an investigation prompt.
        assert "marketing.meta_ads.create_campaign" not in names
        assert len(research) < len(get_mcp_registry().names())

    def test_unconnected_provider_never_reaches_the_prompt(self, db_session):
        from backend.app.agents.marketing_agi.agent import MarketingAGI

        m = make_world(db_session, slug_hint="mcp-promptdisc")[0]
        agent = MarketingAGI(db_session, m.id, llm=None)
        names = {c["name"] for c in agent._mcp_prompt_catalog(phase="research")}
        assert "marketing.google_ads.list_campaigns" not in names
        assert "marketing.instagram.get_account" not in names

    def test_tool_count_and_cache_counters_reach_run_state(self, db_session):
        from backend.app.agents.marketing_agi.agent import MarketingAGI

        m = make_world(db_session, slug_hint="mcp-timing")[0]
        seed_inactive_customers(db_session, m, n=5)
        agent = MarketingAGI(db_session, m.id, llm=None)
        run = run_agent(db_session, m, agent=agent)
        timing = (run.state or {}).get("timing") or {}
        assert timing.get("mcp_calls", 0) > 0
        assert timing.get("mcp_total_ms", -1) >= 0

    def test_non_mcp_tool_still_uses_the_legacy_registry(self, db_session):
        from backend.app.agents.marketing_agi.agent import MarketingAGI
        from backend.app.agents.marketing_agi.state import MarketingAGIState

        m = make_world(db_session, slug_hint="mcp-legacy")[0]
        agent = MarketingAGI(db_session, m.id, llm=None)
        state = MarketingAGIState(run_id="r", merchant_id=str(m.id), objective="o")
        before = len(agent._mcp.records)
        with pytest.raises(Exception):
            agent._registry.call(agent._tool_ctx, "no_such_tool", {})
        assert len(agent._mcp.records) == before  # MCP untouched by legacy path


# ═══════════════════════════════════════════════════════════════════════
# API surface
# ═══════════════════════════════════════════════════════════════════════


class TestMCPSurface:
    @staticmethod
    def _auth(db_session, merchant, hint: str):
        """Real authenticated caller with an owner membership."""
        from backend.app.core.security import create_access_token
        from backend.app.models.enums import UserRole
        from tests.security_utils import make_membership, make_user

        user = make_user(db_session, hint)
        make_membership(db_session, user, merchant, UserRole.owner)
        token, _ = create_access_token(user.id, user.email)
        return {"Authorization": f"Bearer {token}"}

    def test_tools_endpoint_exposes_the_mcp_catalog(self, client, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-api")
        headers = self._auth(db_session, m, "mcp-api")
        r = client.get("/api/marketing-agi/tools", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert "mcp_tools" in body and "mcp_policies" in body
        names = {t["name"] for t in body["mcp_tools"]}
        assert "marketing.analytics.get_revenue" in names
        write = [p for p in body["mcp_policies"] if not p["read_only"]]
        assert write and all(
            p["requires_approval"] for p in write if p["external_write"]
        )

    def test_tools_endpoint_hides_disconnected_providers(self, client, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-apidisc")
        headers = self._auth(db_session, m, "mcp-apidisc")
        r = client.get("/api/marketing-agi/tools", headers=headers)
        google = next(
            t for t in r.json()["mcp_tools"]
            if t["name"] == "marketing.google_ads.list_campaigns"
        )
        assert google["integration_status"] == "requires_integration"

    def test_status_endpoint_reports_the_mcp_layer(self, client, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-apistatus")
        headers = self._auth(db_session, m, "mcp-apistatus")
        r = client.get("/api/marketing-agi/status", headers=headers)
        assert r.status_code == 200
        mcp = r.json()["mcp"]
        assert mcp["enabled"] is True
        assert mcp["tools"] == len(get_mcp_registry().names())
        assert mcp["write_tools"] >= 4
        assert "analytics" in mcp["servers"]
        from backend.app.integrations.mcp.domains import DOMAINS

        # The platform now hosts more than one capability namespace, so the
        # status endpoint reports the whole inventory rather than one domain.
        assert set(mcp["domains"]) <= set(DOMAINS)
        assert "marketing" in mcp["domains"]
        assert mcp["phases"] == [
            "observe", "research", "campaign_prep", "execution",
        ]

    def test_run_state_includes_mcp_calls(self, client, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-apirun")
        headers = self._auth(db_session, m, "mcp-apirun")
        run = start_run_row(db_session, m)
        db_session.commit()
        r = client.get(f"/api/marketing-agi/runs/{run.id}", headers=headers)
        assert r.status_code == 200
        assert "mcp_calls" in r.json()["state"]

# -----------------------------------------------------------------------
# Tool metadata, transport seam, per-tool budgets, agent phase discovery
# -----------------------------------------------------------------------


class TestToolMetadata:
    def test_every_spec_declares_domain_and_budgets(self):
        from backend.app.integrations.mcp.domains import DOMAINS

        specs = get_mcp_registry().all_specs()
        assert specs
        for spec in specs:
            # A spec's declared domain must be a real, registered domain.
            assert spec.domain in DOMAINS, spec.name
            assert spec.timeout_seconds > 0
            assert spec.max_retries >= 0
            policy = spec.policy()
            assert policy["domain"] == spec.domain
            assert policy["timeout_seconds"] == spec.timeout_seconds
            assert policy["max_retries"] == spec.max_retries

    def test_spec_rejects_impossible_budgets(self):
        with pytest.raises(ValueError):
            MCPToolSpec(
                name="marketing.t.zero_timeout",
                description="bad timeout",
                provider="internal",
                handler=lambda **_: {},
                timeout_seconds=0,
            )
        with pytest.raises(ValueError):
            MCPToolSpec(
                name="marketing.t.negative_retries",
                description="bad retries",
                provider="internal",
                handler=lambda **_: {},
                max_retries=-1,
            )

    def test_per_tool_retry_budget_tightens_the_client(self, db_session, monkeypatch):
        """The tool's own budget beats a larger client-wide budget."""
        from backend.app.integrations.mcp import registry as registry_mod

        m, _, _ = make_world(db_session, slug_hint="mcp-toolbudget")
        calls = {"n": 0}

        def always(**kwargs):
            calls["n"] += 1
            raise ProviderCallError(
                "still limited", provider_code="RATE_LIMITED",
                tool="marketing.crm.get_segment", provider="internal",
            )

        real = get_mcp_registry().spec("marketing.crm.get_segment")
        patched = MCPToolSpec(
            name=real.name,
            description=real.description,
            provider=real.provider,
            handler=always,
            input_schema=real.input_schema,
            output_schema={"type": "object"},
            max_retries=0,
        )
        monkeypatch.setitem(registry_mod._REGISTRY._specs, real.name, patched)
        client = MCPClient(
            _client(db_session, m).context, max_retries=3, sleep=lambda s: None
        )
        out = client.call(real.name, {})
        assert out["status"] == "error"
        assert out["error"]["code"] == RATE_LIMITED
        assert calls["n"] == 1  # tool budget 0 wins over client budget 3


class TestTransportSeam:
    def test_in_process_transport_passes_only_the_trusted_context(
        self, db_session
    ):
        from backend.app.integrations.mcp.transport import InProcessTransport

        m, _, _ = make_world(db_session, slug_hint="mcp-transport")
        seen: dict = {}

        def handler(**kwargs):
            seen.update(kwargs)
            return {"ok": True}

        spec = MCPToolSpec(
            name="marketing.t.seam",
            description="seam double",
            provider="internal",
            handler=handler,
            input_schema={},
            output_schema={"type": "object"},
        )
        ctx = MCPExecutionContext(db=db_session, merchant_id=m.id)
        out = InProcessTransport().invoke(spec, ctx, {"q": 1}, None)
        assert out == {"ok": True}
        assert seen["merchant_id"] == m.id
        assert seen["db"] is db_session
        assert seen["q"] == 1  # validated arguments, nothing else

    def test_client_routes_invocation_through_the_injected_transport(
        self, db_session
    ):
        m, _, _ = make_world(db_session, slug_hint="mcp-transport2")
        hits: list[str] = []

        class SpyTransport:
            def invoke(self, spec, ctx, arguments, approved_action_id):
                hits.append(spec.name)
                return {"segments": [], "total": 0}

        client = MCPClient(
            _client(db_session, m).context, transport=SpyTransport()
        )
        out = client.call("marketing.crm.get_segment", {})
        assert out["status"] == "success"
        assert hits == ["marketing.crm.get_segment"]

    def test_transport_failures_are_classified_and_bounded(
        self, db_session
    ):
        m, _, _ = make_world(db_session, slug_hint="mcp-transport3")
        attempts = {"n": 0}

        class FlakyTransport:
            def invoke(self, spec, ctx, arguments, approved_action_id):
                attempts["n"] += 1
                raise ProviderCallError(
                    "upstream limited", provider_code="RATE_LIMITED",
                    tool=spec.name, provider="internal",
                )

        client = MCPClient(
            _client(db_session, m).context,
            transport=FlakyTransport(),
            max_retries=1,
            sleep=lambda s: None,
        )
        out = client.call("marketing.crm.get_segment", {})
        assert out["status"] == "error"  # never a fake success
        assert out["error"]["code"] == RATE_LIMITED
        assert attempts["n"] == 2  # 1 attempt + 1 bounded retry

    def test_build_client_inherits_the_parent_transport(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="mcp-transport4")

        class MarkerTransport:
            def invoke(self, spec, ctx, arguments, approved_action_id):
                return {}

        parent = MCPClient(
            _client(db_session, m).context, transport=MarkerTransport()
        )
        child = mcp_bridge.build_client(db_session, m.id, client=parent)
        assert child.transport is parent.transport


class TestBuildContextIsolation:
    def test_worker_client_never_mutates_the_parent_context(self, db_session):
        """A worker rebinding its session must not move the parent's."""
        m, _, _ = make_world(db_session, slug_hint="mcp-ctxcopy")
        parent = mcp_bridge.build_client(db_session, m.id, run_id="run-1")
        parent.context.cache["k"] = "v"
        child = mcp_bridge.build_client(db_session, m.id, client=parent)

        assert child.context is not parent.context
        # Per-run state stays shared by reference (the fan-out design).
        assert child.context.cache is parent.context.cache
        assert child.context.run_id == "run-1"
        assert child.context.execution_enabled == parent.context.execution_enabled

        # Rebinding the worker's session leaves the parent untouched �
        # the pre-mutation behaviour raced on a single shared context.
        worker_session = object()
        child.context.db = worker_session
        assert parent.context.db is db_session
        assert parent.context.merchant_id == m.id


class TestAgentPhaseDiscovery:
    def test_every_agent_phase_has_an_mcp_catalog_phase(self):
        from backend.app.agents.marketing_agi.agent import _MCP_CATALOG_PHASE
        from backend.app.agents.marketing_agi.state import Phase

        for phase in Phase:
            assert phase.value in _MCP_CATALOG_PHASE, phase.value

    def test_phase_catalogs_match_the_agent_stage(self, db_session):
        from backend.app.agents.marketing_agi.agent import MarketingAGI

        m, _, _ = make_world(db_session, slug_hint="mcp-phasedisc")
        agent = MarketingAGI(db_session, m.id, llm=None)

        observe = {
            c["name"]
            for c in agent._mcp_prompt_catalog(phase="observe", include_write=False)
        }
        assert "marketing.analytics.get_revenue" in observe
        assert "marketing.email.draft_campaign" not in observe

        create = {c["name"] for c in agent._mcp_prompt_catalog(phase="create")}
        # campaign preparation sees the local draft tool ...
        assert "marketing.email.draft_campaign" in create
        # ... but never an external write (execution phase only).
        assert "marketing.email.send_campaign" not in create
        assert "marketing.meta_ads.create_campaign" not in create

        verify = agent._mcp_prompt_catalog(phase="verify", include_write=False)
        assert verify and all(c["read_only"] for c in verify)

        # Dotted MCP names, not the legacy names � MCP is the catalog.
        assert all("." in c["name"] for c in verify)

    def test_unknown_agent_phase_falls_back_to_research_scope(self, db_session):
        from backend.app.agents.marketing_agi.agent import MarketingAGI

        m, _, _ = make_world(db_session, slug_hint="mcp-phasedisc2")
        agent = MarketingAGI(db_session, m.id, llm=None)
        names = {c["name"] for c in agent._mcp_prompt_catalog(phase="bogus")}
        assert "marketing.analytics.get_failed_payments" in names
        assert "marketing.email.send_campaign" not in names

    def test_registered_names_covers_mcp_and_legacy_aliases(self):
        names = mcp_bridge.registered_names()
        assert "marketing.analytics.get_revenue" in names          # dotted MCP
        assert "get_failed_payment_analytics" in names             # legacy alias
        assert "verifier" not in names                             # pseudo-tool
        # Every registered name actually dispatches through MCP.
        for name in list(names)[:5]:
            assert mcp_bridge.resolve(name) is not None

    def test_agent_dispatch_accepts_a_dotted_mcp_name(self, db_session):
        """The loop allowlist and dispatch must agree on dotted names."""
        from backend.app.agents.marketing_agi.agent import MarketingAGI

        m, _, _ = make_world(db_session, slug_hint="mcp-dotted")
        add_customer(db_session, m, name="Ada", total_orders=2)
        agent = MarketingAGI(db_session, m.id, llm=None)
        allowed = {c["name"] for c in agent._registry.catalog()}
        allowed |= mcp_bridge.registered_names()
        assert "marketing.crm.search_customers" in allowed
        call = agent._dispatch_tool(
            _state_for(agent, m), "marketing.crm.search_customers", {}
        )
        assert call["mcp_tool"] == "marketing.crm.search_customers"


def _state_for(agent, merchant):
    from backend.app.agents.marketing_agi.state import MarketingAGIState

    return MarketingAGIState(
        run_id=str(uuid.uuid4()), merchant_id=str(merchant.id), objective="o"
    )
