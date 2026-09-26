"""Marketing integration hub API — per-workspace provider connections.

Final paths (after the single /api application prefix):

  GET  /api/marketing-agi/integrations                    — analyst+ : all providers + live status
  GET  /api/marketing-agi/integrations/audit              — analyst+ : integration audit trail
  GET  /api/marketing-agi/integrations/{provider}         — analyst+ : one provider + live status
  POST /api/marketing-agi/integrations/{provider}/connect — operator+: verify-live + store
  POST /api/marketing-agi/integrations/{provider}/test    — operator+: re-verify stored creds
  POST /api/marketing-agi/integrations/{provider}/disconnect — operator+: revoke + wipe
  GET  /api/marketing-agi/integrations/{provider}/oauth/start    — operator+: auth URL + state
  GET  /api/marketing-agi/integrations/{provider}/oauth/callback — public : signed-state code exchange

Tenant isolation: every row access filters by the authenticated merchant.
The OAuth callback carries no Authorization header; the tenant comes from
the HMAC-signed state token (see integrations/marketing/oauth_state.py).

Responses NEVER contain secrets — only account identity + safe metadata.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx, operator_ctx
from backend.app.core.config import get_settings
from backend.app.integrations.marketing.base import ProviderResult
from backend.app.integrations.marketing.google_ads import GoogleAdsProvider
from backend.app.integrations.marketing.instagram import INSTAGRAM_SCOPES
from backend.app.integrations.marketing.meta_ads import META_ADS_SCOPES, MetaAdsProvider
from backend.app.integrations.marketing.oauth_state import (
    STATE_TTL_SECONDS,
    issue_state,
    verify_state_context,
)
from backend.app.models.audit_event import AuditEvent
from backend.app.schemas.marketing_integrations import (
    IntegrationAuditListResponse,
    IntegrationConnectRequest,
    IntegrationConnectionResponse,
    IntegrationListResponse,
    IntegrationTestResponse,
    OAuthStartResponse,
)
from backend.app.services import integration_service as svc
from backend.app.db.session import get_db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/marketing-agi/integrations", tags=["marketing-integrations"])

# ── OAuth callback redirect safety ─────────────────────────────────────────
# The callback runs in the merchant's browser with NO auth header, so it must
# never echo provider payloads. Only these application-level codes may appear
# in the redirect query string; anything else collapses to CONNECTION_FAILED.
SAFE_CALLBACK_CODES = frozenset({
    "GOOGLE_ADS_ACCOUNT_NOT_LINKED",
    "GOOGLE_ADS_AUTHENTICATION_FAILED",
    "AUTH_EXPIRED",
    "AUTH_REVOKED",
    "OAUTH_SCOPE_INSUFFICIENT",
    "GOOGLE_2SV_REQUIRED",
    "INSUFFICIENT_PERMISSIONS",
    "ACCOUNT_NOT_FOUND",
    "INVALID_CREDENTIALS",
    "MISSING_CONFIGURATION",
    "OAUTH_DENIED",
    "OAUTH_STATE_INVALID",
    "OAUTH_STATE_EXPIRED",
    "MISSING_CALLBACK_PARAMS",
    "RATE_LIMITED",
    "NETWORK_ERROR",
    "TIMEOUT",
    "MALFORMED_RESPONSE",
    "PROVIDER_ERROR",
    "CONNECTION_FAILED",
})

_STATE_REJECTIONS = {
    "INVALID_STATE": "OAUTH_STATE_INVALID",
    "STATE_PROVIDER_MISMATCH": "OAUTH_STATE_INVALID",
    "STATE_REUSED": "OAUTH_STATE_INVALID",
    "STATE_EXPIRED": "OAUTH_STATE_EXPIRED",
}

# Merchant next-step per Google Ads failure code (Google Ads only — the
# other providers keep their existing flat error contract).
_GOOGLE_ADS_ACTIONS = {
    "GOOGLE_ADS_ACCOUNT_NOT_LINKED": (
        "Add this Google account to a Google Ads account (or create one), then reconnect."
    ),
    "GOOGLE_ADS_AUTHENTICATION_FAILED": "Reconnect your Google account.",
    "AUTH_EXPIRED": "Reconnect your Google account.",
    "AUTH_REVOKED": "Reconnect your Google account.",
    "OAUTH_SCOPE_INSUFFICIENT": "Reconnect and approve the requested Google Ads access.",
    "GOOGLE_2SV_REQUIRED": "Enable 2-Step Verification on the Google account, then reconnect.",
    "MISSING_CONFIGURATION": "Ask an admin to finish the Google Ads API setup, then reconnect.",
    "INSUFFICIENT_PERMISSIONS": (
        "Review the Google Ads API access level in the Google Ads API Center, then reconnect."
    ),
    "ACCOUNT_NOT_FOUND": "Verify the selected customer ID, then reconnect.",
    "OAUTH_DENIED": "Start the connection again and approve the Google sign-in.",
    "OAUTH_STATE_INVALID": "Start the connection again — the sign-in link expired.",
    "OAUTH_STATE_EXPIRED": "Start the connection again — the sign-in link expired.",
    "MISSING_CALLBACK_PARAMS": "Start the connection again.",
}


def _not_found(provider: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"UNKNOWN_PROVIDER: {provider}")


def _callback_redirect(provider: str, *, status: str, code: str | None = None) -> RedirectResponse:
    """Send the browser back to the frontend with a SAFE result triple.

    Carries only: integration (provider key), status (connected|error) and a
    whitelisted application error code. Never tokens, secrets, provider JSON
    or free-text messages.
    """
    settings = get_settings()
    base = (settings.FRONTEND_BASE_URL or "").rstrip("/") or "http://localhost:5173"
    params: dict[str, str] = {"integration": provider, "status": status}
    if status != "connected":
        safe = code if code in SAFE_CALLBACK_CODES else "CONNECTION_FAILED"
        params["code"] = safe
    return RedirectResponse(
        url=f"{base}/marketing-agent?{urlencode(params)}", status_code=302
    )


def _google_ads_error_detail(result: ProviderResult) -> dict[str, str]:
    """Structured application error for Google Ads connect failures.

    Follows the {code, message, action} shape — the message is the clean
    provider copy, never a raw Google response body.
    """
    code = result.error_code or "PROVIDER_ERROR"
    if code not in SAFE_CALLBACK_CODES:
        code = "CONNECTION_FAILED"
    return {
        "code": code,
        "message": result.message or "Google Ads connection could not be completed.",
        "action": _GOOGLE_ADS_ACTIONS.get(code, "Reconnect Google Ads and try again."),
    }


def _blank_entry(provider: str) -> dict[str, Any]:
    cfg = svc.PROVIDERS[provider]
    return {
        "provider": provider,
        "integration_type": cfg["integration_type"],
        "label": cfg["label"],
        "status": "not_connected",
        "account_id": None,
        "account_name": None,
        "metadata": {},
        "capabilities": [
            *cfg["read_actions"],
            *[f"{w} (approval required)" for w in cfg["write_actions"]],
        ],
        "read_actions": cfg["read_actions"],
        "write_actions": cfg["write_actions"],
        "writes_require_approval": True,
        "last_verified_at": None,
        "last_error": None,
        "created_at": None,
        "updated_at": None,
    }


@router.get("", response_model=IntegrationListResponse)
def list_integrations(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    rows = {r.provider: r for r in svc.list_connections(db, ctx.merchant_id)}
    out = []
    for provider in svc.PROVIDERS:
        row = rows.get(provider)
        out.append(svc.serialize_connection(row) if row else _blank_entry(provider))
    return {"integrations": out}


@router.get("/audit", response_model=IntegrationAuditListResponse)
def list_integration_audit(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    rows = list(
        db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.merchant_id == ctx.merchant_id,
                AuditEvent.entity_type == "integration_connection",
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        ).all()
    )
    return {
        "audit_events": [
            {
                "id": str(r.id),
                "event_type": str(getattr(r.event_type, "value", r.event_type)),
                "actor_type": str(getattr(r.actor_type, "value", r.actor_type)),
                "actor_id": r.actor_id,
                "entity_id": r.entity_id,
                "payload": r.payload or {},
                "created_at": str(r.created_at),
            }
            for r in rows
        ]
    }


@router.get("/{provider}", response_model=IntegrationConnectionResponse)
def get_integration(
    provider: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    if provider not in svc.PROVIDERS:
        raise _not_found(provider)
    row = svc.get_connection(db, ctx.merchant_id, provider)
    if row is None:
        return _blank_entry(provider)
    return svc.serialize_connection(row)


@router.post("/{provider}/connect", response_model=IntegrationConnectionResponse)
def connect_integration(
    provider: str,
    body: IntegrationConnectRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    if provider not in svc.PROVIDERS:
        raise _not_found(provider)
    actor = ctx.user.email if ctx.user else "operator"
    if provider == "resend":
        if not body.api_key or not body.from_email:
            raise HTTPException(
                status_code=422, detail="api_key and from_email are required."
            )
        row, result = svc.connect_resend(
            db, ctx.merchant_id, actor=actor,
            api_key=body.api_key, from_email=body.from_email,
            from_name=body.from_name or "RazorGrowth",
        )
        if row is None:
            raise HTTPException(status_code=502, detail=f"{result.error_code}: {result.message}")
        return svc.serialize_connection(row)
    if provider in ("google_ads", "meta_ads", "instagram"):
        if body.code:
            row, result = svc.connect_oauth(
                db, ctx.merchant_id, actor=actor, provider=provider,
                code=body.code, account_selector=body.account_id,
                developer_token_override=body.developer_token,
            )
        elif body.access_token and provider in ("meta_ads", "instagram"):
            row, result = svc.connect_token(
                db, ctx.merchant_id, actor=actor, provider=provider,
                access_token=body.access_token, account_selector=body.account_id,
            )
        else:
            raise HTTPException(
                status_code=422,
                detail="Provide an OAuth 'code' (or 'access_token' for meta_ads/instagram).",
            )
        if row is None:
            # Google Ads gets the structured {code, message, action} contract;
            # the other OAuth providers keep their existing flat detail.
            if provider == "google_ads":
                raise HTTPException(
                    status_code=502, detail=_google_ads_error_detail(result)
                )
            raise HTTPException(status_code=502, detail=f"{result.error_code}: {result.message}")
        return svc.serialize_connection(row)
    raise _not_found(provider)


@router.post("/{provider}/test", response_model=IntegrationTestResponse)
def test_integration(
    provider: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    if provider not in svc.PROVIDERS:
        raise _not_found(provider)
    actor = ctx.user.email if ctx.user else "operator"
    result = svc.test_connection(db, ctx.merchant_id, provider, actor=actor)
    row = svc.get_connection(db, ctx.merchant_id, provider)
    return {
        "ok": result.ok,
        "provider": provider,
        "error_code": result.error_code,
        "message": result.message,
        "account": result.account or ({
            "account_id": row.account_id, "account_name": row.account_name,
        } if row else {}),
        "verified_at": row.last_verified_at.isoformat() if row and row.last_verified_at else None,
    }


@router.post("/{provider}/disconnect", response_model=IntegrationConnectionResponse)
def disconnect_integration(
    provider: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    if provider not in svc.PROVIDERS:
        raise _not_found(provider)
    actor = ctx.user.email if ctx.user else "operator"
    row = svc.disconnect(db, ctx.merchant_id, provider, actor=actor)
    if row is None:
        return _blank_entry(provider)
    return svc.serialize_connection(row)


@router.get("/{provider}/oauth/start", response_model=OAuthStartResponse)
def oauth_start(
    provider: str,
    account_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    if provider not in ("google_ads", "meta_ads", "instagram"):
        raise HTTPException(status_code=404, detail=f"OAUTH_NOT_SUPPORTED: {provider}")
    settings = get_settings()
    # Google Ads only: the customer the merchant picked in the connect form
    # rides inside the SIGNED state (never in the OAuth redirect URL).
    state = issue_state(
        ctx.merchant_id, provider,
        account_selector=account_id if provider == "google_ads" else None,
    )
    if provider == "google_ads":
        if not (
            settings.GOOGLE_OAUTH_CLIENT_ID
            and settings.GOOGLE_OAUTH_CLIENT_SECRET
            and settings.GOOGLE_OAUTH_REDIRECT_URI
        ):
            raise HTTPException(
                status_code=503,
                detail="MISSING_CONFIGURATION: Google OAuth client is not configured on this platform.",
            )
        url = GoogleAdsProvider().authorization_url(
            client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
            state=state,
        )
    else:
        if not settings.META_APP_ID or not settings.META_OAUTH_REDIRECT_URI:
            raise HTTPException(
                status_code=503,
                detail="MISSING_CONFIGURATION: Meta OAuth app is not configured on this platform.",
            )
        scopes = INSTAGRAM_SCOPES if provider == "instagram" else META_ADS_SCOPES
        url = MetaAdsProvider().authorization_url(
            app_id=settings.META_APP_ID,
            redirect_uri=settings.META_OAUTH_REDIRECT_URI,
            state=state,
            scopes=scopes,
            graph_version=settings.META_GRAPH_VERSION,
        )
    return {
        "provider": provider,
        "authorization_url": url,
        "state_expires_in_seconds": STATE_TTL_SECONDS,
    }


@router.get("/{provider}/oauth/callback")
def oauth_callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Any:
    """Provider redirect target. Tenant comes from the signed state token.

    This runs in the merchant's browser with no Authorization header, so it
    ALWAYS redirects back to the frontend with a safe integration/status/code
    triple. Raw provider errors, tokens and free-text messages never reach
    the browser URL or the page — the frontend maps the code to merchant copy.
    """
    if provider not in ("google_ads", "meta_ads", "instagram"):
        raise HTTPException(status_code=404, detail=f"OAUTH_NOT_SUPPORTED: {provider}")
    if error:
        # Google's description stays server-side (it can echo request details).
        log.warning(
            "OAuth callback denied: provider=%s error=%s description=%s",
            provider, error[:80], (error_description or "")[:200],
        )
        return _callback_redirect(provider, status="error", code="OAUTH_DENIED")
    if not code or not state:
        log.warning("OAuth callback missing code/state: provider=%s", provider)
        return _callback_redirect(provider, status="error", code="MISSING_CALLBACK_PARAMS")
    try:
        merchant_id, account_selector = verify_state_context(state, provider)
    except ValueError as exc:
        reason = str(exc) or "INVALID_STATE"
        log.warning("OAuth callback state rejected: provider=%s reason=%s", provider, reason)
        return _callback_redirect(
            provider, status="error",
            code=_STATE_REJECTIONS.get(reason, "OAUTH_STATE_INVALID"),
        )
    row, result = svc.connect_oauth(
        db, merchant_id, actor="oauth_callback", provider=provider, code=code,
        account_selector=account_selector,
    )
    if row is None:
        # Failure path: nothing was marked connected (see integration_service
        # connect_oauth) — the merchant gets a whitelisted code only.
        log.warning(
            "OAuth callback connect failed: provider=%s merchant=%s code=%s",
            provider, merchant_id, result.error_code or "PROVIDER_ERROR",
        )
        return _callback_redirect(
            provider, status="error", code=result.error_code or "CONNECTION_FAILED"
        )
    return _callback_redirect(provider, status="connected")
