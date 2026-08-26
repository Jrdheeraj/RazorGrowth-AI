"""
Phase 6 security tests — authentication (Slice 10 scenarios 1–8).

1.  Successful login
2.  Invalid password
3.  Unknown user
4.  Expired token
5.  Invalid token
6.  Missing token
7.  Disabled user
8.  Unauthorized endpoint access
"""
from __future__ import annotations

import time
import uuid

import jwt as pyjwt
import pytest

from backend.app.core.config import get_settings
from backend.app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from tests.security_utils import TEST_SECRET, make_user, register_and_login


@pytest.fixture
def secure(monkeypatch):
    """Force AUTH_MODE=required for the duration of one test."""
    monkeypatch.setenv("AUTH_MODE", "required")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


# ── password hashing sanity ─────────────────────────────────────────────────


def test_hash_is_not_plaintext_and_verifies():
    h = hash_password("CorrectHorse12")
    assert "CorrectHorse12" not in h
    assert h.startswith("scrypt$")
    assert verify_password("CorrectHorse12", h)
    assert not verify_password("wrong-password", h)


def test_hash_salts_are_unique_per_call():
    a, b = hash_password("same-password-1"), hash_password("same-password-1")
    assert a != b


def test_verify_never_raises_on_malformed_hash():
    assert verify_password("x", "") is False
    assert verify_password("x", "garbage") is False
    assert verify_password("x", "md5$1$2$abc$def") is False


# ── login endpoint ───────────────────────────────────────────────────────────


class TestLogin:
    def test_successful_login_returns_token(self, client, secure, db_session):
        u = make_user(db_session)
        r = client.post(
            "/api/auth/login",
            json={"email": u.email, "password": "CorrectHorse12"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
        assert len(body["access_token"]) > 20
        assert body["user"]["email"] == u.email
        # The response must never contain credential material.
        assert "password" not in body["user"]

    def test_invalid_password_rejected(self, client, secure, db_session):
        u = make_user(db_session)
        r = client.post(
            "/api/auth/login", json={"email": u.email, "password": "WrongPass99"}
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "INVALID_CREDENTIALS"

    def test_unknown_user_rejected_with_same_error(self, client, secure):
        r = client.post(
            "/api/auth/login",
            json={"email": f"nobody-{uuid.uuid4().hex[:6]}@x.test",
                  "password": "Whatever123"},
        )
        assert r.status_code == 401
        # Same generic error as wrong password — no account enumeration.
        assert r.json()["detail"] == "INVALID_CREDENTIALS"

    def test_disabled_user_login_forbidden(self, client, secure, db_session):
        from backend.app.models.enums import UserStatus

        u = make_user(db_session)
        u.status = UserStatus.disabled
        db_session.commit()
        r = client.post(
            "/api/auth/login",
            json={"email": u.email, "password": "CorrectHorse12"},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "USER_DISABLED"

    def test_registration_enforces_password_policy(self, client, secure):
        r = client.post(
            "/api/auth/register",
            json={"email": f"weak-{uuid.uuid4().hex[:6]}@x.test",
                  "password": "short"},
        )
        assert r.status_code == 422
        assert "PASSWORD_POLICY_VIOLATION" in r.json()["detail"]


# ── token validation on protected endpoints ────────────────────────────────


class _ProtectedProbe:
    """A representative protected route for token-validation scenarios."""

    path = "/api/customers"


class TestTokenValidation:
    def test_expired_token_rejected(self, client, secure, db_session):
        u = make_user(db_session)
        now = int(time.time())
        claims = {
            "sub": str(u.id),
            "email": u.email,
            "type": "access",
            "iat": now - 7200,
            "exp": now - 3600,          # expired one hour ago
            "iss": get_settings().APP_NAME,
        }
        token = pyjwt.encode(claims, TEST_SECRET, algorithm="HS256")
        r = client.get(
            _ProtectedProbe.path, headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "TOKEN_EXPIRED"

    def test_invalid_signature_rejected(self, client, secure, db_session):
        u = make_user(db_session)
        token, _ = create_access_token(u.id, u.email)
        forged = token[:-6] + ("aaaaaa" if token[-6:] != "aaaaaa" else "bbbbbb")
        r = client.get(
            _ProtectedProbe.path, headers={"Authorization": f"Bearer {forged}"}
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "TOKEN_INVALID"

    def test_garbage_token_rejected(self, client, secure):
        r = client.get(
            _ProtectedProbe.path, headers={"Authorization": "Bearer not.a.jwt"}
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "TOKEN_INVALID"

    def test_missing_token_rejected_in_required_mode(self, client, secure):
        r = client.get(_ProtectedProbe.path)
        assert r.status_code == 401
        assert r.json()["detail"] == "NOT_AUTHENTICATED"
        assert r.headers.get("www-authenticate") == "Bearer"

    def test_non_bearer_scheme_rejected(self, client, secure):
        r = client.get(_ProtectedProbe.path, headers={"Authorization": "Basic abc"})
        assert r.status_code == 401

    def test_token_for_nonexistent_user_rejected(self, client, secure):
        """Forged 'agent'-style principal: valid JWT, but sub has no user row."""
        claims = {
            "sub": str(uuid.uuid4()),
            "email": "rogue-agent@evil.test",
            "type": "access",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
        }
        token = pyjwt.encode(claims, TEST_SECRET, algorithm="HS256")
        r = client.get(
            _ProtectedProbe.path, headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "TOKEN_INVALID"

    def test_disabled_user_token_rejected_on_protected_route(
        self, client, secure, db_session
    ):
        from backend.app.models.enums import UserStatus

        u = make_user(db_session)
        headers = {
            "Authorization": f"Bearer {create_access_token(u.id, u.email)[0]}"
        }
        # Token issued while active…
        r = client.get(_ProtectedProbe.path, headers=headers)
        assert r.status_code in (200, 403)  # 200 empty list or membership-gated
        # …then account disabled → same token must stop working immediately.
        u.status = UserStatus.disabled
        db_session.commit()
        r = client.get(_ProtectedProbe.path, headers=headers)
        assert r.status_code == 403
        assert r.json()["detail"] == "USER_DISABLED"


class TestRegistrationToggle:
    def test_registration_disabled_when_configured(
        self, client, monkeypatch, db_session
    ):
        monkeypatch.setenv("AUTH_ENABLE_REGISTRATION", "false")
        get_settings.cache_clear()
        try:
            r = client.post(
                "/api/auth/register",
                json={"email": f"reg-{uuid.uuid4().hex[:6]}@x.test",
                      "password": "LongEnough123"},
            )
            assert r.status_code == 403
            assert r.json()["detail"] == "REGISTRATION_DISABLED"
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()

    def test_duplicate_email_rejected(self, client, secure, db_session):
        u = make_user(db_session)
        r = client.post(
            "/api/auth/register",
            json={"email": u.email, "password": "LongEnough123"},
        )
        assert r.status_code == 409


class TestMe:
    def test_me_requires_auth(self, client, secure):
        assert client.get("/api/auth/me").status_code == 401

    def test_me_returns_memberships(self, client, secure, db_session):
        from tests.security_utils import make_world

        m, u, mem = make_world(db_session, slug_hint="me")
        r = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {create_access_token(u.id, u.email)[0]}"
        })
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == u.email
        assert len(body["memberships"]) >= 1
        assert body["memberships"][0]["merchant_id"] == str(m.id)
        assert body["memberships"][0]["role"] in {"owner", "admin", "operator", "analyst"}
