"""
Phase 4 regression tests — actions API, state machine, guardrails,
idempotency, executors, measurement.

These tests lock in the Phase 4 contract:
  - /api/actions routes registered exactly once (no /api/api/... duplicates)
  - strict lifecycle: requested → approved → executing → completed
  - human-only approval; approval can never be bypassed
  - double guardrail (before approval + immediately before execution)
  - idempotent execution (duplicate execute is a safe no-op + audit event)
  - executor payload validation & discount limits
  - retry_payment never fakes success while RAZORPAY_ENABLED=false
  - generate_opportunity deduplication
  - measurement service never fabricates revenue
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, func

from backend.app.models.agent_action import AgentAction
from backend.app.models.audit_event import AuditEvent
from backend.app.models.enums import (
    AgentActionStatus,
    AgentActionType,
    CampaignStatus,
    Currency,
    MerchantStatus,
    OrderStatus,
    PaymentStatus,
)
from backend.app.services.action_executor import get_executor


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

VALID_PAYLOADS = {
    "send_campaign": {
        "campaign_type": "email",
        "target": {"segment": "all"},
        "target_count": 10,
    },
    "create_discount": {"percentage": 10},
    "retry_payment": {"payment_id": "pay_test_123"},
    "generate_opportunity": {
        "title": "Generated opportunity",
        "opportunity_type": "upsell",
    },
}


def make_merchant(db_session) -> object:
    from backend.app.models.merchant import Merchant

    slug = f"p4-{uuid.uuid4().hex[:10]}"
    m = Merchant(
        name="P4 Merchant",
        slug=slug,
        email=f"{slug}@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(m)
    db_session.commit()
    return m


def make_action(
    db_session,
    merchant,
    action_type="send_campaign",
    status="requested",
    payload_overrides: dict | None = None,
) -> AgentAction:
    action = AgentAction(
        id=uuid.uuid4(),
        merchant_id=merchant.id,
        action_type=AgentActionType(action_type),
        status=AgentActionStatus(status),
        input_payload={**VALID_PAYLOADS[action_type], **(payload_overrides or {})},
        requested_by="tester",
    )
    db_session.add(action)
    db_session.commit()
    return action


def audit_events_for(db_session, action_id) -> list[AuditEvent]:
    return list(
        db_session.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == str(action_id))
        ).all()
    )


# --------------------------------------------------------------------------- #
# Route registration — the Swagger double-prefix regression
# --------------------------------------------------------------------------- #


class TestRouteRegistration:
    def test_openapi_has_no_double_prefixed_action_routes(self, client):
        spec = client.get("/openapi.json").json()
        assert "/api/api/actions" not in spec["paths"]
        for path in spec["paths"]:
            assert "/api/api/" not in path, f"double-prefixed route leaked: {path}"

    def test_all_six_action_routes_registered(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/actions" in paths
        assert "/api/actions/{action_id}" in paths
        assert "/api/actions/{action_id}/approve" in paths
        assert "/api/actions/{action_id}/reject" in paths
        assert "/api/actions/{action_id}/execute" in paths
        assert "/api/actions/{action_id}/audit" in paths

    def test_actions_list_endpoint_shape(self, client):
        res = client.get("/api/actions")
        assert res.status_code == 200
        body = res.json()
        assert set(body.keys()) == {"actions"}
        for action in body["actions"]:
            assert {"id", "merchant_id", "action_type", "status"} <= set(action.keys())

    def test_invalid_status_filter_rejected(self, client):
        res = client.get("/api/actions", params={"status": "bogus_status"})
        assert res.status_code == 400

    def test_invalid_uuid_rejected_with_400(self, client):
        assert client.get("/api/actions/not-a-uuid").status_code == 400
        assert client.post("/api/actions/not-a-uuid/approve").status_code == 400
        assert client.get("/api/actions/not-a-uuid/audit").status_code == 400

    def test_unknown_action_returns_404(self, client):
        missing = uuid.uuid4()
        assert client.get(f"/api/actions/{missing}").status_code == 404
        assert client.post(f"/api/actions/{missing}/approve").status_code == 404
        assert client.post(f"/api/actions/{missing}/execute").status_code == 404
        assert client.get(f"/api/actions/{missing}/audit").status_code == 404


# --------------------------------------------------------------------------- #
# Lifecycle / state machine via HTTP
# --------------------------------------------------------------------------- #


class TestLifecycle:
    def test_full_lifecycle_requested_to_completed(self, client, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m, "send_campaign")

        r = client.get(f"/api/actions/{action.id}")
        assert r.status_code == 200 and r.json()["status"] == "requested"

        r = client.post(f"/api/actions/{action.id}/approve")
        assert r.status_code == 200 and r.json()["status"] == "approved"
        assert r.json()["approved_by"]

        r = client.post(f"/api/actions/{action.id}/execute")
        assert r.status_code == 200
        assert r.json()["status"] == "completed"
        assert r.json()["message"] == "Action executed successfully"

        # Persisted terminal state
        db_session.expire_all()
        refreshed = db_session.get(AgentAction, action.id)
        assert refreshed.status == AgentActionStatus.completed
        assert refreshed.output_payload.get("mode") == "test"
        # Test mode must never claim a real send happened
        assert refreshed.output_payload.get("sent") is False

    def test_approve_twice_fails(self, client, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m)
        assert client.post(f"/api/actions/{action.id}/approve").status_code == 200
        r = client.post(f"/api/actions/{action.id}/approve")
        assert r.status_code == 400
        assert "INVALID_ACTION_STATE" in r.json()["detail"]

    def test_reject_then_approve_fails(self, client, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m)
        assert client.post(f"/api/actions/{action.id}/reject").status_code == 200
        assert client.post(f"/api/actions/{action.id}/approve").status_code == 400
        # And it stays rejected
        assert client.get(f"/api/actions/{action.id}").json()["status"] == "rejected"

    def test_reject_twice_fails(self, client, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m)
        assert client.post(f"/api/actions/{action.id}/reject").status_code == 200
        r = client.post(f"/api/actions/{action.id}/reject")
        assert r.status_code == 400
        body = r.json()
        assert body["detail"]["error"] if isinstance(body["detail"], dict) else True

    def test_execute_requested_is_blocked(self, client, db_session):
        """requested → execute must be impossible (no approval bypass)."""
        m = make_merchant(db_session)
        action = make_action(db_session, m, status="requested")
        r = client.post(f"/api/actions/{action.id}/execute")
        assert r.status_code == 400
        detail = r.json()["detail"]
        error_text = detail["error"] if isinstance(detail, dict) else str(detail)
        assert "INVALID_ACTION_STATE" in error_text
        # Still requested afterwards
        assert client.get(f"/api/actions/{action.id}").json()["status"] == "requested"

    def test_execute_rejected_and_failed_blocked(self, client, db_session):
        m = make_merchant(db_session)

        rejected = make_action(db_session, m, status="rejected")
        r = client.post(f"/api/actions/{rejected.id}/execute")
        assert r.status_code == 400

        failed = make_action(db_session, m, "create_discount", status="failed")
        r = client.post(f"/api/actions/{failed.id}/execute")
        assert r.status_code == 400

    def test_execute_while_executing_blocked(self, client, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m, status="executing")
        r = client.post(f"/api/actions/{action.id}/execute")
        assert r.status_code == 400
        detail = r.json()["detail"]
        detail_str = detail if isinstance(detail, str) else str(detail)
        assert "EXECUTING" in detail_str.upper() or "STATE" in detail_str.upper()

    def test_execute_completed_is_idempotent(self, client, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m, status="completed")

        r = client.post(f"/api/actions/{action.id}/execute")
        assert r.status_code == 200
        body = r.json()
        assert body["result"]["idempotent"] is True
        assert body["result"]["previous_status"] == "completed"
        assert "idempotent" in body["message"].lower()

        events = [e.event_type for e in audit_events_for(db_session, action.id)]
        assert "action_skipped_idempotent" in [
            str(getattr(e, "value", e)) for e in events
        ]

    def test_reject_response_reports_rejected_by(self, client, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m)
        r = client.post(f"/api/actions/{action.id}/reject")
        assert r.status_code == 200
        assert r.json()["rejected_by"]
        assert r.json()["status"] == "rejected"


# --------------------------------------------------------------------------- #
# Merchant ownership
# --------------------------------------------------------------------------- #


class TestMerchantOwnership:
    def test_cross_merchant_access_denied_on_all_routes(self, client, db_session):
        owner = make_merchant(db_session)
        intruder = make_merchant(db_session)
        action = make_action(db_session, owner)

        base = f"/api/actions/{action.id}"
        routes = [
            ("GET", base),
            ("POST", f"{base}/approve"),
            ("POST", f"{base}/reject"),
            ("POST", f"{base}/execute"),
            ("GET", f"{base}/audit"),
        ]
        for method, url in routes:
            r = client.request(method, url, params={"merchant_id": str(intruder.id)})
            assert r.status_code == 403, f"{method} {url} did not deny cross-merchant access"
            assert r.json()["detail"] == "MERCHANT_ACCESS_DENIED"

    def test_matching_merchant_allowed(self, client, db_session):
        owner = make_merchant(db_session)
        action = make_action(db_session, owner)
        r = client.get(f"/api/actions/{action.id}", params={"merchant_id": str(owner.id)})
        assert r.status_code == 200

    def test_merchant_id_is_not_nullable_at_schema_level(self, db_session):
        """DB schema guarantees every action has an owner — no orphan actions."""
        from backend.app.models.agent_action import AgentAction

        col = AgentAction.__table__.columns["merchant_id"]
        assert col.nullable is False


# --------------------------------------------------------------------------- #
# Double guardrail
# --------------------------------------------------------------------------- #


class TestDoubleGuardrail:
    def test_guardrail_blocks_approval(self, client, db_session):
        """Guardrail evaluation BEFORE approval: oversized amount cannot be approved."""
        m = make_merchant(db_session)
        action = make_action(
            db_session,
            m,
            "create_discount",
            payload_overrides={"proposed_amount": 999999},  # > GUARDRAIL_MAX_AMOUNT_INR
        )
        r = client.post(f"/api/actions/{action.id}/approve")
        assert r.status_code == 400
        assert "GUARDRAIL_REJECTED" in r.json()["detail"]
        # Action remains requested so a human can review/reject it
        assert client.get(f"/api/actions/{action.id}").json()["status"] == "requested"
        # Rejection is audited
        event_types = [
            str(getattr(e.event_type, "value", e.event_type))
            for e in audit_events_for(db_session, action.id)
        ]
        assert "guardrail_rejected" in event_types

    def test_second_guardrail_blocks_execution_of_stale_approved_action(
        self, client, db_session
    ):
        """
        Second guardrail evaluation immediately before execution.

        Simulates an action approved earlier whose payload now violates the
        limit (e.g. limits tightened after approval): execution must not
        happen, action must transition to failed, audit event recorded.
        """
        m = make_merchant(db_session)
        action = make_action(
            db_session,
            m,
            "create_discount",
            status="approved",
            payload_overrides={"percentage": 10, "proposed_amount": 60000},
        )

        r = client.post(f"/api/actions/{action.id}/execute")
        assert r.status_code == 400
        detail = str(r.json()["detail"])
        # The guardrail reason is surfaced; the persisted error code is canonical
        assert "exceeds maximum" in detail or "GUARDRAIL_REJECTED" in detail

        db_session.expire_all()
        refreshed = db_session.get(AgentAction, action.id)
        assert refreshed.status == AgentActionStatus.failed
        assert refreshed.error_code == "GUARDRAIL_REJECTED"
        assert refreshed.completed_at is not None

        event_types = [
            str(getattr(e.event_type, "value", e.event_type))
            for e in audit_events_for(db_session, action.id)
        ]
        assert "guardrail_rejected" in event_types
        assert "action_failed" in event_types

    def test_normal_amount_passes_both_guardrails(self, client, db_session):
        m = make_merchant(db_session)
        action = make_action(
            db_session,
            m,
            "create_discount",
            payload_overrides={"percentage": 15, "proposed_amount": 5000},
        )
        assert client.post(f"/api/actions/{action.id}/approve").status_code == 200
        r = client.post(f"/api/actions/{action.id}/execute")
        assert r.status_code == 200
        assert r.json()["status"] == "completed"


# --------------------------------------------------------------------------- #
# Idempotency of real execution
# --------------------------------------------------------------------------- #


class TestIdempotency:
    def test_duplicate_execute_never_runs_executor_twice(self, client, db_session):
        m = make_merchant(db_session)
        action = make_action(
            db_session,
            m,
            "generate_opportunity",
            payload_overrides={"opportunity_key": f"idem-{uuid.uuid4().hex[:8]}"},
        )
        client.post(f"/api/actions/{action.id}/approve")

        r1 = client.post(f"/api/actions/{action.id}/execute")
        assert r1.status_code == 200
        first_result = r1.json()["result"]

        r2 = client.post(f"/api/actions/{action.id}/execute")
        assert r2.status_code == 200
        second_result = r2.json()["result"]

        # First call completed; duplicate call must be a no-op, not a re-run
        assert second_result.get("idempotent") is True
        assert second_result.get("previous_status") == "completed"


# --------------------------------------------------------------------------- #
# Executors
# --------------------------------------------------------------------------- #


class TestSendCampaignExecutor:
    def _run(self, action):
        return get_executor("send_campaign").execute(action, db=None)

    def test_valid_campaign_succeeds_in_test_mode(self, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m, "send_campaign", status="approved")
        result = self._run(action)
        assert result.success is True
        assert result.result_metadata["mode"] == "test"
        assert result.result_metadata["sent"] is False

    def test_unsupported_campaign_type_fails(self, db_session):
        m = make_merchant(db_session)
        action = make_action(
            db_session,
            m,
            "send_campaign",
            status="approved",
            payload_overrides={"campaign_type": "carrier_pigeon"},
        )
        result = self._run(action)
        assert result.success is False
        assert "INVALID_PAYLOAD" in result.error

    def test_target_above_configured_limit_fails(self, db_session, monkeypatch):
        from backend.app.core.config import Settings

        monkeypatch.setattr(
            "backend.app.services.action_executor.get_settings",
            lambda: Settings(CAMPAIGN_MAX_TARGET=5, DATABASE_URL="sqlite:///:memory:", APP_ENV="testing"),
        )
        m = make_merchant(db_session)
        action = make_action(db_session, m, "send_campaign", status="approved")
        result = self._run(action)  # target_count=10 > limit 5
        assert result.success is False
        assert "CAMPAIGN_TARGET_EXCEEDS_LIMIT" in result.error


class TestCreateDiscountExecutor:
    def _run(self, action):
        return get_executor("create_discount").execute(action, db=None)

    def test_valid_discount(self, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m, "create_discount", status="approved")
        result = self._run(action)
        assert result.success is True
        assert result.result_metadata["mode"] == "test"
        assert result.result_metadata["created"] is False

    def test_percentage_above_schema_limit_rejected(self, db_session):
        m = make_merchant(db_session)
        action = make_action(
            db_session, m, "create_discount", status="approved",
            payload_overrides={"percentage": 150},
        )
        result = self._run(action)
        assert result.success is False
        assert "INVALID_PAYLOAD" in result.error

    def test_negative_percentage_rejected(self, db_session):
        m = make_merchant(db_session)
        action = make_action(
            db_session, m, "create_discount", status="approved",
            payload_overrides={"percentage": -5},
        )
        result = self._run(action)
        assert result.success is False

    def test_zero_percentage_rejected(self, db_session):
        m = make_merchant(db_session)
        action = make_action(
            db_session, m, "create_discount", status="approved",
            payload_overrides={"percentage": 0},
        )
        result = self._run(action)
        assert result.success is False
        assert result.error == "DISCOUNT_MUST_BE_POSITIVE"

    def test_percentage_above_configured_discount_max(self, db_session, monkeypatch):
        from backend.app.core.config import Settings

        monkeypatch.setattr(
            "backend.app.services.action_executor.get_settings",
            lambda: Settings(
                DISCOUNT_MAX_PERCENTAGE=Decimal("30"),
                DATABASE_URL="sqlite:///:memory:",
                APP_ENV="testing",
            ),
        )
        m = make_merchant(db_session)
        action = make_action(
            db_session, m, "create_discount", status="approved",
            payload_overrides={"percentage": 50},
        )
        result = self._run(action)
        assert result.success is False
        assert "DISCOUNT_EXCEEDS_MAX_PERCENTAGE" in result.error

    def test_amount_above_discount_limit_rejected(self, db_session):
        m = make_merchant(db_session)
        action = make_action(
            db_session, m, "create_discount", status="approved",
            payload_overrides={"percentage": 10, "proposed_amount": 60000},
        )
        result = self._run(action)
        assert result.success is False
        assert "DISCOUNT_AMOUNT_EXCEEDS_LIMIT" in result.error

    def test_malformed_payload_rejected(self, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m, "create_discount", status="approved")
        action.input_payload = {"nonsense": True}
        db_session.commit()
        result = self._run(action)
        assert result.success is False
        assert "INVALID_PAYLOAD" in result.error


class TestRetryPaymentExecutor:
    def _run(self, action):
        return get_executor("retry_payment").execute(action, db=None)

    def test_razorpay_disabled_by_default_and_safe(self, db_session):
        from backend.app.core.config import get_settings

        assert get_settings().RAZORPAY_ENABLED is False

    def test_disabled_retry_returns_clear_failure_not_fake_success(self, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m, "retry_payment", status="approved")
        result = self._run(action)
        assert result.success is False, "disabled retry must not report success"
        assert result.error == "RAZORPAY_DISABLED"
        assert "Nothing was charged or retried" in result.result_metadata["note"]

    def test_missing_payment_id_rejected(self, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m, "retry_payment", status="approved")
        action.input_payload = {"metadata": {}}
        db_session.commit()
        result = self._run(action)
        assert result.success is False
        assert "INVALID_PAYLOAD" in result.error


class TestGenerateOpportunityExecutor:
    def _run(self, action, db):
        return get_executor("generate_opportunity").execute(action, db)

    def test_creates_opportunity_once_then_deduplicates(self, db_session):
        from backend.app.repositories.opportunity import GrowthOpportunityRepository

        m = make_merchant(db_session)
        key = f"dedup-{uuid.uuid4().hex[:8]}"
        action = make_action(
            db_session, m, "generate_opportunity", status="approved",
            payload_overrides={"opportunity_key": key},
        )

        r1 = self._run(action, db_session)
        assert r1.success is True
        opp_id = r1.result_metadata["opportunity_id"]

        r2 = self._run(action, db_session)
        assert r2.success is True
        assert r2.result_metadata["idempotent"] is True
        assert r2.result_metadata["opportunity_id"] == opp_id

        repo = GrowthOpportunityRepository(db_session)
        matches = repo.get_by_key(m.id, key)
        assert matches is not None
        assert str(matches.id) == opp_id

    def test_deterministic_default_key_prevents_duplicates(self, db_session):
        """Without an explicit key, the key derives from action.id — stable."""
        m = make_merchant(db_session)
        action = make_action(db_session, m, "generate_opportunity", status="approved")

        r1 = self._run(action, db_session)
        r2 = self._run(action, db_session)
        assert r1.result_metadata["opportunity_id"] == r2.result_metadata["opportunity_id"]

    def test_unsupported_opportunity_type_fails(self, db_session):
        m = make_merchant(db_session)
        action = make_action(
            db_session, m, "generate_opportunity", status="approved",
            payload_overrides={"opportunity_type": "moonshot"},
        )
        result = self._run(action, db_session)
        assert result.success is False
        assert "UNSUPPORTED_OPPORTUNITY_TYPE" in result.error


class TestUnknownActionType:
    def test_unknown_action_type_has_no_executor(self, db_session):
        assert get_executor("wipe_database") is None

    def test_service_level_execute_via_http_reports_unknown(self, client, db_session):
        m = make_merchant(db_session)
        action = AgentAction(
            id=uuid.uuid4(),
            merchant_id=m.id,
            action_type="teleport_cart",  # not a real action type
            status=AgentActionStatus.approved,
            input_payload={},
            requested_by="tester",
        )
        db_session.add(action)
        db_session.commit()

        r = client.post(f"/api/actions/{action.id}/execute")
        assert r.status_code == 400
        detail = str(r.json()["detail"])
        # Blocked by the pre-execution guardrail (policy validator) or,
        # if it reached dispatch, by the missing-executor check.
        assert "not permitted" in detail or "UNKNOWN_ACTION_TYPE" in detail

        db_session.expire_all()
        assert db_session.get(AgentAction, action.id).status == AgentActionStatus.failed


# --------------------------------------------------------------------------- #
# Audit trail endpoint
# --------------------------------------------------------------------------- #


class TestAuditTrail:
    def test_audit_records_each_lifecycle_step(self, client, db_session):
        m = make_merchant(db_session)
        action = make_action(db_session, m)

        client.post(f"/api/actions/{action.id}/approve")
        client.post(f"/api/actions/{action.id}/execute")

        r = client.get(f"/api/actions/{action.id}/audit")
        assert r.status_code == 200
        types = [e["event_type"] for e in r.json()["audit_events"]]
        assert "action_approved" in types
        assert "action_started" in types
        assert "action_completed" in types
        # Payloads carry no secrets
        for e in r.json()["audit_events"]:
            assert "secret" not in str(e).lower()

    def test_audit_denied_for_wrong_merchant(self, client, db_session):
        owner = make_merchant(db_session)
        intruder = make_merchant(db_session)
        action = make_action(db_session, owner)
        r = client.get(
            f"/api/actions/{action.id}/audit", params={"merchant_id": str(intruder.id)}
        )
        assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Human-only approval — AI toolkit stays read-only
# --------------------------------------------------------------------------- #


class TestHumanOnlyApproval:
    def test_agent_toolkit_has_no_approval_or_execution_tools(self):
        from backend.app.ai.agents.tools import AgentToolkit

        for tool in AgentToolkit.AVAILABLE_TOOLS:
            assert "approve" not in tool.lower()
            assert "execute" not in tool.lower()
            assert "reject" not in tool.lower()

    def test_toolkit_registry_only_contains_read_tools(self):
        from backend.app.ai.agents.tools import AgentToolkit

        assert set(AgentToolkit.AVAILABLE_TOOLS) == {
            "search_knowledge",
            "get_merchant_context",
            "get_failed_payments",
            "get_product",
            "get_customer_segments",
            "get_order_patterns",
        }


# --------------------------------------------------------------------------- #
# Pydantic payload schemas
# --------------------------------------------------------------------------- #


class TestPayloadValidation:
    def test_valid_send_campaign(self):
        from backend.app.schemas.action import validate_action_payload

        inst, err = validate_action_payload(
            "send_campaign",
            {"merchant_id": str(uuid.uuid4()), "campaign_type": "sms", "target": {}},
        )
        assert err is None and inst.campaign_type == "sms"

    def test_invalid_send_campaign_type(self):
        from backend.app.schemas.action import validate_action_payload

        _, err = validate_action_payload(
            "send_campaign",
            {
                "merchant_id": str(uuid.uuid4()),
                "campaign_type": "fax",
                "target": {},
            },
        )
        assert err and "campaign_type" in err

    def test_invalid_merchant_uuid(self):
        from backend.app.schemas.action import validate_action_payload

        _, err = validate_action_payload(
            "send_campaign",
            {"merchant_id": "not-a-uuid", "campaign_type": "email", "target": {}},
        )
        assert err and "UUID" in err

    def test_discount_percentage_bounds(self):
        from backend.app.schemas.action import validate_action_payload

        mid = str(uuid.uuid4())
        _, err = validate_action_payload("create_discount", {"merchant_id": mid, "percentage": 101})
        assert err
        _, err = validate_action_payload("create_discount", {"merchant_id": mid, "percentage": "-1"})
        assert err
        inst, err = validate_action_payload("create_discount", {"merchant_id": mid, "percentage": "25.5"})
        assert err is None and inst.percentage == Decimal("25.5")

    def test_unknown_action_type(self):
        from backend.app.schemas.action import validate_action_payload

        _, err = validate_action_payload("format_disk", {})
        assert err and "Unknown action type" in err


# --------------------------------------------------------------------------- #
# Measurement service
# --------------------------------------------------------------------------- #


def make_campaign(db_session, merchant, *, status=CampaignStatus.completed, estimated=None):
    from backend.app.models.campaign import Campaign

    c = Campaign(
        merchant_id=merchant.id,
        name=f"camp-{uuid.uuid4().hex[:8]}",
        type="email",
        status=status,
        target_count=5,
        estimated_revenue=estimated,
    )
    db_session.add(c)
    db_session.commit()
    return c


def make_paid_order_with_captured_payment(db_session, merchant, amount) -> None:
    from backend.app.models.customer import Customer
    from backend.app.models.order import Order
    from backend.app.models.payment import Payment

    cust = Customer(
        merchant_id=merchant.id,
        name=f"Customer {uuid.uuid4().hex[:6]}",
        email=f"c{uuid.uuid4().hex[:8]}@x.com",
        phone="+911234567890",
    )
    db_session.add(cust)
    db_session.flush()

    order = Order(
        merchant_id=merchant.id,
        customer_id=cust.id,
        order_number=f"o-{uuid.uuid4().hex[:12]}",
        status=OrderStatus.paid,
        subtotal=amount,
        total=amount,
    )
    db_session.add(order)
    db_session.flush()

    payment = Payment(
        merchant_id=merchant.id,
        order_id=order.id,
        amount=amount,
        status=PaymentStatus.captured,
    )
    db_session.add(payment)
    db_session.commit()


class TestMeasurementService:
    def test_real_revenue_computed_from_db(self, db_session):
        from backend.app.services.measurement_service import measure_campaign_revenue

        m = make_merchant(db_session)
        campaign = make_campaign(db_session, m, estimated=Decimal("1000"))
        make_paid_order_with_captured_payment(db_session, m, Decimal("1200"))

        result = measure_campaign_revenue(db_session, campaign.id)
        assert result["status"] == "completed"
        assert result["actual_revenue"] == 1200.0
        assert result["variance"] == 200.0
        assert result["variance_percentage"] == pytest.approx(20.0)

        db_session.refresh(campaign)
        assert Decimal(str(campaign.actual_revenue)) == Decimal("1200")

    def test_negative_variance_correct(self, db_session):
        from backend.app.services.measurement_service import measure_campaign_revenue

        m = make_merchant(db_session)
        campaign = make_campaign(db_session, m, estimated=Decimal("1000"))
        make_paid_order_with_captured_payment(db_session, m, Decimal("600"))

        result = measure_campaign_revenue(db_session, campaign.id)
        assert result["variance"] == -400.0
        assert result["variance_percentage"] == pytest.approx(-40.0)

    def test_no_revenue_data_returns_pending_not_zero(self, db_session):
        """Never fabricate revenue — missing data ⇒ measurement_pending."""
        from backend.app.services.measurement_service import measure_campaign_revenue

        m = make_merchant(db_session)
        campaign = make_campaign(db_session, m, estimated=Decimal("1000"))

        result = measure_campaign_revenue(db_session, campaign.id)
        assert result["status"] == "measurement_pending"
        assert result["actual_revenue"] is None
        assert result["variance"] is None

        db_session.refresh(campaign)
        assert campaign.actual_revenue is None

    def test_zero_estimated_revenue_handles_percentage_safely(self, db_session):
        from backend.app.services.measurement_service import measure_campaign_revenue

        m = make_merchant(db_session)
        campaign = make_campaign(db_session, m, estimated=Decimal("0"))
        make_paid_order_with_captured_payment(db_session, m, Decimal("500"))

        result = measure_campaign_revenue(db_session, campaign.id)
        assert result["status"] == "completed"
        assert result["variance_percentage"] is None  # division by zero avoided
        assert result["estimated_revenue"] == 0.0
        assert result["variance"] == 500.0

    def test_missing_estimated_revenue_handles_safely(self, db_session):
        from backend.app.services.measurement_service import measure_campaign_revenue

        m = make_merchant(db_session)
        campaign = make_campaign(db_session, m, estimated=None)
        make_paid_order_with_captured_payment(db_session, m, Decimal("300"))

        result = measure_campaign_revenue(db_session, campaign.id)
        assert result["status"] == "completed"
        assert result["actual_revenue"] == 300.0
        assert result["variance"] is None
        assert result["variance_percentage"] is None

    def test_non_completed_campaign_is_pending(self, db_session):
        from backend.app.services.measurement_service import measure_campaign_revenue

        m = make_merchant(db_session)
        campaign = make_campaign(db_session, m, status=CampaignStatus.running)

        result = measure_campaign_revenue(db_session, campaign.id)
        assert result["status"] == "measurement_pending"

    def test_unknown_campaign_reported(self, db_session):
        from backend.app.services.measurement_service import measure_campaign_revenue

        result = measure_campaign_revenue(db_session, uuid.uuid4())
        assert result["status"] == "campaign_not_found"

    def test_repeated_measurement_is_idempotent(self, db_session):
        from backend.app.services.measurement_service import measure_campaign_revenue

        m = make_merchant(db_session)
        campaign = make_campaign(db_session, m, estimated=Decimal("800"))
        make_paid_order_with_captured_payment(db_session, m, Decimal("900"))

        first = measure_campaign_revenue(db_session, campaign.id)
        db_session.expire_all()
        second = measure_campaign_revenue(db_session, campaign.id)

        assert first["actual_revenue"] == second["actual_revenue"]
        assert first["variance"] == second["variance"]
        db_session.refresh(campaign)
        assert Decimal(str(campaign.actual_revenue)) == Decimal("900")


# --------------------------------------------------------------------------- #
# Configuration safety defaults
# --------------------------------------------------------------------------- #


class TestSafetyDefaults:
    def test_execution_switches_off_by_default(self):
        from backend.app.core.config import get_settings

        s = get_settings()
        assert s.RAZORPAY_ENABLED is False
        assert s.EXECUTION_ENABLED is False
        assert s.GUARDRAIL_REQUIRE_APPROVAL is True
        assert s.MEASUREMENT_REQUIRE_REAL_DATA is True

    def test_no_placeholder_credentials_in_settings_defaults(self):
        from backend.app.core.config import Settings

        s = Settings(DATABASE_URL="sqlite:///:memory:", APP_ENV="testing")
        assert s.RAZORPAY_KEY_ID == ""
        assert s.RAZORPAY_KEY_SECRET == ""
