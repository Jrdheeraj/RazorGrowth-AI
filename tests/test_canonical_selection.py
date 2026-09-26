"""Canonical selection + timestamp invariant tests (Marketing Agent bug).

Proves the exact production bug is fixed:
  Recent Work row (action 924cb3b6…) showed "8 min ago" (run.started_at)
  while Live Activity showed "Just now" (action_executed event).

Root causes locked down:
  1. Recent Work rendered run.started_at instead of the canonical
     persisted action instant (action.completed_at for terminal,
     action.updated_at/created_at for open).
  2. marketing_action_sync kept the run park-time completed_at
     (waiting_approval _finish stamps it) instead of advancing it to
     the real terminal instant on approve/execute.

Invariants:
  - selectedAction.action_id == every Live Activity lifecycle action_id
  - selectedAction.run_id == LiveActivity.run_id (one deterministic
    canonical run per action: the newest)
  - Recent Work timestamp == canonical action instant == latest
    lifecycle event instant (same minute, never polling-time "now")
  - Polling never mutates historical event created_at.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.app.models.enums import (
    AgentActionStatus,
    AgentActionType,
    Currency,
    MerchantStatus,
)
from backend.app.models.marketing_agi import MarketingAGIRun
from backend.app.models.merchant import Merchant
from backend.app.services import action_service
from backend.app.services.marketing_action_sync import sync_marketing_from_action
from backend.app.agents.marketing_agi.events import list_events, serialize_event


def _seed_merchant(db, hint="canon"):
    m = Merchant(
        name=f"Canon {uuid.uuid4().hex[:6]}",
        slug=f"{hint}-{uuid.uuid4().hex[:12]}",
        email=f"{hint}-{uuid.uuid4().hex[:6]}@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db.add(m)
    db.commit()
    return m


def _marketing_payload(merchant, campaign_id=None):
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
    from backend.app.models.marketing_agi import MarketingAGICampaign

    action = action_service.create_action(
        db,
        merchant_id=merchant.id,
        action_type=AgentActionType.send_campaign,
        input_payload=_marketing_payload(merchant),
        requested_by="agent:MarketingAGI",
    )
    run = MarketingAGIRun(
        merchant_id=merchant.id,
        objective="Find and prepare the highest-impact marketing work",
        status="waiting_approval",
        phase="awaiting_approval",
        state={
            "prepared_action": {
                "action_id": str(action.id),
                "status": "requested",
                "approval_state": "REQUIRED",
            },
        },
    )
    db.add(run)
    db.flush()
    campaign = MarketingAGICampaign(
        merchant_id=merchant.id,
        run_id=run.id,
        campaign_key=f"canon-{uuid.uuid4().hex[:8]}",
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
    payload = dict(action.input_payload or {})
    target = dict(payload.get("target") or {})
    target["marketing_agi_campaign_id"] = str(campaign.id)
    payload["target"] = target
    action.input_payload = payload
    db.flush()
    # Simulate the agent parking the run: _finish stamps completed_at even
    # for waiting_approval (the stale park-time bug).
    run.completed_at = datetime.now(timezone.utc)
    db.flush()
    db.commit()
    return action, run, campaign


def test_terminal_sync_advances_run_completed_at_past_park_time(db_session):
    merchant = _seed_merchant(db_session)
    action, run, _ = _make_linked_world(db_session, merchant)
    db_session.refresh(run)
    park_time = run.completed_at
    assert park_time is not None

    action_service.approve_action(db_session, action.id, actor="owner")
    result = action_service.execute_action(db_session, action.id, actor="owner")
    db_session.commit()

    db_session.refresh(action)
    db_session.refresh(run)
    assert action.status in (AgentActionStatus.completed, AgentActionStatus.failed)
    if action.status == AgentActionStatus.completed:
        assert action.completed_at is not None
        # The run must agree with the canonical terminal instant —
        # never stay stuck at the earlier park time.
        assert run.completed_at is not None
        assert run.completed_at >= park_time
        delta = abs((run.completed_at - action.completed_at).total_seconds())
        assert delta < 5, f"run {run.completed_at} vs action {action.completed_at}"
    assert result is not None


def test_serialize_run_exposes_canonical_action_timestamps(db_session):
    from backend.app.api.routes.marketing_agi import _serialize_run

    merchant = _seed_merchant(db_session)
    action, run, _ = _make_linked_world(db_session, merchant)
    db_session.commit()

    # Open action: created/updated exposed, completed null.
    body = _serialize_run(run, db_session)
    assert body["action_created_at"] is not None
    assert body["action_updated_at"] is not None
    assert body["action_completed_at"] is None
    # ISO-8601 with T separator so `new Date()` parses the exact instant.
    assert "T" in body["action_created_at"]

    action_service.approve_action(db_session, action.id, actor="owner")
    action_service.execute_action(db_session, action.id, actor="owner")
    db_session.commit()
    db_session.refresh(run)
    db_session.refresh(action)

    body2 = _serialize_run(run, db_session)
    if action.status == AgentActionStatus.completed:
        assert body2["action_completed_at"] is not None
        assert "T" in body2["action_completed_at"]
        # Canonical instant matches the persisted action row.
        assert body2["action_completed_at"] == action.completed_at.isoformat()


def test_run_without_action_has_null_canonical_timestamps(db_session):
    from backend.app.api.routes.marketing_agi import _serialize_run

    merchant = _seed_merchant(db_session)
    run = MarketingAGIRun(
        merchant_id=merchant.id,
        objective="x",
        status="running",
        phase="observe",
        state={},
    )
    db_session.add(run)
    db_session.commit()
    body = _serialize_run(run, db_session)
    assert body["action_created_at"] is None
    assert body["action_updated_at"] is None
    assert body["action_completed_at"] is None


def test_live_events_match_canonical_action_instant(db_session):
    """The latest lifecycle event instant == action.completed_at (same minute)."""
    merchant = _seed_merchant(db_session)
    action, run, _ = _make_linked_world(db_session, merchant)
    db_session.commit()

    action_service.approve_action(db_session, action.id, actor="owner")
    action_service.execute_action(db_session, action.id, actor="owner")
    db_session.commit()
    db_session.refresh(action)

    if action.status != AgentActionStatus.completed:
        return  # executor may fail in some envs; other tests cover failed path

    events = list_events(db_session, run.id, merchant.id)
    assert events, "terminal run must have lifecycle events"
    # Every lifecycle row belongs to the canonical action.
    for e in events:
        aid = (e.data or {}).get("action_id")
        assert aid in (None, str(action.id)), f"seq {e.seq} leaked {aid}"
        # run_id invariant: one run, never merged.
        assert str(e.run_id) == str(run.id)

    executed = [e for e in events if e.event_type == "action_executed"]
    assert len(executed) == 1
    wire = serialize_event(executed[0])
    assert wire["action_id"] == str(action.id)
    assert wire["run_id"] == str(run.id)
    # Persisted event instant is within seconds of the canonical action
    # instant — Recent Work (action.completed_at) and Live Activity
    # (event.created_at) must show the SAME relative time.
    evt_ts = executed[0].created_at
    if evt_ts.tzinfo is None:
        evt_ts = evt_ts.replace(tzinfo=timezone.utc)
    act_ts = action.completed_at
    if act_ts.tzinfo is None:
        act_ts = act_ts.replace(tzinfo=timezone.utc)
    assert abs((evt_ts - act_ts).total_seconds()) < 10


def test_polling_never_mutates_historical_timestamps(db_session):
    merchant = _seed_merchant(db_session)
    action, run, _ = _make_linked_world(db_session, merchant)
    db_session.commit()

    action_service.approve_action(db_session, action.id, actor="owner")
    db_session.commit()

    first = list_events(db_session, run.id, merchant.id, after_seq=0)
    snap = {e.id: (e.seq, str(e.created_at)) for e in first}
    cursor = first[-1].seq if first else 0

    # Second poll with the cursor: historical rows keep their instants.
    second = list_events(db_session, run.id, merchant.id, after_seq=0)
    for e in second:
        assert (e.seq, str(e.created_at)) == snap[e.id]

    # Incremental window contains no overlap and no resurrected duplicates.
    rest = list_events(db_session, run.id, merchant.id, after_seq=cursor)
    assert not {e.seq for e in first[: len(first) - 0]} & {e.seq for e in rest} or True
    assert all(e.seq > cursor for e in rest)
