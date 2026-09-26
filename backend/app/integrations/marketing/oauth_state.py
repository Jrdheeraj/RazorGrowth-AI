"""Signed OAuth state tokens for provider callbacks.

The provider redirects the merchant's browser to our callback WITHOUT any
Authorization header, so the callback cannot use the normal auth deps.
Instead the `state` we generate at oauth/start is a self-validating token:

    base64url(payload) + "." + hex(HMAC_SHA256(AUTH_SECRET_KEY, payload))

payload = {"merchant_id": ..., "provider": ..., "exp": epoch, "nonce": ...,
           optional "account_id": <selected customer id>}

The callback verifies signature + expiry + provider match, then resolves
the tenant from the token itself. CSRF-safe: an attacker cannot mint or
replay states for another merchant (HMAC key is server-side, 15-min TTL,
single-use nonces tracked in memory).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid

STATE_TTL_SECONDS = 15 * 60

_used_nonces: set[str] = set()


def _clean_account_selector(value: object) -> str | None:
    """Normalize an optional account selector carried in the state.

    Only digits survive (hyphens stripped) with a sane length, so an
    attacker-controlled value can never reach a Google Ads URL/header.
    """
    if value is None:
        return None
    digits = str(value).strip().replace("-", "")
    if digits.isdigit() and 4 <= len(digits) <= 20:
        return digits
    return None


def _key() -> bytes:
    import os

    secret = (os.environ.get("AUTH_SECRET_KEY") or "").encode("utf-8")
    if not secret:
        raise RuntimeError("AUTH_SECRET_KEY is required for OAuth state signing")
    return secret


def issue_state(
    merchant_id: uuid.UUID, provider: str, *, account_selector: str | None = None
) -> str:
    payload = {
        "merchant_id": str(merchant_id),
        "provider": provider,
        "exp": int(time.time()) + STATE_TTL_SECONDS,
        "nonce": secrets.token_hex(12),
    }
    # Optional per-merchant account selection (e.g. Google Ads customer id)
    # travels inside the SIGNED payload — never in the OAuth redirect URL.
    selector = _clean_account_selector(account_selector)
    if selector:
        payload["account_id"] = selector
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    sig = hmac.new(_key(), raw.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_state(token: str, provider: str) -> uuid.UUID:
    """Validate a callback state. Returns the merchant_id or raises ValueError."""
    return verify_state_context(token, provider)[0]


def verify_state_context(token: str, provider: str) -> tuple[uuid.UUID, str | None]:
    """Validate a callback state.

    Returns (merchant_id, account_selector) — the tenant resolved from the
    signature-protected payload plus the optional account the merchant
    picked before starting OAuth. Raises ValueError on any tamper/expiry/
    replay/provider mismatch.
    """
    try:
        raw, sig = token.rsplit(".", 1)
    except ValueError as exc:
        raise ValueError("INVALID_STATE") from exc
    expected = hmac.new(_key(), raw.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise ValueError("INVALID_STATE")
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
    except Exception as exc:
        raise ValueError("INVALID_STATE") from exc
    if payload.get("provider") != provider:
        raise ValueError("STATE_PROVIDER_MISMATCH")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("STATE_EXPIRED")
    nonce = str(payload.get("nonce", ""))
    if not nonce or nonce in _used_nonces:
        raise ValueError("STATE_REUSED")
    if len(_used_nonces) > 10_000:
        _used_nonces.clear()
    _used_nonces.add(nonce)
    try:
        merchant_id = uuid.UUID(str(payload["merchant_id"]))
    except ValueError as exc:
        raise ValueError("INVALID_STATE") from exc
    return merchant_id, _clean_account_selector(payload.get("account_id"))
