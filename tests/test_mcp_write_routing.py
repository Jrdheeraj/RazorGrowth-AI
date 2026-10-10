"""Approved external-write routing THROUGH MCP — the no-bypass guarantee.

The architecture under test:

    human approves
        -> /api/actions/{id}/execute
        -> MCP (mcp.execution.execute_approved_action)
        -> policy: tenant -> integration -> approval -> EXECUTION_ENABLED
        -> existing action_service.execute_action
        -> existing provider executor
        -> audit

There must be NO second external-write path. In particular there must not
be a "connected -> MCP, disconnected -> legacy executor" split, because a
disconnected integration would then be exactly how you reach a provider
while bypassing the connectivity layer.

These tests pin that, plus the shared-registry / per-agent discovery
foundation that future agents (Product Agent, Growth Radar) consume.
"""
from __future__ import annotations

import uuid

import pytest

from backend.app.integrations.mcp import bridge as mcp_bridge
from backend.app.integrations.mcp.execution import (
    MARKETING_EXTERNAL_WRITE_TYPES,
    execute_approved_action,
    is_marketing_external_write,
    mcp_tool_for_action,
)
from backend.app.integrations.mcp.registry import get_mcp_registry
from tests.security_utils import make_world
from tests.test_mcp_layer import _connect_google, _connect_instagram, _connect_resend


def _approved(db, merchant, action_type, payload=None, *, status="approved"):
    from backend.app.models.agent_action import AgentAction
    from backend.app.models.enums import AgentActionStatus

    action = AgentAction(
        merchant_id=merchant.id,
        action_type=action_type,
        status=AgentActionStatus(status),
        input_payload={"merchant_id": str(merchant.id), **(payload or {})},
        requested_by="agent:test",
        approved_by="owner@test" if status == "approved" else None,
    )
    db.add(action)
    db.commit()
    return action


# ══════════════════════════════════════════════════════════════════════
# 1 — no legacy external-write bypass
# ══════════════════════════════════════════════════════════════════════


class TestNoLegacyExternalWriteBypass:
    def test_all_marketing_external_write_types_are_claimed(self):
        assert MARKETING_EXTERNAL_WRITE_TYPES == {
            "send_campaign",
            "publish_social_post",
            "create_ad_campaign",
        }

    def test_every_claimed_type_maps_to_a_registered_tool(self):
        """No marketing write type may lack an MCP tool (that would fall back)."""
        registry = get_mcp_registry()
        expected = {
            "send_campaign": "marketing.email.send_campaign",
            "publish_social_post": "marketing.instagram.publish",
        }
        for at, tool in expected.items():
            assert registry.spec(tool).external_write is True, at
            assert registry.spec(tool).requires_approval is True, at
            assert registry.spec(tool).requires_execution_enabled is True, at

    @pytest.mark.parametrize(
        "action_type,payload,disconnect",
        [
            ("send_campaign", {}, None),
            ("publish_social_post", {}, None),
            ("create_ad_campaign", {"platform": "google_ads"}, None),
            ("create_ad_campaign", {"platform": "meta_ads"}, None),
        ],
    )
    def test_disconnected_provider_is_refused_with_no_execution(
        self, db_session, action_type, payload, disconnect
    ):
        """MCP refuses; it never routes around itself to the executor."""
        m, _, _ = make_world(db_session, slug_hint="wrt-noexec")
        action = _approved(db_session, m, action_type, payload)
        result = execute_approved_action(db_session, m.id, action.id)
        assert result is not None, "MCP did not claim the write"
        assert result.success is False
        assert "INTEGRATION_NOT_CONNECTED" in (result.error or "")
        assert (
            result.result_metadata["external_execution_performed"] is False
        )
        # The action was NOT executed and stays approved (retryable later).
        db_session.refresh(action)
        assert str(action.status.value if hasattr(action.status, "value") else action.status) == "approved"

    def test_executor_is_never_invoked_for_a_disconnected_provider(
        self, db_session, monkeypatch
    ):
        """The strongest form: patch the executor and prove it is not called."""
        import backend.app.services.action_service as action_service

        calls = {"n": 0}

        def _boom(db, action_id, *, actor=None):
            calls["n"] += 1
            from backend.app.services.action_executor import ExecutorResult

            return ExecutorResult(success=True, result_metadata={"leaked": True})

        monkeypatch.setattr(action_service, "execute_action", _boom)
        m, _, _ = make_world(db_session, slug_hint="wrt-nocall")
        action = _approved(db_session, m, "send_campaign", {})
        result = execute_approved_action(db_session, m.id, action.id)
        assert calls["n"] == 0, "an external write reached the executor while disconnected"
        assert result.success is False

    def test_unknown_ad_platform_is_refused_not_rerouted(self, db_session):
        from backend.app.integrations.mcp.errors import MCPError

        m, _, _ = make_world(db_session, slug_hint="wrt-badad")
        action = _approved(
            db_session, m, "create_ad_campaign", {"platform": "totally_unknown"}
        )
        with pytest.raises(MCPError):
            execute_approved_action(db_session, m.id, action.id)

    def test_non_marketing_types_are_not_claimed(self, db_session):
        """Scope boundary, not a second write path."""
        m, _, _ = make_world(db_session, slug_hint="wrt-scope")
        for at in ("create_discount", "retry_payment", "generate_opportunity"):
            action = _approved(db_session, m, at, {"percentage": 10})
            assert is_marketing_external_write(action) is False
            assert mcp_tool_for_action(action) is None


# ══════════════════════════════════════════════════════════════════════
# 2 — connected providers still execute through MCP
# ══════════════════════════════════════════════════════════════════════


class TestConnectedProviderRoutesThroughMCP:
    def _enable_execution(self, monkeypatch):
        from backend.app.core.config import get_settings

        monkeypatch.setenv("EXECUTION_ENABLED", "true")
        get_settings.cache_clear()

    def _disable_execution(self, monkeypatch):
        from backend.app.core.config import get_settings

        monkeypatch.setenv("EXECUTION_ENABLED", "false")
        get_settings.cache_clear()

    @pytest.mark.parametrize(
        "connect,action_type,payload,tool",
        [
            ("resend", "send_campaign", {}, "marketing.email.send_campaign"),
            (
                "instagram",
                "publish_social_post",
                {},
                "marketing.instagram.publish",
            ),
            (
                "google",
                "create_ad_campaign",
                {"platform": "google_ads"},
                "marketing.google_ads.create_campaign",
            ),
        ],
    )
    def test_connected_provider_executes_via_the_existing_executor(
        self, db_session, monkeypatch, connect, action_type, payload, tool
    ):
        """MCP is the boundary; action_service + the executor stay the logic."""
        self._enable_execution(monkeypatch)
        m, _, _ = make_world(db_session, slug_hint=f"wrt-{connect}")
        if connect == "resend":
            _connect_resend(db_session, m)
        elif connect == "instagram":
            _connect_instagram(db_session, m)
        else:
            _connect_google(db_session, m, monkeypatch)

        seen = {}

        def _fake_execute(db, action_id, *, actor=None):
            from backend.app.services.action_executor import ExecutorResult

            seen["called"] = True
            seen["actor"] = actor
            return ExecutorResult(
                success=True, result_metadata={"mode": "test", "provider": tool}
            )

        import backend.app.services.action_service as action_service

        monkeypatch.setattr(action_service, "execute_action", _fake_execute)
        action = _approved(db_session, m, action_type, payload)
        result = execute_approved_action(db_session, m.id, action.id)

        assert seen.get("called") is True, "the existing executor was bypassed"
        assert str(seen["actor"]).startswith("mcp:")
        assert result.success is True
        assert result.result_metadata["executed_via"] == "mcp_tool_layer"
        assert result.result_metadata["mcp_tool"] == tool
        self._disable_execution(monkeypatch)

    def test_execution_disabled_withholds_before_the_executor(
        self, db_session, monkeypatch
    ):
        self._disable_execution(monkeypatch)
        m, _, _ = make_world(db_session, slug_hint="wrt-execoff")
        _connect_resend(db_session, m)

        calls = {"n": 0}

        def _fake(db, action_id, *, actor=None):
            calls["n"] += 1
            from backend.app.services.action_executor import ExecutorResult

            return ExecutorResult(success=True)

        import backend.app.services.action_service as action_service

        monkeypatch.setattr(action_service, "execute_action", _fake)
        action = _approved(db_session, m, "send_campaign", {})
        result = execute_approved_action(db_session, m.id, action.id)
        assert result.success is False
        assert "EXECUTION_DISABLED" in (result.error or "")
        assert calls["n"] == 0

    @pytest.mark.parametrize(
        "status", ["requested", "executing", "completed", "rejected", "failed"]
    )
    def test_non_approved_states_are_left_to_the_state_machine(
        self, db_session, status
    ):
        m, _, _ = make_world(db_session, slug_hint="wrt-state")
        _connect_resend(db_session, m)
        action = _approved(db_session, m, "send_campaign", {}, status=status)
        # None => action_service owns the canonical lifecycle refusal.
        assert execute_approved_action(db_session, m.id, action.id) is None


# ══════════════════════════════════════════════════════════════════════
# 3 — the HTTP route itself must not bypass MCP
# ══════════════════════════════════════════════════════════════════════


class TestHttpRouteUsesMCP:
    def test_execute_route_refuses_a_disconnected_provider(
        self, client, db_session
    ):
        """End-to-end through the API: no external execution, honest error."""
        import json as _json

        from backend.app.models.merchant import Merchant
        from backend.app.models.enums import Currency, MerchantStatus

        slug = f"wrt-http-{uuid.uuid4().hex[:8]}"
        m = Merchant(
            name="WRT HTTP",
            slug=slug,
            email=f"{slug}@x.com",
            status=MerchantStatus.active,
            currency=Currency.INR,
        )
        db_session.add(m)
        db_session.commit()

        action = _approved(db_session, m, "send_campaign", {})
        r = client.post(f"/api/actions/{action.id}/execute")
        assert r.status_code == 400
        detail = r.json()["detail"]
        error = detail["error"] if isinstance(detail, dict) else str(detail)
        assert "INTEGRATION_NOT_CONNECTED" in error
        # ...and it must not claim a completed external action.
        db_session.refresh(action)
        raw = str(action.status)
        assert "completed" not in raw

    def test_execute_route_rejects_an_unapproved_action(self, client, db_session):
        from backend.app.models.merchant import Merchant
        from backend.app.models.enums import Currency, MerchantStatus

        slug = f"wrt-http2-{uuid.uuid4().hex[:8]}"
        m = Merchant(
            name="WRT HTTP2",
            slug=slug,
            email=f"{slug}@x.com",
            status=MerchantStatus.active,
            currency=Currency.INR,
        )
        db_session.add(m)
        db_session.commit()

        action = _approved(db_session, m, "send_campaign", {}, status="requested")
        r = client.post(f"/api/actions/{action.id}/execute")
        assert r.status_code == 400
        detail = r.json()["detail"]
        error = detail["error"] if isinstance(detail, dict) else str(detail)
        # The state machine still answers with its canonical code, not a
        # connectivity or MCP code.
        assert "INVALID_ACTION_STATE" in error


# ══════════════════════════════════════════════════════════════════════
# 4 — shared registry + per-agent discovery
# ══════════════════════════════════════════════════════════════════════


class TestSharedRegistryAndAgentDiscovery:
    def test_registry_is_a_single_shared_instance(self):
        assert get_mcp_registry() is get_mcp_registry()

    def test_marketing_agent_sees_its_three_domains(self):
        from backend.app.integrations.mcp.domains import capability_domain

        names = get_mcp_registry().names_for_agent("marketing_agent")
        assert names, "the Marketing Agent must have tools"
        assert {capability_domain(n) for n in names} == {
            "analytics",
            "customer",
            "marketing",
        }

    def test_product_agent_sees_only_its_granted_domains(self):
        from backend.app.integrations.mcp.domains import capability_domain, domains_for_agent

        names = get_mcp_registry().names_for_agent("product_agent")
        # commerce and product_intelligence are now OPERATIONAL (they have
        # real registered reads), so the Product Agent sees exactly the three
        # domains it was granted — and nothing else.
        granted = set(domains_for_agent("product_agent"))
        assert granted == {"commerce", "analytics", "product_intelligence"}
        assert {capability_domain(n) for n in names} <= granted
        assert {"commerce", "analytics", "product_intelligence"} == {
            capability_domain(n) for n in names
        }
        # It must NOT see the Marketing Agent's customer/marketing tools.
        assert not any("google_ads" in n or "instagram" in n for n in names)
        assert not any(n.startswith("marketing.crm.") for n in names)
        assert not any(n.startswith("marketing.email.") for n in names)

    def test_growth_radar_sees_every_operational_domain(self):
        from backend.app.integrations.mcp.domains import (
            AGENT_CAPABILITIES,
            capability_domain,
            domains_for_agent,
        )

        names = get_mcp_registry().names_for_agent("growth_radar")
        granted = set(domains_for_agent("growth_radar"))
        # Growth Radar watches everything, so it sees every domain it was
        # granted — derived from AGENT_CAPABILITIES rather than hardcoded, so
        # this stays true as the platform gains domains.
        assert granted == set(AGENT_CAPABILITIES["growth_radar"].domains)
        assert {capability_domain(n) for n in names} == granted

    def test_unknown_agent_gets_an_empty_catalog(self):
        """Fail closed: a new agent cannot see the platform by accident."""
        assert get_mcp_registry().names_for_agent("not_an_agent") == []

    def test_domain_filtering_never_grants_execution(self, db_session):
        """Filtering is DISCOVERY only; call still validates the full registry."""
        m, _, _ = make_world(db_session, slug_hint="wrt-filter")
        _connect_resend(db_session, m)
        client = mcp_bridge.build_client(db_session, m.id, execution_enabled=True)
        # Not in the product_agent catalog...
        assert not any(
            e["name"] == "marketing.email.send_campaign"
            for e in client.catalog_for_agent("product_agent", phase="execution")
        )
        # ...but an explicit direct call is still governed by the registry +
        # policy, not by discovery filtering.
        out = client.call("marketing.email.send_campaign", None)
        assert out["error"]["code"] == "APPROVAL_REQUIRED"

    def test_catalog_entries_carry_their_capability_domain(self):
        from backend.app.integrations.mcp.domains import DOMAINS

        catalog = get_mcp_registry().catalog()
        assert catalog
        for entry in catalog:
            assert entry["capability_domain"] in DOMAINS

    def test_domain_status_is_honest(self):
        from backend.app.integrations.mcp.domains import (
            AGENT_CAPABILITIES,
            DOMAINS,
            OPERATIONAL,
            STRUCTURAL,
            capability_domain,
        )

        catalog = get_mcp_registry().catalog()
        # The invariant the whole taxonomy rests on: a domain is OPERATIONAL
        # exactly when it has real, registered tools, and STRUCTURAL exactly
        # when it has none. Nothing is ever faked to make a domain look
        # complete, and nothing is left structural once it has real tools.
        for name, domain in DOMAINS.items():
            has_tools = any(capability_domain(e["name"]) == name for e in catalog)
            if has_tools:
                assert domain.status == OPERATIONAL, (
                    f"{name} has registered tools but is not operational"
                )
            else:
                assert domain.status == STRUCTURAL, (
                    f"{name} has no tools but is not marked structural"
                )
        # Every granted domain is a declared domain.
        for agent, caps in AGENT_CAPABILITIES.items():
            for domain in caps.domains:
                assert domain in DOMAINS, f"{agent} granted unknown {domain}"

    def test_agent_scoped_catalog_respects_live_connections(self, db_session):
        """A disconnected provider's tools are not offered to the model."""
        m, _, _ = make_world(db_session, slug_hint="wrt-conn")
        client = mcp_bridge.build_client(db_session, m.id)
        entries = client.catalog_for_agent("marketing_agent", phase="execution")
        assert entries == [], "unconnected write tools must not be advertised"

    def test_agent_scoped_catalog_offers_connected_write_tools(
        self, db_session
    ):
        m, _, _ = make_world(db_session, slug_hint="wrt-conn2")
        _connect_resend(db_session, m)
        client = mcp_bridge.build_client(db_session, m.id)
        entries = client.catalog_for_agent("marketing_agent", phase="execution")
        names = [e["name"] for e in entries]
        assert "marketing.email.send_campaign" in names
        # Still gated in the catalog contract.
        entry = next(e for e in entries if e["name"] == "marketing.email.send_campaign")
        assert entry["requires_approval"] is True
        assert entry["capability_domain"] == "marketing"
