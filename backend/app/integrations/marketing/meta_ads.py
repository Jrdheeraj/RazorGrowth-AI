"""Meta Marketing API provider — ad accounts, campaigns, insights.

OAuth (Meta Login for Business / standard web flow):
  start     https://www.facebook.com/{v}/dialog/oauth
  exchange  GET {graph}/{v}/oauth/access_token (code -> short-lived token)
  extend    grant_type=fb_exchange_token (short -> ~60-day long-lived)
Verification = live debug_token + adaccounts read. Writes (campaign
create, forced PAUSED) run ONLY from approval-gated executors.
Access tokens never leave the backend except in Graph HTTPS calls.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.app.integrations.marketing.base import (
    BaseProvider,
    ProviderResult,
    _summarise_httpx_error,
    classify_http_status,
    ERR_MALFORMED_RESPONSE,
    ERR_MISSING_CONFIGURATION,
)

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"

META_ADS_SCOPES = ["ads_read", "ads_management"]


class MetaAdsProvider(BaseProvider):
    provider_key = "meta_ads"

    def authorization_url(
        self, *, app_id: str, redirect_uri: str, state: str,
        scopes: list[str] | None = None, graph_version: str = "v24.0",
    ) -> str:
        params = {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "scope": ",".join(scopes or META_ADS_SCOPES),
            "response_type": "code",
            "state": state,
        }
        return f"https://www.facebook.com/{graph_version}/dialog/oauth?{urlencode(params)}"

    def exchange_code(
        self,
        *,
        code: str,
        app_id: str,
        app_secret: str,
        redirect_uri: str,
        graph_version: str = "v24.0",
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        try:
            with self._client(transport) as client:
                resp = client.get(
                    f"{GRAPH_BASE}/{graph_version}/oauth/access_token",
                    params={
                        "client_id": app_id,
                        "redirect_uri": redirect_uri,
                        "client_secret": app_secret,
                        "code": code,
                    },
                )
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        if resp.status_code != 200:
            err_code, message = classify_http_status(resp.status_code, "Meta OAuth", resp.text[:500])
            return ProviderResult(ok=False, provider=self.provider_key, error_code=err_code, message=message)
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Meta returned an unreadable token response.",
            )
        short_token = payload.get("access_token")
        if not short_token:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Meta did not return an access token.",
            )
        # Extend to a long-lived token (best effort — short token still works).
        long_token: str | None = None
        try:
            with self._client(transport) as client:
                erep = client.get(
                    f"{GRAPH_BASE}/{graph_version}/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": app_id,
                        "client_secret": app_secret,
                        "fb_exchange_token": short_token,
                    },
                )
            if erep.status_code == 200:
                long_token = erep.json().get("access_token") or None
        except Exception:
            pass
        return ProviderResult(
            ok=True, provider=self.provider_key,
            data={
                "access_token": long_token or short_token,
                "long_lived": bool(long_token),
            },
            message="Meta authorization granted.",
        )

    def revoke(
        self, *, user_id: str, access_token: str, graph_version: str = "v24.0",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Best-effort permission revoke on disconnect. Never raises."""
        try:
            with self._client(transport) as client:
                client.delete(
                    f"{GRAPH_BASE}/{graph_version}/{user_id}/permissions",
                    params={"access_token": access_token},
                )
        except Exception as exc:
            log.warning("Meta revoke best-effort failed: %s", type(exc).__name__)

    # -- verification -------------------------------------------------------
    def verify(
        self,
        *,
        access_token: str,
        ad_account_id: str | None = None,
        graph_version: str = "v24.0",
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        """Live verification: debug the token + read ad accounts. Only a
        successful live read sets status=connected."""
        if not access_token:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MISSING_CONFIGURATION,
                message="No Meta access token is stored. Connect the account first.",
            )
        try:
            with self._client(transport) as client:
                resp = client.get(
                    f"{GRAPH_BASE}/{graph_version}/me/adaccounts",
                    params={
                        "access_token": access_token,
                        "fields": "id,name,account_status",
                        "limit": 25,
                    },
                )
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        if resp.status_code != 200:
            err_code, message = classify_http_status(resp.status_code, "Meta", resp.text[:500])
            return ProviderResult(ok=False, provider=self.provider_key, error_code=err_code, message=message)
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Meta returned an unreadable response.",
            )
        accounts = payload.get("data", []) if isinstance(payload, dict) else []
        if not accounts:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_ACCOUNT_NOT_FOUND,
                message="Meta authorized the app but exposed no ad accounts.",
            )
        chosen = None
        if ad_account_id:
            norm = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
            chosen = next((a for a in accounts if a.get("id") == norm), None)
            if chosen is None:
                return ProviderResult(
                    ok=False, provider=self.provider_key,
                    error_code=ERR_ACCOUNT_NOT_FOUND,
                    message=f"Ad account {ad_account_id} is not accessible with this authorization.",
                )
        else:
            chosen = accounts[0]
        return ProviderResult(
            ok=True,
            provider=self.provider_key,
            account={
                "ad_account_id": chosen.get("id"),
                "ad_account_name": chosen.get("name"),
                "account_status": chosen.get("account_status"),
                "accessible_count": len(accounts),
            },
            data={"ad_account_id": chosen.get("id"), "accounts": [
                {"id": a.get("id"), "name": a.get("name")} for a in accounts
            ]},
            message=f"Meta Ads verified ({chosen.get('name')}).",
        )

    # -- reads ----------------------------------------------------------------
    def list_campaigns(
        self,
        *,
        access_token: str,
        ad_account_id: str,
        graph_version: str = "v24.0",
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        norm = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
        try:
            with self._client(transport) as client:
                resp = client.get(
                    f"{GRAPH_BASE}/{graph_version}/{norm}/campaigns",
                    params={
                        "access_token": access_token,
                        "fields": "id,name,status,objective",
                        "limit": 50,
                    },
                )
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        if resp.status_code != 200:
            err_code, message = classify_http_status(resp.status_code, "Meta", resp.text[:500])
            return ProviderResult(ok=False, provider=self.provider_key, error_code=err_code, message=message)
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Meta returned an unreadable response.",
            )
        campaigns = payload.get("data", []) if isinstance(payload, dict) else []
        # Attach lightweight insights per campaign (best effort, batched serially).
        out: list[dict[str, Any]] = []
        try:
            with self._client(transport) as client:
                for camp in campaigns:
                    row = {
                        "id": camp.get("id"), "name": camp.get("name"),
                        "status": camp.get("status"), "objective": camp.get("objective"),
                        "impressions": None, "clicks": None, "spend": None,
                    }
                    try:
                        irep = client.get(
                            f"{GRAPH_BASE}/{graph_version}/{camp.get('id')}/insights",
                            params={
                                "access_token": access_token,
                                "fields": "impressions,clicks,spend",
                                "date_preset": "last_30d",
                            },
                        )
                        if irep.status_code == 200:
                            ins = (irep.json().get("data") or [{}])[0]
                            row.update({
                                "impressions": ins.get("impressions"),
                                "clicks": ins.get("clicks"),
                                "spend": ins.get("spend"),
                            })
                    except Exception:
                        pass
                    out.append(row)
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        return ProviderResult(
            ok=True, provider=self.provider_key,
            data={"campaigns": out, "ad_account_id": norm},
            message=f"{len(out)} campaign(s) read from Meta Ads.",
        )

    # -- approval-gated write ---------------------------------------------------
    def create_campaign(
        self,
        *,
        access_token: str,
        ad_account_id: str,
        name: str,
        objective: str = "OUTCOME_TRAFFIC",
        graph_version: str = "v24.0",
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        """Create a PAUSED campaign. Caller MUST hold human approval."""
        norm = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
        try:
            with self._client(transport) as client:
                resp = client.post(
                    f"{GRAPH_BASE}/{graph_version}/{norm}/campaigns",
                    data={
                        "access_token": access_token,
                        "name": name,
                        "objective": objective,
                        "status": "PAUSED",
                        "special_ad_categories": "[]",
                    },
                )
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        if resp.status_code != 200:
            err_code, message = classify_http_status(resp.status_code, "Meta", resp.text[:1000])
            return ProviderResult(ok=False, provider=self.provider_key, error_code=err_code, message=message)
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Meta accepted the campaign but returned an unreadable response.",
            )
        return ProviderResult(
            ok=True, provider=self.provider_key, executed=True,
            data={"campaign_id": payload.get("id"), "status": "PAUSED", "ad_account_id": norm},
            provider_request_id=payload.get("id"),
            message="Campaign created PAUSED in Meta Ads.",
        )
