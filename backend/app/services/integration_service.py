"""Integration hub service — per-workspace provider connections.

Owns ALL connection state for the Marketing Agent integration layer:
  - connect / verify / test / disconnect per provider + merchant
  - Fernet-encrypted credential storage (credential_vault)
  - live verification before ANY status is called "connected"
  - audit events for every external action (redacted — never secrets)
  - stack snapshots consumed by /api/marketing-agi/status

Tenant isolation: every query filters by merchant_id. There is no path
that reads or writes another workspace's connection row.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.credential_vault import (
    decrypt_secret,
    encrypt_secret,
    is_vault_blob,
)
from backend.app.integrations.marketing.base import (
    ProviderResult,
    redact_mapping,
)
from backend.app.integrations.marketing.google_ads import GoogleAdsProvider
from backend.app.integrations.marketing.instagram import InstagramProvider
from backend.app.integrations.marketing.meta_ads import MetaAdsProvider
from backend.app.integrations.marketing.resend_email import ResendProvider
from backend.app.models.audit_event import AuditEvent
from backend.app.models.enums import ActorType, AuditEventType
from backend.app.models.integration_connection import IntegrationConnection

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Provider catalogue (the single source of truth — no competing registry)
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, dict[str, Any]] = {
    "resend": {
        "integration_type": "email",
        "label": "Email (Resend)",
        "stack_key": "email",
        "read_actions": ["verify_connection", "sending_identity", "delivery_status"],
        "write_actions": ["send_email"],
        "writes_require_approval": True,
        "requires_connection": True,
    },
    "google_ads": {
        "integration_type": "ads",
        "label": "Google Ads",
        "stack_key": "google_ads",
        "read_actions": ["verify_connection", "list_accounts", "list_campaigns", "performance"],
        "write_actions": ["create_campaign_paused"],
        "writes_require_approval": True,
        "requires_connection": True,
    },
    "meta_ads": {
        "integration_type": "ads",
        "label": "Meta Ads",
        "stack_key": "meta_ads",
        "read_actions": ["verify_connection", "list_accounts", "list_campaigns", "performance"],
        "write_actions": ["create_campaign_paused"],
        "writes_require_approval": True,
        "requires_connection": True,
    },
    "instagram": {
        "integration_type": "social",
        "label": "Instagram",
        "stack_key": "social",
        "read_actions": ["verify_connection", "account_identity"],
        "write_actions": ["publish_photo"],
        "writes_require_approval": True,
        "requires_connection": True,
    },
}

STACK_PROVIDERS: dict[str, str] = {
    "email": "resend",
    "google_ads": "google_ads",
    "meta_ads": "meta_ads",
    "social": "instagram",
}


def _provider_adapter(provider: str):
    if provider == "resend":
        return ResendProvider()
    if provider == "google_ads":
        return GoogleAdsProvider()
    if provider == "meta_ads":
        return MetaAdsProvider()
    if provider == "instagram":
        return InstagramProvider()
    raise ValueError(f"UNKNOWN_PROVIDER: {provider}")


# ---------------------------------------------------------------------------
# Audit (redacted — secrets can never reach the audit log)
# ---------------------------------------------------------------------------


def write_integration_audit(
    db: Session,
    merchant_id: uuid.UUID,
    actor_type: ActorType,
    event_type: AuditEventType,
    provider: str,
    payload: dict[str, Any] | None = None,
    actor_id: str | None = None,
    entity_id: str | None = None,
) -> None:
    """Append a redacted integration audit event. Never raises."""
    try:
        evt = AuditEvent(
            merchant_id=merchant_id,
            actor_type=actor_type,
            actor_id=actor_id or actor_type.value,
            event_type=event_type,
            entity_type="integration_connection",
            entity_id=entity_id or provider,
            payload=redact_mapping(payload or {}),
        )
        db.add(evt)
        db.flush()
    except Exception as exc:
        log.warning("Failed to write integration audit %s: %s", event_type, exc)


# ---------------------------------------------------------------------------
# Connection CRUD (merchant-scoped)
# ---------------------------------------------------------------------------


def get_connection(
    db: Session, merchant_id: uuid.UUID, provider: str
) -> IntegrationConnection | None:
    if provider not in PROVIDERS:
        raise ValueError(f"UNKNOWN_PROVIDER: {provider}")
    return db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.merchant_id == merchant_id,
            IntegrationConnection.provider == provider,
        )
    )


def list_connections(
    db: Session, merchant_id: uuid.UUID
) -> list[IntegrationConnection]:
    rows = list(
        db.scalars(
            select(IntegrationConnection)
            .where(IntegrationConnection.merchant_id == merchant_id)
            .order_by(IntegrationConnection.provider)
        ).all()
    )
    return rows


def decrypt_credentials(row: IntegrationConnection) -> dict[str, Any]:
    """Decrypt stored credentials into memory. Caller must never persist,
    log, or return them."""
    import json

    blob = row.encrypted_credentials or ""
    if not is_vault_blob(blob):
        return {}
    try:
        return json.loads(decrypt_secret(blob))
    except Exception:
        log.warning("Could not decrypt credentials for %s", row.provider)
        return {}


def _store_credentials(row: IntegrationConnection, creds: dict[str, Any]) -> None:
    import json

    row.encrypted_credentials = encrypt_secret(json.dumps(creds))


def serialize_connection(row: IntegrationConnection) -> dict[str, Any]:
    """Client-safe projection — account identity + metadata only."""
    meta = dict(row.connection_metadata or {})
    return {
        "provider": row.provider,
        "integration_type": row.integration_type,
        "label": PROVIDERS[row.provider]["label"],
        "status": row.status,
        "account_id": row.account_id,
        "account_name": row.account_name,
        "metadata": meta,
        "capabilities": row.capabilities or [],
        "read_actions": PROVIDERS[row.provider]["read_actions"],
        "write_actions": PROVIDERS[row.provider]["write_actions"],
        "writes_require_approval": True,
        "last_verified_at": row.last_verified_at.isoformat() if row.last_verified_at else None,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _upsert_row(
    db: Session,
    merchant_id: uuid.UUID,
    provider: str,
    *,
    status: str,
    account_id: str | None,
    account_name: str | None,
    creds: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    last_error: str | None,
    verified: bool,
) -> IntegrationConnection:
    row = get_connection(db, merchant_id, provider)
    now = _utcnow()
    if row is None:
        row = IntegrationConnection(
            merchant_id=merchant_id,
            provider=provider,
            integration_type=PROVIDERS[provider]["integration_type"],
            status=status,
            capabilities=[
                *PROVIDERS[provider]["read_actions"],
                *[f"{w} (approval required)" for w in PROVIDERS[provider]["write_actions"]],
            ],
        )
        db.add(row)
    row.status = status
    row.account_id = account_id
    row.account_name = account_name
    if creds is None:
        row.encrypted_credentials = None
    else:
        _store_credentials(row, creds)
    row.connection_metadata = redact_mapping(metadata or {})
    row.last_error = last_error
    row.last_verified_at = now if verified else row.last_verified_at
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Connect flows (every success is preceded by a LIVE verification call)
# ---------------------------------------------------------------------------


def connect_resend(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    actor: str | None,
    api_key: str,
    from_email: str,
    from_name: str = "RazorGrowth",
    transport: httpx.BaseTransport | None = None,
) -> tuple[IntegrationConnection | None, ProviderResult]:
    """Connect a workspace Resend key. Verifies live before storing."""
    adapter: ResendProvider = _provider_adapter("resend")
    result = adapter.verify(api_key, transport=transport)
    if not result.ok:
        row = _upsert_row(
            db, merchant_id, "resend", status="error",
            account_id=None, account_name=None, creds=None,
            metadata={"from_email": from_email}, last_error=result.message,
            verified=False,
        )
        db.commit()
        write_integration_audit(
            db, merchant_id, ActorType.merchant_user,
            AuditEventType.integration_connection_failed, "resend",
            {"error_code": result.error_code, "message": result.message},
            actor_id=actor, entity_id=str(row.id),
        )
        db.commit()
        return None, result
    domains = result.data.get("domains", [])
    row = _upsert_row(
        db, merchant_id, "resend", status="connected",
        account_id=from_email, account_name=from_name or from_email,
        creds={"api_key": api_key},
        metadata={
            "from_email": from_email,
            "from_name": from_name,
            "domain_count": len(domains),
            "domains": [{"name": d.get("name"), "status": d.get("status")} for d in domains],
        },
        last_error=None, verified=True,
    )
    db.commit()
    write_integration_audit(
        db, merchant_id, ActorType.merchant_user,
        AuditEventType.integration_connected, "resend",
        {"account": row.account_id, "domains": len(domains)},
        actor_id=actor, entity_id=str(row.id),
    )
    db.commit()
    log.info("Resend connected merchant=%s from=%s", merchant_id, from_email)
    return row, result


def connect_oauth(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    actor: str | None,
    provider: str,
    code: str,
    account_selector: str | None = None,
    developer_token_override: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[IntegrationConnection | None, ProviderResult]:
    """Exchange an OAuth code, verify live, store encrypted tokens."""
    if provider not in ("google_ads", "meta_ads", "instagram"):
        raise ValueError(f"OAUTH_NOT_SUPPORTED: {provider}")
    settings = get_settings()

    def fail(message: str, error_code: str) -> tuple[None, ProviderResult]:
        res = ProviderResult(ok=False, provider=provider, error_code=error_code, message=message)
        row = _upsert_row(
            db, merchant_id, provider, status="error",
            account_id=None, account_name=None, creds=None,
            metadata={}, last_error=message, verified=False,
        )
        db.commit()
        write_integration_audit(
            db, merchant_id, ActorType.merchant_user,
            AuditEventType.integration_connection_failed, provider,
            {"error_code": error_code, "message": message},
            actor_id=actor, entity_id=str(row.id),
        )
        db.commit()
        return None, res

    if provider == "google_ads":
        if not (
            settings.GOOGLE_OAUTH_CLIENT_ID
            and settings.GOOGLE_OAUTH_CLIENT_SECRET
            and settings.GOOGLE_OAUTH_REDIRECT_URI
        ):
            return fail(
                "Google OAuth is not configured on this platform (missing client ID/secret/redirect URI).",
                "MISSING_CONFIGURATION",
            )
        adapter: GoogleAdsProvider = _provider_adapter("google_ads")
        exchanged = adapter.exchange_code(
            code=code, client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI, transport=transport,
        )
        if not exchanged.ok:
            return fail(exchanged.message or "Google authorization failed.", exchanged.error_code or "PROVIDER_ERROR")
        refresh_token = exchanged.data["refresh_token"]
        # A developer token is sent when configured (platform setting or the
        # caller's per-connection override). Google may require the header; in
        # that case verify() surfaces MISSING_CONFIGURATION instead of a raw
        # Google error. Its absence here is never itself a success signal —
        # status=connected is only ever set after verify() passes live.
        developer_token = (developer_token_override or settings.GOOGLE_ADS_DEVELOPER_TOKEN or "").strip() or None
        verified = adapter.verify(
            refresh_token=refresh_token, client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            developer_token=developer_token, customer_id=account_selector,
            api_version=settings.GOOGLE_ADS_API_VERSION, transport=transport,
        )
        if not verified.ok:
            return fail(verified.message or "Google Ads verification failed.", verified.error_code or "PROVIDER_ERROR")
        acct = verified.account
        row = _upsert_row(
            db, merchant_id, provider, status="connected",
            account_id=acct.get("customer_id"), account_name=acct.get("customer_name"),
            creds={"refresh_token": refresh_token,
                   **({"developer_token": developer_token_override} if developer_token_override else {})},
            metadata={
                "customer_id": acct.get("customer_id"),
                "accessible_count": acct.get("accessible_count"),
                "accessible_customer_ids": verified.data.get("accessible_customer_ids", []),
                "developer_token_configured": bool(developer_token),
            },
            last_error=None, verified=True,
        )
    else:
        # meta_ads + instagram share the Meta OAuth app + token.
        if not settings.META_APP_ID or not settings.META_APP_SECRET:
            return fail(
                "Meta OAuth is not configured on this platform (missing app ID/secret).",
                "MISSING_CONFIGURATION",
            )
        from backend.app.integrations.marketing.instagram import INSTAGRAM_SCOPES
        from backend.app.integrations.marketing.meta_ads import META_ADS_SCOPES

        scopes = INSTAGRAM_SCOPES if provider == "instagram" else META_ADS_SCOPES
        _ = scopes  # scopes are requested at oauth/start; the token carries them
        adapter = _provider_adapter(provider)
        exchanged = adapter.exchange_code(
            code=code, app_id=settings.META_APP_ID, app_secret=settings.META_APP_SECRET,
            redirect_uri=settings.META_OAUTH_REDIRECT_URI,
            graph_version=settings.META_GRAPH_VERSION, transport=transport,
        ) if provider == "meta_ads" else None
        if provider == "instagram":
            # Instagram uses the same Meta token endpoint; exchange via Meta adapter.
            meta_adapter: MetaAdsProvider = _provider_adapter("meta_ads")
            exchanged = meta_adapter.exchange_code(
                code=code, app_id=settings.META_APP_ID, app_secret=settings.META_APP_SECRET,
                redirect_uri=settings.META_OAUTH_REDIRECT_URI,
                graph_version=settings.META_GRAPH_VERSION, transport=transport,
            )
        assert exchanged is not None
        if not exchanged.ok:
            return fail(exchanged.message or "Meta authorization failed.", exchanged.error_code or "PROVIDER_ERROR")
        access_token = exchanged.data["access_token"]
        if provider == "meta_ads":
            verified = adapter.verify(
                access_token=access_token, ad_account_id=account_selector,
                graph_version=settings.META_GRAPH_VERSION, transport=transport,
            )
        else:
            verified = adapter.verify(
                access_token=access_token, page_id=account_selector,
                graph_version=settings.META_GRAPH_VERSION, transport=transport,
            )
        if not verified.ok:
            return fail(verified.message or "Verification failed.", verified.error_code or "PROVIDER_ERROR")
        acct = verified.account
        if provider == "meta_ads":
            row = _upsert_row(
                db, merchant_id, provider, status="connected",
                account_id=acct.get("ad_account_id"), account_name=acct.get("ad_account_name"),
                creds={"access_token": access_token},
                metadata={"ad_account_id": acct.get("ad_account_id")},
                last_error=None, verified=True,
            )
        else:
            row = _upsert_row(
                db, merchant_id, provider, status="connected",
                account_id=acct.get("instagram_user_id"), account_name=f"@{acct.get('username')}",
                creds={"access_token": access_token},
                metadata={"username": acct.get("username"), "page_id": acct.get("page_id"),
                           "page_name": acct.get("page_name")},
                last_error=None, verified=True,
            )
    db.commit()
    write_integration_audit(
        db, merchant_id, ActorType.merchant_user,
        AuditEventType.integration_connected, provider,
        {"account": row.account_name},
        actor_id=actor, entity_id=str(row.id),
    )
    db.commit()
    log.info("Provider connected merchant=%s provider=%s", merchant_id, provider)
    return row, verified


def connect_token(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    actor: str | None,
    provider: str,
    access_token: str,
    account_selector: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[IntegrationConnection | None, ProviderResult]:
    """Direct-token connect (Meta/Instagram manual token or tests).
    Verifies live before storing — never stored blind."""
    if provider not in ("meta_ads", "instagram"):
        raise ValueError(f"TOKEN_CONNECT_NOT_SUPPORTED: {provider}")
    settings = get_settings()
    adapter = _provider_adapter(provider)
    if provider == "meta_ads":
        verified = adapter.verify(
            access_token=access_token, ad_account_id=account_selector,
            graph_version=settings.META_GRAPH_VERSION, transport=transport,
        )
    else:
        verified = adapter.verify(
            access_token=access_token, page_id=account_selector,
            graph_version=settings.META_GRAPH_VERSION, transport=transport,
        )
    if not verified.ok:
        row = _upsert_row(
            db, merchant_id, provider, status="error",
            account_id=None, account_name=None, creds=None,
            metadata={}, last_error=verified.message, verified=False,
        )
        db.commit()
        write_integration_audit(
            db, merchant_id, ActorType.merchant_user,
            AuditEventType.integration_connection_failed, provider,
            {"error_code": verified.error_code, "message": verified.message},
            actor_id=actor, entity_id=str(row.id),
        )
        db.commit()
        return None, verified
    acct = verified.account
    if provider == "meta_ads":
        row = _upsert_row(
            db, merchant_id, provider, status="connected",
            account_id=acct.get("ad_account_id"), account_name=acct.get("ad_account_name"),
            creds={"access_token": access_token},
            metadata={"ad_account_id": acct.get("ad_account_id")},
            last_error=None, verified=True,
        )
    else:
        row = _upsert_row(
            db, merchant_id, provider, status="connected",
            account_id=acct.get("instagram_user_id"), account_name=f"@{acct.get('username')}",
            creds={"access_token": access_token},
            metadata={"username": acct.get("username"), "page_id": acct.get("page_id")},
            last_error=None, verified=True,
        )
    db.commit()
    write_integration_audit(
        db, merchant_id, ActorType.merchant_user,
        AuditEventType.integration_connected, provider,
        {"account": row.account_name},
        actor_id=actor, entity_id=str(row.id),
    )
    db.commit()
    return row, verified


# ---------------------------------------------------------------------------
# Test / disconnect
# ---------------------------------------------------------------------------


def test_connection(
    db: Session,
    merchant_id: uuid.UUID,
    provider: str,
    *,
    actor: str | None,
    transport: httpx.BaseTransport | None = None,
) -> ProviderResult:
    """Re-verify stored credentials live. Updates status + last_verified_at."""
    row = get_connection(db, merchant_id, provider)
    if row is None or row.status != "connected":
        return ProviderResult(
            ok=False, provider=provider, error_code="NOT_CONNECTED",
            message=f"{PROVIDERS[provider]['label']} is not connected.",
        )
    creds = decrypt_credentials(row)
    settings = get_settings()
    adapter = _provider_adapter(provider)
    if provider == "resend":
        result = adapter.verify(creds.get("api_key", ""), transport=transport)
    elif provider == "google_ads":
        result = adapter.verify(
            refresh_token=creds.get("refresh_token", ""),
            client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            developer_token=creds.get("developer_token") or settings.GOOGLE_ADS_DEVELOPER_TOKEN,
            customer_id=(row.connection_metadata or {}).get("customer_id"),
            api_version=settings.GOOGLE_ADS_API_VERSION, transport=transport,
        )
    elif provider == "meta_ads":
        result = adapter.verify(
            access_token=creds.get("access_token", ""),
            ad_account_id=(row.connection_metadata or {}).get("ad_account_id"),
            graph_version=settings.META_GRAPH_VERSION, transport=transport,
        )
    else:
        result = adapter.verify(
            access_token=creds.get("access_token", ""),
            page_id=(row.connection_metadata or {}).get("page_id"),
            graph_version=settings.META_GRAPH_VERSION, transport=transport,
        )
    if result.ok:
        row.status = "connected"
        row.last_verified_at = _utcnow()
        row.last_error = None
        db.commit()
        write_integration_audit(
            db, merchant_id, ActorType.merchant_user,
            AuditEventType.integration_connection_verified, provider,
            {"account": row.account_name},
            actor_id=actor, entity_id=str(row.id),
        )
        db.commit()
    else:
        row.status = "error"
        row.last_error = result.message
        db.commit()
        write_integration_audit(
            db, merchant_id, ActorType.merchant_user,
            AuditEventType.integration_connection_failed, provider,
            {"error_code": result.error_code, "message": result.message},
            actor_id=actor, entity_id=str(row.id),
        )
        db.commit()
    return result


def disconnect(
    db: Session,
    merchant_id: uuid.UUID,
    provider: str,
    *,
    actor: str | None,
    transport: httpx.BaseTransport | None = None,
) -> IntegrationConnection | None:
    """Disconnect: best-effort remote revoke, wipe secrets, audit."""
    row = get_connection(db, merchant_id, provider)
    if row is None:
        return None
    creds = decrypt_credentials(row)
    try:
        if provider == "google_ads" and creds.get("refresh_token"):
            _provider_adapter(provider).revoke(
                token=creds["refresh_token"], transport=transport
            )
        elif provider in ("meta_ads", "instagram") and creds.get("access_token"):
            user_part = (row.account_id or "").split("/")[-1]
            _provider_adapter("meta_ads").revoke(
                user_id=user_part or "me",
                access_token=creds["access_token"],
                transport=transport,
            )
    except Exception as exc:
        log.warning("Best-effort revoke failed for %s: %s", provider, type(exc).__name__)
    row.status = "disconnected"
    row.encrypted_credentials = None
    row.last_error = None
    db.commit()
    write_integration_audit(
        db, merchant_id, ActorType.merchant_user,
        AuditEventType.integration_disconnected, provider,
        {"account": row.account_name},
        actor_id=actor, entity_id=str(row.id),
    )
    db.commit()
    log.info("Provider disconnected merchant=%s provider=%s", merchant_id, provider)
    return row


# ---------------------------------------------------------------------------
# Stack snapshot for /api/marketing-agi/status (REAL state only)
# ---------------------------------------------------------------------------


def connected_row(
    db: Session, merchant_id: uuid.UUID, provider: str
) -> IntegrationConnection | None:
    row = get_connection(db, merchant_id, provider)
    if row is not None and row.status == "connected":
        return row
    return None


def live_stack_snapshot(db: Session, merchant_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """Per-stack-key live state. 'connected' appears ONLY with a verified row."""
    out: dict[str, dict[str, Any]] = {}
    for stack_key, provider in STACK_PROVIDERS.items():
        row = connected_row(db, merchant_id, provider)
        if row is None:
            out[stack_key] = {"status": None, "connection": None}
            continue
        out[stack_key] = {"status": "connected", "connection": serialize_connection(row)}
    return out
