"""Live Activity timeline regression tests (Marketing Agent /marketing-agent).

Guards the exact production bug: ONE Recent Work action must map to ONE
chronological, action-scoped, deduplicated Live Activity timeline.

Root cause being locked down (forensic-verified against the live DB):
the run f827a861-… / action 102577fa-… produced 8 raw rows where
  - phase_started(prepare) + action_prepared both meant "preparing"   (dup)
  - awaiting_approval + run_finished(waiting) both meant "waiting"    (dup)
  - rows stamped with a prior action must never join the timeline     (cross)
and the backend used to return everything verbatim.

No historical rows are ever deleted: these tests also prove the raw
rows still exist in marketing_agi_events after the deduplicated read.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.marketing_agi.events import list_events, serialize_event
from backend.app.models.enums import Currency, MerchantStatus
from backend.app.models.marketing_agi import MarketingAGIEvent, MarketingAGIRun
from backend.app.models.merchant import Merchant

# The exact 8-row screenshot sequence (real production seq numbers).
SCREENSHOT_SEQ = [
    (22, "prepare", "phase_started", "12 — Preparing action for human approval"),
    (23, "prepare", "action_prepared", "Proposal prepared for approval"),
    (24, "prepare", "handoff_opened", "Handoff opened for future creative review"),
    (25, "prepare", "awaiting_approval", "14 — Waiting for your approval"),
    (26, "complete", "run_finished", "Run finished — waiting for your approval"),
    (27, "execute", "action_approved", "Approved by you"),
    (28, "execute", "execution_started", "Campaign execution started"),
    (29, "execute", "action_executed", "Campaign executed successfully"),
]

LIFECYCLE_TYPES = {
    "phase_started",
    "action_prepared",
    "awaiting_approval",
    "run_finished",
    "action_approved",
    "execution_started",
    "action_executed",
}


def _seed_merchant(db: Session, hint: str = "live") -> Merchant:
    m = Merchant(
        name=f"Live {uuid.uuid4().hex[:6]}",
        slug=f"{hint}-{uuid.uuid4().hex[:12]}",
        email=f"{hint}-{uuid.uuid4().hex[:6]}@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db.add(m)
    db.commit()
    return m


def _seed_run(
    db: Session,
    merchant: Merchant,
    *,
    action_id: str | None = None,
    status: str = "waiting_approval",
    phase: str = "awaiting_approval",
) -> MarketingAGIRun:
    state: dict = {}
    if action_id is not None:
        state = {
            "prepared_action": {
                "action_id": str(action_id),
                "status": "requested",
                "approval_state": "REQUIRED",
            },
            "reasoning_status": "waiting_for_approval",
        }
    run = MarketingAGIRun(
        merchant_id=merchant.id,
        objective="Find and prepare the highest-impact marketing work",
        status=status,
        phase=phase,
        state=state,
    )
    db.add(run)
    db.flush()
    return run


def _emit(
    db: Session,
    run: MarketingAGIRun,
    *,
    seq: int,
    phase: str,
    event_type: str,
    message: str,
    data: dict | None = None,
) -> MarketingAGIEvent:
    event = MarketingAGIEvent(
        run_id=run.id,
        merchant_id=run.merchant_id,
        seq=seq,
        phase=phase,
        event_type=event_type,
        message=message,
        data=data,
    )
    db.add(event)
    db.flush()
    return event


def _seed_screenshot_run(db: Session, merchant: Merchant, action_id: str) -> MarketingAGIRun:
    run = _seed_run(db, merchant, action_id=action_id)
    for seq, phase, event_type, message in SCREENSHOT_SEQ:
        _emit(
            db,
            run,
            seq=seq,
            phase=phase,
            event_type=event_type,
            message=message,
            data={"action_id": action_id},
        )
    db.commit()
    return run


def _raw_rows(db: Session, run: MarketingAGIRun) -> list[MarketingAGIEvent]:
    return list(
        db.scalars(
            select(MarketingAGIEvent)
            .where(MarketingAGIEvent.run_id == run.id)
            .order_by(MarketingAGIEvent.seq.asc())
        ).all()
    )


def _seqs(events) -> list[int]:
    return [e.seq for e in events]


# ── 1. Screenshot sequence: exactly one row per lifecycle transition ─────


def test_screenshot_sequence_collapses_to_single_waiting_and_preparing(db_session):
    merchant = _seed_merchant(db_session)
    action_id = str(uuid.uuid4())
    run = _seed_screenshot_run(db_session, merchant, action_id)

    events = list_events(db_session, run.id, merchant.id)

    # phase_started + action_prepared → ONE "preparing";
    # awaiting_approval + run_finished(waiting) → ONE "waiting".
    # handoff_opened / approved / started / executed pass through.
    assert _seqs(events) == [22, 24, 25, 27, 28, 29]
    assert len(events) == 6

    lifecycle_seen = [e for e in events if e.event_type in LIFECYCLE_TYPES]
    types = [e.event_type for e in lifecycle_seen]
    assert types.count("action_prepared") <= 1
    assert types.count("run_finished") == 0 or types.count("awaiting_approval") == 0
    # Exactly one "preparing" representative and one "waiting" representative:
    preparing = [e for e in events if e.event_type in ("phase_started", "action_prepared")]
    waiting = [e for e in events if e.event_type in ("awaiting_approval", "run_finished")]
    assert len(preparing) == 1
    assert len(waiting) == 1
    assert preparing[0].seq == 22   # earliest row wins
    assert waiting[0].seq == 25     # earliest row wins


def test_screenshot_raw_rows_are_never_deleted(db_session):
    merchant = _seed_merchant(db_session)
    action_id = str(uuid.uuid4())
    run = _seed_screenshot_run(db_session, merchant, action_id)

    list_events(db_session, run.id, merchant.id)
    db_session.expire_all()

    # Dedup is read-time only — historical truth stays in the table.
    assert len(_raw_rows(db_session, run)) == 8


# ── 2. Action ownership scope (cross-action guard) ───────────────────────


def test_events_from_other_action_are_dropped(db_session):
    merchant = _seed_merchant(db_session)
    current_action = str(uuid.uuid4())
    prior_action = str(uuid.uuid4())
    run = _seed_run(db_session, merchant, action_id=current_action)

    _emit(db_session, run, seq=1, phase="execute",
          event_type="action_approved", message="Approved by you",
          data={"action_id": prior_action})          # stale prior action
    _emit(db_session, run, seq=2, phase="prepare",
          event_type="action_prepared", message="Proposal prepared",
          data={"action_id": current_action})        # current action
    _emit(db_session, run, seq=3, phase="research",
          event_type="tool_call", message="read revenue trends",
          data=None)                                 # run-level detail
    db_session.commit()

    events = list_events(db_session, run.id, merchant.id)
    assert _seqs(events) == [2, 3]


def test_zero_cross_action_rows_returned(db_session):
    merchant = _seed_merchant(db_session)
    current_action = str(uuid.uuid4())
    run = _seed_run(db_session, merchant, action_id=current_action)
    for i in range(1, 6):
        stamped = str(uuid.uuid4()) if i <= 3 else current_action
        _emit(db_session, run, seq=i, phase="execute",
              event_type="observation", message=f"row {i}",
              data={"action_id": stamped})
    db_session.commit()

    events = list_events(db_session, run.id, merchant.id)
    assert events, "current-action rows must survive"
    assert all(
        (e.data or {}).get("action_id") in (None, current_action)
        for e in events
    )


def test_run_without_prepared_action_returns_all_run_rows(db_session):
    merchant = _seed_merchant(db_session)
    run = _seed_run(db_session, merchant, action_id=None, status="running", phase="research")
    _emit(db_session, run, seq=1, phase="research", event_type="phase_started",
          message="Researching your business", data=None)
    _emit(db_session, run, seq=2, phase="research", event_type="tool_call",
          message="read failed payments", data=None)
    db_session.commit()

    events = list_events(db_session, run.id, merchant.id)
    assert _seqs(events) == [1, 2]


# ── 3. Duplicate lifecycle rows collapse, earliest wins ──────────────────


def test_repeated_approved_rows_collapse_to_one(db_session):
    merchant = _seed_merchant(db_session)
    action_id = str(uuid.uuid4())
    run = _seed_run(db_session, merchant, action_id=action_id, status="completed", phase="execute")
    # A retried mirror sync wrote the same transition twice.
    _emit(db_session, run, seq=1, phase="execute", event_type="action_approved",
          message="Approved by you", data={"action_id": action_id})
    _emit(db_session, run, seq=2, phase="execute", event_type="action_approved",
          message="Approved by you", data={"action_id": action_id})
    _emit(db_session, run, seq=3, phase="execute", event_type="action_executed",
          message="Campaign executed successfully", data={"action_id": action_id})
    db_session.commit()

    events = list_events(db_session, run.id, merchant.id)
    assert _seqs(events) == [1, 3]
    assert len(_raw_rows(db_session, run)) == 3  # rows preserved


def test_repeated_executing_rows_collapse_to_one(db_session):
    merchant = _seed_merchant(db_session)
    action_id = str(uuid.uuid4())
    run = _seed_run(db_session, merchant, action_id=action_id, status="running", phase="execute")
    for seq in (1, 2, 3):
        _emit(db_session, run, seq=seq, phase="execute",
              event_type="execution_started", message="Campaign execution started",
              data={"action_id": action_id})
    db_session.commit()

    events = list_events(db_session, run.id, merchant.id)
    assert _seqs(events) == [1]


def test_non_lifecycle_rows_are_never_collapsed(db_session):
    merchant = _seed_merchant(db_session)
    action_id = str(uuid.uuid4())
    run = _seed_run(db_session, merchant, action_id=action_id)
    # Two legitimate identical tool calls must both survive.
    _emit(db_session, run, seq=1, phase="research", event_type="tool_call",
          message="read revenue trends", data={"action_id": action_id})
    _emit(db_session, run, seq=2, phase="research", event_type="tool_call",
          message="read revenue trends", data={"action_id": action_id})
    db_session.commit()

    events = list_events(db_session, run.id, merchant.id)
    assert _seqs(events) == [1, 2]


# ── 4. after_seq pagination cannot resurrect a collapsed duplicate ───────


def test_after_seq_filter_applies_after_dedup(db_session):
    merchant = _seed_merchant(db_session)
    action_id = str(uuid.uuid4())
    run = _seed_run(db_session, merchant, action_id=action_id, status="completed", phase="execute")
    # earliest "waiting" at 4, the collapsed park-row duplicate at 5.
    _emit(db_session, run, seq=4, phase="prepare", event_type="awaiting_approval",
          message="Waiting for your approval", data={"action_id": action_id})
    _emit(db_session, run, seq=5, phase="complete", event_type="run_finished",
          message="Run finished — waiting for your approval", data={"action_id": action_id})
    _emit(db_session, run, seq=6, phase="execute", event_type="action_approved",
          message="Approved by you", data={"action_id": action_id})
    db_session.commit()

    full = list_events(db_session, run.id, merchant.id, after_seq=0)
    assert _seqs(full) == [4, 6]

    # Cursor past the kept row: the collapsed seq-5 twin must NOT reappear.
    window = list_events(db_session, run.id, merchant.id, after_seq=4)
    assert _seqs(window) == [6]


def test_after_seq_is_strictly_incremental(db_session):
    merchant = _seed_merchant(db_session)
    action_id = str(uuid.uuid4())
    run = _seed_screenshot_run(db_session, merchant, action_id)

    first = list_events(db_session, run.id, merchant.id, after_seq=0)
    cursor = first[-1].seq
    rest = list_events(db_session, run.id, merchant.id, after_seq=cursor)
    # No overlap, no loss across the two windows.
    assert _seqs(first) + _seqs(rest) == _seqs(list_events(db_session, run.id, merchant.id))
    assert not set(_seqs(first)) & set(_seqs(rest))


# ── 5. One action → one timeline; runs never merge ───────────────────────


def test_two_runs_never_merge(db_session):
    merchant = _seed_merchant(db_session)
    action_a, action_b = str(uuid.uuid4()), str(uuid.uuid4())
    run_a = _seed_run(db_session, merchant, action_id=action_a, status="completed", phase="execute")
    run_b = _seed_run(db_session, merchant, action_id=action_b, status="completed", phase="execute")
    _emit(db_session, run_a, seq=1, phase="execute", event_type="action_executed",
          message="Campaign executed successfully", data={"action_id": action_a})
    _emit(db_session, run_b, seq=1, phase="execute", event_type="action_executed",
          message="Campaign executed successfully", data={"action_id": action_b})
    db_session.commit()

    events_a = list_events(db_session, run_a.id, merchant.id)
    events_b = list_events(db_session, run_b.id, merchant.id)
    assert [str(e.run_id) for e in events_a] == [str(run_a.id)]
    assert [str(e.run_id) for e in events_b] == [str(run_b.id)]
    assert (events_a[0].data or {}).get("action_id") == action_a
    assert (events_b[0].data or {}).get("action_id") == action_b


def test_cross_tenant_read_returns_nothing(db_session):
    merchant_a = _seed_merchant(db_session, hint="livea")
    merchant_b = _seed_merchant(db_session, hint="liveb")
    action_id = str(uuid.uuid4())
    run = _seed_run(db_session, merchant_a, action_id=action_id)
    _emit(db_session, run, seq=1, phase="execute", event_type="action_executed",
          message="Campaign executed successfully", data={"action_id": action_id})
    db_session.commit()

    # Merchant B's caller, merchant A's run → SQL merchant scope drops it.
    assert list_events(db_session, run.id, merchant_b.id) == []
    assert len(list_events(db_session, run.id, merchant_a.id)) == 1


# ── 6. Serialization exposes action ownership + ordering stays truthful ──


def test_serialize_event_exposes_action_id(db_session):
    merchant = _seed_merchant(db_session)
    action_id = str(uuid.uuid4())
    run = _seed_run(db_session, merchant, action_id=action_id)
    lifecycle = _emit(db_session, run, seq=1, phase="execute",
                      event_type="action_executed",
                      message="Campaign executed successfully",
                      data={"action_id": action_id})
    detail = _emit(db_session, run, seq=2, phase="research",
                   event_type="tool_call", message="read revenue trends",
                   data=None)
    db_session.commit()

    life = serialize_event(lifecycle)
    info = serialize_event(detail)
    assert life["action_id"] == action_id
    assert info["action_id"] is None
    assert life["run_id"] == str(run.id)


def test_timeline_is_strictly_chronological(db_session):
    merchant = _seed_merchant(db_session)
    run = _seed_screenshot_run(db_session, merchant, str(uuid.uuid4()))
    events = list_events(db_session, run.id, merchant.id)
    seqs = _seqs(events)
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))


# ── 7. API endpoint: GET /api/marketing-agi/runs/{id}/events ────────────


def test_api_events_endpoint_scopes_dedupes_and_paginates(db_session, client):
    from tests.security_utils import bearer, make_world

    merchant, user, _ = make_world(db_session, slug_hint="liveapi")
    action_id = str(uuid.uuid4())
    run = _seed_screenshot_run(db_session, merchant, action_id)

    r = client.get(
        f"/api/marketing-agi/runs/{run.id}/events",
        params={"after_seq": 0},
        headers=bearer(user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] == str(run.id)

    events = body["events"]
    seqs = [e["seq"] for e in events]
    assert seqs == [22, 24, 25, 27, 28, 29]
    # No duplicate lifecycle transitions in the wire payload.
    assert len({e["id"] for e in events}) == len(events)
    lifecycle_types = [e["event_type"] for e in events if e["event_type"] in LIFECYCLE_TYPES]
    assert lifecycle_types.count("action_prepared") <= 1
    # Ownership visible to the client for future action-scoped renders.
    for e in events:
        assert e["action_id"] in (action_id, None)

    # Pagination window.
    r2 = client.get(
        f"/api/marketing-agi/runs/{run.id}/events",
        params={"after_seq": 25},
        headers=bearer(user),
    )
    assert [e["seq"] for e in r2.json()["events"]] == [27, 28, 29]


def test_api_events_endpoint_cross_tenant_is_404(db_session, client):
    from tests.security_utils import bearer, make_world

    merchant_a, _, _ = make_world(db_session, slug_hint="livexa")
    _, user_b, _ = make_world(db_session, slug_hint="livexb")
    action_id = str(uuid.uuid4())
    run = _seed_screenshot_run(db_session, merchant_a, action_id)

    r = client.get(
        f"/api/marketing-agi/runs/{run.id}/events",
        headers=bearer(user_b),
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "RUN_NOT_FOUND"
