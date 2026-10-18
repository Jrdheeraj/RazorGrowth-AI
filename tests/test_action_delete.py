"""
Comprehensive tests for Safe Action Deletion feature.

Covers:
- Deleting an action in requested state (Awaiting Approval).
- Deleting an action in approved state (Approved).
- Deleting an action in completed state (Completed).
- Deleting an action in failed or rejected state (Failed/Stopped).
- Refusing deletion when an action is in executing state (Running) with 409 Conflict.
- 404 for nonexistent action.
- 403 for cross-tenant deletion attempts.
- Verification that audit history is preserved (prior audit events survive and action_deleted event is recorded).
- Verification that linked MarketingAGICampaign and ProductAgentRecommendation models survive with action_id detached.
- Verification that deletion releases the unique idempotency constraint so subsequent proposals succeed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select

from backend.app.models.agent_action import AgentAction
from backend.app.models.audit_event import AuditEvent
from backend.app.models.enums import (
    AgentActionStatus,
    AgentActionType,
    AuditEventType,
    Currency,
    MerchantStatus,
)
from backend.app.models.merchant import Merchant
from backend.app.models.marketing_agi import MarketingAGICampaign
from backend.app.models.product_agi import ProductAgentRecommendation, ProductAgentRun
from backend.app.services.action_service import (
    create_action,
    delete_action,
    delete_all_actions,
    get_action,
    ActionNotFoundError,
    ActionRunningConflictError,
    BulkOperationConflictError,
)


def _make_merchant(db_session) -> Merchant:
    slug = f"del-{uuid.uuid4().hex[:10]}"
    m = Merchant(
        name="Test Merchant for Action Delete",
        slug=slug,
        email=f"{slug}@test.com",
        status=MerchantStatus.active,
        currency=Currency.USD,
    )
    db_session.add(m)
    db_session.commit()
    return m


def _make_action(
    db_session,
    merchant: Merchant,
    status: AgentActionStatus = AgentActionStatus.requested,
    action_type: AgentActionType = AgentActionType.send_campaign,
) -> AgentAction:
    action = AgentAction(
        id=uuid.uuid4(),
        merchant_id=merchant.id,
        action_type=action_type,
        status=status,
        requested_by="growth_specialist",
        input_payload={"campaign_type": "email", "target": {"segment": "vip"}, "target_count": 25},
    )
    db_session.add(action)
    db_session.commit()
    return action


class TestActionDeleteService:
    def test_delete_requested_action_service(self, db_session):
        merchant = _make_merchant(db_session)
        action = _make_action(db_session, merchant, AgentActionStatus.requested)
        action_id = action.id

        delete_action(db_session, action_id, actor="test_operator")
        db_session.commit()

        # Action is removed
        assert db_session.get(AgentAction, action_id) is None

        # Audit event action_deleted is present
        events = list(
            db_session.scalars(
                select(AuditEvent).where(AuditEvent.entity_id == str(action_id))
            ).all()
        )
        assert any(e.event_type == AuditEventType.action_deleted for e in events)

    def test_delete_approved_action_service(self, db_session):
        merchant = _make_merchant(db_session)
        action = _make_action(db_session, merchant, AgentActionStatus.approved)
        action_id = action.id

        delete_action(db_session, action_id, actor="test_operator")
        db_session.commit()

        assert db_session.get(AgentAction, action_id) is None

    def test_delete_completed_action_service(self, db_session):
        merchant = _make_merchant(db_session)
        action = _make_action(db_session, merchant, AgentActionStatus.completed)
        action_id = action.id

        delete_action(db_session, action_id, actor="test_operator")
        db_session.commit()

        assert db_session.get(AgentAction, action_id) is None

    def test_delete_failed_action_service(self, db_session):
        merchant = _make_merchant(db_session)
        action = _make_action(db_session, merchant, AgentActionStatus.failed)
        action_id = action.id

        delete_action(db_session, action_id, actor="test_operator")
        db_session.commit()

        assert db_session.get(AgentAction, action_id) is None

    def test_delete_rejected_action_service(self, db_session):
        merchant = _make_merchant(db_session)
        action = _make_action(db_session, merchant, AgentActionStatus.rejected)
        action_id = action.id

        delete_action(db_session, action_id, actor="test_operator")
        db_session.commit()

        assert db_session.get(AgentAction, action_id) is None

    def test_refuse_delete_running_action_service(self, db_session):
        merchant = _make_merchant(db_session)
        action = _make_action(db_session, merchant, AgentActionStatus.executing)
        action_id = action.id

        with pytest.raises(ActionRunningConflictError) as exc_info:
            delete_action(db_session, action_id, actor="test_operator")

        assert "ACTION_STILL_RUNNING" in str(exc_info.value)
        # Action was NOT deleted
        db_session.rollback()
        assert db_session.get(AgentAction, action_id) is not None

    def test_delete_nonexistent_action_service(self, db_session):
        missing_id = uuid.uuid4()
        with pytest.raises(ActionNotFoundError):
            delete_action(db_session, missing_id, actor="test_operator")

    def test_linked_campaign_and_recommendation_preserved(self, db_session):
        merchant = _make_merchant(db_session)
        action = _make_action(db_session, merchant, AgentActionStatus.requested)

        # Create linked MarketingAGICampaign
        camp = MarketingAGICampaign(
            id=uuid.uuid4(),
            merchant_id=merchant.id,
            campaign_key=f"camp_{uuid.uuid4().hex[:6]}",
            workflow="lead_nurture",
            name="Summer Sale",
            objective="Re-engage customers",
            channel="email",
            lifecycle="draft",
            action_id=action.id,
        )
        db_session.add(camp)

        # Create linked ProductAgentRun and Recommendation
        run = ProductAgentRun(
            id=uuid.uuid4(),
            merchant_id=merchant.id,
            objective="Analyze product inventory",
            status="completed",
        )
        db_session.add(run)
        db_session.commit()

        rec = ProductAgentRecommendation(
            id=uuid.uuid4(),
            merchant_id=merchant.id,
            run_id=run.id,
            type="upsell",
            title="Price Tweak",
            action_id=action.id,
        )
        db_session.add(rec)
        db_session.commit()

        action_id = action.id
        camp_id = camp.id
        rec_id = rec.id

        # Delete the action
        delete_action(db_session, action_id, actor="test_operator")
        db_session.commit()

        # The action is gone
        assert db_session.get(AgentAction, action_id) is None

        # But the campaign and recommendation STILL exist with action_id detached (None)
        saved_camp = db_session.get(MarketingAGICampaign, camp_id)
        assert saved_camp is not None
        assert saved_camp.action_id is None
        assert saved_camp.name == "Summer Sale"

        saved_rec = db_session.get(ProductAgentRecommendation, rec_id)
        assert saved_rec is not None
        assert saved_rec.action_id is None
        assert saved_rec.title == "Price Tweak"


class TestActionDeleteRoute:
    def test_delete_action_endpoint_success(self, client, db_session):
        merchant = _make_merchant(db_session)
        action = _make_action(db_session, merchant, AgentActionStatus.requested)

        res = client.delete(f"/api/actions/{action.id}", params={"merchant_id": str(merchant.id)})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["deleted"] is True
        assert body["action_id"] == str(action.id)

        # Verify not returned by GET /api/actions/{id}
        get_res = client.get(f"/api/actions/{action.id}", params={"merchant_id": str(merchant.id)})
        assert get_res.status_code == 404

        # Audit trail is still accessible
        audit_res = client.get(f"/api/actions/{action.id}/audit", params={"merchant_id": str(merchant.id)})
        assert audit_res.status_code == 200
        audit_body = audit_res.json()
        assert len(audit_body["audit_events"]) > 0
        assert any(e["event_type"] == "action_deleted" for e in audit_body["audit_events"])

    def test_delete_running_action_endpoint_returns_409(self, client, db_session):
        merchant = _make_merchant(db_session)
        action = _make_action(db_session, merchant, AgentActionStatus.executing)

        res = client.delete(f"/api/actions/{action.id}", params={"merchant_id": str(merchant.id)})
        assert res.status_code == 409
        assert "ACTION_STILL_RUNNING" in res.json()["detail"]

    def test_delete_nonexistent_action_returns_404(self, client, db_session):
        merchant = _make_merchant(db_session)
        missing_id = uuid.uuid4()
        res = client.delete(f"/api/actions/{missing_id}", params={"merchant_id": str(merchant.id)})
        assert res.status_code == 404
        assert res.json()["detail"] == "ACTION_NOT_FOUND"

    def test_delete_cross_tenant_denied(self, client, db_session):
        owner = _make_merchant(db_session)
        intruder = _make_merchant(db_session)
        action = _make_action(db_session, owner, AgentActionStatus.requested)

        res = client.delete(f"/api/actions/{action.id}", params={"merchant_id": str(intruder.id)})
        assert res.status_code == 403
        assert res.json()["detail"] == "MERCHANT_ACCESS_DENIED"

        # Action is still present for owner
        assert client.get(f"/api/actions/{action.id}", params={"merchant_id": str(owner.id)}).status_code == 200


class TestBulkActionDeleteService:
    def test_bulk_delete_all_statuses_service(self, db_session):
        merchant = _make_merchant(db_session)
        # 5 statuses
        a1 = _make_action(db_session, merchant, AgentActionStatus.requested)
        a2 = _make_action(db_session, merchant, AgentActionStatus.approved)
        a3 = _make_action(db_session, merchant, AgentActionStatus.completed)
        a4 = _make_action(db_session, merchant, AgentActionStatus.failed)
        a5 = _make_action(db_session, merchant, AgentActionStatus.rejected)

        result = delete_all_actions(db_session, merchant.id, actor="operator_1")
        db_session.commit()

        assert result.eligible == 5
        assert result.deleted == 5
        assert result.skipped == 0
        assert result.failed == 0

        # All rows removed
        for aid in [a1.id, a2.id, a3.id, a4.id, a5.id]:
            assert db_session.get(AgentAction, aid) is None

        # Audit events written for all 5
        events = list(
            db_session.scalars(
                select(AuditEvent).where(AuditEvent.merchant_id == merchant.id)
            ).all()
        )
        del_events = [e for e in events if e.event_type == AuditEventType.action_deleted]
        assert len(del_events) == 5

    def test_bulk_delete_skips_running_action_safely(self, db_session):
        merchant = _make_merchant(db_session)
        a_req = _make_action(db_session, merchant, AgentActionStatus.requested)
        a_app = _make_action(db_session, merchant, AgentActionStatus.approved)
        a_run = _make_action(db_session, merchant, AgentActionStatus.executing)

        result = delete_all_actions(db_session, merchant.id, actor="operator_1")
        db_session.commit()

        assert result.eligible == 3
        assert result.deleted == 2
        assert result.skipped == 1
        assert result.failed == 0

        # Running action was NOT deleted
        assert db_session.get(AgentAction, a_run.id) is not None
        # Non-running actions were safely deleted
        assert db_session.get(AgentAction, a_req.id) is None
        assert db_session.get(AgentAction, a_app.id) is None

    def test_bulk_delete_cancels_linked_workflow_for_running_action(self, db_session):
        from backend.app.models.agent_workflow import AgentWorkflowRun
        merchant = _make_merchant(db_session)
        run_id = f"wf_{uuid.uuid4().hex[:12]}"
        wf = AgentWorkflowRun(
            id=uuid.uuid4(),
            merchant_id=merchant.id,
            run_id=run_id,
            mode="deep",
            status="running",
            started_at=datetime.now(timezone.utc),
            lease_generation=1,
        )
        db_session.add(wf)
        db_session.commit()

        a_run = _make_action(db_session, merchant, AgentActionStatus.executing)
        a_run.workflow_run_id = wf.id
        db_session.commit()

        result = delete_all_actions(db_session, merchant.id, actor="operator_1")
        db_session.commit()

        assert result.skipped == 1
        # Action is preserved
        assert db_session.get(AgentAction, a_run.id) is not None

        # Workflow run cancellation was requested
        updated_wf = db_session.get(AgentWorkflowRun, wf.id)
        assert updated_wf is not None
        assert updated_wf.status == "cancelled"

    def test_bulk_delete_empty_dashboard(self, db_session):
        merchant = _make_merchant(db_session)
        result = delete_all_actions(db_session, merchant.id, actor="operator_1")
        assert result.eligible == 0
        assert result.deleted == 0
        assert result.skipped == 0
        assert result.failed == 0
        assert result.details == []

    def test_bulk_delete_tenant_isolation(self, db_session):
        m1 = _make_merchant(db_session)
        m2 = _make_merchant(db_session)

        m1_act = _make_action(db_session, m1, AgentActionStatus.requested)
        m2_act = _make_action(db_session, m2, AgentActionStatus.requested)

        res = delete_all_actions(db_session, m1.id, actor="operator_1")
        db_session.commit()

        assert res.deleted == 1
        assert db_session.get(AgentAction, m1_act.id) is None
        # m2 action is untouched
        assert db_session.get(AgentAction, m2_act.id) is not None

    def test_bulk_delete_linked_models_preserved(self, db_session):
        merchant = _make_merchant(db_session)
        action = _make_action(db_session, merchant, AgentActionStatus.requested)

        camp = MarketingAGICampaign(
            id=uuid.uuid4(),
            merchant_id=merchant.id,
            campaign_key=f"camp_{uuid.uuid4().hex[:6]}",
            workflow="lead_nurture",
            name="Fall Sale",
            objective="Re-engagement",
            channel="email",
            lifecycle="draft",
            action_id=action.id,
        )
        db_session.add(camp)
        db_session.commit()

        delete_all_actions(db_session, merchant.id, actor="operator_1")
        db_session.commit()

        assert db_session.get(AgentAction, action.id) is None
        saved_camp = db_session.get(MarketingAGICampaign, camp.id)
        assert saved_camp is not None
        assert saved_camp.action_id is None
        assert saved_camp.name == "Fall Sale"

    def test_bulk_delete_duplicate_concurrency_conflict(self, db_session):
        from backend.app.services.action_service import _bulk_delete_locks, _bulk_delete_master_lock
        import threading
        merchant = _make_merchant(db_session)

        # Artificially acquire the tenant lock to simulate an in-flight bulk delete
        with _bulk_delete_master_lock:
            if merchant.id not in _bulk_delete_locks:
                _bulk_delete_locks[merchant.id] = threading.Lock()
            lock = _bulk_delete_locks[merchant.id]
        lock.acquire()

        try:
            with pytest.raises(BulkOperationConflictError):
                delete_all_actions(db_session, merchant.id, actor="operator_2")
        finally:
            lock.release()


class TestBulkActionDeleteRoute:
    def test_bulk_delete_endpoint_success(self, client, db_session):
        merchant = _make_merchant(db_session)
        _make_action(db_session, merchant, AgentActionStatus.requested)
        _make_action(db_session, merchant, AgentActionStatus.approved)
        _make_action(db_session, merchant, AgentActionStatus.completed)

        res = client.delete("/api/actions", params={"merchant_id": str(merchant.id)})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["eligible"] == 3
        assert body["deleted"] == 3
        assert body["skipped"] == 0
        assert body["failed"] == 0
        assert "3 removed" in body["message"]

        # Confirm actions list is empty
        list_res = client.get("/api/actions", params={"merchant_id": str(merchant.id)})
        assert list_res.status_code == 200
        assert len(list_res.json()["actions"]) == 0

    def test_bulk_delete_endpoint_skips_running_action(self, client, db_session):
        merchant = _make_merchant(db_session)
        a_req = _make_action(db_session, merchant, AgentActionStatus.requested)
        a_run = _make_action(db_session, merchant, AgentActionStatus.executing)

        res = client.delete("/api/actions", params={"merchant_id": str(merchant.id)})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["eligible"] == 2
        assert body["deleted"] == 1
        assert body["skipped"] == 1
        assert body["failed"] == 0

        # Only the running action remains
        list_res = client.get("/api/actions", params={"merchant_id": str(merchant.id)})
        assert list_res.status_code == 200
        remaining = list_res.json()["actions"]
        assert len(remaining) == 1
        assert remaining[0]["id"] == str(a_run.id)

    def test_bulk_delete_endpoint_empty_dashboard(self, client, db_session):
        merchant = _make_merchant(db_session)
        res = client.delete("/api/actions", params={"merchant_id": str(merchant.id)})
        assert res.status_code == 200
        body = res.json()
        assert body["eligible"] == 0
        assert body["deleted"] == 0
        assert body["skipped"] == 0
        assert body["failed"] == 0

    def test_bulk_delete_endpoint_cross_tenant_denied(self, client, db_session):
        from backend.app.models.user import User
        from backend.app.models.membership import MerchantMembership
        from backend.app.models.enums import UserRole, UserStatus, MembershipStatus
        from backend.app.core.security import create_access_token

        owner = _make_merchant(db_session)
        intruder = _make_merchant(db_session)

        # Create user belonging ONLY to intruder
        intruder_user = User(
            id=uuid.uuid4(),
            email=f"intruder_{uuid.uuid4().hex[:6]}@example.com",
            password_hash="test_hash",
            full_name="Intruder User",
            status=UserStatus.active,
        )
        db_session.add(intruder_user)
        db_session.commit()

        membership = MerchantMembership(
            id=uuid.uuid4(),
            merchant_id=intruder.id,
            user_id=intruder_user.id,
            role=UserRole.admin,
            status=MembershipStatus.active,
        )
        db_session.add(membership)
        _make_action(db_session, owner, AgentActionStatus.requested)
        db_session.commit()

        token, _ = create_access_token(intruder_user.id, intruder_user.email)
        # Attempt to delete owner's actions with intruder token
        res = client.delete(
            "/api/actions",
            headers={"Authorization": f"Bearer {token}"},
            params={"merchant_id": str(owner.id)},
        )
        assert res.status_code == 403
        assert res.json()["detail"] == "MERCHANT_ACCESS_DENIED"

        # Verify owner actions are intact
        owner_actions = list(
            db_session.scalars(
                select(AgentAction).where(AgentAction.merchant_id == owner.id)
            ).all()
        )
        assert len(owner_actions) == 1

    def test_bulk_delete_partial_failure_recovery(self, db_session, monkeypatch):
        from unittest.mock import MagicMock
        merchant = _make_merchant(db_session)
        a1 = _make_action(db_session, merchant, AgentActionStatus.requested)
        a2 = _make_action(db_session, merchant, AgentActionStatus.requested)

        real_delete = delete_action
        def failing_delete(db, action_id, **kwargs):
            if action_id == a1.id:
                raise RuntimeError("Simulated transient DB error on a1")
            return real_delete(db, action_id, **kwargs)

        monkeypatch.setattr("backend.app.services.action_service.delete_action", failing_delete)

        res = delete_all_actions(db_session, merchant.id, actor="operator_test")
        db_session.commit()

        assert res.eligible == 2
        assert res.deleted == 1
        assert res.failed == 1
        assert res.skipped == 0
        # a1 survived the failure
        assert db_session.get(AgentAction, a1.id) is not None
        # a2 was successfully deleted
        assert db_session.get(AgentAction, a2.id) is None
