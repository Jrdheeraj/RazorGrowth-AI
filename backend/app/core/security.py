"""
Cryptographic security primitives — Phase 6.

Password hashing:
  - hashlib.scrypt (RFC 7914): memory-hard KDF, salted per password.
  - Stored format:  scrypt$<n>$<r>$<p>$<b64salt>$<b64digest>
  - Verification is constant-time (hmac.compare_digest).
  - Plaintext passwords are never stored or logged.

Tokens:
  - HS256 JWT access tokens via PyJWT. The signing key comes exclusively
    from configuration (AUTH_SECRET_KEY). Tokens carry sub/email/type claims
    plus iat/exp; expiry is mandatory.

Secret hygiene: no function in this module logs secrets.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from typing import Any

import jwt

from backend.app.core.config import get_settings

# ── scrypt parameters (OWASP-aligned for interactive logins) ────────────────
_SCRYPT_N = 2 ** 14     # CPU/memory cost
_SCRYPT_R = 8           # block size
_SCRYPT_DKLEN = 32      # digest length
_SCRYPT_MAXMEM = 64 * 1024 * 1024  # OpenSSL max memory allowance

_ALGORITHM = "HS256"
_TOKEN_TYPE_ACCESS = "access"


class PasswordPolicyError(ValueError):
    """Raised when a candidate password violates the configured policy."""


# ─────────────────────────────────────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a plaintext password into a storable scrypt digest string."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=1,
        dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        1,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """
    Constant-time verification of a plaintext password against a stored
    scrypt hash. Returns False on any malformed input — never raises.
    """
    try:
        scheme, n_s, r_s, p_s, salt_b64, digest_b64 = stored_hash.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            dklen=len(expected),
            maxmem=_SCRYPT_MAXMEM,
        )
        return hmac.compare_digest(candidate, expected)
    except (ValueError, TypeError):
        return False


def validate_password_policy(password: str) -> None:
    """
    Enforce the configured password policy.

    Raises PasswordPolicyError with a client-safe message on violation.
    Policy (defaults): min length 12, at least one letter and one digit.
    """
    settings = get_settings()
    min_len = settings.PASSWORD_MIN_LENGTH
    errors: list[str] = []
    if len(password) < min_len:
        errors.append(f"at least {min_len} characters")
    if not any(c.isalpha() for c in password):
        errors.append("at least one letter")
    if not any(c.isdigit() for c in password):
        errors.append("at least one digit")
    if errors:
        raise PasswordPolicyError(
            "PASSWORD_POLICY_VIOLATION: password must contain " + ", ".join(errors)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Access tokens
# ─────────────────────────────────────────────────────────────────────────────


def create_access_token(user_id: uuid.UUID, email: str) -> tuple[str, int]:
    """
    Mint an access token for a human user.

    Returns (token, expires_in_seconds). Expiry is always set — there are
    no non-expiring tokens.
    """
    settings = get_settings()
    now = int(time.time())
    expires_in = settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "type": _TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": now + expires_in,
        "iss": settings.APP_NAME,
        "jti": secrets.token_urlsafe(16),
    }
    token = jwt.encode(payload, settings.AUTH_SECRET_KEY, algorithm=_ALGORITHM)
    return token, expires_in


class TokenError(Exception):
    """Base class for token validation failures (never leaks internals)."""


class TokenExpiredError(TokenError):
    pass


class TokenInvalidError(TokenError):
    pass


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Validate signature + expiry + type and return the JWT claims.

    Raises TokenExpiredError / TokenInvalidError (client-safe).
    """
    settings = get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.AUTH_SECRET_KEY,
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "sub", "type"]},
            issuer=settings.APP_NAME,
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError("TOKEN_INVALID") from exc

    if claims.get("type") != _TOKEN_TYPE_ACCESS:
        raise TokenInvalidError("TOKEN_INVALID")
    try:
        uuid.UUID(str(claims.get("sub")))
    except ValueError as exc:
        raise TokenInvalidError("TOKEN_INVALID") from exc
    return claims
