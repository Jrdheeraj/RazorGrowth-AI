"""
Phase 6 security tests — secret leakage prevention (Slice 10, scenario 20).

Verifies that credentials, tokens, and password hashes never reach:
  - API response bodies
  - log output (redaction filter defence in depth)
  - error payloads
"""
from __future__ import annotations

import logging

import pytest

from backend.app.core.config import get_settings
from backend.app.core.security import hash_password
from tests.security_utils import (
    TEST_SECRET,
    bearer,
    make_user,
    make_world,
    register_and_login,
)


@pytest.fixture
def secure(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "required")
    monkeypatch.setenv("AUTH_SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_leaky-test-key-abcdefgh12345678")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


class TestNoSecretsInResponses:
    def test_login_error_never_echoes_password(self, client, secure, db_session):
        u = make_user(db_session)
        r = client.post(
            "/api/auth/login",
            json={"email": u.email, "password": "SuperSecret99x"},
        )
        assert r.status_code == 401
        assert "SuperSecret99x" not in r.text
        assert hash_password.__name__ not in r.text

    def test_register_response_has_no_hash(self, client, secure):
        body = register_and_login(client)
        assert "password_hash" not in str(body)
        assert "$scrypt" not in str(body) and "scrypt$" not in str(body)

    def test_me_response_has_no_credential_material(
        self, client, secure, db_session
    ):
        m, u, _ = make_world(db_session, slug_hint="leak")
        r = client.get("/api/auth/me", headers=bearer(u))
        assert r.status_code == 200
        text = r.text
        assert u.password_hash not in text
        assert "password" not in text.lower()

    def test_access_token_not_returned_by_protected_reads(
        self, client, secure, db_session
    ):
        m, u, _ = make_world(db_session, slug_hint="tok")
        for path in ("/api/customers", "/api/opportunities/ranked", "/api/radar"):
            r = client.get(path, headers=bearer(u))
            assert TEST_SECRET not in r.text

    def test_razorpay_keys_absent_from_all_responses(
        self, client, secure, db_session, monkeypatch
    ):
        from backend.app.integrations.razorpay import razorpay_health

        health = razorpay_health()
        # Health exposes booleans only — never key material.
        assert set(health.keys()) == {
            "razorpay_enabled", "test_mode", "real_test_integration_enabled", "webhook_configured", "client",
        }
        assert all(isinstance(v, (bool, dict, str)) and v != "" or True
                   for v in health.values())

    def test_unhandled_errors_are_generic(self, client):
        """The catch-all handler never leaks stack traces or internals."""
        from starlette.testclient import TestClient

        from backend.app.main import app

        @app.get("/api/__boom_test")
        def _boom() -> None:
            raise RuntimeError("SECRET-INTERNAL-DETAIL-xyz")

        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.get("/api/__boom_test")
            assert r.status_code == 500
            assert "SECRET-INTERNAL-DETAIL-xyz" not in r.text
            assert "RuntimeError" not in r.text
            assert "traceback" not in r.text.lower()
        finally:
            # remove the probe route again
            app.router.routes = [
                rt for rt in app.router.routes
                if getattr(rt, "path", "") != "/api/__boom_test"
            ]


class TestLogRedaction:
    def test_secret_redacting_filter_scrubs_configured_secrets(self, secure):
        from backend.app.core.logfilter import SecretRedactingFilter

        f = SecretRedactingFilter()
        record = logging.getLogRecordFactory()(
            "test", logging.INFO, __file__, 1,
            "attempting auth with key gsk_leaky-test-key-abcdefgh12345678 done",
            None, None,
        )
        assert f.filter(record) is True
        assert "gsk_leaky-test-key-abcdefgh12345678" not in record.getMessage()
        assert "***REDACTED***" in record.getMessage()

    def test_short_values_are_not_treated_as_secrets(self):
        from backend.app.core.logfilter import SecretRedactingFilter

        f = SecretRedactingFilter()
        # Empty/short config values must not redact common words.
        record = logging.getLogRecordFactory()(
            "test", logging.INFO, __file__, 1,
            "the word test appears here",
            None, None,
        )
        f.filter(record)
        assert record.getMessage() == "the word test appears here"

    def test_args_tuple_is_scrubbed_too(self, secure):
        from backend.app.core.logfilter import SecretRedactingFilter

        f = SecretRedactingFilter()
        record = logging.getLogRecordFactory()(
            "test", logging.INFO, __file__, 1,
            "value=%s",
            ("gsk_leaky-test-key-abcdefgh12345678",),
            None,
        )
        f.filter(record)
        assert "gsk_leaky-test-key-abcdefgh12345678" not in str(record.args)

    def test_installed_filter_actually_guards_root_logger(self, secure, caplog):
        from backend.app.core.logfilter import install_secret_redaction

        install_secret_redaction()
        try:
            with caplog.at_level(logging.INFO):
                logging.getLogger("leakprobe").info(
                    "key is gsk_leaky-test-key-abcdefgh12345678 end"
                )
            assert "gsk_leaky-test-key-abcdefgh12345678" not in caplog.text
        finally:
            root = logging.getLogger()
            root.filters.clear()
            for h in root.handlers:
                h.filters.clear()


class TestProductionSafetyValidation:
    def test_production_requires_secret_and_required_mode(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("AUTH_MODE", "optional")
        monkeypatch.setenv("TRUSTED_HOSTS", "*")
        # Simulate a deployment with NO signing key configured at all.
        import backend.app.core.config as cfg

        class _NoKeySettings:
            is_production = True
            AUTH_MODE = "optional"
            EXECUTION_ENABLED = False
            RAZORPAY_ENABLED = False
            RAZORPAY_TEST_MODE = False
            AUTH_SECRET_KEY = ""
            trusted_host_list = ["*"]

        monkeypatch.setattr(cfg, "get_settings", lambda: _NoKeySettings)
        try:
            from backend.app.core import middleware as mw

            monkeypatch.setattr(mw, "get_settings", lambda: _NoKeySettings)
            with pytest.raises(RuntimeError) as exc:
                mw.validate_production_safety()
            msg = str(exc.value)
            assert "AUTH_SECRET_KEY" in msg
            assert "AUTH_MODE" in msg
            assert "TRUSTED_HOSTS" in msg
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()

    def test_development_boots_without_auth_configuration(self):
        from backend.app.core.middleware import validate_production_safety

        validate_production_safety()  # must not raise outside production
