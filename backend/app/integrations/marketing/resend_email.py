"""Resend email provider — the Marketing Agent's real email backend.

Resend REST API (https://api.resend.com):
  verify  GET  /domains            — 200 with a valid API key
  send    POST /emails             — {from, to[], subject, html?, text?}
  status  GET  /emails/{email_id}  — delivery status polling

Sending NEVER happens from agent tools: the only send path is the
approval-gated send_campaign executor (see services/action_executor.py).
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
    redact_mapping,
    ERR_MALFORMED_RESPONSE,
    ERR_MISSING_CONFIGURATION,
)

log = logging.getLogger(__name__)

RESEND_BASE = "https://api.resend.com"


class ResendProvider(BaseProvider):
    provider_key = "resend"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # -- verification ----------------------------------------------------
    def verify(
        self,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        """Verify the key against the live API. No email is sent."""
        if not api_key:
            return ProviderResult(
                ok=False,
                provider=self.provider_key,
                error_code=ERR_MISSING_CONFIGURATION,
                message="No Resend API key was provided.",
            )
        try:
            with self._client(transport) as client:
                resp = client.get(f"{RESEND_BASE}/domains", headers=self._headers(api_key))
        except Exception as exc:
            code, message = _summarise_httpx_error(exc)
            log.warning("Resend verify transport failure: %s", code)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code, message=message)
        if resp.status_code != 200:
            code, message = classify_http_status(resp.status_code, "Resend", resp.text[:500])
            log.warning("Resend verify failed: %s http=%s", code, resp.status_code)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code, message=message)
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Resend returned an unreadable response.",
            )
        domains = payload.get("data", []) if isinstance(payload, dict) else []
        verified = [
            {"id": d.get("id"), "name": d.get("name"), "status": d.get("status")}
            for d in domains if isinstance(d, dict)
        ]
        return ProviderResult(
            ok=True,
            provider=self.provider_key,
            account={"domains": verified, "domain_count": len(verified)},
            data={"domains": verified},
            message=f"Resend key verified ({len(verified)} domain(s) on record).",
        )

    # -- sending (approval-gated executors only) --------------------------
    def send_email(
        self,
        *,
        api_key: str,
        from_email: str,
        to: list[str],
        subject: str,
        html: str | None = None,
        text: str | None = None,
        reply_to: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        """Send one email via Resend. Caller MUST have human approval."""
        if not api_key or not from_email or not to or not subject:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MISSING_CONFIGURATION,
                message="from, to and subject are all required to send.",
            )
        body: dict[str, Any] = {
            "from": from_email,
            "to": to,
            "subject": subject,
        }
        if html:
            body["html"] = html
        if text:
            body["text"] = text
        if reply_to:
            body["reply_to"] = reply_to
        try:
            with self._client(transport) as client:
                resp = client.post(
                    f"{RESEND_BASE}/emails",
                    headers=self._headers(api_key),
                    json=body,
                )
        except Exception as exc:
            code, message = _summarise_httpx_error(exc)
            log.warning("Resend send transport failure: %s", code)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code, message=message)
        if resp.status_code not in (200, 201, 202):
            code, message = classify_http_status(resp.status_code, "Resend", resp.text[:500])
            log.warning("Resend send failed: %s http=%s", code, resp.status_code)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code, message=message)
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Resend accepted the send but returned an unreadable response.",
            )
        email_id = payload.get("id") if isinstance(payload, dict) else None
        log.info("Resend email accepted id=%s to_count=%d", email_id, len(to))
        return ProviderResult(
            ok=True,
            provider=self.provider_key,
            executed=True,
            account={},
            data={"email_id": email_id, "to_count": len(to), "subject": subject},
            provider_request_id=email_id,
            message="Email accepted by Resend.",
        )

    # -- delivery status ---------------------------------------------------
    def get_email_status(
        self,
        *,
        api_key: str,
        email_id: str,
        transport: httpx.BaseTransport | None = None,
    ) -> ProviderResult:
        try:
            with self._client(transport) as client:
                resp = client.get(
                    f"{RESEND_BASE}/emails/{email_id}", headers=self._headers(api_key)
                )
        except Exception as exc:
            code, message = _summarise_httpx_error(exc)
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code, message=message)
        if resp.status_code != 200:
            code, message = classify_http_status(resp.status_code, "Resend", resp.text[:500])
            return ProviderResult(ok=False, provider=self.provider_key, error_code=code, message=message)
        try:
            payload = resp.json()
        except Exception:
            return ProviderResult(
                ok=False, provider=self.provider_key,
                error_code=ERR_MALFORMED_RESPONSE,
                message="Resend returned an unreadable response.",
            )
        safe = redact_mapping(payload if isinstance(payload, dict) else {})
        return ProviderResult(
            ok=True, provider=self.provider_key, data={"email": safe},
            message="Delivery record retrieved.",
        )
