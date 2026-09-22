"""Instagram provider — shares the Meta OAuth infrastructure.

Discovery: /me/accounts -> pages -> instagram_business_account.
Verification = live discovery of a real IG business identity; the UI
shows the actual @username, never a generic "Social Platforms" label.
Publishing is the two-step container flow (media + media_publish) and
runs ONLY from approval-gated executors.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.app.integrations.marketing.base import (
    BaseProvider,
    ProviderResult,
    _summarise_httpx_error,
    classify_http_status,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_MALFORMED_RESPONSE,
    ERR_MISSING_CONFIGURATION,
)
from backend.app.integrations.marketing.meta_ads import META_ADS_SCOPES

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"

INSTAGRAM_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_content_publish",
] + META_ADS_SCOPES


class InstagramProvider(BaseProvider):
    provider_key = "instagram"

    # -- verification / discovery --------------------------------------------
    def verify(
        self,
        *,
        access_token: str,
        page_id: str | None = None,
        graph_version: str = "v24.0",
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        """Discover the real Instagram business identity behind the token."""
        if not access_token:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MISSING_CONFIGURATION,
                message="No Meta access token is stored. Connect Instagram first.",
            )
        try:
            with self._client(transport) as client:
                resp = client.get(
                    f"{GRAPH_BASE}/{graph_version}/me/accounts",
                    params={
                        "access_token": access_token,
                        "fields": "id,name,instagram_business_account{id,username}",
                        "limit": 25,
                    },
                )
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        if resp.status_code != 200:
            err_code, message = classify_http_status(resp.status_code, "Instagram", resp.text[:500])
            return ProviderResult(ok=False, provider=self.provider_key, error_code=err_code, message=message)
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Meta returned an unreadable response.",
            )
        pages = payload.get("data", []) if isinstance(payload, dict) else []
        linked = [
            {"page_id": p.get("id"), "page_name": p.get("name"),
             **(p.get("instagram_business_account") or {})}
            for p in pages if (p.get("instagram_business_account") or {}).get("id")
        ]
        if not linked:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_ACCOUNT_NOT_FOUND,
                message="No Instagram business account is linked to these Facebook Pages.",
            )
        chosen = next((l for l in linked if l["page_id"] == page_id), None) if page_id else linked[0]
        if chosen is None:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_ACCOUNT_NOT_FOUND,
                message="The requested Page has no linked Instagram business account.",
            )
        return ProviderResult(
            ok=True,
            provider=self.provider_key,
            account={
                "instagram_user_id": chosen.get("id"),
                "username": chosen.get("username"),
                "page_id": chosen.get("page_id"),
                "page_name": chosen.get("page_name"),
            },
            data={"linked": linked},
            message=f"Instagram verified (@{chosen.get('username')}).",
        )

    # -- approval-gated publish --------------------------------------------------
    def publish_photo(
        self,
        *,
        access_token: str,
        instagram_user_id: str,
        image_url: str,
        caption: str,
        graph_version: str = "v24.0",
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        """Two-step publish: container, then media_publish. Approval required."""
        if not image_url or not caption:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MISSING_CONFIGURATION,
                message="An image URL and caption are required to publish.",
            )
        try:
            with self._client(transport) as client:
                c1 = client.post(
                    f"{GRAPH_BASE}/{graph_version}/{instagram_user_id}/media",
                    data={
                        "access_token": access_token,
                        "image_url": image_url,
                        "caption": caption,
                    },
                )
                if c1.status_code != 200:
                    err_code, message = classify_http_status(c1.status_code, "Instagram", c1.text[:1000])
                    return ProviderResult(ok=False, provider=self.provider_key, error_code=err_code, message=message)
                try:
                    creation_id = c1.json().get("id")
                except Exception:
                    return ProviderResult(
                        ok=False, provider=self.provider_key,
                        error_code=ERR_MALFORMED_RESPONSE,
                        message="Instagram returned an unreadable container response.",
                    )
                if not creation_id:
                    return ProviderResult(
                        ok=False, provider=self.provider_key,
                        error_code=ERR_MALFORMED_RESPONSE,
                        message="Instagram did not return a media container id.",
                    )
                c2 = client.post(
                    f"{GRAPH_BASE}/{graph_version}/{instagram_user_id}/media_publish",
                    data={"access_token": access_token, "creation_id": creation_id},
                )
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        if c2.status_code != 200:
            err_code, message = classify_http_status(c2.status_code, "Instagram", c2.text[:1000])
            return ProviderResult(ok=False, provider=self.provider_key, error_code=err_code, message=message)
        try:
            media_id = c2.json().get("id")
        except Exception:
            media_id = None
        return ProviderResult(
            ok=True, provider=self.provider_key, executed=True,
            data={"media_id": media_id, "instagram_user_id": instagram_user_id},
            provider_request_id=media_id,
            message="Post published to Instagram.",
        )
