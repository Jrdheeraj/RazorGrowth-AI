"""Google Ads provider — OAuth2 REST client (developer-token sunset model).

Implements the CURRENT Google Ads API authentication contract:
  - OAuth 2.0 user flow, scope https://www.googleapis.com/auth/adwords;
    short-lived access tokens minted from the stored refresh token at
    https://oauth2.googleapis.com/token (grant_type=refresh_token).
  - Since the September 2026 developer-token sunset, Google associates
    API access levels with the Google Cloud project that owns the OAuth
    credentials — NO developer token is required. The legacy
    `developer-token` header is sent ONLY when a token is explicitly
    available (backward compatibility); it is never required and never
    requested from the merchant.
  - Verification = live `customers:listAccessibleCustomers` + customer read.
  - Reads use GAQL `googleAds:search`.
  - Writes use `googleAds:mutate` (campaign budgets + campaigns, created
    PAUSED for safety) and run ONLY from approval-gated executors.

Note (2026 docs): generating NEW refresh tokens requires the Google
account to have 2SV (and passkeys for enforced users). Existing refresh
tokens keep working. The connect flow surfaces provider errors honestly.
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
    ERR_AUTH_EXPIRED,
    ERR_AUTH_REVOKED,
    ERR_GOOGLE_2SV_REQUIRED,
    ERR_GOOGLE_ACCOUNT_NOT_LINKED,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_CREDENTIALS,
    ERR_MALFORMED_RESPONSE,
    ERR_MISSING_CONFIGURATION,
    ERR_OAUTH_SCOPE_INSUFFICIENT,
)

log = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
GOOGLE_ADS_BASE = "https://googleads.googleapis.com"


def _sanitize_google_message(msg: str, limit: int = 300) -> str:
    """Truncate + redact any token-like material from a Google error message.

    Google error messages never contain secrets, but we defensively redact
    access/refresh-token shapes before surfacing them.
    """
    import re as _re

    if not msg:
        return ""
    cleaned = msg.strip()[:limit]
    # Defensively redact token shapes if ever echoed (never expected).
    cleaned = _re.sub(r"ya29\.[A-Za-z0-9\-_]+", "[REDACTED_TOKEN]", cleaned)
    cleaned = _re.sub(r"1//[A-Za-z0-9\-_]+", "[REDACTED_TOKEN]", cleaned)
    cleaned = _re.sub(r"4/[A-Za-z0-9\-_]+", "[REDACTED_CODE]", cleaned)
    cleaned = _re.sub(r"Bearer\s+[A-Za-z0-9\-_\.]+", "Bearer [REDACTED]", cleaned, flags=_re.IGNORECASE)
    return cleaned


def _extract_google_diagnostics(body_text: str = "") -> dict[str, str]:
    """Extract safe Google Ads diagnostics without touching secrets.

    Returns {google_error_code, google_status, sanitized_message, request_id}.
    Only surfaces: error enums/codes, HTTP-mapped status strings,
    sanitized message snippet, endpoint-agnostic request id.
    Never includes tokens, secrets, cookies, or auth codes.
    """
    import json as _json

    out = {"google_error_code": "", "google_status": "", "sanitized_message": "", "request_id": ""}
    if not body_text:
        return out
    try:
        payload = _json.loads(body_text)
    except Exception:
        # Non-JSON (e.g. HTML proxy error): sanitize raw snippet only.
        out["sanitized_message"] = _sanitize_google_message(body_text, 200)
        return out
    # REST shape: {"error": {"code","message","status","details":[...]}}
    err = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(err, dict):
        # OAuth token endpoint shape: {"error": "invalid_grant", ...}
        if isinstance(payload, dict) and isinstance(payload.get("error"), str):
            out["google_error_code"] = str(payload["error"])[:80].upper()
            out["sanitized_message"] = _sanitize_google_message(
                str(payload.get("error_description", "")), 200
            )
        return out
    if isinstance(err.get("status"), str):
        out["google_status"] = str(err["status"])[:60]
    if isinstance(err.get("message"), str):
        out["sanitized_message"] = _sanitize_google_message(str(err["message"]), 300)
    codes: list[str] = []
    request_id = ""
    for detail in err.get("details", []) or []:
        if not isinstance(detail, dict):
            continue
        # google.rpc.ErrorInfo shape: {"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT", ...}
        reason = detail.get("reason")
        if isinstance(reason, str) and reason:
            codes.append(reason.strip().upper())
        for gerr in detail.get("errors", []) or []:
            if not isinstance(gerr, dict):
                continue
            ec = gerr.get("errorCode")
            if isinstance(ec, dict):
                for _k, _v in ec.items():
                    if isinstance(_v, str) and _v and _v.upper() not in ("UNSPECIFIED", "UNKNOWN"):
                        codes.append(_v.strip().upper())
                    elif isinstance(_v, str) and _v:
                        codes.append(_v.strip().upper())
            elif isinstance(ec, str) and ec:
                codes.append(ec.strip().upper())
            # message inside GoogleAdsError is more specific than top-level
            if not out["sanitized_message"] and isinstance(gerr.get("message"), str):
                out["sanitized_message"] = _sanitize_google_message(str(gerr["message"]), 300)
        if not request_id and isinstance(detail.get("requestId"), str):
            request_id = str(detail["requestId"])[:80]
    # Deduplicate preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    if uniq:
        out["google_error_code"] = "+".join(uniq[:3])
    out["request_id"] = request_id
    return out


class GoogleAdsProvider(BaseProvider):
    provider_key = "google_ads"

    @staticmethod
    def _token_failure(resp: httpx.Response) -> ProviderResult:
        """Classify an OAuth token-endpoint failure.

        Google returns HTTP 400 (not 401) with {"error": "invalid_grant"}
        for expired/revoked refresh tokens — map that to AUTH_EXPIRED so
        the agent/UI can instruct a reconnect.
        """
        body = resp.text[:500]
        if "invalid_grant" in body.lower():
            return ProviderResult(
                ok=False, provider="google_ads",
                error_code=ERR_AUTH_EXPIRED,
                message="Google Ads authorization has expired. Reconnect the account.",
            )
        err_code, message = classify_http_status(resp.status_code, "Google OAuth", body)
        return ProviderResult(ok=False, provider="google_ads", error_code=err_code, message=message)

    # -- OAuth -----------------------------------------------------------
    def authorization_url(
        self, *, client_id: str, redirect_uri: str, state: str
    ) -> str:
        from urllib.parse import urlencode

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_ADS_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def exchange_code(
        self,
        *,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        try:
            with self._client(transport) as client:
                resp = client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        if resp.status_code != 200:
            return self._token_failure(resp)
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Google returned an unreadable token response.",
            )
        if not payload.get("refresh_token") or not payload.get("access_token"):
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Google did not return a refresh token. Reconnect and approve offline access.",
            )
        # Scope guard: if Google echoes the granted scope and adwords is
        # missing, the token can never reach the Ads API. Fail fast with a
        # precise code (safe: scope string only, never token material) so
        # the caller forces a fresh consent instead of reusing the token.
        scope_raw = str(payload.get("scope") or "")
        if scope_raw and GOOGLE_ADS_SCOPE not in scope_raw:
            log.warning(
                "Google OAuth scope insufficient: %s",
                self._safe_log({"has_scope": bool(scope_raw), "scope_present": scope_raw[:200]}),
            )
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_OAUTH_SCOPE_INSUFFICIENT,
                message=(
                    "Google OAuth scope is insufficient (missing "
                    "https://www.googleapis.com/auth/adwords). Force a fresh "
                    "consent with the adwords scope, then reconnect."
                ),
                data={"has_refresh_token": True, "scope_present": scope_raw[:200]},
            )
        return ProviderResult(
            ok=True, provider=self.provider_key,
            data={
                "refresh_token": payload["refresh_token"],
                "access_token": payload["access_token"],
                "expires_in": payload.get("expires_in"),
                "scope": payload.get("scope"),
            },
            message="Google authorization granted.",
        )

    def refresh_access_token(
        self,
        *,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        try:
            with self._client(transport) as client:
                resp = client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "refresh_token": refresh_token,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "grant_type": "refresh_token",
                    },
                )
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        if resp.status_code != 200:
            return self._token_failure(resp)
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Google returned an unreadable token response.",
            )
        if not payload.get("access_token"):
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Google did not return an access token.",
            )
        return ProviderResult(
            ok=True, provider=self.provider_key,
            data={"access_token": payload["access_token"], "expires_in": payload.get("expires_in")},
        )

    def revoke(self, *, token: str, transport: httpx.BaseTransport | None = None) -> None:
        """Best-effort revoke on disconnect. Failures are logged, never raised."""
        try:
            with self._client(transport) as client:
                client.post(GOOGLE_REVOKE_URL, data={"token": token})
        except Exception as exc:
            log.warning("Google revoke best-effort failed: %s", type(exc).__name__)

    # -- request plumbing --------------------------------------------------
    # Body markers indicating the Google Cloud project's API access level
    # does not cover the requested account (e.g. Test access used against
    # a production account). Surfaced as INSUFFICIENT_PERMISSIONS with an
    # actionable message — never disguised as an OAuth failure.
    _ACCESS_LEVEL_MARKERS = (
        "access level",
        "access_level",
        "accessleveldenied",
        "test account",
        "production account",
        "user_permission_denied",
        "customer_not_enabled",
        "not enabled for",
        "cloud_project_not_approved_for_production",
        "action_not_permitted",
        "developer_token_not_approved",
        "developer_token_prohibited",
        "organization_not_approved",
    )

    @classmethod
    def _classify_ads_error(
        cls, status: int, body_text: str = "", endpoint: str = ""
    ) -> tuple[str, str]:
        """Google-Ads-aware error classification preserving the real cause.

        Parses the GoogleAdsFailure / google.rpc.ErrorInfo payload (safe
        fields only: error enum/code, HTTP status, sanitized message) and
        maps each authentication/authorization enum to a DISTINCT error
        code — never collapsing everything to INVALID_CREDENTIALS.

        Precise mapping (post developer-token sunset, no token required):
          OAUTH_TOKEN_INVALID                       -> INVALID_CREDENTIALS
          OAUTH_TOKEN_EXPIRED / invalid_grant       -> AUTH_EXPIRED
          OAUTH_TOKEN_REVOKED / DISABLED            -> AUTH_REVOKED
          ACCESS_TOKEN_SCOPE_INSUFFICIENT           -> OAUTH_SCOPE_INSUFFICIENT
          NOT_ADS_USER                              -> GOOGLE_ACCOUNT_NOT_LINKED_TO_ADS
          TWO_STEP_VERIFICATION_NOT_ENROLLED (+ ADVANCED_PROTECTION)
                                                    -> GOOGLE_2SV_REQUIRED
          CLIENT_CUSTOMER_ID_INVALID / REQUIRED,
          CUSTOMER_NOT_FOUND                        -> ACCOUNT_NOT_FOUND
          CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION
          (+ ACTION_NOT_PERMITTED, USER_PERMISSION_DENIED,
           AUTHORIZATION_ERROR, CUSTOMER_NOT_ENABLED, org errors)
                                                    -> INSUFFICIENT_PERMISSIONS
        """
        diag = _extract_google_diagnostics(body_text or "")
        gcode = (diag.get("google_error_code") or "").upper()
        gstatus = diag.get("google_status") or ""
        gmsg = diag.get("sanitized_message") or ""
        where = f" at {endpoint}" if endpoint else ""

        def _suffix() -> str:
            base = f" (HTTP {status}"
            if gstatus:
                base += f" {gstatus}"
            base += f"{where})"
            if gmsg:
                base += f" {gmsg}"
            return base[:420]

        def _with_code(human: str) -> str:
            if gcode:
                return f"{human} [{gcode}]{_suffix()}"
            return f"{human}{_suffix()}"

        # --- precise GoogleAdsFailure / ErrorInfo mapping (checked first) ---
        if gcode:
            # Expiry / revocation stay distinct (also caught by base classifier).
            if any(k in gcode for k in ("OAUTH_TOKEN_EXPIRED", "OAUTH_TOKEN_HEADER_INVALID")) or "INVALID_GRANT" in gcode:
                return ERR_AUTH_EXPIRED, _with_code(
                    "Google Ads authorization has expired. Reconnect the account."
                )
            if any(k in gcode for k in ("OAUTH_TOKEN_REVOKED", "OAUTH_TOKEN_DISABLED")):
                return ERR_AUTH_REVOKED, _with_code(
                    "Google Ads access was revoked. Reconnect the account."
                )
            if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in gcode:
                return ERR_OAUTH_SCOPE_INSUFFICIENT, _with_code(
                    "Google Ads OAuth scope is insufficient (missing "
                    "https://www.googleapis.com/auth/adwords). Force a fresh "
                    "consent with the adwords scope, then reconnect."
                )
            if "NOT_ADS_USER" in gcode or "GOOGLE_ACCOUNT_COOKIE_INVALID" in gcode:
                return ERR_GOOGLE_ACCOUNT_NOT_LINKED, _with_code(
                    "This Google account is not linked to any Google Ads account. "
                    "Add it to an Ads account (or create one), then reconnect."
                )
            if any(k in gcode for k in ("TWO_STEP_VERIFICATION_NOT_ENROLLED", "ADVANCED_PROTECTION_NOT_ENROLLED")):
                return ERR_GOOGLE_2SV_REQUIRED, _with_code(
                    "Google Ads requires 2-Step Verification (and passkeys for "
                    "enforced users) on this Google account. Enable 2SV, then "
                    "generate a fresh authorization."
                )
            if any(k in gcode for k in (
                "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION",
                "ACTION_NOT_PERMITTED",
                "DEVELOPER_TOKEN_NOT_APPROVED",
                "DEVELOPER_TOKEN_PROHIBITED",
                "USER_PERMISSION_DENIED",
                "CUSTOMER_NOT_ENABLED",
                "AUTHORIZATION_ERROR",
                "ORGANIZATION_NOT_APPROVED",
                "ORGANIZATION_NOT_ASSOCIATED",
            )):
                return ERR_INSUFFICIENT_PERMISSIONS, _with_code(
                    "Google Ads API access level denied. The Google Cloud "
                    "project owning this OAuth client needs the appropriate "
                    "Google Ads API access level for the requested account "
                    "(e.g. Test access cannot reach production accounts). "
                    "Review access in the Google Ads API Center, then reconnect."
                )
            if any(k in gcode for k in (
                "CLIENT_CUSTOMER_ID_INVALID",
                "CLIENT_CUSTOMER_ID_IS_REQUIRED",
                "CUSTOMER_NOT_FOUND",
            )):
                return ERR_ACCOUNT_NOT_FOUND, _with_code(
                    "The Google Ads account was not found or is not accessible "
                    "with this authorization. Verify the customer ID."
                )
            if "OAUTH_TOKEN_INVALID" in gcode or "AUTHENTICATION_ERROR" in gcode:
                return ERR_INVALID_CREDENTIALS, _with_code(
                    "Google Ads rejected the credentials. Check the key/token and reconnect."
                )
            # Any other GoogleAdsFailure enum: preserve it, never hide behind
            # a generic label without the code.
            if status in (401, 403):
                return ERR_INSUFFICIENT_PERMISSIONS if status == 403 else ERR_INVALID_CREDENTIALS, _with_code(
                    "Google Ads authentication/authorization failed."
                )
            if status == 404:
                return ERR_ACCOUNT_NOT_FOUND, _with_code(
                    "The Google Ads account was not found. Verify the account ID."
                )

        # --- legacy access-level body-marker fallback (no structured code) ---
        if status in (401, 403):
            lowered = (body_text or "").lower()
            if any(m in lowered for m in cls._ACCESS_LEVEL_MARKERS):
                return ERR_INSUFFICIENT_PERMISSIONS, (
                    "Google Ads API access level denied [ACCESS_LEVEL_DENIED]"
                    f"{_suffix()} The Google Cloud project owning this OAuth "
                    "client needs the appropriate Google Ads API access level "
                    "for the requested account (e.g. Test access cannot reach "
                    "production accounts). Review access in the Google Ads API "
                    "Center, then reconnect."
                )
        return classify_http_status(status, "Google Ads", body_text)

    def _headers(
        self, *, access_token: str, developer_token: str | None = None,
        login_customer_id: str | None,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        # Post-sunset the header is legacy: send only when explicitly set.
        if developer_token:
            headers["developer-token"] = developer_token
        if login_customer_id:
            headers["login-customer-id"] = login_customer_id.replace("-", "")
        return headers

    # -- verification -------------------------------------------------------
    def verify(
        self,
        *,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        developer_token: str | None = None,
        customer_id: str | None = None,
        login_customer_id: str | None = None,
        api_version: str = "v25",
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        """Live verification: mint access token, list accessible customers,
        read the operating customer. Sets status=connected ONLY on success.

        No developer token required (post-sunset model); a legacy token is
        still forwarded when explicitly provided.
        """
        if not all([refresh_token, client_id, client_secret]):
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MISSING_CONFIGURATION,
                message="Google Ads needs an OAuth client and a refresh token.",
            )
        tok = self.refresh_access_token(
            refresh_token=refresh_token, client_id=client_id,
            client_secret=client_secret, transport=transport,
        )
        if not tok.ok:
            return tok
        access = tok.data["access_token"]
        headers = self._headers(
            access_token=access, developer_token=developer_token,
            login_customer_id=login_customer_id,
        )
        try:
            with self._client(transport) as client:
                resp = client.get(
                    f"{GOOGLE_ADS_BASE}/{api_version}/customers:listAccessibleCustomers",
                    headers=headers,
                )
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        if resp.status_code != 200:
            endpoint = "customers:listAccessibleCustomers"
            err_code, message = self._classify_ads_error(
                resp.status_code, resp.text[:2000], endpoint=endpoint
            )
            # SAFE diagnostics only: error enum/code, HTTP status, endpoint,
            # whether an access token was minted — never token/secret material.
            diag = _extract_google_diagnostics(resp.text[:2000])
            log.warning(
                "Google Ads verify failed: %s",
                self._safe_log({
                    "endpoint": endpoint,
                    "http_status": resp.status_code,
                    "google_error_code": diag.get("google_error_code"),
                    "google_status": diag.get("google_status"),
                    "has_access_token": bool(access),
                    "api_version": api_version,
                }),
            )
            return ProviderResult(
                ok=False, provider=self.provider_key, error_code=err_code, message=message,
                data={
                    "google_error_code": diag.get("google_error_code"),
                    "http_status": resp.status_code,
                    "endpoint": endpoint,
                    "has_access_token": bool(access),
                },
            )
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Google Ads returned an unreadable response.",
            )
        names = payload.get("resourceNames", [])
        ids: set[str] = set()
        for n in names:
            if isinstance(n, str) and n.startswith("customers/"):
                ids.add(n.split("/")[-1])
            elif isinstance(n, dict) and n.get("resourceName", "").startswith("customers/"):
                ids.add(n["resourceName"].split("/")[-1])
            elif isinstance(n, str) and n.isdigit():
                ids.add(n)
        ids = sorted(ids)
        if not ids:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_ACCOUNT_NOT_FOUND,
                message="Google authorized the app but exposed no ad accounts [NOT_ADS_USER-equivalent]. "
                "Add this Google account to a Google Ads account (or create one), then reconnect.",
                data={"google_error_code": "NOT_ADS_USER(empty list)", "http_status": 200,
                      "endpoint": "customers:listAccessibleCustomers", "has_access_token": True},
            )
        operating = (customer_id or "").replace("-", "") or ids[0]
        if operating not in ids:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_ACCOUNT_NOT_FOUND,
                message=f"Customer {operating} is not accessible with this authorization.",
            )
        # Read the customer for a display name (honest identity).
        account_name = operating
        try:
            with self._client(transport) as client:
                cresp = client.get(
                    f"{GOOGLE_ADS_BASE}/{api_version}/customers/{operating}",
                    headers=headers,
                )
            if cresp.status_code == 200:
                cpay = cresp.json()
                account_name = cpay.get("descriptiveName") or operating
        except Exception:
            pass  # identity falls back to the raw customer id
        return ProviderResult(
            ok=True,
            provider=self.provider_key,
            account={"customer_id": operating, "customer_name": account_name, "accessible_count": len(ids)},
            data={"accessible_customer_ids": ids, "customer_id": operating},
            message=f"Google Ads verified (customer {operating}).",
        )

    # -- reads ----------------------------------------------------------------
    def search(
        self,
        *,
        access_token: str,
        developer_token: str | None = None,
        customer_id: str,
        login_customer_id: str | None,
        query: str,
        api_version: str = "v25",
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        headers = self._headers(
            access_token=access_token, developer_token=developer_token,
            login_customer_id=login_customer_id,
        )
        try:
            with self._client(transport) as client:
                resp = client.post(
                    f"{GOOGLE_ADS_BASE}/{api_version}/customers/{customer_id}/googleAds:search",
                    headers=headers,
                    json={"query": query},
                )
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        if resp.status_code != 200:
            err_code, message = self._classify_ads_error(
                resp.status_code, resp.text[:2000], endpoint="googleAds:search"
            )
            return ProviderResult(ok=False, provider=self.provider_key, error_code=err_code, message=message)
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Google Ads returned an unreadable response.",
            )
        return ProviderResult(ok=True, provider=self.provider_key, data={"results": payload.get("results", [])})

    def list_campaigns(
        self,
        *,
        access_token: str,
        developer_token: str | None = None,
        customer_id: str,
        login_customer_id: str | None,
        api_version: str = "v25",
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        query = (
            "SELECT campaign.id, campaign.name, campaign.status, "
            "campaign.advertising_channel_type, metrics.impressions, metrics.clicks, "
            "metrics.cost_micros FROM campaign ORDER BY campaign.id LIMIT 50"
        )
        res = self.search(
            access_token=access_token, developer_token=developer_token,
            customer_id=customer_id, login_customer_id=login_customer_id,
            query=query, api_version=api_version, transport=transport,
        )
        if not res.ok:
            return res
        campaigns: list[dict[str, Any]] = []
        for row in res.data.get("results", []):
            camp = row.get("campaign", {})
            metrics = row.get("metrics", {})
            cost_micros = metrics.get("costMicros") or metrics.get("cost_micros") or "0"
            try:
                cost = int(cost_micros) / 1_000_000
            except (TypeError, ValueError):
                cost = 0.0
            campaigns.append(
                {
                    "id": str(camp.get("id", "")),
                    "name": camp.get("name"),
                    "status": camp.get("status"),
                    "channel": camp.get("advertisingChannelType") or camp.get("advertising_channel_type"),
                    "impressions": metrics.get("impressions"),
                    "clicks": metrics.get("clicks"),
                    "cost": cost,
                }
            )
        return ProviderResult(
            ok=True, provider=self.provider_key,
            data={"campaigns": campaigns, "customer_id": customer_id},
            message=f"{len(campaigns)} campaign(s) read from Google Ads.",
        )

    # -- approval-gated write ---------------------------------------------------
    def create_campaign(
        self,
        *,
        access_token: str,
        developer_token: str | None = None,
        customer_id: str,
        login_customer_id: str | None,
        name: str,
        budget_amount_micros: int,
        api_version: str = "v25",
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        """Create a PAUSED Search campaign + budget via googleAds:mutate.

        Status is forced PAUSED — the merchant unpauses in the UI after
        review. Caller MUST hold human approval (enforced by executors).
        """
        if budget_amount_micros <= 0:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MISSING_CONFIGURATION,
                message="A positive budget is required to create a campaign.",
            )
        headers = self._headers(
            access_token=access_token, developer_token=developer_token,
            login_customer_id=login_customer_id,
        )
        base = f"{GOOGLE_ADS_BASE}/{api_version}/customers/{customer_id}/googleAds:mutate"
        try:
            with self._client(transport) as client:
                # 1) Create the campaign budget first (resource name needed below).
                bresp = client.post(
                    base,
                    headers=headers,
                    json={
                        "mutateOperations": [
                            {
                                "create": {
                                    "name": f"{name} — budget",
                                    "amountMicros": str(budget_amount_micros),
                                    "deliveryMethod": "STANDARD",
                                }
                            }
                        ],
                        "responseContentType": "RESOURCE_NAME_ONLY",
                    },
                )
                if bresp.status_code != 200:
                    err_code, message = self._classify_ads_error(
                        bresp.status_code, bresp.text[:2000], endpoint="googleAds:mutate(budget)"
                    )
                    return ProviderResult(ok=False, provider=self.provider_key, error_code=err_code, message=message)
                try:
                    bpay = bresp.json()
                except Exception:
                    return ProviderResult(
                        ok=False, provider=self.provider_key,
                        error_code=ERR_MALFORMED_RESPONSE,
                        message="Google Ads accepted the budget but returned an unreadable response.",
                    )
                budget_name = (
                    (bpay.get("mutateOperationResponses") or [{}])[0]
                    .get("campaignBudget", {})
                    .get("resourceName")
                )
                if not budget_name:
                    return ProviderResult(
                        ok=False, provider=self.provider_key,
                        error_code=ERR_MALFORMED_RESPONSE,
                        message="Google Ads did not return a budget resource name.",
                    )
                # 2) Create the campaign, bound to that budget.
                cresp = client.post(
                    base,
                    headers=headers,
                    json={
                        "mutateOperations": [
                            {
                                "create": {
                                    "name": name,
                                    "status": "PAUSED",
                                    "advertisingChannelType": "SEARCH",
                                    "campaignBudget": budget_name,
                                    "manualCpc": {},
                                }
                            }
                        ],
                        "responseContentType": "RESOURCE_NAME_ONLY",
                    },
                )
        except Exception as exc:
            code_, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code_, message=message)
        if cresp.status_code != 200:
            err_code, message = self._classify_ads_error(
                cresp.status_code, cresp.text[:2000], endpoint="googleAds:mutate(campaign)"
            )
            return ProviderResult(ok=False, provider=self.provider_key, error_code=err_code, message=message)
        try:
            payload = cresp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Google Ads accepted the campaign but returned an unreadable response.",
            )
        names = [budget_name] + [
            r.get("campaign", {}).get("resourceName")
            for r in payload.get("mutateOperationResponses", [])
        ]
        return ProviderResult(
            ok=True, provider=self.provider_key, executed=True,
            data={"resource_names": names, "customer_id": customer_id, "status": "PAUSED"},
            provider_request_id=(cresp.headers.get("request-id")),
            message="Campaign created PAUSED in Google Ads.",
        )
