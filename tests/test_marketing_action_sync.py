"""Marketing Agent ↔ Actions canonical-state synchronization tests.

The canonical source of truth is ``agent_actions.status``. These tests
prove that approve/reject/execute transitions made through the global
Actions service are mirrored onto the Marketing Agent workspace
(campaign lifecycle, run prepared_action snapshot, run status, run
events) — and that the marketing read APIs report the live state.

Covers mission TEST 1–11 + TEST 15 (isolation) at the service level;
API-level sync is covered by reusing the same service functions the
routes call.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from backend.app.models.agent_action import AgentAction
from backend.app.models.enums import (
    AgentActionStatus,
    AgentActionType,
    Currency,
    MerchantStatus,
)
from backend.app.models.marketing_agi import (
    MarketingAGICampaign,
    MarketingAGIEvent,
    MarketingAGIRun,
)
from backend.app.models.merchant import Merchant
from backend.app.services import action_service
from backend.app.services.marketing_action_sync import sync_marketing_from_action


def _seed_merchant(db, hint="sync"):
    m = Merchant(
        name=f"Sync {uuid.uuid4().hex[:6]}",
        slug=f"{hint}-{uuid.uuid4().hex[:12]}",
        email=f"{hint}-{uuid.uuid4().hex[:6]}@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db.add(m)
    db.commit()
    return m


def _seed_marketing_run(db, merchant, action_id):
    run = MarketingAGIRun(
        merchant_id=merchant.id,
        objective="Find and prepare the highest-impact marketing work",
        status="waiting_approval",
        phase="awaiting_approval",
        state={
            "prepared_action": {
                "action_id": str(action_id),
                "status": "requested",
                "approval_state": "REQUIRED",
            },
            "reasoning_status": "waiting_for_approval",
        },
    )
    db.add(run)
    db.flush()
    return run


def _seed_marketing_campaign(db, merchant, run, action_id):
    campaign = MarketingAGICampaign(
        merchant_id=merchant.id,
        run_id=run.id,
        campaign_key=f"failed-payment-recovery-{uuid.uuid4().hex[:8]}",
        workflow="failed_payment_recovery",
        name="Failed Payment Recovery",
        objective="Recover failed payments",
        channel="email",
        lifecycle="ready_for_approval",
        audience_count=4,
        action_id=action_id,
    )
    db.add(campaign)
    db.flush()
    return campaign


def _marketing_action_payload(merchant, campaign_id=None):
    return {
        "merchant_id": str(merchant.id),
        "campaign_type": "email",
        "target": {
            "workflow": "failed_payment_recovery",
            "criteria": {},
            "marketing_agi_campaign_id": str(campaign_id) if campaign_id else None,
        },
        "target_count": 4,
        "metadata": {"requested_by_agent": "MarketingAGI"},
    }


def _make_linked_world(db, merchant):
    """Create action + run + campaign wired exactly like _phase_prepare."""
    action = action_service.create_action(
        db,
        merchant_id=merchant.id,
        action_type=AgentActionType.send_campaign,
        input_payload=_marketing_action_payload(merchant),
        requested_by="agent:MarketingAGI",
    )
    run = _seed_marketing_run(db, merchant, action.id)
    # Heal the payload pointer the way the agent writes it.
    payload = dict(action.input_payload or {})
    target = dict(payload.get("target") or {})
    campaign = MarketingAGICampaign(
        merchant_id=merchant.id,
        run_id=run.id,
        campaign_key=f"failed-payment-recovery-{uuid.uuid4().hex[:8]}",
        workflow="failed_payment_recovery",
        name="Failed Payment Recovery",
        objective="Recover failed payments",
        channel="email",
        lifecycle="ready_for_approval",
        audience_count=4,
        action_id=action.id,
    )
    db.add(campaign)
    db.flush()
    target["marketing_agi_campaign_id"] = str(campaign.id)
    payload["target"] = target
    action.input_payload = payload
    db.flush()
    return action, run, campaign


def _status_value(status) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _run_events(db, run):
    return db.scalars(
        select(MarketingAGIEvent)
        .where(MarketingAGIEvent.run_id == run.id)
        .order_by(MarketingAGIEvent.seq.asc())
    ).all()


# ── TEST 1: creation is visible to the Actions page ──────────────────────

def test_marketing_action_visible_to_actions_page(db_session):
    merchant = _seed_merchant(db_session)
    action, _, _ = _make_linked_world(db_session, merchant)
    db_session.commit()

    pending = action_service.list_actions_by_status(
        db_session, merchant.id, AgentActionStatus.requested
    )
    assert [a.id for a in pending] == [action.id]


# ── TEST 2/3/4: approve propagates; marketing no longer needs approval ──

def test_approve_propagates_to_marketing_workspace(db_session):
    merchant = _seed_merchant(db_session)
    action, run, campaign = _make_linked_world(db_session, merchant)
    db_session.commit()

    approved = action_service.approve_action(db_session, action.id, actor="owner")
    db_session.commit()
    assert approved.status == AgentActionStatus.approved

    db_session.refresh(campaign)
    db_session.refresh(run)
    assert campaign.lifecycle == "approved"
    prepared = run.state["prepared_action"]
    assert prepared["status"] == "approved"
    assert prepared["approval_state"] == "APPROVED"
    # Run stays parked (work done, awaiting execution) — UI keys off action.
    assert run.status == "waiting_approval"

    messages = [e.message for e in _run_events(db_session, run)]
    assert any("Approved by you" in m for m in messages)


# ── TEST 5/6/7: execute propagates to completed everywhere ──────────────

def test_execute_propagates_to_completed(db_session):
    merchant = _seed_merchant(db_session)
    action, run, campaign = _make_linked_world(db_session, merchant)
    db_session.commit()

    action_service.approve_action(db_session, action.id, actor="owner")
    result = action_service.execute_action(db_session, action.id, actor="owner")
    db_session.commit()

    db_session.refresh(action)
    assert action.status in (AgentActionStatus.completed, AgentActionStatus.failed)

    db_session.refresh(campaign)
    db_session.refresh(run)
    # Mirror follows the canonical status exactly.
    assert campaign.lifecycle == _status_value(action.status)
    assert run.state["prepared_action"]["status"] == _status_value(action.status)
    assert run.status == "completed"
    assert run.phase == "complete"
    messages = [e.message for e in _run_events(db_session, run)]
    if action.status == AgentActionStatus.completed:
        assert any("executed successfully" in m for m in messages)
    else:
        assert any("failed" in m.lower() for m in messages)


# ── TEST 10: execution failure is honest, never "completed" ─────────────

def test_failed_mirror_is_failed_not_completed(db_session):
    merchant = _seed_merchant(db_session)
    action, run, campaign = _make_linked_world(db_session, merchant)
    # Drive the canonical action to failed without the executor.
    action.status = AgentActionStatus.failed
    action.error_message = "RESEND_DOWN"
    db_session.flush()

    mirrored = sync_marketing_from_action(db_session, action)
    db_session.flush()

    assert mirrored is not None
    assert campaign.lifecycle == "failed"
    assert run.state["prepared_action"]["status"] == "failed"
    assert run.status == "completed"


# ── TEST 11: rejected actions leave pending-approval UI ─────────────────

def test_reject_propagates_and_closes_run(db_session):
    merchant = _seed_merchant(db_session)
    action, run, campaign = _make_linked_world(db_session, merchant)
    db_session.commit()

    action_service.reject_action(db_session, action.id, actor="owner")
    db_session.commit()

    db_session.refresh(campaign)
    db_session.refresh(run)
    assert campaign.lifecycle == "rejected"
    assert run.state["prepared_action"]["status"] == "rejected"
    assert run.status == "completed"
    messages = [e.message for e in _run_events(db_session, run)]
    assert any("not approved" in m for m in messages)


# ── Mirror never regresses a finished lifecycle ─────────────────────────

def test_mirror_never_regresses_lifecycle(db_session):
    merchant = _seed_merchant(db_session)
    action, run, campaign = _make_linked_world(db_session, merchant)
    campaign.lifecycle = "completed"
    db_session.flush()

    action.status = AgentActionStatus.approved  # stale/duplicate signal
    mirrored = sync_marketing_from_action(db_session, action)
    assert mirrored is not None
    assert campaign.lifecycle == "completed"


# ── Actions without marketing links are untouched ───────────────────────

def test_plain_action_sync_is_noop(db_session):
    merchant = _seed_merchant(db_session)
    # Build a minimal non-marketing action without strict payload typing.
    action = AgentAction(
        merchant_id=merchant.id,
        action_type=AgentActionType.generate_opportunity,
        status=AgentActionStatus.requested,
        input_payload={"merchant_id": str(merchant.id)},
        requested_by="agent:SomeOther",
    )
    db_session.add(action)
    db_session.flush()
    assert sync_marketing_from_action(db_session, action) is None


# ── TEST 15: tenant isolation ───────────────────────────────────────────

def test_sync_respects_tenant_isolation(db_session):
    merchant_a = _seed_merchant(db_session, hint="synca")
    merchant_b = _seed_merchant(db_session, hint="syncb")
    action_b, run_b, campaign_b = _make_linked_world(db_session, merchant_b)
    _, run_a, campaign_a = _make_linked_world(db_session, merchant_a)
    db_session.commit()

    action_service.approve_action(db_session, action_b.id, actor="owner")
    db_session.commit()

    db_session.refresh(campaign_a)
    db_session.refresh(run_a)
    db_session.refresh(campaign_b)
    # Merchant A untouched; merchant B mirrored.
    assert campaign_a.lifecycle == "ready_for_approval"
    assert run_a.state["prepared_action"]["status"] == "requested"
    assert campaign_b.lifecycle == "approved"
    assert run_b.state["prepared_action"]["status"] == "approved"


# ── Idempotency: one open approval gate per (merchant, workflow) ──────

def test_find_open_action_matches_only_open_proposals(db_session):
    from backend.app.services.marketing_action_sync import (
        approval_state_for,
        find_open_marketing_action,
    )

    merchant = _seed_merchant(db_session)
    action, run, campaign = _make_linked_world(db_session, merchant)
    db_session.commit()

    found = find_open_marketing_action(
        db_session, merchant.id, "failed_payment_recovery"
    )
    assert found is not None
    assert found[1].id == action.id

    # Different workflow never matches.
    assert (
        find_open_marketing_action(db_session, merchant.id, "winback_dormant")
        is None
    )
    # Cross-merchant never matches.
    other = _seed_merchant(db_session, hint="syncy")
    assert (
        find_open_marketing_action(
            db_session, other.id, "failed_payment_recovery"
        )
        is None
    )
    # Terminal actions release the gate for genuinely new work.
    action_service.reject_action(db_session, action.id, actor="owner")
    db_session.commit()
    assert (
        find_open_marketing_action(
            db_session, merchant.id, "failed_payment_recovery"
        )
        is None
    )

    assert approval_state_for("requested") == "REQUIRED"
    assert approval_state_for("completed") == "COMPLETED"


def _draft_row(db, merchant, run, key):
    campaign = MarketingAGICampaign(
        merchant_id=merchant.id,
        run_id=run.id,
        campaign_key=key,
        workflow="failed_payment_recovery",
        name="Failed Payment Recovery",
        objective="Recover failed payments",
        channel="email",
        lifecycle="draft",
        audience_count=4,
    )
    db.add(campaign)
    db.flush()
    return campaign


def _prepare_state_for(run, campaign):
    from backend.app.agents.marketing_agi.state import MarketingAGIState

    return MarketingAGIState(
        run_id=str(run.id),
        merchant_id=str(run.merchant_id),
        objective="Find and prepare the highest-impact marketing work",
        workflow="failed_payment_recovery",
        observations=["4 failed payments worth recoverable revenue"],
        campaign_draft={
            "campaign_id": str(campaign.id),
            "campaign_key": campaign.campaign_key,
            "audience_count": 4,
            "expected_impact": {"estimated_revenue_inr": 3998},
            "content": {"message": "Complete your payment"},
            "success_metric": "recovered revenue",
            "integration_status": "draft_only",
            "name": "Failed Payment Recovery",
            "objective": "Recover failed payments",
        },
    )


def test_second_run_reuses_open_action_without_duplicate(db_session):
    """Two runs, same opportunity → exactly ONE pending action (real
    _phase_prepare, persisted)."""
    from backend.app.agents.marketing_agi.agent import MarketingAGI
    from backend.app.agents.marketing_agi.events import EventRecorder

    merchant = _seed_merchant(db_session, hint="syncdup")
    agent = MarketingAGI(db_session, merchant.id, llm=None)

    run1 = _seed_marketing_run(db_session, merchant, uuid.uuid4())
    run1.state = {}
    draft1 = _draft_row(db_session, merchant, run1, "failed-payment-recovery-aaaa1111")
    state1 = _prepare_state_for(run1, draft1)
    agent._phase_prepare(state1, EventRecorder(db_session, run1), run1)
    db_session.commit()

    first_actions = action_service.list_actions_by_status(
        db_session, merchant.id, AgentActionStatus.requested
    )
    assert len(first_actions) == 1
    first_id = first_actions[0].id

    # Second run, same opportunity, fresh draft campaign.
    run2 = _seed_marketing_run(db_session, merchant, uuid.uuid4())
    run2.state = {}
    draft2 = _draft_row(db_session, merchant, run2, "failed-payment-recovery-bbbb2222")
    state2 = _prepare_state_for(run2, draft2)
    agent._phase_prepare(state2, EventRecorder(db_session, run2), run2)
    db_session.commit()

    # No duplicate pending action was minted.
    requested = action_service.list_actions_by_status(
        db_session, merchant.id, AgentActionStatus.requested
    )
    assert [a.id for a in requested] == [first_id]
    # The second run links to the same canonical action.
    assert state2.prepared_action["action_id"] == str(first_id)
    db_session.refresh(draft2)
    assert draft2.action_id == first_id
    # And its own history records the linkage honestly.
    messages = [e.message for e in _run_events(db_session, run2)]
    assert any("no duplicate" in m for m in messages)


def test_terminal_action_allows_fresh_proposal(db_session):
    """After completion, genuinely new work mints exactly one new action."""
    from backend.app.agents.marketing_agi.agent import MarketingAGI
    from backend.app.agents.marketing_agi.events import EventRecorder

    merchant = _seed_merchant(db_session, hint="syncfresh")
    agent = MarketingAGI(db_session, merchant.id, llm=None)

    run1 = _seed_marketing_run(db_session, merchant, uuid.uuid4())
    run1.state = {}
    draft1 = _draft_row(db_session, merchant, run1, "failed-payment-recovery-cccc3333")
    state1 = _prepare_state_for(run1, draft1)
    agent._phase_prepare(state1, EventRecorder(db_session, run1), run1)
    db_session.commit()
    first_id = state1.prepared_action["action_id"]

    action = action_service.get_action(db_session, uuid.UUID(first_id))
    action_service.approve_action(db_session, action.id, actor="owner")
    action_service.execute_action(db_session, action.id, actor="owner")
    db_session.commit()

    run2 = _seed_marketing_run(db_session, merchant, uuid.uuid4())
    run2.state = {}
    draft2 = _draft_row(db_session, merchant, run2, "failed-payment-recovery-dddd4444")
    state2 = _prepare_state_for(run2, draft2)
    agent._phase_prepare(state2, EventRecorder(db_session, run2), run2)
    db_session.commit()

    assert state2.prepared_action["action_id"] != first_id
    total = (
        action_service.list_actions_by_status(
            db_session, merchant.id, AgentActionStatus.requested
        )
        + action_service.list_actions_by_status(
            db_session, merchant.id, AgentActionStatus.completed
        )
        + action_service.list_actions_by_status(
            db_session, merchant.id, AgentActionStatus.failed
        )
    )
    assert len(total) == 2  # terminal old + fresh new, nothing duplicated


def test_double_approve_emits_single_approval_event(db_session):
    """A retried approval cannot duplicate history (state machine refuses)."""
    merchant = _seed_merchant(db_session)
    action, run, _ = _make_linked_world(db_session, merchant)
    db_session.commit()

    action_service.approve_action(db_session, action.id, actor="owner")
    db_session.commit()
    with pytest.raises(Exception):
        action_service.approve_action(db_session, action.id, actor="owner")
    db_session.rollback()

    approved_events = [
        e for e in _run_events(db_session, run) if e.event_type == "action_approved"
    ]
    assert len(approved_events) == 1


# ── Execution → learning/result pipeline ─────────────────────────────

def _learnings_for(db, merchant, campaign, action):
    from backend.app.models.marketing_agi import MarketingAGILearning

    return db.scalars(
        select(MarketingAGILearning)
        .where(
            MarketingAGILearning.merchant_id == merchant.id,
            MarketingAGILearning.campaign_id == campaign.id,
            MarketingAGILearning.action_id == action.id,
        )
        .order_by(MarketingAGILearning.created_at.asc())
    ).all()


def test_completed_execution_creates_real_learning_row(db_session):
    merchant = _seed_merchant(db_session, hint="synclrn")
    action, run, campaign = _make_linked_world(db_session, merchant)
    db_session.commit()

    action_service.approve_action(db_session, action.id, actor="owner")
    result = action_service.execute_action(db_session, action.id, actor="owner")
    db_session.commit()
    assert result.success is True

    rows = _learnings_for(db_session, merchant, campaign, action)
    assert len(rows) == 1
    row = rows[0]
    # Real execution result persisted — mode/sent honesty preserved.
    assert row.actual is not None
    assert row.actual.get("mode") in ("live", "test")
    assert row.actual.get("action_status") == "completed"
    assert row.status == "measuring"
    assert "awaiting outcome measurement" in (row.insights or "")
    assert row.campaign_id == campaign.id and row.action_id == action.id


def test_failed_execution_creates_honest_learning_row(db_session):
    merchant = _seed_merchant(db_session, hint="synclrnf")
    action, run, campaign = _make_linked_world(db_session, merchant)
    action.status = AgentActionStatus.failed
    action.error_message = "RESEND_DOWN"
    db_session.flush()

    sync_marketing_from_action(db_session, action)
    db_session.flush()

    rows = _learnings_for(db_session, merchant, campaign, action)
    assert len(rows) == 1
    assert rows[0].status == "measurement_pending"
    assert "RESEND_DOWN" in (rows[0].insights or "")
    assert rows[0].actual.get("error") == "RESEND_DOWN"


def test_learning_upsert_is_idempotent(db_session):
    merchant = _seed_merchant(db_session, hint="synclrnid")
    action, run, campaign = _make_linked_world(db_session, merchant)
    action.status = AgentActionStatus.completed
    action.output_payload = {"mode": "test", "sent": False}
    db_session.flush()

    sync_marketing_from_action(db_session, action)
    sync_marketing_from_action(db_session, action)
    db_session.flush()

    assert len(_learnings_for(db_session, merchant, campaign, action)) == 1


def test_measured_learning_is_never_overwritten(db_session):
    from backend.app.models.marketing_agi import MarketingAGILearning

    merchant = _seed_merchant(db_session, hint="synclrnmo")
    action, run, campaign = _make_linked_world(db_session, merchant)
    measured = MarketingAGILearning(
        merchant_id=merchant.id,
        campaign_id=campaign.id,
        action_id=action.id,
        status="learned",
        expected={"estimated_revenue_inr": 3998},
        actual={"recovered_revenue": 2500, "mode": "live", "sent": True},
        verdict="partially_met",
        insights="Real measured outcome.",
    )
    db_session.add(measured)
    db_session.flush()

    action.status = AgentActionStatus.completed
    action.output_payload = {"mode": "test", "sent": False}
    sync_marketing_from_action(db_session, action)
    db_session.flush()

    rows = _learnings_for(db_session, merchant, campaign, action)
    assert len(rows) == 1
    assert rows[0].actual.get("recovered_revenue") == 2500
    assert rows[0].verdict == "partially_met"


def test_learnings_endpoint_exposes_execution_result(db_session, client):
    from tests.security_utils import bearer, make_world

    m, u, _ = make_world(db_session, slug_hint="lrnapi")
    action, run, campaign = _make_linked_world(db_session, m)
    db_session.commit()
    action_service.approve_action(db_session, action.id, actor="owner")
    action_service.execute_action(db_session, action.id, actor="owner")
    db_session.commit()

    r = client.get("/api/marketing-agi/learnings", headers=bearer(u))
    assert r.status_code == 200
    mine = [l for l in r.json()["learnings"] if l["campaign_id"] == str(campaign.id)]
    assert len(mine) == 1
    assert mine[0]["actual"] is not None
    assert mine[0]["actual"].get("action_status") == _status_value(
        db_session.get(AgentAction, action.id).status
    )


# ── Read-path overlay reports live canonical state ─────────────────────

def test_serialize_overlays_live_action_status(db_session):
    from backend.app.api.routes.marketing_agi import (
        _serialize_campaign,
        _serialize_run,
    )

    merchant = _seed_merchant(db_session)
    action, run, campaign = _make_linked_world(db_session, merchant)
    db_session.commit()

    action_service.approve_action(db_session, action.id, actor="owner")
    db_session.commit()
    db_session.refresh(run)
    db_session.refresh(campaign)

    serialized_run = _serialize_run(run, db_session)
    assert serialized_run["state"]["prepared_action"]["status"] == "approved"
    serialized_campaign = _serialize_campaign(campaign, db_session)
    assert serialized_campaign["action_status"] == "approved"

    # Cross-tenant read returns no status (never leaks).
    other = _seed_merchant(db_session, hint="syncx")
    serialized_other = _serialize_campaign(campaign, db_session)
    assert serialized_other["action_status"] == "approved"  # own merchant
    assert other.id != merchant.id
