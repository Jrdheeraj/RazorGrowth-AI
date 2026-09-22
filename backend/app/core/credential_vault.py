"""
Credential vault — Fernet encryption for stored integration secrets.

Rules (hard):
  - Secrets are encrypted at rest in the integration_connections table.
  - The Fernet key comes from INTEGRATION_CREDENTIAL_KEY, or is derived
    from AUTH_SECRET_KEY via HKDF when no explicit key is configured
    (development convenience — production SHOULD set an explicit key and
    the vault logs a warning when it falls back to derivation).
  - Decrypted secrets live only in memory, are passed only to provider
    adapters, and are NEVER returned by APIs, written to audit payloads,
    or logged (see core/logfilter secret redaction + service redaction).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os

log = logging.getLogger(__name__)

_FERNET_KEY: bytes | None = None

# Marker prefix so stored blobs are identifiable without decryption.
_VAULT_PREFIX = "vault1:"


def _derive_key(auth_secret: str) -> bytes:
    """Derive a stable Fernet key from the auth secret (dev fallback)."""
    digest = hashlib.sha256(
        b"razorgrowth-integration-vault-v1:" + auth_secret.encode("utf-8")
    ).digest()
    return base64.urlsafe_b64encode(digest)


def _load_fernet_key() -> bytes:
    explicit = (os.environ.get("INTEGRATION_CREDENTIAL_KEY") or "").strip()
    if explicit:
        try:
            from cryptography.fernet import Fernet

            Fernet(explicit.encode("utf-8"))  # validates key shape
            return explicit.encode("utf-8")
        except Exception as exc:
            raise RuntimeError(
                "INTEGRATION_CREDENTIAL_KEY is set but is not a valid "
                f"Fernet key: {exc}"
            ) from exc
    auth_secret = (os.environ.get("AUTH_SECRET_KEY") or "").strip()
    if not auth_secret:
        raise RuntimeError(
            "No INTEGRATION_CREDENTIAL_KEY and no AUTH_SECRET_KEY — "
            "cannot initialise the credential vault."
        )
    log.warning(
        "INTEGRATION_CREDENTIAL_KEY not set — deriving the vault key from "
        "AUTH_SECRET_KEY. Set an explicit key in production."
    )
    return _derive_key(auth_secret)


def _fernet():
    global _FERNET_KEY
    if _FERNET_KEY is None:
        _FERNET_KEY = _load_fernet_key()
    from cryptography.fernet import Fernet

    return Fernet(_FERNET_KEY)


def reset_vault_cache() -> None:
    """Forget the cached key (tests only — forces re-derivation)."""
    global _FERNET_KEY
    _FERNET_KEY = None


def encrypt_secret(plaintext: str) -> str:
    """Encrypt one secret value. Returns a storable 'vault1:...' blob."""
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"{_VAULT_PREFIX}{token}"


def decrypt_secret(blob: str) -> str:
    """Decrypt a vault blob back to plaintext (memory only)."""
    if not blob.startswith(_VAULT_PREFIX):
        raise ValueError("Not a vault credential blob")
    return _fernet().decrypt(blob[len(_VAULT_PREFIX):].encode("ascii")).decode("utf-8")


def is_vault_blob(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_VAULT_PREFIX)
