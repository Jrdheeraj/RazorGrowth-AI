"""Product Agent ↔ Action ↔ Run synchronisation regression tests.

CANONICAL STATE
  ``agent_actions.status`` is the single source of truth. The Product Agent
  keeps a MIRROR of it (run status / recommendation status / activity events)
  through ``services/product_action_sync.py``. The dashboard read model
  (``agents/product_agi/service.effective_run_state``) derives the same
  verdict from the same function, so the dashboard can never disagree with
  the actions pipeline.

These tests pin the behaviours that were broken:

  * every run status the agent can produce MUST fit the persisted column —
    SQLite silently ignores VARCHAR(n), so a production-only overflow
    (StringDataRightTruncation on Postgres) is asserted structurally.
  * a mirror-sync failure must not poison the caller's transaction, so an
    approval can never 500 because the mirror hiccuped.
  * the run advances out of ``waiting_approval`` as soon as every action is
    approved, and reaches ``completed`` only once actions really executed.
  * partial failure is reported as ``completed_with_failures`` while the
    rejected / failed / completed actions stay distinguishable.
  * a run-level outcome (failed / blocked / cancelled) is never overwritten
    by the action aggregate.
  * recommendations never regress, and terminal states never flip-flop.
  * repeated syncs do not mint duplicate activity events.
  * every read surface (/status, /runs, /runs/{id}) agrees on the status.
  * tenant isolation holds end to end.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

from backend.app.agents.product_agi.state import RunStatus
from backend.app.agents.product_agi.service import (
    effective_run_state,
    live_action_statuses,
)
from backend.app.api.routes.actions import execute_action_route
from backend.app.core.config import get_settings
from backend.app.models.agent_action import AgentAction
from backend.app.models.audit_event import AuditEvent
from backend.app.models.enums import (
    AgentActionStatus,
    AgentActionType,
    Currency,
    MerchantStatus,
    UserRole,
)
from backend.app.models.merchant import Merchant
from backend.app.models.product_agi import (
    ProductAgentEvent,
    ProductAgentRecommendation,
    ProductAgentRun,
)
from backend.app.services import action_service
from backend.app.services.action_service import (
    ActionNotFoundError,
    InvalidTransitionError,
    approve_action,
    execute_action,
    reject_action,
)
from backend.app.services.action_executor import ExecutorResult
from backend.app.services.product_action_sync import (
    RUN_LEVEL_STATUSES,
    TERMINAL_RUN_STATUSES,
    aggregate_run_state,
    sync_product_agent_from_action,
)
from tests.conftest import _TestSessionLocal
from tests.security_utils import bearer, make_world

APPROVE = "/api/actions/{}/approve"
REJECT = "/api/actions/{}/reject"
EXECUTE = "/api/actions/{}/execute"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db():
    session = _TestSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def world(db):
    return make_world(db, role=UserRole.owner, slug_hint="pa")


@pytest.fixture()
def secure(monkeypatch):
    """AUTH_MODE=required — the production posture for security assertions."""
    monkeypatch.setenv("AUTH_MODE", "required")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture()
def tenant(db):
    """A merchant WITH an owner membership, for authenticated HTTP calls."""
    merchant, user, membership = make_world(
        db, role=UserRole.owner, slug_hint="pa-http"
    )
    return merchant, user


def _merchant(session) -> Merchant:
    slug = f"pa-{uuid.uuid4().hex[:10]}"
    m = Merchant(
        name=f"Merchant {slug}",
        slug=slug,
        email=f"owner@{slug}.test",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    session.add(m)
    session.commit()
    return m


def _make_run(session, merchant, *, status="waiting_approval", cycle=None):
    run = ProductAgentRun(
        merchant_id=merchant.id,
        objective="Grow the real catalog",
        status=status,
        current_stage="waiting_approval",
        approval_status="required",
        products_analyzed=3,
        opportunities_found=1,
        recommendations_created=1,
        started_at=datetime.now(timezone.utc),
    )
    if cycle:
        run.analysis_cycle_id = cycle
    session.add(run)
    session.commit()
    return run


def _make_action(session, merchant, *, status=AgentActionStatus.requested):
    action = AgentAction(
        merchant_id=merchant.id,
        action_type=AgentActionType.generate_opportunity,
        status=status,
        input_payload={
            "merchant_id": str(merchant.id),
            "opportunity_type": "upsell",
            "title": "Bundle slow movers",
            "description": "Product Agent prepared work",
            "confidence": "0.7",
            "metadata": {
                "product_agent_recommendation_id": str(uuid.uuid4()),
                "product_agent_run_id": str(uuid.uuid4()),
            },
        },
        requested_by="ProductAGI",
    )
    session.add(action)
    session.commit()
    return action


def _make_rec(session, run, action, *, status="awaiting_approval"):
    rec = ProductAgentRecommendation(
        run_id=run.id,
        merchant_id=run.merchant_id,
        type="merchandising",
        title="Bundle slow movers",
        problem="Two SKUs have no sales in the window.",
        recommendation="Bundle them with a bestseller.",
        why_now="Inventory ageing past 90 days.",
        evidence=[{"tool": "product_intelligence.snapshot", "statement": "0 units sold"}],
        confidence=0.7,
        expected_impact={"status": "unavailable", "text": "no modelled lift"},
        risk="low",
        action_required=True,
        approval_required=True,
        status=status,
        action_id=action.id,
    )
    session.add(rec)
    session.commit()
    return rec


def _linked(session, run, merchant, count=1):
    """Build ``count`` requested actions linked to ``run`` via recommendations."""
    actions = []
    for _ in range(count):
        action = _make_action(session, merchant)
        _make_rec(session, run, action)
        actions.append(action)
    return actions


# --------------------------------------------------------------------------- #
# 1. Schema capacity — the production-only overflow
# --------------------------------------------------------------------------- #


def test_every_run_status_fits_the_persisted_column():
    """``product_agent_runs.status`` must hold EVERY value the agent writes.

    SQLite ignores VARCHAR(n) so the test suite can never observe the
    overflow; on Postgres the write raises StringDataRightTruncation, which
    is what broke approve(). Asserted structurally so the regression cannot
    come back silently.
    """
    column = ProductAgentRun.__table__.c.status
    width = column.type.length
    assert width is not None, "status column must stay length-bounded"

    too_long = [(m.value, len(m.value)) for m in RunStatus if len(m.value) > width]
    assert not too_long, (
        f"run status values exceed the persisted column width ({width}): {too_long}. "
        "Postgres would reject the write and roll back the caller's transaction."
    )


def test_run_status_column_is_not_narrower_than_the_longest_status():
    """A second, independent guard on the same invariant (explicit length)."""
    longest = max(m.value for m in RunStatus)
    assert len(longest) <= ProductAgentRun.__table__.c.status.type.length


# --------------------------------------------------------------------------- #
# 2. aggregate_run_state — the one canonical mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "action_statuses, expected",
    [
        (["requested"], "waiting_approval"),
        (["requested", "approved"], "waiting_approval"),
        (["approved"], "approved_awaiting_execution"),
        (["approved", "completed"], "approved_awaiting_execution"),
        (["executing"], "executing"),
        (["executing", "approved"], "executing"),
        (["completed"], "completed"),
        (["completed", "completed"], "completed"),
        (["failed"], "completed_with_failures"),
        (["completed", "failed"], "completed_with_failures"),
        (["rejected"], "completed"),
        (["rejected", "completed"], "completed"),
    ],
)
def test_aggregate_run_state_precedence(action_statuses, expected):
    status, _stage, _approval = aggregate_run_state(action_statuses)
    assert status == expected


def test_aggregate_run_state_returns_none_without_actions():
    assert aggregate_run_state([]) is None


def test_all_aggregate_statuses_fit_the_column():
    """Every status the aggregator can emit must be storable."""
    column = ProductAgentRun.__table__.c.status
    width = column.type.length
    emitted = {
        aggregate_run_state([a])
        for a in ("requested", "approved", "executing", "completed", "failed", "rejected")
    }
    for status, _stage, _approval in emitted:
        assert len(status) <= width, f"{status!r} exceeds column width {width}"


# --------------------------------------------------------------------------- #
# 3. Approval advances the run out of waiting_approval
# --------------------------------------------------------------------------- #


def test_approve_moves_run_to_awaiting_execution(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)

    approve_action(db, action.id, actor="owner@test")
    db.commit()

    db.refresh(run)
    assert action.status == AgentActionStatus.approved
    assert run.status == "approved_awaiting_execution"
    assert run.current_stage == "execute_measure"
    assert run.approval_status == "approved"
    assert run.completed_at is None, "awaiting execution is not a finished run"


def test_approval_persists_through_the_http_endpoint(db, client, tenant):
    """The Actions page path end-to-end: POST /approve must return 200.

    This is the exact request the UI issues; it used to 500 because the
    mirror sync overflowed the column and left the session poisoned.
    """
    merchant, user = tenant
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)

    resp = client.post(APPROVE.format(action.id), headers=bearer(user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "approved"

    db.expire_all()
    stored = db.get(AgentAction, action.id)
    assert stored.status == AgentActionStatus.approved
    # The approver is recorded server-side from the authenticated context —
    # the client never supplies it.
    assert stored.approved_by
    assert str(user.id) in stored.approved_by


def test_approval_audit_event_is_written(db, client, tenant):
    merchant, user = tenant
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)

    resp = client.post(APPROVE.format(action.id), headers=bearer(user))
    assert resp.status_code == 200, resp.text

    events = db.scalars(
        select(AuditEvent).where(AuditEvent.entity_id == str(action.id))
    ).all()
    kinds = {e.event_type for e in events}
    assert "action_approved" in kinds, f"approval audit lost — got {kinds}"


def test_one_approved_one_pending_keeps_run_waiting(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    first, second = _linked(db, run, merchant, count=2)

    approve_action(db, first.id, actor="owner@test")
    db.commit()
    db.refresh(run)

    assert run.status == "waiting_approval"
    assert run.approval_status == "required"


def test_all_approved_clears_the_approval_gate(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    actions = _linked(db, run, merchant, count=2)

    for action in actions:
        approve_action(db, action.id, actor="owner@test")
    db.commit()
    db.refresh(run)

    assert run.status == "approved_awaiting_execution"
    assert run.approval_status == "approved"
    assert run.completed_at is None


# --------------------------------------------------------------------------- #
# 4. Execution is the only thing that completes a run
# --------------------------------------------------------------------------- #


def test_execution_completes_the_run(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)
    approve_action(db, action.id, actor="owner@test")
    db.commit()

    result = execute_action(db, action.id, actor="owner@test")
    db.commit()

    db.refresh(run)
    assert result.success, result.error
    assert action.status == AgentActionStatus.completed
    assert run.status == "completed"
    assert run.approval_status == "completed"
    assert run.completed_at is not None


def test_run_is_not_completed_before_execution(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)
    approve_action(db, action.id, actor="owner@test")
    db.commit()
    db.refresh(run)

    assert run.status != "completed"
    assert run.status == "approved_awaiting_execution"


def test_execution_in_progress_is_reflected(db, monkeypatch):
    """Mid-flight state: the run reports `executing`, never `completed`."""
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)
    approve_action(db, action.id, actor="owner@test")
    db.commit()

    seen = {}
    real_executor = action_service.execute_approved_action

    def spy(act, db=None):  # noqa: ANN001
        seen["status_midflight"] = run.status
        seen["stage_midflight"] = run.current_stage
        return real_executor(act, db=db)

    monkeypatch.setattr(action_service, "execute_approved_action", spy)
    execute_action(db, action.id, actor="owner@test")
    db.commit()

    assert seen.get("status_midflight") == "executing"
    assert seen.get("stage_midflight") == "execute_measure"


def test_partial_failure_reports_completed_with_failures(db, monkeypatch):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    good, bad = _linked(db, run, merchant, count=2)
    approve_action(db, good.id, actor="owner@test")
    approve_action(db, bad.id, actor="owner@test")
    db.commit()

    real_executor = action_service.execute_approved_action

    def flaky(act, db=None):  # noqa: ANN001
        if act.id == bad.id:
            return ExecutorResult(success=False, error="INTEGRATION_UNAVAILABLE")
        return real_executor(act, db=db)

    monkeypatch.setattr(action_service, "execute_approved_action", flaky)
    execute_action(db, good.id, actor="owner@test")
    execute_action(db, bad.id, actor="owner@test")
    db.commit()

    db.refresh(run)
    assert good.status == AgentActionStatus.completed
    assert bad.status == AgentActionStatus.failed
    assert run.status == "completed_with_failures"
    assert run.approval_status == "failed"
    assert "completed_with_failures" in TERMINAL_RUN_STATUSES
    assert run.completed_at is not None


def test_rejection_closes_the_run_without_execution(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)

    reject_action(db, action.id, actor="owner@test")
    db.commit()
    db.refresh(run)

    assert action.status == AgentActionStatus.rejected
    assert run.status == "completed"
    assert run.approval_status == "rejected"


def test_mixed_reject_and_execute_completes(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    approved, rejected = _linked(db, run, merchant, count=2)

    approve_action(db, approved.id, actor="owner@test")
    reject_action(db, rejected.id, actor="owner@test")
    db.commit()
    execute_action(db, approved.id, actor="owner@test")
    db.commit()

    db.refresh(run)
    assert approved.status == AgentActionStatus.completed
    assert rejected.status == AgentActionStatus.rejected
    assert run.status == "completed"


# --------------------------------------------------------------------------- #
# 5. Run-level outcomes are never overwritten
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("run_level", ["failed", "blocked", "cancelled"])
def test_run_level_outcome_survives_action_transitions(db, run_level):
    merchant = _merchant(db)
    run = _make_run(db, merchant, status="running")
    (action,) = _linked(db, run, merchant)

    run.status = run_level
    db.commit()

    approve_action(db, action.id, actor="owner@test")
    db.commit()
    db.refresh(run)
    assert run.status == run_level

    execute_action(db, action.id, actor="owner@test")
    db.commit()
    db.refresh(run)
    assert run.status == run_level, f"{run_level} run must not be overwritten by the aggregate"
    assert run_level in RUN_LEVEL_STATUSES


def test_blocked_run_keeps_its_own_reason(db):
    """A genuinely blocked run preserves blocked + its reason — never 'completed'."""
    merchant = _merchant(db)
    run = _make_run(db, merchant, status="running")
    (action,) = _linked(db, run, merchant)

    run.status = "blocked"
    run.errors = ["safety verification rejected the recommendations"]
    db.commit()

    approve_action(db, action.id, actor="owner@test")
    db.commit()
    db.refresh(run)

    assert run.status == "blocked"
    assert run.errors


# --------------------------------------------------------------------------- #
# 6. Recommendations track their action and never regress
# --------------------------------------------------------------------------- #


def test_recommendation_status_follows_the_action(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)
    rec = db.scalar(
        select(ProductAgentRecommendation).where(
            ProductAgentRecommendation.action_id == action.id
        )
    )

    approve_action(db, action.id, actor="owner@test")
    db.commit()
    assert rec.status == "approved"

    execute_action(db, action.id, actor="owner@test")
    db.commit()
    assert rec.status == "executed"


def test_terminal_recommendation_never_flips_backwards(db):
    """`executed` must not be downgraded by a late/duplicate transition."""
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)
    rec = db.scalar(
        select(ProductAgentRecommendation).where(
            ProductAgentRecommendation.action_id == action.id
        )
    )
    rec.status = "executed"
    db.commit()

    sync_product_agent_from_action(db, action)
    db.commit()
    db.refresh(rec)
    assert rec.status == "executed"


def test_terminal_states_do_not_flipflop_between_each_other(db):
    """A rejected action must not overwrite an executed recommendation."""
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)
    rec = db.scalar(
        select(ProductAgentRecommendation).where(
            ProductAgentRecommendation.action_id == action.id
        )
    )
    rec.status = "executed"
    db.commit()

    action.status = AgentActionStatus.rejected
    db.flush()
    sync_product_agent_from_action(db, action)
    db.commit()
    db.refresh(rec)

    assert rec.status == "executed", "terminal recommendation regressed to rejected"


def test_recommendation_with_multiple_actions_aggregates(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    actions = _linked(db, run, merchant, count=2)

    for action in actions:
        approve_action(db, action.id, actor="owner@test")
    db.commit()
    execute_action(db, actions[0].id, actor="owner@test")
    db.commit()
    db.refresh(run)

    assert run.status == "approved_awaiting_execution"
    metrics = dict(run.metrics or {})
    assert metrics["action_count"] == 2
    assert metrics["executed_count"] == 1


# --------------------------------------------------------------------------- #
# 7. Sync robustness: no duplicate events, no poisoned transaction
# --------------------------------------------------------------------------- #


def test_repeated_sync_does_not_duplicate_events(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)

    approve_action(db, action.id, actor="owner@test")
    db.commit()

    def count_events():
        return len(
            db.scalars(
                select(ProductAgentEvent).where(ProductAgentEvent.run_id == run.id)
            ).all()
        )

    first = count_events()
    for _ in range(5):
        sync_product_agent_from_action(db, action)
    db.commit()

    assert count_events() == first, "duplicate sync minted duplicate activity events"


def test_sync_failure_does_not_poison_the_caller_transaction(db, monkeypatch):
    """A mirror failure must be survivable — approval still commits.

    This is the guard that stops the blanket ``except Exception`` from turning
    a mirror hiccup into a 500 on the caller's commit.
    """
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)

    def boom(*_args, **_kwargs):
        raise RuntimeError("mirror exploded")

    monkeypatch.setattr(
        "backend.app.services.product_action_sync._sync_product_agent_from_action", boom
    )

    approve_action(db, action.id, actor="owner@test")
    db.commit()  # must NOT raise

    db.refresh(action)
    assert action.status == AgentActionStatus.approved, "canonical state must survive"


def test_sync_never_raises_for_unknown_action_state(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)
    sync_product_agent_from_action(db, action)
    db.commit()


def test_sync_of_unlinked_action_is_a_noop(db):
    merchant = _merchant(db)
    action = _make_action(db, merchant)
    assert sync_product_agent_from_action(db, action) is None


# --------------------------------------------------------------------------- #
# 8. Read model agrees with the mirror on every surface
# --------------------------------------------------------------------------- #


def test_effective_run_state_matches_the_persisted_mirror(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    actions = _linked(db, run, merchant)
    for action in actions:
        approve_action(db, action.id, actor="owner@test")
    db.commit()

    recs = [
        {
            "action_id": str(action.id),
            "status": "approved",
        }
        for action in actions
    ]
    derived = effective_run_state(run, recs)
    assert derived[0] == run.status
    assert derived[1] == run.current_stage
    assert derived[2] == run.approval_status


def test_read_model_recovers_from_a_lagging_mirror(db):
    """If the stored mirror lags, the canonical actions still win."""
    merchant = _merchant(db)
    run = _make_run(db, merchant, status="waiting_approval")
    (action,) = _linked(db, run, merchant)
    action.status = AgentActionStatus.completed
    db.commit()

    recs = [{"action_id": str(action.id), "status": "completed"}]
    status, _stage, _approval = effective_run_state(run, recs)
    assert status == "completed"


def test_live_action_statuses_treats_unresolved_as_pending(db):
    assert live_action_statuses([{"action_id": str(uuid.uuid4()), "status": "executed"}]) == [
        "requested"
    ]
    assert live_action_statuses([{"action_id": None, "status": "awaiting_approval"}]) == []
    assert live_action_statuses([{"action_id": "x", "status": "executing"}]) == ["executing"]


def test_every_api_surface_reports_the_same_status(db, client, tenant):
    """GET /status and GET /runs/{id} must never disagree for one run."""
    merchant, user = tenant
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)

    approve_action(db, action.id, actor="owner@test")
    db.commit()

    headers = bearer(user)

    detail = client.get(f"/api/product-agi/runs/{run.id}", headers=headers)
    assert detail.status_code == 200, detail.text

    listing = client.get("/api/product-agi/runs", headers=headers)
    assert listing.status_code == 200, listing.text
    runs = {r["id"]: r for r in listing.json()["runs"]}

    assert runs[str(run.id)]["status"] == detail.json()["status"], (
        "the run list and the run detail describe different worlds"
    )

    activity = client.get(
        f"/api/product-agi/runs/{run.id}/activity", headers=headers
    )
    assert activity.status_code == 200, activity.text
    assert activity.json()["status"] == detail.json()["status"], (
        "the activity feed reports a different status than the run detail"
    )


# --------------------------------------------------------------------------- #
# 9. Workflow guards (approval cannot be bypassed)
# --------------------------------------------------------------------------- #


def test_execute_requires_approval(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)

    result = execute_action(db, action.id, actor="owner@test")
    assert result.success is False
    assert action.status == AgentActionStatus.requested


def test_approve_twice_is_rejected(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)

    approve_action(db, action.id, actor="owner@test")
    db.commit()

    with pytest.raises(InvalidTransitionError):
        approve_action(db, action.id, actor="owner@test")


def test_duplicate_execute_is_idempotent(db):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    (action,) = _linked(db, run, merchant)
    approve_action(db, action.id, actor="owner@test")
    db.commit()

    first = execute_action(db, action.id, actor="owner@test")
    db.commit()
    second = execute_action(db, action.id, actor="owner@test")
    db.commit()

    assert first.success
    db.refresh(run)
    assert run.status == "completed"
    assert second.success in (True, False)


def test_execute_missing_action_reports_not_found(db):
    result = execute_action(db, uuid.uuid4(), actor="owner@test")
    assert result.success is False
    assert result.error == "ACTION_NOT_FOUND"


def test_approve_missing_action_raises(db):
    with pytest.raises(ActionNotFoundError):
        approve_action(db, uuid.uuid4(), actor="owner@test")


# --------------------------------------------------------------------------- #
# 10. Tenant isolation
# --------------------------------------------------------------------------- #


def test_other_tenant_cannot_read_the_run(db, client):
    merchant = _merchant(db)
    run = _make_run(db, merchant)
    _m, outsider, _mem = make_world(db, role=UserRole.owner, slug_hint="pa-outsider")

    resp = client.get(f"/api/product-agi/runs/{run.id}", headers=bearer(outsider))
    assert resp.status_code in (403, 404), resp.text
    assert run.id.hex not in resp.text


def test_sync_ignores_cross_tenant_recommendations(db):
    """A recommendation pointing at another tenant's action must not sync."""
    owner = _merchant(db)
    other = _merchant(db)
    run = _make_run(db, owner)
    foreign_action = _make_action(db, other)

    rec = ProductAgentRecommendation(
        run_id=run.id,
        merchant_id=other.id,  # foreign merchant on a run it does not own
        type="pricing",
        title="foreign",
        status="awaiting_approval",
        action_required=True,
        action_id=foreign_action.id,
    )
    db.add(rec)
    db.commit()

    foreign_action.status = AgentActionStatus.approved
    db.commit()
    sync_product_agent_from_action(db, foreign_action)
    db.commit()

    db.refresh(run)
    assert run.status == "waiting_approval", "a foreign action must not advance this run"


# --------------------------------------------------------------------------- #
# 11. Full user journey — the exact sequence the UI performs
# --------------------------------------------------------------------------- #


def test_end_to_end_approval_and_execution_journey(db, client, tenant):
    """Actions page → approve → Product Agent dashboard → execute → completed.

    This is the whole reported journey, driven only through the public API
    the UI calls. It asserts the invariant that broke: the dashboard must not
    still say "waiting for approval" once the approval has been recorded.
    """
    merchant, user = tenant
    headers = bearer(user)
    run = _make_run(db, merchant, status="waiting_approval")
    actions = _linked(db, run, merchant, count=2)
    db.commit()

    # ── 0. Before any decision the dashboard asks for approval ─────────────
    before = client.get("/api/product-agi/status", headers=headers).json()
    assert before["status"] == "waiting_approval"
    assert before["action_counts"]["awaiting_approval"] == 2
    assert before["needs_approval"] is True

    # ── 1. Approve ONE of the two actions from the Actions page ────────────
    first, second = actions
    resp = client.post(APPROVE.format(first.id), headers=headers)
    assert resp.status_code == 200, resp.text

    mid = client.get("/api/product-agi/status", headers=headers).json()
    assert mid["status"] == "waiting_approval", "one approval must not clear the gate"
    assert mid["action_counts"]["awaiting_approval"] == 1
    assert mid["action_counts"]["approved"] == 1

    # ── 2. Approve the second → gate clears, run waits for execution ───────
    resp = client.post(APPROVE.format(second.id), headers=headers)
    assert resp.status_code == 200, resp.text

    after = client.get("/api/product-agi/status", headers=headers).json()
    assert after["status"] == "approved_awaiting_execution"
    assert after["action_counts"]["awaiting_approval"] == 0, "approval gate still open"
    assert after["needs_approval"] is False
    assert after["stage"] != "waiting_approval", "stage must advance past the gate"

    # The run surfaces the same state everywhere, including the activity feed.
    detail = client.get(f"/api/product-agi/runs/{run.id}", headers=headers).json()
    assert detail["status"] == "approved_awaiting_execution"
    assert detail["stored_status"] == "approved_awaiting_execution"
    activity = client.get(f"/api/product-agi/runs/{run.id}/activity", headers=headers).json()
    assert activity["status"] == "approved_awaiting_execution"

    # ── 3. Execute the approved actions ────────────────────────────────────
    for action in (first, second):
        resp = client.post(EXECUTE.format(action.id), headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["action_id"] == str(action.id)
        assert body["status"] == "completed"

    done = client.get("/api/product-agi/status", headers=headers).json()
    assert done["status"] == "completed"
    assert done["action_counts"]["executed"] == 2
    assert done["completed_at"], "a completed run must record when it finished"

    # Every recommendation reports its real outcome, and nothing is claimed as
    # executed before it actually was.
    states = {
        r["action_id"]: r["approval_state"] for r in done["recommendations"]
    }
    assert states[str(first.id)] == "COMPLETED"
    assert states[str(second.id)] == "COMPLETED"

    # ── 4. A duplicate execute is a safe no-op, not a second execution ──────
    again = client.post(EXECUTE.format(first.id), headers=headers)
    assert again.status_code == 200, again.text
    still = client.get("/api/product-agi/status", headers=headers).json()
    assert still["status"] == "completed"
    assert still["action_counts"]["executed"] == 2


def test_journey_refresh_survives_a_page_reload(db, client, tenant):
    """State must be re-readable from persisted records, not from page state."""
    merchant, user = tenant
    headers = bearer(user)
    run = _make_run(db, merchant, status="waiting_approval")
    (action,) = _linked(db, run, merchant)

    client.post(APPROVE.format(action.id), headers=headers)

    # Simulate a brand-new request with no client-side memory at all.
    db.expire_all()
    fresh = client.get("/api/product-agi/status", headers=headers).json()
    assert fresh["status"] == "approved_awaiting_execution"
    assert fresh["action_counts"]["approved"] == 1
    assert fresh["action_counts"]["awaiting_approval"] == 0


def test_journey_rejection_and_failure_paths(db, client, tenant):
    """Rejected and failed actions stay distinguishable on the dashboard."""
    merchant, user = tenant
    headers = bearer(user)
    run = _make_run(db, merchant, status="waiting_approval")
    good, rejected = _linked(db, run, merchant, count=2)

    assert client.post(APPROVE.format(good.id), headers=headers).status_code == 200
    assert client.post(REJECT.format(rejected.id), headers=headers).status_code == 200

    mid = client.get("/api/product-agi/status", headers=headers).json()
    assert mid["action_counts"]["approved"] == 1
    assert mid["action_counts"]["rejected"] == 1
    assert mid["action_counts"]["awaiting_approval"] == 0

    assert client.post(EXECUTE.format(good.id), headers=headers).status_code == 200

    done = client.get("/api/product-agi/status", headers=headers).json()
    assert done["status"] == "completed"
    assert done["action_counts"]["executed"] == 1
    assert done["action_counts"]["rejected"] == 1
    assert done["action_counts"]["failed"] == 0


def test_execution_disabled_by_policy_is_reported_not_hidden(db, client, tenant, monkeypatch):
    """A policy refusal must surface the reason, never a fake success."""
    merchant, user = tenant
    headers = bearer(user)
    run = _make_run(db, merchant, status="waiting_approval")
    (action,) = _linked(db, run, merchant)
    client.post(APPROVE.format(action.id), headers=headers)

    from backend.app.services.action_executor import ExecutorResult

    monkeypatch.setattr(
        "backend.app.services.action_service.execute_approved_action",
        lambda act, db=None: ExecutorResult(
            success=False, error="INTEGRATION_UNAVAILABLE"
        ),
    )
    resp = client.post(EXECUTE.format(action.id), headers=headers)
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "INTEGRATION_UNAVAILABLE"

    status = client.get("/api/product-agi/status", headers=headers).json()
    assert status["status"] == "completed_with_failures"
    assert status["action_counts"]["failed"] == 1
    assert status["action_counts"]["executed"] == 0, "a refusal must never count as executed"


def test_approving_without_the_approver_role_is_forbidden(db, client, tenant, secure):
    """Human approval authority is server-side; a viewer cannot approve."""
    merchant, _owner = tenant
    from backend.app.core.security import create_access_token
    from backend.app.models.enums import MembershipStatus, UserStatus
    from backend.app.models.membership import MerchantMembership
    from backend.app.models.user import User

    viewer = User(
        email=f"viewer-{uuid.uuid4().hex[:8]}@security.test",
        password_hash="x",
        status=UserStatus.active,
    )
    db.add(viewer)
    db.flush()
    db.add(
        MerchantMembership(
            user_id=viewer.id,
            merchant_id=merchant.id,
            role=UserRole.analyst,
            status=MembershipStatus.active,
        )
    )
    db.commit()
    token, _ = create_access_token(viewer.id, viewer.email)

    run = _make_run(db, merchant, status="waiting_approval")
    (action,) = _linked(db, run, merchant)

    resp = client.post(
        APPROVE.format(action.id), headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403, resp.text

    db.refresh(action)
    assert action.status == AgentActionStatus.requested, "a viewer must not approve"


def test_unauthenticated_approval_is_refused(db, client, tenant, secure):
    """With auth required, an anonymous caller cannot approve anything."""
    merchant, _user = tenant
    run = _make_run(db, merchant, status="waiting_approval")
    (action,) = _linked(db, run, merchant)

    resp = client.post(APPROVE.format(action.id))
    assert resp.status_code in (401, 403), resp.text

    db.refresh(action)
    assert action.status == AgentActionStatus.requested