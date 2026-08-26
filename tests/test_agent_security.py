"""
Phase 6 security tests — agent privilege-escalation attempts (Slice 10, 17–19).

Agents are NOT users. They hold capability sets from
backend.app.agents.permissions and must NEVER obtain:

    approve_action · reject_action · execute_action · bypass_guardrails ·
    direct_database_mutation · send_money

17. Agent attempting approval
18. Agent attempting execution
19. Agent attempting guardrail bypass
"""
from __future__ import annotations

import time
import uuid

import jwt as pyjwt
import pytest

from backend.app.agents import permissions as perms
from backend.app.core.config import get_settings
from tests.security_utils import TEST_SECRET, bearer, make_world


@pytest.fixture
def secure(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "required")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


# ── 17/18: capability layer — every agent × every forbidden capability ─────


class TestForbiddenCapabilities:
    def test_no_agent_holds_any_forbidden_capability(self):
        for agent_name in perms.AGENT_PERMISSIONS:
            held = perms.AGENT_PERMISSIONS[agent_name]
            overlap = held & perms.FORBIDDEN_CAPABILITIES
            assert not overlap, f"{agent_name} holds forbidden: {overlap}"

    @pytest.mark.parametrize("capability", sorted(perms.FORBIDDEN_CAPABILITIES))
    @pytest.mark.parametrize("agent_name", sorted(perms.AGENT_PERMISSIONS))
    def test_every_agent_denied_every_forbidden_capability(
        self, agent_name, capability
    ):
        with pytest.raises(perms.AgentPermissionError):
            perms.assert_permission(agent_name, capability)

    def test_rogue_agent_permission_error_is_permission_denied(self):
        try:
            perms.assert_permission("GrowthDiscoveryAgent", "approve_action")
            raise AssertionError("expected AgentPermissionError")
        except perms.AgentPermissionError as exc:
            assert "does not hold capability 'approve_action'" in str(exc)


class TestAgentCannotApproveOrExecuteViaApi:
    """
    There is no agent login path. A 'rogue agent' is simulated by a forged
    JWT whose subject claims an agent identity — it must fail closed at the
    authentication layer because agents have no User row.
    """

    def _forged_agent_headers(self, label: str) -> dict[str, str]:
        now = int(time.time())
        claims = {
            "sub": f"agent:{label}",       # not a UUID → fails closed
            "email": f"{label}@agents.evil",
            "type": "access",
            "iat": now,
            "exp": now + 600,
        }
        token = pyjwt.encode(claims, TEST_SECRET, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    def _valid_uuid_nonexistent_user_headers(self) -> dict[str, str]:
        now = int(time.time())
        claims = {
            "sub": str(uuid.uuid4()),      # valid UUID, but no such user
            "email": "ghost-agent@agents.evil",
            "type": "access",
            "iat": now,
            "exp": now + 600,
        }
        token = pyjwt.encode(claims, TEST_SECRET, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    def _seed_action(self, db_session, merchant_id: uuid.UUID) -> uuid.UUID:
        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import AgentActionStatus, AgentActionType

        action = AgentAction(
            id=uuid.uuid4(),
            merchant_id=merchant_id,
            action_type=AgentActionType.send_campaign,
            status=AgentActionStatus.requested,
            input_payload={"campaign_type": "email",
                           "target": {"segment": "all"}, "target_count": 2},
            requested_by="rogue_seed",
        )
        db_session.add(action)
        db_session.commit()
        return action.id

    @pytest.mark.parametrize("path_suffix", ["approve", "reject", "execute"])
    def test_forged_agent_token_cannot_transition_actions(
        self, client, secure, db_session, path_suffix
    ):
        m, _, _ = make_world(db_session, slug_hint="rog")
        aid = self._seed_action(db_session, m.id)
        for headers in (
            self._forged_agent_headers("PaymentRecoveryAgent"),
            self._valid_uuid_nonexistent_user_headers(),
        ):
            r = client.post(f"/api/actions/{aid}/{path_suffix}", headers=headers)
            assert r.status_code == 401, f"{path_suffix}: {r.status_code}"
            assert r.json()["detail"] in {"TOKEN_INVALID", "NOT_AUTHENTICATED"}

        # The action remains untouched in 'requested'.
        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import AgentActionStatus

        action = db_session.get(AgentAction, aid)
        assert action.status == AgentActionStatus.requested

    def test_forged_agent_token_cannot_run_agents_or_read_data(
        self, client, secure, db_session
    ):
        for headers in (
            self._forged_agent_headers("CampaignStrategistAgent"),
            self._valid_uuid_nonexistent_user_headers(),
        ):
            r = client.post("/api/agents/run", json={"mode": "fast"}, headers=headers)
            assert r.status_code == 401
            r = client.get("/api/customers", headers=headers)
            assert r.status_code == 401

    def test_approval_service_is_not_exposed_as_agent_tool(self):
        """The AI toolkit exposes only read-only tools; approval/rejection/
        execution live exclusively on the human-only HTTP surface."""
        from backend.app.ai.agents.tools import AgentToolkit

        tool_names = {
            name for name in vars(AgentToolkit)
            if not name.startswith("_")
        }
        forbidden = perms.FORBIDDEN_CAPABILITIES | {
            "approve", "reject", "execute", "approve_action",
            "reject_action", "execute_action", "send_money",
        }
        overlap = {t for t in tool_names if t.lower() in
                   {f.strip("_").lower() for f in forbidden}}
        assert not overlap, f"Toolkit leaks privileged methods: {overlap}"


# ── 19: guardrail bypass attempts ───────────────────────────────────────────


class TestGuardrailBypass:
    def test_owner_cannot_bypass_double_guardrail_on_execution(
        self, client, secure, db_session, monkeypatch
    ):
        """Even an OWNER with a valid approved action cannot execute when the
        stored payload violates amount bounds — Guardrail #2 re-evaluates
        immediately before execution and no role bypasses it."""
        from decimal import Decimal

        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import AgentActionStatus, AgentActionType

        m, u_owner, _ = make_world(db_session, slug_hint="gdl")
        action = AgentAction(
            id=uuid.uuid4(),
            merchant_id=m.id,
            action_type=AgentActionType.create_discount,
            status=AgentActionStatus.approved,   # already approved…
            input_payload={"percentage": 10,
                           "proposed_amount": 999999},   # …but wildly out of bounds
            requested_by="guardrail_probe",
        )
        db_session.add(action)
        db_session.commit()

        r = client.post(f"/api/actions/{action.id}/execute", headers=bearer(u_owner))
        assert r.status_code == 400
        body = r.json()
        detail = body["detail"]
        error = detail["error"] if isinstance(detail, dict) else str(detail)
        assert (
            "GUARDRAIL" in error
            or "DISCOUNT_AMOUNT_EXCEEDS" in error
            or "exceeds maximum allowed" in error
        )

        refreshed = db_session.get(AgentAction, action.id)
        db_session.refresh(refreshed)
        assert refreshed.status == AgentActionStatus.failed
        assert refreshed.error_code == "GUARDRAIL_REJECTED"

    def test_approval_blocked_by_guardrail_even_for_owner(
        self, client, secure, db_session
    ):
        from decimal import Decimal

        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import AgentActionStatus, AgentActionType

        m, u_owner, _ = make_world(db_session, slug_hint="gdla")
        action = AgentAction(
            id=uuid.uuid4(),
            merchant_id=m.id,
            action_type=AgentActionType.create_discount,
            status=AgentActionStatus.requested,
            input_payload={"percentage": 10,
                           "proposed_amount": 999999},
            requested_by="guardrail_probe",
        )
        db_session.add(action)
        db_session.commit()

        r = client.post(f"/api/actions/{action.id}/approve", headers=bearer(u_owner))
        assert r.status_code == 400
        assert "GUARDRAIL_REJECTED" in str(r.json()["detail"])

    def test_execution_enabled_false_blocks_in_production(
        self, client, secure, db_session, monkeypatch
    ):
        """Production + EXECUTION_ENABLED=false → nothing may execute."""
        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import AgentActionStatus, AgentActionType

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("EXECUTION_ENABLED", raising=False)
        monkeypatch.delenv("EXECUTION_ENABLED", raising=False)
        monkeypatch.setenv("EXECUTION_ENABLED", "false")
        get_settings.cache_clear()

        m, u_owner, _ = make_world(db_session, slug_hint="prode")
        action = AgentAction(
            id=uuid.uuid4(),
            merchant_id=m.id,
            action_type=AgentActionType.send_campaign,
            status=AgentActionStatus.approved,
            input_payload={"campaign_type": "email",
                           "target": {"segment": "all"}, "target_count": 1},
            requested_by="prod_probe",
        )
        db_session.add(action)
        db_session.commit()

        r = client.post(f"/api/actions/{action.id}/execute", headers=bearer(u_owner))
        assert r.status_code == 400
        body = r.json()["detail"]
        error = body["error"] if isinstance(body, dict) else str(body)
        assert error == "EXECUTION_DISABLED_BY_ENVIRONMENT"
        monkeypatch.undo()
        get_settings.cache_clear()
