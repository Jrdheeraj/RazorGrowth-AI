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

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx, operator_ctx
from backend.app.core.config import get_settings
from backend.app.integrations.marketing.google_ads import GoogleAdsProvider
from backend.app.integrations.marketing.instagram import INSTAGRAM_SCOPES
from backend.app.integrations.marketing.meta_ads import META_ADS_SCOPES, MetaAdsProvider
from backend.app.integrations.marketing.oauth_state import (
    STATE_TTL_SECONDS,
    issue_state,
    verify_state,
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


def _not_found(provider: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"UNKNOWN_PROVIDER: {provider}")


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
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    if provider not in ("google_ads", "meta_ads", "instagram"):
        raise HTTPException(status_code=404, detail=f"OAUTH_NOT_SUPPORTED: {provider}")
    settings = get_settings()
    state = issue_state(ctx.merchant_id, provider)
    if provider == "google_ads":
        if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_REDIRECT_URI:
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
    """Provider redirect target. Tenant comes from the signed state token."""
    if provider not in ("google_ads", "meta_ads", "instagram"):
        raise HTTPException(status_code=404, detail=f"OAUTH_NOT_SUPPORTED: {provider}")
    if error:
        raise HTTPException(
            status_code=400,
            detail=f"OAUTH_DENIED: {error_description or error}",
        )
    if not code or not state:
        raise HTTPException(status_code=400, detail="OAUTH_CALLBACK requires code + state.")
    try:
        merchant_id = verify_state(state, provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "INVALID_STATE")
    row, result = svc.connect_oauth(
        db, merchant_id, actor="oauth_callback", provider=provider, code=code,
    )
    if row is None:
        raise HTTPException(status_code=502, detail=f"{result.error_code}: {result.message}")
    return {
        "provider": provider,
        "status": "connected",
        "account_id": row.account_id,
        "account_name": row.account_name,
        "message": result.message,
    }
