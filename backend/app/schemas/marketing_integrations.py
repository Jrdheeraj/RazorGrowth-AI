"""Marketing integration hub schemas — request/response contracts.

Secrets only ever travel INBOUND (connect bodies). They are NEVER part of
any response schema: responses carry account identity + safe metadata.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IntegrationConnectionResponse(BaseModel):
    provider: str
    integration_type: str
    label: str
    status: str
    account_id: str | None = None
    account_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    read_actions: list[str] = Field(default_factory=list)
    write_actions: list[str] = Field(default_factory=list)
    writes_require_approval: bool = True
    last_verified_at: str | None = None
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class IntegrationListResponse(BaseModel):
    integrations: list[IntegrationConnectionResponse]


class IntegrationConnectRequest(BaseModel):
    """Provider-specific connect body. Only the fields each provider needs
    are read; unknown fields are ignored (never stored)."""

    # resend
    api_key: str | None = None
    from_email: str | None = None
    from_name: str | None = "RazorGrowth"
    # oauth (google_ads / meta_ads / instagram)
    code: str | None = None
    # direct token (meta_ads / instagram manual connect)
    access_token: str | None = None
    # account selection
    account_id: str | None = None
    # legacy google ads developer-token override (post-sunset: optional,
    # forwarded only when provided; never required, never requested in UI)
    developer_token: str | None = None


class IntegrationTestResponse(BaseModel):
    ok: bool
    provider: str
    error_code: str | None = None
    message: str | None = None
    account: dict[str, Any] = Field(default_factory=dict)
    verified_at: str | None = None


class OAuthStartResponse(BaseModel):
    provider: str
    authorization_url: str
    state_expires_in_seconds: int = 900


class IntegrationAuditResponse(BaseModel):
    id: str
    event_type: str
    actor_type: str
    actor_id: str | None = None
    entity_id: str | None = None
    payload: dict[str, Any] | None = None
    created_at: str


class IntegrationAuditListResponse(BaseModel):
    audit_events: list[IntegrationAuditResponse]
