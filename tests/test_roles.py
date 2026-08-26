"""
Phase 6 security tests — role/permission matrix (Slice 10, scenarios 15–16).

15. Analyst attempting approval → denied
    Operator attempting approval → denied
16. Operator attempting admin-only operations → denied
Plus positive checks that owner/admin retain their legitimate powers.
"""
from __future__ import annotations

import uuid

import pytest

from backend.app.core.config import get_settings
from backend.app.core.roles import (
    can_approve,
    can_manage_owners,
    can_manage_users,
    can_read,
    can_run_operations,
)
from backend.app.models.enums import UserRole
from tests.security_utils import bearer, make_world


@pytest.fixture
def secure(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "required")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def _seed_action(db_session, merchant) -> uuid.UUID:
    from backend.app.models.agent_action import AgentAction
    from backend.app.models.enums import AgentActionStatus, AgentActionType

    action = AgentAction(
        id=uuid.uuid4(),
        merchant_id=merchant.id,
        action_type=AgentActionType.send_campaign,
        status=AgentActionStatus.requested,
        input_payload={"campaign_type": "email", "target": {"segment": "all"},
                       "target_count": 3},
        requested_by="role_seed",
    )
    db_session.add(action)
    db_session.commit()
    return action.id


class TestRoleMatrixUnits:
    def test_matrix_matches_specification(self):
        # read: everyone
        for r in UserRole:
            assert can_read(r)
        # operational: operator and above; never analyst
        assert can_run_operations(UserRole.owner)
        assert can_run_operations(UserRole.admin)
        assert can_run_operations(UserRole.operator)
        assert not can_run_operations(UserRole.analyst)
        # approve: admin and above only
        assert can_approve(UserRole.owner)
        assert can_approve(UserRole.admin)
        assert not can_approve(UserRole.operator)
        assert not can_approve(UserRole.analyst)
        # manage users: admin and above
        assert can_manage_users(UserRole.owner)
        assert can_manage_users(UserRole.admin)
        assert not can_manage_users(UserRole.operator)
        # owners only: owner-tier management
        assert can_manage_owners(UserRole.owner)
        assert not can_manage_owners(UserRole.admin)


class TestApprovalRoleEnforcement:
    @pytest.mark.parametrize("role", [UserRole.analyst, UserRole.operator])
    def test_low_roles_cannot_approve(self, client, secure, db_session, role):
        m, u, _ = make_world(db_session, role=role, slug_hint=f"ap{role.value[:3]}")
        aid = _seed_action(db_session, m)
        r = client.post(f"/api/actions/{aid}/approve", headers=bearer(u))
        assert r.status_code == 403
        assert r.json()["detail"] == "INSUFFICIENT_ROLE"
        # Action must remain untouched.
        from backend.app.models.agent_action import AgentAction

        status = db_session.get(AgentAction, aid).status
        assert str(getattr(status, "value", status)) == "requested"

    @pytest.mark.parametrize("role", [UserRole.analyst, UserRole.operator])
    def test_low_roles_cannot_reject(self, client, secure, db_session, role):
        m, u, _ = make_world(db_session, role=role, slug_hint=f"rj{role.value[:3]}")
        aid = _seed_action(db_session, m)
        r = client.post(f"/api/actions/{aid}/reject", headers=bearer(u))
        assert r.status_code == 403

    @pytest.mark.parametrize("role", [UserRole.owner, UserRole.admin])
    def test_privileged_roles_can_approve(self, client, secure, db_session, role):
        m, u, _ = make_world(db_session, role=role, slug_hint=f"ok{role.value[:3]}")
        aid = _seed_action(db_session, m)
        r = client.post(f"/api/actions/{aid}/approve", headers=bearer(u))
        assert r.status_code == 200
        assert r.json()["status"] == "approved"


class TestOperationalRoleEnforcement:
    def test_analyst_cannot_run_agents(self, client, secure, db_session):
        m, u, _ = make_world(db_session, role=UserRole.analyst, slug_hint="anag")
        r = client.post(
            "/api/agents/run",
            json={"mode": "fast"},
            headers=bearer(u),
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "INSUFFICIENT_ROLE"

    def test_analyst_cannot_create_simulation(self, client, secure, db_session):
        m, u, _ = make_world(db_session, role=UserRole.analyst, slug_hint="ansim")
        r = client.post(
            "/api/simulations",
            json={"scenario_type": "discount", "discount_percentage": 5,
                  "target_customers": 10, "expected_conversion": 0.2,
                  "avg_order_value": 100},
            headers=bearer(u),
        )
        assert r.status_code == 403

    def test_analyst_can_read(self, client, secure, db_session):
        m, u, _ = make_world(db_session, role=UserRole.analyst, slug_hint="anrd")
        for path in ("/api/customers", "/api/products", "/api/orders",
                     "/api/payments", "/api/opportunities/ranked",
                     "/api/radar", "/api/simulations", "/api/experiments",
                     "/api/growth-memory", "/api/growth-brief"):
            r = client.get(path, headers=bearer(u))
            assert r.status_code == 200, f"{path} -> {r.status_code}"

    def test_analyst_cannot_refresh_radar(self, client, secure, db_session):
        m, u, _ = make_world(db_session, role=UserRole.analyst, slug_hint="anrf")
        r = client.get("/api/radar?refresh=true", headers=bearer(u))
        assert r.status_code == 403

    def test_operator_can_execute_but_not_approve(self, client, secure, db_session):
        """Execution is an allowed OPERATOR workflow — but only after an
        admin/owner approved, and always behind Guardrail #2."""
        from tests.security_utils import make_user, make_membership

        m, u_op, _ = make_world(db_session, role=UserRole.operator, slug_hint="opex")
        u_admin = make_user(db_session, "opadmin")
        make_membership(db_session, u_admin, m, UserRole.admin)
        aid = _seed_action(db_session, m)

        r = client.post(f"/api/actions/{aid}/execute", headers=bearer(u_op))
        # Not yet approved — blocked by state machine, NOT by role.
        assert r.status_code == 400
        body = r.json()
        assert body["detail"]["error"].startswith("INVALID_ACTION_STATE")

        # Admin approves…
        r = client.post(f"/api/actions/{aid}/approve", headers=bearer(u_admin))
        assert r.status_code == 200
        # …operator may now execute (test-mode executor).
        r = client.post(f"/api/actions/{aid}/execute", headers=bearer(u_op))
        assert r.status_code == 200


class TestMembershipAdministration:
    def test_operator_cannot_manage_members(self, client, secure, db_session):
        m, u_op, _ = make_world(db_session, role=UserRole.operator, slug_hint="opmm")
        r = client.get(
            f"/api/auth/merchants/{m.id}/members", headers=bearer(u_op)
        )
        assert r.status_code == 403

        r = client.post(
            f"/api/auth/merchants/{m.id}/members",
            json={"email": f"x-{uuid.uuid4().hex[:6]}@t.test",
                  "role": "analyst", "initial_password": "LongEnough123"},
            headers=bearer(u_op),
        )
        assert r.status_code == 403

    def test_admin_can_add_analyst_member(self, client, secure, db_session):
        m, u_admin, _ = make_world(db_session, role=UserRole.admin, slug_hint="adma")
        email = f"new-analyst-{uuid.uuid4().hex[:6]}@t.test"
        r = client.post(
            f"/api/auth/merchants/{m.id}/members",
            json={"email": email, "role": "analyst",
                  "initial_password": "LongEnough123"},
            headers=bearer(u_admin),
        )
        assert r.status_code == 201
        assert r.json()["role"] == "analyst"

        # The new analyst can authenticate and read, but cannot approve.
        login = client.post(
            "/api/auth/login", json={"email": email, "password": "LongEnough123"}
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        r = client.get(
            "/api/customers", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
        aid = _seed_action(db_session, m)
        r = client.post(
            f"/api/actions/{aid}/approve", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 403

    def test_admin_cannot_create_owner(self, client, secure, db_session):
        m, u_admin, _ = make_world(db_session, role=UserRole.admin, slug_hint="admo")
        r = client.post(
            f"/api/auth/merchants/{m.id}/members",
            json={"email": f"o-{uuid.uuid4().hex[:6]}@t.test", "role": "owner",
                  "initial_password": "LongEnough123"},
            headers=bearer(u_admin),
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "OWNER_REQUIRED"

    def test_owner_can_promote_to_owner(self, client, secure, db_session):
        m, u_owner, _ = make_world(db_session, role=UserRole.owner, slug_hint="owno")
        email = f"co-owner-{uuid.uuid4().hex[:6]}@t.test"
        r = client.post(
            f"/api/auth/merchants/{m.id}/members",
            json={"email": email, "role": "owner",
                  "initial_password": "LongEnough123"},
            headers=bearer(u_owner),
        )
        assert r.status_code == 201

    def test_last_owner_protected_from_demotion_and_removal(
        self, client, secure, db_session
    ):
        m, u_owner, mem = make_world(db_session, role=UserRole.owner, slug_hint="lsto")
        me_id = None
        me = client.get("/api/auth/me", headers=bearer(u_owner)).json()
        mine = [
            x for x in me["memberships"] if x["merchant_id"] == str(m.id)
        ]
        my_membership_user = u_owner.id

        # Demote own sole-owner role → blocked.
        r = client.patch(
            f"/api/auth/merchants/{m.id}/members/{my_membership_user}",
            json={"role": "analyst"},
            headers=bearer(u_owner),
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "LAST_OWNER_PROTECTED"

        # Remove self as sole owner → blocked.
        r = client.delete(
            f"/api/auth/merchants/{m.id}/members/{my_membership_user}",
            headers=bearer(u_owner),
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "LAST_OWNER_PROTECTED"

    def test_cross_tenant_member_listing_denied(self, client, secure, db_session):
        m_a, u_a, _ = make_world(db_session, role=UserRole.owner, slug_hint="mma")
        m_b, _, _ = make_world(db_session, role=UserRole.owner, slug_hint="mmb")
        r = client.get(
            f"/api/auth/merchants/{m_b.id}/members", headers=bearer(u_a)
        )
        assert r.status_code == 403
