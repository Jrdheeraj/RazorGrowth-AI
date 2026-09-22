"""
Safe execution engine for Phase 4 agent actions.

CRITICAL REQUIREMENTS:
- NO arbitrary tool execution.
- Executor may ONLY execute explicitly supported action types.
- Unknown action type → reject safely → audit → never execute.
- Idempotency: duplicate executes produce no-op result
  (enforced by the state machine in action_service.execute_action).
- Double guardrail: guardrails re-evaluated immediately before execution
  (enforced by action_service BEFORE this module is invoked).
- Real Razorpay execution remains disabled by default (RAZORPAY_ENABLED=false).
  When disabled, retry_payment returns a clear non-success result —
  a fake/simulated payment success is NEVER recorded.
- Test-mode executors label their output explicitly (mode="test") and never
  claim that a real external side effect occurred.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.app.core.config import get_settings
from backend.app.guardrails.policy import GuardrailResult
from backend.app.schemas.action import (
    SendCampaignPayload,
    CreateDiscountPayload,
    RetryPaymentPayload,
    GenerateOpportunityPayload,
    PublishSocialPostPayload,
    CreateAdCampaignPayload,
    validate_action_payload,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Executor result
# ---------------------------------------------------------------------------


class ExecutorResult:
    """Structured result from an action executor."""

    def __init__(
        self,
        success: bool,
        error: str | None = None,
        result_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.success = success
        self.error = error
        self.result_metadata = result_metadata or {}


def _validated_payload(schema_name: str, action: Any) -> tuple[Any | None, str | None]:
    """
    Validate the stored input payload against its typed schema.
    Returns (payload_instance, error_message). Defense-in-depth: payloads may
    have been written directly to the DB, so they are re-validated here even
    though create_action already validates them at creation time.
    """
    raw = dict(action.input_payload or {})
    raw["merchant_id"] = str(action.merchant_id)
    return validate_action_payload(schema_name, raw)


# ---------------------------------------------------------------------------
# Executor registry
# ---------------------------------------------------------------------------


class BaseActionExecutor:
    """All concrete executors must subclass this."""

    action_type: str  # must match AgentActionType.value
    payload_schema: str  # schema name used by validate_action_payload

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        """Execute the action. Must return ExecutorResult."""
        raise NotImplementedError()


class SendCampaignExecutor(BaseActionExecutor):
    """Executor for send_campaign actions.

    Email channel with a reachable Resend key (merchant connection first,
    platform default second) + EXECUTION_ENABLED sends for REAL through
    Resend AFTER a live key verification. Every other case returns the
    honest test-mode result (sent=False) — never a fake delivery.
    """

    action_type = "send_campaign"
    payload_schema = "send_campaign"

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        ok, err = _validated_payload(self.payload_schema, action)
        if not ok:
            return ExecutorResult(success=False, error=f"INVALID_PAYLOAD: {err}")
        payload = SendCampaignPayload.model_validate(ok.model_dump())
        campaign_type = payload.campaign_type
        target_count = payload.target_count

        settings = get_settings()
        if settings.CAMPAIGN_MAX_TARGET is not None and target_count > settings.CAMPAIGN_MAX_TARGET:
            return ExecutorResult(
                success=False,
                error=f"CAMPAIGN_TARGET_EXCEEDS_LIMIT: {target_count} > max {settings.CAMPAIGN_MAX_TARGET}",
            )

        if campaign_type != "email":
            return self._test_mode(campaign_type, target_count)

        # If no db session, we can't look up connections — honest test mode.
        if db is None:
            return self._test_mode(campaign_type, target_count, note=(
                "No database session available — test preview only"
            ))

        from backend.app.integrations.marketing.resend_email import ResendProvider
        from backend.app.services import integration_service as svc

        row = svc.connected_row(db, action.merchant_id, "resend")
        if row is not None:
            api_key = svc.decrypt_credentials(row).get("api_key", "")
            meta = dict(row.connection_metadata or {})
            from_email = meta.get("from_email") or settings.RESEND_FROM_EMAIL
            from_name = meta.get("from_name") or settings.RESEND_FROM_NAME
        else:
            api_key = settings.RESEND_API_KEY or ""
            from_email = settings.RESEND_FROM_EMAIL
            from_name = settings.RESEND_FROM_NAME
        if not api_key or not from_email:
            # No sending capability at all — honest test-mode, nothing sent.
            return self._test_mode(campaign_type, target_count, note=(
                "No Resend key / sender identity available — no external message sent"
            ))

        # Live-verify the key before touching the network for a send.
        # "CONNECTED because the key exists" is forbidden: test the provider.
        verify = ResendProvider().verify(api_key)
        if not verify.ok:
            self._audit_external(
                db, action, "resend", False,
                {"error_code": verify.error_code, "message": verify.message,
                 "stage": "pre_send_verify"},
            )
            return ExecutorResult(
                success=False,
                error=f"{verify.error_code}: {verify.message}",
            )

        if not settings.EXECUTION_ENABLED:
            return self._test_mode(
                campaign_type, target_count,
                note=("EXECUTION_ENABLED=false — verified Resend key, send withheld (test preview)"),
                extra={"provider": "resend", "verified": True, "from": from_email},
            )

        resolved = self._resolve_email_content(db, action)
        if resolved is None:
            return ExecutorResult(
                success=False,
                error="UNRESOLVABLE_AUDIENCE: no recipient emails found for this campaign",
            )
        to_addrs, subject, html, text = resolved
        result = ResendProvider().send_email(
            api_key=api_key,
            from_email=f"{from_name} <{from_email}>" if from_name else from_email,
            to=to_addrs,
            subject=subject,
            html=html,
            text=text,
        )
        if not result.ok:
            self._audit_external(
                db, action, "resend", False,
                {"error_code": result.error_code, "message": result.message},
            )
            return ExecutorResult(
                success=False,
                error=f"{result.error_code}: {result.message}",
            )
        self._mark_campaign_sent(db, action)
        self._audit_external(
            db, action, "resend", True,
            {"email_id": result.data.get("email_id"), "to_count": len(to_addrs)},
            provider_request_id=result.provider_request_id,
        )
        return ExecutorResult(
            success=True,
            result_metadata={
                "campaign_type": campaign_type,
                "target_count": len(to_addrs),
                "mode": "live",
                "sent": True,
                "executed": True,
                "provider": "resend",
                "email_id": result.data.get("email_id"),
                "from": from_email,
                "subject": subject,
            },
        )

    @staticmethod
    def _test_mode(
        campaign_type: str, target_count: int, note: str | None = None,
        extra: dict | None = None,
    ) -> ExecutorResult:
        # TEST MODE ONLY — no external message is ever sent from here.
        # The result metadata states this explicitly so nothing upstream can
        # mistake it for a real delivery.
        meta: dict[str, Any] = {
            "campaign_type": campaign_type,
            "target_count": target_count,
            "mode": "test",
            "sent": False,
            "executed": False,
            "execution": f"test_campaign_{campaign_type}",
            "note": note or "Development/test mode — no external message sent",
        }
        if extra:
            meta.update(extra)
        return ExecutorResult(success=True, result_metadata=meta)

    @staticmethod
    def _audit_external(
        db: Any, action: Any, provider: str, success: bool,
        payload: dict[str, Any], provider_request_id: str | None = None,
    ) -> None:
        from backend.app.models.enums import ActorType, AuditEventType
        from backend.app.services.integration_service import write_integration_audit

        write_integration_audit(
            db, action.merchant_id,
            ActorType.merchant_user,
            AuditEventType.integration_action_executed if success
            else AuditEventType.integration_action_failed,
            provider,
            {
                "action_id": str(action.id),
                "action_type": str(getattr(action.action_type, "value", action.action_type)),
                "provider_request_id": provider_request_id,
                **payload,
            },
            actor_id=str(getattr(action, "approved_by", None) or "executor"),
            entity_id=str(action.id),
        )

    @staticmethod
    def _resolve_email_content(
        db: Any, action: Any
    ) -> tuple[list[str], str, str | None, str | None] | None:
        """Resolve (recipients, subject, html, text) from the linked draft.

        Recipients come from live Customer rows (merchant-scoped, must have
        an email address). Subject/body come from the verified draft content.
        Returns None when there is nobody to send to.
        """
        import uuid as _uuid

        from sqlalchemy import select

        from backend.app.models.customer import Customer
        from backend.app.models.marketing_agi import MarketingAGICampaign

        payload = dict(action.input_payload or {})
        target = payload.get("target") or {}
        campaign_id = target.get("marketing_agi_campaign_id")
        draft = None
        if campaign_id:
            try:
                draft = db.get(MarketingAGICampaign, _uuid.UUID(str(campaign_id)))
            except (ValueError, AttributeError):
                draft = None
        audience = (draft.audience if draft and draft.audience else {}) or {}
        customer_ids = audience.get("customer_ids") or []
        try:
            wanted = {_uuid.UUID(str(c)) for c in customer_ids}
        except (ValueError, AttributeError, TypeError):
            wanted = set()

        to_addrs: list[str] = []
        if wanted:
            rows = list(
                db.scalars(
                    select(Customer).where(
                        Customer.merchant_id == action.merchant_id,
                        Customer.id.in_(wanted),
                    )
                ).all()
            )
            for c in rows:
                email = (getattr(c, "email", None) or "").strip()
                if email and email not in to_addrs:
                    to_addrs.append(email)
        if not to_addrs:
            return None

        content = (draft.content if draft and draft.content else {}) or {}
        message = (content.get("message") or "").strip()
        variants = content.get("subject_variants") or content.get("variants") or []
        subject = (variants[0] if variants else "") or (draft.name if draft else "") or "News from your store"
        cta = (content.get("cta") or "").strip()
        timing = (content.get("timing") or "").strip()
        paragraphs = [p for p in [message, cta, timing] if p]
        text = "\n\n".join(paragraphs) if paragraphs else None
        html = (
            "".join(f"<p>{p}</p>" for p in paragraphs) if paragraphs else None
        )
        return to_addrs, subject, html, text

    @staticmethod
    def _mark_campaign_sent(db: Any, action: Any) -> None:
        """Advance the linked draft: it was really sent, record it honestly."""
        import uuid as _uuid

        from backend.app.models.marketing_agi import MarketingAGICampaign

        payload = dict(action.input_payload or {})
        campaign_id = (payload.get("target") or {}).get("marketing_agi_campaign_id")
        if not campaign_id:
            return
        try:
            draft = db.get(MarketingAGICampaign, _uuid.UUID(str(campaign_id)))
        except (ValueError, AttributeError):
            return
        if draft is None or draft.merchant_id != action.merchant_id:
            return
        draft.lifecycle = "completed"
        draft.integration_status = "sent"
        db.flush()


class CreateDiscountExecutor(BaseActionExecutor):
    """Executor for create_discount actions."""

    action_type = "create_discount"
    payload_schema = "create_discount"

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        ok, err = _validated_payload(self.payload_schema, action)
        if not ok:
            return ExecutorResult(success=False, error=f"INVALID_PAYLOAD: {err}")
        payload = CreateDiscountPayload.model_validate(ok.model_dump())

        settings = get_settings()

        # ─── Percentage limits ───────────────────────────────────────────
        pct: Decimal = payload.percentage
        if pct <= 0:
            return ExecutorResult(success=False, error="DISCOUNT_MUST_BE_POSITIVE")
        if pct > 100:
            return ExecutorResult(success=False, error="DISCOUNT_CANNOT_EXCEED_100_PCT")
        max_pct = settings.DISCOUNT_MAX_PERCENTAGE
        if pct > Decimal(str(max_pct)):
            return ExecutorResult(
                success=False,
                error=f"DISCOUNT_EXCEEDS_MAX_PERCENTAGE: {pct}% > max {max_pct}%",
            )

        # ─── Amount limits (optional proposed_amount) ────────────────────
        if payload.proposed_amount is not None:
            try:
                pa = Decimal(str(payload.proposed_amount))
            except (InvalidOperation, TypeError, ValueError):
                return ExecutorResult(success=False, error="INVALID_DISCOUNT_AMOUNT")
            discount_max = Decimal(str(settings.DISCOUNT_MAX_AMOUNT_INR))
            guardrail_max = Decimal(str(settings.GUARDRAIL_MAX_AMOUNT_INR))
            if pa < 0:
                return ExecutorResult(success=False, error="INVALID_DISCOUNT_AMOUNT")
            if pa > discount_max:
                return ExecutorResult(
                    success=False,
                    error=f"DISCOUNT_AMOUNT_EXCEEDS_LIMIT: INR {pa} > max INR {discount_max}",
                )
            if pa > guardrail_max:
                return ExecutorResult(
                    success=False,
                    error=f"DISCOUNT_AMOUNT_EXCEEDS_GUARDRAIL: INR {pa} > max INR {guardrail_max}",
                )

        discount_id = f"discount_{action.id}"
        return ExecutorResult(
            success=True,
            result_metadata={
                "discount_id": discount_id,
                "percentage": float(pct),
                "mode": "test",
                "created": False,
                "execution": "test_discount",
                "note": "Development/test mode — no real discount created",
            },
        )


class RetryPaymentExecutor(BaseActionExecutor):
    """Executor for retry_payment actions.

    Delegates to the Razorpay integration adapter (integrations/razorpay.py).
    Default state: RAZORPAY_DISABLED — an honest non-success, never a fake
    payment success. Test mode produces clearly-labelled simulated outcomes;
    the live path refuses honestly until deliberately implemented.
    """

    action_type = "retry_payment"
    payload_schema = "retry_payment"

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        ok, err = _validated_payload(self.payload_schema, action)
        if not ok:
            return ExecutorResult(success=False, error=f"INVALID_PAYLOAD: {err}")
        payload = RetryPaymentPayload.model_validate(ok.model_dump())
        payment_id = ok.payment_id

        from backend.app.integrations.razorpay import build_razorpay_client

        settings = get_settings()
        result = build_razorpay_client().retry_payment(
            payment_id, amount_inr=None
        )

        if not result.ok:
            return ExecutorResult(
                success=False,
                error=result.error or "RAZORPAY_FAILED",
                result_metadata={
                    "payment_id": payment_id,
                    **result.metadata,
                },
            )

        # Test-mode simulated success: executed=False, simulated=True.
        # Nothing upstream may mistake this for a real external effect.
        return ExecutorResult(
            success=True,
            result_metadata={
                "payment_id": payment_id,
                "mode": result.mode,
                "executed": result.executed,
                "simulated": result.simulated,
                **{
                    k: v
                    for k, v in result.metadata.items()
                    if k != "payment_id"
                },
                "note": (
                    "Razorpay test mode — simulated outcome only; "
                    "no real payment was retried."
                ),
            },
        )


class PublishSocialPostExecutor(BaseActionExecutor):
    """Executor for publish_social_post actions (Instagram).

    Approval-gated: runs only on human-approved actions. Requires a
    verified Instagram connection + EXECUTION_ENABLED; otherwise returns
    an honest TEST_MODE preview (executed=False).
    """

    action_type = "publish_social_post"
    payload_schema = "publish_social_post"

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        ok, err = _validated_payload(self.payload_schema, action)
        if not ok:
            return ExecutorResult(success=False, error=f"INVALID_PAYLOAD: {err}")
        payload = PublishSocialPostPayload.model_validate(ok.model_dump())

        from backend.app.integrations.marketing.instagram import InstagramProvider
        from backend.app.services import integration_service as svc

        row = svc.connected_row(db, action.merchant_id, "instagram")
        if row is None:
            return ExecutorResult(
                success=False,
                error="NOT_CONNECTED: Instagram is not connected for this workspace.",
            )
        settings = get_settings()
        if not settings.EXECUTION_ENABLED:
            SendCampaignExecutor._audit_external(
                db, action, "instagram", True,
                {"mode": "test", "executed": False,
                 "note": "EXECUTION_ENABLED=false — publish withheld (test preview)"},
            )
            return ExecutorResult(
                success=True,
                result_metadata={
                    "mode": "test", "executed": False, "provider": "instagram",
                    "caption_preview": payload.caption[:120],
                    "note": "EXECUTION_ENABLED=false — nothing published (test preview)",
                },
            )
        creds = svc.decrypt_credentials(row)
        meta = dict(row.connection_metadata or {})
        result = InstagramProvider().publish_photo(
            access_token=creds.get("access_token", ""),
            instagram_user_id=payload.instagram_user_id or meta.get("instagram_user_id") or (row.account_id or ""),
            image_url=payload.image_url,
            caption=payload.caption,
            graph_version=settings.META_GRAPH_VERSION,
        )
        SendCampaignExecutor._audit_external(
            db, action, "instagram", result.ok,
            {"error_code": result.error_code, "message": result.message,
             **result.data} if not result.ok else dict(result.data),
            provider_request_id=result.provider_request_id,
        )
        if not result.ok:
            return ExecutorResult(success=False, error=f"{result.error_code}: {result.message}")
        return ExecutorResult(
            success=True,
            result_metadata={
                "mode": "live", "executed": True, "provider": "instagram",
                "media_id": result.data.get("media_id"),
            },
        )


class CreateAdCampaignExecutor(BaseActionExecutor):
    """Executor for create_ad_campaign actions (Google Ads / Meta Ads).

    Campaigns are created PAUSED. Approval-gated + EXECUTION_ENABLED;
    otherwise an honest TEST_MODE preview.
    """

    action_type = "create_ad_campaign"
    payload_schema = "create_ad_campaign"

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        ok, err = _validated_payload(self.payload_schema, action)
        if not ok:
            return ExecutorResult(success=False, error=f"INVALID_PAYLOAD: {err}")
        payload = CreateAdCampaignPayload.model_validate(ok.model_dump())

        from backend.app.services import integration_service as svc

        row = svc.connected_row(db, action.merchant_id, payload.provider)
        if row is None:
            label = svc.PROVIDERS[payload.provider]["label"]
            return ExecutorResult(
                success=False,
                error=f"NOT_CONNECTED: {label} is not connected for this workspace.",
            )
        settings = get_settings()
        if not settings.EXECUTION_ENABLED:
            SendCampaignExecutor._audit_external(
                db, action, payload.provider, True,
                {"mode": "test", "executed": False,
                 "note": "EXECUTION_ENABLED=false — creation withheld (test preview)"},
            )
            return ExecutorResult(
                success=True,
                result_metadata={
                    "mode": "test", "executed": False, "provider": payload.provider,
                    "name": payload.name,
                    "note": "EXECUTION_ENABLED=false — nothing created (test preview)",
                },
            )
        creds = svc.decrypt_credentials(row)
        meta = dict(row.connection_metadata or {})
        if payload.provider == "google_ads":
            from backend.app.integrations.marketing.google_ads import GoogleAdsProvider

            if payload.budget_amount_micros is None:
                return ExecutorResult(
                    success=False, error="INVALID_PAYLOAD: budget_amount_micros is required for google_ads",
                )
            tok = GoogleAdsProvider().refresh_access_token(
                refresh_token=creds.get("refresh_token", ""),
                client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
                client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            )
            if not tok.ok:
                SendCampaignExecutor._audit_external(
                    db, action, payload.provider, False,
                    {"error_code": tok.error_code, "message": tok.message},
                )
                return ExecutorResult(success=False, error=f"{tok.error_code}: {tok.message}")
            result = GoogleAdsProvider().create_campaign(
                access_token=tok.data["access_token"],
                developer_token=creds.get("developer_token") or settings.GOOGLE_ADS_DEVELOPER_TOKEN,
                customer_id=payload.account_id or meta.get("customer_id") or (row.account_id or ""),
                login_customer_id=meta.get("customer_id"),
                name=payload.name,
                budget_amount_micros=payload.budget_amount_micros,
                api_version=settings.GOOGLE_ADS_API_VERSION,
            )
        else:
            from backend.app.integrations.marketing.meta_ads import MetaAdsProvider

            result = MetaAdsProvider().create_campaign(
                access_token=creds.get("access_token", ""),
                ad_account_id=payload.account_id or meta.get("ad_account_id") or (row.account_id or ""),
                name=payload.name,
                objective=payload.objective or "OUTCOME_TRAFFIC",
                graph_version=settings.META_GRAPH_VERSION,
            )
        SendCampaignExecutor._audit_external(
            db, action, payload.provider, result.ok,
            {"error_code": result.error_code, "message": result.message,
             **result.data} if not result.ok else dict(result.data),
            provider_request_id=result.provider_request_id,
        )
        if not result.ok:
            return ExecutorResult(success=False, error=f"{result.error_code}: {result.message}")
        return ExecutorResult(
            success=True,
            result_metadata={
                "mode": "live", "executed": True, "provider": payload.provider,
                **result.data,
            },
        )


class GenerateOpportunityExecutor(BaseActionExecutor):
    """Executor for generate_opportunity actions."""

    action_type = "generate_opportunity"
    payload_schema = "generate_opportunity"

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        ok, err = _validated_payload(self.payload_schema, action)
        if not ok:
            return ExecutorResult(success=False, error=f"INVALID_PAYLOAD: {err}")

        from backend.app.models.enums import OpportunityType, OpportunityStatus
        from backend.app.repositories.opportunity import GrowthOpportunityRepository

        payload = GenerateOpportunityPayload.model_validate(ok.model_dump())

        try:
            opp_type = OpportunityType(payload.opportunity_type)
        except ValueError:
            valid = sorted(t.value for t in OpportunityType)
            return ExecutorResult(
                success=False,
                error=f"UNSUPPORTED_OPPORTUNITY_TYPE: '{payload.opportunity_type}'. Valid types: {valid}",
            )

        repo = GrowthOpportunityRepository(db)

        # Deterministic key → duplicate executes cannot create duplicate rows.
        opportunity_key = payload.opportunity_key or f"gen-{action.id}"

        # Idempotency: same key returns the existing opportunity.
        existing = repo.get_by_key(action.merchant_id, opportunity_key)
        if existing is not None:
            return ExecutorResult(
                success=True,
                result_metadata={
                    "opportunity_id": str(existing.id),
                    "opportunity_key": existing.opportunity_key,
                    "idempotent": True,
                    "note": "Duplicate prevention — existing opportunity returned",
                },
            )

        new_opp = repo.create(
            merchant_id=action.merchant_id,
            opportunity_key=opportunity_key,
            type=opp_type,
            title=payload.title,
            description=payload.description or None,
            confidence=Decimal(str(payload.confidence)),
            expected_revenue=Decimal(str(payload.expected_revenue)),
            target_customer_count=payload.target_customer_count,
            reasoning=payload.reasoning,
            status=OpportunityStatus.pending_approval,
        )
        db.flush()

        return ExecutorResult(
            success=True,
            result_metadata={
                "opportunity_id": str(new_opp.id),
                "opportunity_key": new_opp.opportunity_key,
                "type": str(getattr(new_opp.type, "value", new_opp.type)),
                "status": str(getattr(new_opp.status, "value", new_opp.status)),
                "execution": "generate_opportunity",
            },
        )


# ---------------------------------------------------------------------------
# Executor dispatcher
# ---------------------------------------------------------------------------

_executor_registry: dict[str, BaseActionExecutor] = {
    "send_campaign": SendCampaignExecutor(),
    "create_discount": CreateDiscountExecutor(),
    "retry_payment": RetryPaymentExecutor(),
    "generate_opportunity": GenerateOpportunityExecutor(),
    "publish_social_post": PublishSocialPostExecutor(),
    "create_ad_campaign": CreateAdCampaignExecutor(),
}


def get_executor(action_type: str) -> BaseActionExecutor | None:
    """Return the executor for the given action type, or None."""
    return _executor_registry.get(action_type)


def execute_approved_action(action: Any, db: Any) -> ExecutorResult:
    """
    Dispatch to the correct executor for the action's type.

    If the action type has no registered executor → safe rejection.
    """
    action_type = str(getattr(action.action_type, "value", action.action_type))
    executor = get_executor(action_type)
    if executor is None:
        log.warning(
            "No executor registered for action type %r. "
            "Action ID=%s merchant=%s will not execute.",
            action_type,
            action.id,
            action.merchant_id,
        )
        return ExecutorResult(
            success=False,
            error=f"UNKNOWN_ACTION_TYPE: '{action_type}' has no registered executor",
        )

    result = executor.execute(action, db)
    log.info(
        "Executor %s for action type %s result: success=%s error=%s",
        type(executor).__name__,
        action_type,
        result.success,
        result.error,
    )
    return result
