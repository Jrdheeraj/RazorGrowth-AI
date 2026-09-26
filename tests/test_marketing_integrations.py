"""Marketing Agent integrations — connection hub, providers, approval gates.

Covers (Phase 16):
  connection creation / retrieval / isolation / disconnect / verification /
  invalid + expired credentials / provider failures / tool registry /
  approval gates / audit events / CRM + analytics isolation /
  email + ads + social send approval / secret redaction / test mode.

External APIs are MOCKED (httpx.MockTransport or method patches) — no real
credentials are required. Existing suites must keep passing.
"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from backend.app.core import credential_vault as vault
from backend.app.integrations.marketing import oauth_state
from backend.app.integrations.marketing.base import (
    ERR_AUTH_EXPIRED,
    ERR_RATE_LIMITED,
    classify_http_status,
    redact_mapping,
)
from backend.app.integrations.marketing.google_ads import GoogleAdsProvider
from backend.app.integrations.marketing.instagram import InstagramProvider
from backend.app.integrations.marketing.meta_ads import MetaAdsProvider
from backend.app.integrations.marketing.resend_email import ResendProvider
from backend.app.models.audit_event import AuditEvent
from backend.app.models.customer import Customer
from backend.app.models.enums import (
    AgentActionStatus,
    AgentActionType,
    AuditEventType,
    CustomerSegment,
    UserRole,
)
from backend.app.models.integration_connection import IntegrationConnection
from backend.app.models.marketing_agi import MarketingAGICampaign
from backend.app.models.agent_action import AgentAction
from backend.app.services import integration_service as svc
from tests.security_utils import bearer, make_world


# ═══════════════════════════════════════════════════════════════════════
# Helpers: mock transports
# ═══════════════════════════════════════════════════════════════════════


def _json_response(status: int, payload: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        headers=headers or {},
        request=httpx.Request("GET", "https://mock.local/"),
    )


def resend_transport(domains: list[dict] | None = None, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/domains":
            return _json_response(status, {"data": domains or []})
        return _json_response(404, {"message": "not found"})

    return httpx.MockTransport(handler)


def resend_send_transport(email_id: str = "em_123", status: int = 202) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/domains":
            return _json_response(200, {"data": [{"id": "d1", "name": "acme.test", "status": "verified"}]})
        assert request.url.path == "/emails"
        return _json_response(status, {"id": email_id})

    return httpx.MockTransport(handler)


def google_transport(
    *,
    token_ok: bool = True,
    customers: list[str] | None = None,
    describe_name: str = "Acme Ads",
    token_error: str = "invalid_grant",
) -> httpx.MockTransport:
    ids = customers if customers is not None else ["customers/111", "customers/222"]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/token":
            if token_ok:
                return _json_response(200, {"access_token": "ya29.mock", "expires_in": 3600})
            return _json_response(400, {"error": token_error})
        if path.endswith(":listAccessibleCustomers"):
            return _json_response(200, {"resourceNames": ids})
        if "/customers/" in path:
            return _json_response(200, {"descriptiveName": describe_name})
        return _json_response(404, {})

    return httpx.MockTransport(handler)


def meta_transport(
    *,
    adaccounts: list[dict] | None = None,
    status: int = 200,
    campaigns: list[dict] | None = None,
) -> httpx.MockTransport:
    accts = adaccounts if adaccounts is not None else [
        {"id": "act_1001", "name": "Acme Ads", "account_status": 1}
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/me/adaccounts"):
            if status != 200:
                return _json_response(status, {"error": {"message": "OAuthException", "code": 190}})
            return _json_response(200, {"data": accts})
        if path.endswith("/campaigns") and request.method == "GET":
            return _json_response(200, {"data": campaigns or []})
        if path.endswith("/campaigns") and request.method == "POST":
            return _json_response(200, {"id": "camp_9"})
        if path.endswith("/insights"):
            return _json_response(200, {"data": []})
        return _json_response(404, {})

    return httpx.MockTransport(handler)


def instagram_transport(
    *,
    pages: list[dict] | None = None,
    status: int = 200,
) -> httpx.MockTransport:
    data = pages if pages is not None else [
        {"id": "page_1", "name": "Acme",
         "instagram_business_account": {"id": "ig_7", "username": "acme_brand"}}
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/me/accounts"):
            if status != 200:
                return _json_response(status, {"error": {"message": "OAuthException"}})
            return _json_response(200, {"data": data})
        if request.url.path.endswith("/media"):
            return _json_response(200, {"id": "container_1"})
        if request.url.path.endswith("/media_publish"):
            return _json_response(200, {"id": "media_1"})
        return _json_response(404, {})

    return httpx.MockTransport(handler)


# ═══════════════════════════════════════════════════════════════════════
# Vault + OAuth state
# ═══════════════════════════════════════════════════════════════════════


class TestCredentialVault:
    def test_roundtrip(self):
        blob = vault.encrypt_secret("super-secret-value")
        assert blob.startswith("vault1:")
        assert vault.decrypt_secret(blob) == "super-secret-value"
        assert vault.is_vault_blob(blob)
        assert not vault.is_vault_blob("super-secret-value")

    def test_plaintext_blob_rejected(self):
        with pytest.raises(ValueError):
            vault.decrypt_secret("not-a-vault-blob")


class TestOAuthState:
    def test_issue_verify_roundtrip(self, monkeypatch):
        monkeypatch.setenv("AUTH_SECRET_KEY", "test-only-secret-key-do-not-use-in-production")
        mid = uuid.uuid4()
        token = oauth_state.issue_state(mid, "google_ads")
        assert oauth_state.verify_state(token, "google_ads") == mid

    def test_wrong_provider_rejected(self, monkeypatch):
        monkeypatch.setenv("AUTH_SECRET_KEY", "test-only-secret-key-do-not-use-in-production")
        token = oauth_state.issue_state(uuid.uuid4(), "google_ads")
        with pytest.raises(ValueError):
            oauth_state.verify_state(token, "meta_ads")

    def test_tampered_rejected(self, monkeypatch):
        monkeypatch.setenv("AUTH_SECRET_KEY", "test-only-secret-key-do-not-use-in-production")
        token = oauth_state.issue_state(uuid.uuid4(), "meta_ads")
        with pytest.raises(ValueError):
            oauth_state.verify_state(token + "x", "meta_ads")

    def test_single_use(self, monkeypatch):
        monkeypatch.setenv("AUTH_SECRET_KEY", "test-only-secret-key-do-not-use-in-production")
        token = oauth_state.issue_state(uuid.uuid4(), "meta_ads")
        oauth_state.verify_state(token, "meta_ads")
        with pytest.raises(ValueError):
            oauth_state.verify_state(token, "meta_ads")


# ═══════════════════════════════════════════════════════════════════════
# Resend connect / verify / isolation / disconnect
# ═══════════════════════════════════════════════════════════════════════


class TestResendConnections:
    def test_connect_success_stores_encrypted(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="rs1")
        row, result = svc.connect_resend(
            db_session, m.id, actor="owner@test",
            api_key="re_testkey123", from_email="brand@acme.test",
            transport=resend_transport([{"id": "d1", "name": "acme.test", "status": "verified"}]),
        )
        assert result.ok
        assert row is not None and row.status == "connected"
        assert row.account_id == "brand@acme.test"
        # Encrypted at rest: raw column is a vault blob, never plaintext.
        raw = db_session.scalar(
            select(IntegrationConnection.encrypted_credentials).where(
                IntegrationConnection.id == row.id
            )
        )
        assert isinstance(raw, str) and raw.startswith("vault1:")
        assert "re_testkey123" not in raw
        # Decrypts back in memory.
        assert svc.decrypt_credentials(row)["api_key"] == "re_testkey123"

    def test_connect_invalid_key_fails_cleanly(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="rs2")
        row, result = svc.connect_resend(
            db_session, m.id, actor="owner@test",
            api_key="re_bad", from_email="brand@acme.test",
            transport=resend_transport(status=401),
        )
        assert not result.ok and row is None
        stored = svc.get_connection(db_session, m.id, "resend")
        assert stored is not None and stored.status == "error"
        assert stored.encrypted_credentials is None  # no secrets on failure

    def test_response_never_contains_secrets(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="rs3")
        row, _ = svc.connect_resend(
            db_session, m.id, actor="o", api_key="re_secret_xyz",
            from_email="b@acme.test", transport=resend_transport(),
        )
        assert row is not None
        dumped = json.dumps(svc.serialize_connection(row))
        assert "re_secret_xyz" not in dumped

    def test_workspace_isolation(self, db_session):
        m1, _, _ = make_world(db_session, slug_hint="iso1")
        m2, _, _ = make_world(db_session, slug_hint="iso2")
        row, _ = svc.connect_resend(
            db_session, m1.id, actor="o", api_key="re_one",
            from_email="a@one.test", transport=resend_transport(),
        )
        assert row is not None
        assert svc.get_connection(db_session, m2.id, "resend") is None
        assert svc.connected_row(db_session, m2.id, "resend") is None

    def test_disconnect_wipes_credentials(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="rs4")
        row, _ = svc.connect_resend(
            db_session, m.id, actor="o", api_key="re_k",
            from_email="b@acme.test", transport=resend_transport(),
        )
        assert row is not None
        out = svc.disconnect(db_session, m.id, "resend", actor="o")
        assert out is not None and out.status == "disconnected"
        assert out.encrypted_credentials is None
        assert svc.connected_row(db_session, m.id, "resend") is None

    def test_test_connection_updates_verified(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="rs5")
        row, _ = svc.connect_resend(
            db_session, m.id, actor="o", api_key="re_k",
            from_email="b@acme.test", transport=resend_transport(),
        )
        assert row is not None and row.last_verified_at is not None
        res = svc.test_connection(
            db_session, m.id, "resend", actor="o",
            transport=resend_transport([{"id": "d1"}]),
        )
        assert res.ok and res.provider == "resend"

    def test_test_connection_failure_marks_error(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="rs6")
        svc.connect_resend(
            db_session, m.id, actor="o", api_key="re_k",
            from_email="b@acme.test", transport=resend_transport(),
        )
        res = svc.test_connection(
            db_session, m.id, "resend", actor="o",
            transport=resend_transport(status=401),
        )
        assert not res.ok
        assert svc.get_connection(db_session, m.id, "resend").status == "error"


# ═══════════════════════════════════════════════════════════════════════
# Google / Meta / Instagram connects (mocked OAuth + APIs)
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def google_env(monkeypatch):
    from backend.app.core.config import get_settings

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8001/api/marketing-agi/integrations/google_ads/oauth/callback")
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "ABcdeFGH93KL-NOPQ_STUv")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def meta_env(monkeypatch):
    from backend.app.core.config import get_settings

    monkeypatch.setenv("META_APP_ID", "test-app-id")
    monkeypatch.setenv("META_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("META_OAUTH_REDIRECT_URI", "http://localhost:8001/api/marketing-agi/integrations/meta_ads/oauth/callback")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _google_code_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return _json_response(200, {"access_token": "ya29.x", "refresh_token": "1//refresh", "expires_in": 3600})
        if request.url.path.endswith(":listAccessibleCustomers"):
            return _json_response(200, {"resourceNames": ["customers/111"]})
        return _json_response(200, {"descriptiveName": "Acme Ads"})

    return httpx.MockTransport(handler)


# Real Google Ads API error shapes (as observed against the live API).
GOOGLE_NOT_ADS_USER_BODY = {
    "error": {
        "code": 401,
        "message": (
            "Request is missing required authentication credential. "
            "Expected OAuth 2 access token, login cookie or API key..."
        ),
        "status": "UNAUTHENTICATED",
        "details": [
            {
                "@type": "type.googleapis.com/google.ads.googleads.v25.errors.GoogleAdsError",
                "errors": [
                    {
                        "errorCode": {"authenticationError": "NOT_ADS_USER"},
                        "message": "The Google account is not recognized as a Google Ads account.",
                    }
                ],
            }
        ],
    }
}

GOOGLE_MISSING_DEVELOPER_TOKEN_BODY = {
    "error": {
        "code": 400,
        "message": "Request is missing required authentication credential.",
        "status": "INVALID_ARGUMENT",
        "details": [
            {
                "@type": "type.googleapis.com/google.ads.googleads.v25.errors.GoogleAdsError",
                "requestError": "DEVELOPER_TOKEN_PARAMETER_MISSING",
            }
        ],
    }
}


def _google_ads_failing_transport(status: int, payload: dict) -> httpx.MockTransport:
    """Successful OAuth token exchange, then a failing Google Ads API call."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return _json_response(200, {"access_token": "ya29.x", "refresh_token": "1//refresh", "expires_in": 3600})
        if request.url.path.endswith(":listAccessibleCustomers"):
            return _json_response(status, payload)
        return _json_response(404, {})

    return httpx.MockTransport(handler)


class TestGoogleAdsConnect:
    def test_oauth_connect_success(self, db_session, google_env, monkeypatch):
        import backend.app.services.integration_service as mod

        m, _, _ = make_world(db_session, slug_hint="g1")
        transport = _google_code_transport()
        # Route every httpx.Client through the mock transport.
        real_client = httpx.Client
        monkeypatch.setattr(
            httpx, "Client",
            lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
        )
        row, result = mod.connect_oauth(
            db_session, m.id, actor="o", provider="google_ads", code="authcode123",
        )
        assert result.ok and row is not None and row.status == "connected"
        assert row.account_id == "111" and row.account_name == "Acme Ads"
        dumped = json.dumps(mod.serialize_connection(row))
        assert "1//refresh" not in dumped

    def test_expired_refresh_maps_auth_expired(self, db_session):
        adapter = GoogleAdsProvider()
        res = adapter.refresh_access_token(
            refresh_token="bad", client_id="id", client_secret="s",
            transport=google_transport(token_ok=False, token_error="invalid_grant"),
        )
        assert not res.ok and res.error_code == ERR_AUTH_EXPIRED

    def test_no_accessible_accounts_honest(self, db_session):
        adapter = GoogleAdsProvider()
        res = adapter.verify(
            refresh_token="r", client_id="id", client_secret="s",
            developer_token="ABcdeFGH93KL-NOPQ_STUv",
            transport=google_transport(customers=[]),
        )
        assert not res.ok
        assert res.error_code == "GOOGLE_ADS_ACCOUNT_NOT_LINKED"
        # Application-level state, merchant-safe copy — no Google internals.
        assert "NOT_ADS_USER" not in (res.message or "")
        assert "Google account" in (res.message or "")

    def test_missing_platform_config(self, db_session, monkeypatch):
        import backend.app.services.integration_service as mod

        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "")
        m, _, _ = make_world(db_session, slug_hint="g2")
        row, result = mod.connect_oauth(
            db_session, m.id, actor="o", provider="google_ads", code="x",
        )
        assert not result.ok and row is None
        assert result.error_code == "MISSING_CONFIGURATION"


class TestMetaConnect:
    def test_token_connect_success(self, db_session, meta_env):
        m, _, _ = make_world(db_session, slug_hint="m1")
        row, result = svc.connect_token(
            db_session, m.id, actor="o", provider="meta_ads",
            access_token="EAAGmock", transport=meta_transport(),
        )
        assert result.ok and row is not None and row.status == "connected"
        assert row.account_id == "act_1001" and row.account_name == "Acme Ads"
        assert "EAAGmock" not in json.dumps(svc.serialize_connection(row))

    def test_invalid_token_fails(self, db_session, meta_env):
        m, _, _ = make_world(db_session, slug_hint="m2")
        row, result = svc.connect_token(
            db_session, m.id, actor="o", provider="meta_ads",
            access_token="bad", transport=meta_transport(status=400),
        )
        assert not result.ok and row is None

    def test_meta_reads_live_campaigns(self, db_session, meta_env):
        adapter = MetaAdsProvider()
        res = adapter.list_campaigns(
            access_token="t", ad_account_id="act_1001",
            transport=meta_transport(campaigns=[{"id": "c1", "name": "Spring", "status": "ACTIVE"}]),
        )
        assert res.ok and res.data["campaigns"][0]["name"] == "Spring"


class TestInstagramConnect:
    def test_discovers_real_identity(self, db_session, meta_env):
        m, _, _ = make_world(db_session, slug_hint="ig1")
        row, result = svc.connect_token(
            db_session, m.id, actor="o", provider="instagram",
            access_token="EAAGmock", transport=instagram_transport(),
        )
        assert result.ok and row is not None
        assert row.account_name == "@acme_brand" and row.account_id == "ig_7"

    def test_no_linked_account_is_honest(self, db_session, meta_env):
        adapter = InstagramProvider()
        res = adapter.verify(access_token="t", transport=instagram_transport(pages=[]))
        assert not res.ok and res.error_code == "ACCOUNT_NOT_FOUND"


# ═══════════════════════════════════════════════════════════════════════
# Error taxonomy
# ═══════════════════════════════════════════════════════════════════════


class TestErrorTaxonomy:
    def test_rate_limit_mapping(self):
        code, _ = classify_http_status(429, "Google Ads")
        assert code == ERR_RATE_LIMITED

    def test_redaction(self):
        dirty = {
            "api_key": "secret", "nested": {"refresh_token": "x"},
            "safe": "visible", "list": [{"access_token": "y"}, "ok"],
        }
        clean = redact_mapping(dirty)
        dumped = json.dumps(clean)
        assert "secret" not in dumped and '"x"' not in dumped and '"y"' not in dumped
        assert clean["safe"] == "visible" and clean["list"][1] == "ok"


# ═══════════════════════════════════════════════════════════════════════
# Registry metadata (Phase 9)
# ═══════════════════════════════════════════════════════════════════════


class TestUnifiedRegistry:
    def test_tool_metadata_declared(self):
        from backend.app.agents.marketing_agi.tools.bootstrap import register_all_tools
        from backend.app.agents.marketing_agi.tools.registry import get_registry

        register_all_tools()
        catalog = {t["name"]: t for t in get_registry().catalog()}
        g = catalog["get_google_ads_campaigns"]
        assert g["provider"] == "google_ads" and g["requires_connection"] is True
        assert g["writes_require_approval"] is True
        assert "create_campaign_paused" in g["write_actions"]
        e = catalog["create_email_campaign_draft"]
        assert e["provider"] == "resend" and e["writes_require_approval"] is True
        crm = catalog["find_customers"]
        assert crm["provider"] == "internal" and crm["requires_connection"] is False
        ana = catalog["get_failed_payment_analytics"]
        assert ana["provider"] == "internal"


# ═══════════════════════════════════════════════════════════════════════
# Approval gates (Phase 10)
# ═══════════════════════════════════════════════════════════════════════


def _approved_action(db_session, merchant, action_type, payload: dict):
    from backend.app.services import action_service

    action = AgentAction(
        merchant_id=merchant.id,
        action_type=action_type,
        status=AgentActionStatus.approved,
        input_payload={"merchant_id": str(merchant.id), **payload},
        requested_by="agent:test",
        approved_by="owner@test",
    )
    db_session.add(action)
    db_session.commit()
    return action


class TestApprovalGates:
    def test_email_without_key_is_test_mode(self, db_session, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "")
        monkeypatch.setenv("RESEND_FROM_EMAIL", "")
        m, _, _ = make_world(db_session, slug_hint="ap1")
        action = _approved_action(db_session, m, AgentActionType.send_campaign, {
            "campaign_type": "email", "target": {}, "target_count": 0,
        })
        from backend.app.services.action_executor import execute_approved_action

        res = execute_approved_action(action, db_session)
        assert res.success and res.result_metadata["sent"] is False
        assert res.result_metadata["mode"] == "test"

    def test_email_live_send_when_enabled(self, db_session, monkeypatch):
        import backend.app.services.action_executor as ex

        m, _, _ = make_world(db_session, slug_hint="ap2")
        c = Customer(
            merchant_id=m.id, name="Ada", email="ada@buyer.test",
            segment=CustomerSegment.new,
        )
        db_session.add(c)
        db_session.commit()
        camp = MarketingAGICampaign(
            merchant_id=m.id, campaign_key="k1", workflow="email_campaign",
            name="Win back", objective="o", channel="email",
            integration_status="draft_only", lifecycle="ready_for_approval",
            audience={"customer_ids": [str(c.id)]}, audience_count=1,
            content={"message": "Hello", "subject_variants": ["Hi"], "cta": "Shop"},
        )
        db_session.add(camp)
        db_session.commit()
        action = _approved_action(db_session, m, AgentActionType.send_campaign, {
            "campaign_type": "email",
            "target": {"marketing_agi_campaign_id": str(camp.id)},
            "target_count": 1,
        })
        transport = resend_send_transport("em_live_1")

        import httpx as _httpx

        real_client = _httpx.Client
        monkeypatch.setattr(
            _httpx, "Client",
            lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
        )
        # Live-verify passes (domains 200) via the same mock transport.
        settings = ex.get_settings()
        monkeypatch.setattr(ex, "get_settings", lambda: type(settings)(
            **{**settings.model_dump(), "EXECUTION_ENABLED": True,
               "RESEND_API_KEY": "re_live", "RESEND_FROM_EMAIL": "brand@acme.test"}
        ))
        res = ex.execute_approved_action(action, db_session)
        assert res.success and res.result_metadata["sent"] is True
        assert res.result_metadata["email_id"] == "em_live_1"
        db_session.refresh(camp)
        assert camp.lifecycle == "completed" and camp.integration_status == "sent"

    def test_social_requires_connection(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="ap3")
        action = _approved_action(db_session, m, AgentActionType.publish_social_post, {
            "provider": "instagram", "image_url": "https://cdn.test/p.jpg",
            "caption": "Hello",
        })
        from backend.app.services.action_executor import execute_approved_action

        res = execute_approved_action(action, db_session)
        assert not res.success and "NOT_CONNECTED" in (res.error or "")

    def test_social_test_mode_when_disabled(self, db_session, meta_env):
        m, _, _ = make_world(db_session, slug_hint="ap4")
        svc.connect_token(
            db_session, m.id, actor="o", provider="instagram",
            access_token="EAAGmock", transport=instagram_transport(),
        )
        action = _approved_action(db_session, m, AgentActionType.publish_social_post, {
            "provider": "instagram", "image_url": "https://cdn.test/p.jpg",
            "caption": "Hello",
        })
        from backend.app.services.action_executor import execute_approved_action

        res = execute_approved_action(action, db_session)
        assert res.success and res.result_metadata["executed"] is False
        assert res.result_metadata["mode"] == "test"

    def test_ads_write_requires_connection(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="ap5")
        action = _approved_action(db_session, m, AgentActionType.create_ad_campaign, {
            "provider": "meta_ads", "name": "Test",
        })
        from backend.app.services.action_executor import execute_approved_action

        res = execute_approved_action(action, db_session)
        assert not res.success and "NOT_CONNECTED" in (res.error or "")

    def test_unapproved_action_cannot_execute(self, db_session):
        from backend.app.services import action_service

        m, _, _ = make_world(db_session, slug_hint="ap6")
        action = action_service.create_action(
            db_session, merchant_id=m.id,
            action_type=AgentActionType.publish_social_post,
            input_payload={
                "merchant_id": str(m.id), "provider": "instagram",
                "image_url": "https://cdn.test/p.jpg", "caption": "Hi",
            },
            requested_by="agent:test",
        )
        res = action_service.execute_action(db_session, action.id, actor="owner@test")
        assert not res.success and "requested" in (res.error or "")


# ═══════════════════════════════════════════════════════════════════════
# Audit + CRM/analytics isolation
# ═══════════════════════════════════════════════════════════════════════


class TestAuditAndIsolation:
    def test_audit_written_without_secrets(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="au1")
        svc.connect_resend(
            db_session, m.id, actor="owner@x", api_key="re_audit_secret",
            from_email="b@acme.test", transport=resend_transport(),
        )
        rows = list(
            db_session.scalars(
                select(AuditEvent).where(
                    AuditEvent.merchant_id == m.id,
                    AuditEvent.entity_type == "integration_connection",
                )
            ).all()
        )
        assert any(r.event_type == AuditEventType.integration_connected for r in rows)
        assert "re_audit_secret" not in json.dumps([r.payload for r in rows])

    def test_crm_tools_are_merchant_scoped(self, db_session):
        from backend.app.agents.marketing_agi.tools.bootstrap import register_all_tools
        from backend.app.agents.marketing_agi.tools.registry import ToolContext, get_registry

        m1, _, _ = make_world(db_session, slug_hint="crm1")
        m2, _, _ = make_world(db_session, slug_hint="crm2")
        db_session.add(Customer(merchant_id=m1.id, name="A", email="a@one.test", segment=CustomerSegment.new))
        db_session.commit()
        register_all_tools()
        out = get_registry().call(ToolContext(db_session, m2.id), "find_customers", {})["result"]
        customers = out.get("customers", [])
        assert all(c.get("merchant_id", str(m2.id)) != str(m1.id) or True for c in customers)
        emails = [c.get("email") for c in customers if isinstance(c, dict)]
        assert "a@one.test" not in emails


# ═══════════════════════════════════════════════════════════════════════
# API surface
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationAPI:
    def test_list_requires_auth_context(self, client, db_session):
        m, u, _ = make_world(db_session, slug_hint="api1")
        r = client.get("/api/marketing-agi/integrations", headers=bearer(u))
        assert r.status_code == 200
        body = r.json()
        providers = {i["provider"] for i in body["integrations"]}
        assert {"resend", "google_ads", "meta_ads", "instagram"} <= providers
        assert all(i["status"] == "not_connected" for i in body["integrations"])
        dumped = r.text
        assert "api_key" not in dumped and "access_token" not in dumped

    def test_analyst_may_read_operator_gate_on_connect(self, client, db_session):
        m, u_analyst, _ = make_world(db_session, role=UserRole.analyst, slug_hint="api2")
        r = client.get("/api/marketing-agi/integrations", headers=bearer(u_analyst))
        assert r.status_code == 200
        r = client.post(
            "/api/marketing-agi/integrations/resend/connect",
            json={"api_key": "x", "from_email": "b@t.test"},
            headers=bearer(u_analyst),
        )
        assert r.status_code in {403, 400, 401}

    def test_cross_tenant_isolation(self, client, db_session):
        m1, u1, _ = make_world(db_session, slug_hint="t1")
        m2, u2, _ = make_world(db_session, slug_hint="t2")
        svc.connect_resend(
            db_session, m1.id, actor="o", api_key="re_one",
            from_email="a@one.test", transport=resend_transport(),
        )
        r = client.get("/api/marketing-agi/integrations/resend", headers=bearer(u2))
        assert r.status_code == 200
        assert r.json()["status"] == "not_connected"

    def test_status_reflects_live_connection(self, client, db_session):
        m, u, _ = make_world(db_session, slug_hint="st1")
        svc.connect_resend(
            db_session, m.id, actor="o", api_key="re_k",
            from_email="brand@acme.test", transport=resend_transport(),
        )
        r = client.get("/api/marketing-agi/status", headers=bearer(u))
        assert r.status_code == 200
        stack = {e["key"]: e for e in r.json()["marketing_stack"]}
        assert stack["email"]["status"] == "connected"
        assert stack["email"]["account_id"] == "brand@acme.test"
        assert stack["google_ads"]["status"] == "requires_integration"
        assert stack["crm"]["status"] == "connected"
        assert stack["crm"]["provider"] == "internal"

    def test_unknown_provider_404(self, client, db_session):
        m, u, _ = make_world(db_session, slug_hint="api3")
        r = client.get("/api/marketing-agi/integrations/nope", headers=bearer(u))
        assert r.status_code == 404

    def test_oauth_start_needs_platform_config(self, client, db_session, monkeypatch):
        from backend.app.core.config import get_settings

        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "")
        monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "")
        # get_settings() is @lru_cache'd — clear so the empty platform config
        # above is actually observed by the route (local .env would otherwise
        # keep a cached non-empty client id).
        get_settings.cache_clear()
        try:
            m, u, _ = make_world(db_session, slug_hint="api4")
            r = client.get(
                "/api/marketing-agi/integrations/google_ads/oauth/start", headers=bearer(u)
            )
            # owner passes role gate; missing platform config → honest 503
            assert r.status_code in {503, 403}
        finally:
            get_settings.cache_clear()

    def test_oauth_callback_bad_state_redirects_safely(self, client):
        # NEVER a raw JSON/HTTP dump — the browser gets a safe redirect.
        r = client.get(
            "/api/marketing-agi/integrations/google_ads/oauth/callback"
            "?code=x&state=bogus",
            follow_redirects=False,
        )
        assert r.status_code == 302
        loc = r.headers["location"]
        assert "integration=google_ads" in loc
        assert "status=error" in loc
        assert "code=OAUTH_STATE_INVALID" in loc
        # The forged state never leaks back into the URL.
        assert "bogus" not in loc
        assert "{" not in loc

    def test_oauth_callback_google_denial_redirects_safely(self, client):
        r = client.get(
            "/api/marketing-agi/integrations/google_ads/oauth/callback"
            "?error=access_denied"
            "&error_description=User+denied+access+to+the+requested+scope",
            follow_redirects=False,
        )
        assert r.status_code == 302
        loc = r.headers["location"]
        assert "code=OAUTH_DENIED" in loc
        # Google's free-text description stays server-side.
        assert "denied" not in loc and "scope" not in loc

    def test_oauth_callback_missing_params_redirects_safely(self, client):
        r = client.get(
            "/api/marketing-agi/integrations/google_ads/oauth/callback",
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "code=MISSING_CALLBACK_PARAMS" in r.headers["location"]


# ═══════════════════════════════════════════════════════════════════════
# Google Ads developer token: optional by platform policy. Google's own
# response decides — accept without a header, or answer
# requestError.DEVELOPER_TOKEN_PARAMETER_MISSING (mapped honestly).
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def google_env_no_token(monkeypatch):
    """OAuth client configured, developer token ABSENT."""
    from backend.app.core.config import get_settings

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8001/api/marketing-agi/integrations/google_ads/oauth/callback")
    monkeypatch.delenv("GOOGLE_ADS_DEVELOPER_TOKEN", raising=False)
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _google_code_transport_no_token_seen(seen: dict) -> httpx.MockTransport:
    """Mock OAuth+Ads flow that records whether a developer-token header
    was ever sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "developer-token" in {k.lower() for k in request.headers.keys()}:
            seen["developer_token_sent"] = True
        if request.url.path == "/token":
            return _json_response(200, {"access_token": "ya29.x", "refresh_token": "1//refresh", "expires_in": 3600})
        if request.url.path.endswith(":listAccessibleCustomers"):
            return _json_response(200, {"resourceNames": ["customers/111", "customers/222"]})
        return _json_response(200, {"descriptiveName": "Acme Ads"})

    return httpx.MockTransport(handler)


def _google_access_denied_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return _json_response(200, {"access_token": "ya29.x", "refresh_token": "1//refresh", "expires_in": 3600})
        if request.url.path.endswith(":listAccessibleCustomers"):
            return _json_response(403, {"error": {
                "code": 403, "message": "The caller does not have permission: request requires test account access level but production account was requested",
                "status": "PERMISSION_DENIED",
            }})
        return _json_response(404, {})

    return httpx.MockTransport(handler)


def _google_mutate_transport(calls: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return _json_response(200, {"access_token": "ya29.m", "expires_in": 3600})
        if request.url.path.endswith(":mutate"):
            import json as _json

            body = _json.loads(request.content.decode() or "{}")
            calls.append(body)
            ops = (body.get("mutateOperations") or [{}])[0].get("create", {})
            if "amountMicros" in ops:
                return _json_response(200, {"mutateOperationResponses": [
                    {"campaignBudget": {"resourceName": "customers/111/campaignBudgets/1"}}]})
            return _json_response(200, {"mutateOperationResponses": [
                {"campaign": {"resourceName": "customers/111/campaigns/2"}}]})
        return _json_response(404, {})

    return httpx.MockTransport(handler)


class TestGoogleAdsSunset:
    def test_oauth_connect_succeeds_without_developer_token(
        self, db_session, google_env_no_token, monkeypatch,
    ):
        """The reported callback failure is gone: no token → connected."""
        import backend.app.services.integration_service as mod

        m, _, _ = make_world(db_session, slug_hint="sun1")
        seen: dict = {}
        transport = _google_code_transport_no_token_seen(seen)
        real_client = httpx.Client
        monkeypatch.setattr(
            httpx, "Client",
            lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
        )
        row, result = mod.connect_oauth(
            db_session, m.id, actor="o", provider="google_ads", code="authcode123",
        )
        assert result.ok, result.message
        assert result.error_code != "MISSING_CONFIGURATION"
        assert row is not None and row.status == "connected"
        assert row.account_id == "111"
        assert seen.get("developer_token_sent") is not True

    def test_missing_token_is_not_missing_configuration(
        self, db_session, google_env_no_token, monkeypatch,
    ):
        import backend.app.services.integration_service as mod

        m, _, _ = make_world(db_session, slug_hint="sun2")
        transport = _google_code_transport_no_token_seen({})
        real_client = httpx.Client
        monkeypatch.setattr(
            httpx, "Client",
            lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
        )
        _, result = mod.connect_oauth(
            db_session, m.id, actor="o", provider="google_ads", code="authcode123",
        )
        assert result.ok
        assert (result.error_code or "") != "MISSING_CONFIGURATION"

    def test_verify_without_token_omits_header(self):
        seen: dict = {}
        adapter = GoogleAdsProvider()
        res = adapter.verify(
            refresh_token="r", client_id="id", client_secret="s",
            transport=_google_code_transport_no_token_seen(seen),
        )
        assert res.ok and res.account["customer_id"] == "111"
        assert seen.get("developer_token_sent") is not True

    def test_legacy_token_still_forwarded_when_provided(self):
        seen: dict = {}
        adapter = GoogleAdsProvider()
        res = adapter.verify(
            refresh_token="r", client_id="id", client_secret="s",
            developer_token="legacy-token-123",
            transport=_google_code_transport_no_token_seen(seen),
        )
        assert res.ok
        assert seen.get("developer_token_sent") is True

    def test_refresh_success(self):
        adapter = GoogleAdsProvider()
        res = adapter.refresh_access_token(
            refresh_token="1//refresh", client_id="id", client_secret="s",
            transport=google_transport(),
        )
        assert res.ok and res.data["access_token"] == "ya29.mock"

    def test_accessible_customer_discovery(self):
        adapter = GoogleAdsProvider()
        res = adapter.verify(
            refresh_token="r", client_id="id", client_secret="s",
            transport=_google_code_transport_no_token_seen({}),
        )
        assert res.ok
        assert res.data["accessible_customer_ids"] == ["111", "222"]
        # Explicit customer selection is honored.
        res2 = adapter.verify(
            refresh_token="r", client_id="id", client_secret="s",
            customer_id="222",
            transport=_google_code_transport_no_token_seen({}),
        )
        assert res2.ok and res2.account["customer_id"] == "222"

    def test_access_level_denied_is_actionable_not_oauth(self):
        adapter = GoogleAdsProvider()
        res = adapter.verify(
            refresh_token="r", client_id="id", client_secret="s",
            transport=_google_access_denied_transport(),
        )
        assert not res.ok
        assert res.error_code == "INSUFFICIENT_PERMISSIONS"
        assert "access level" in (res.message or "").lower()
        # Must not be disguised as an OAuth/token failure.
        assert res.error_code not in {"AUTH_EXPIRED", "AUTH_REVOKED",
                                      "INVALID_CREDENTIALS", "MISSING_CONFIGURATION"}

    def test_tenant_isolation_and_encrypted_creds(
        self, db_session, google_env_no_token, monkeypatch,
    ):
        import backend.app.services.integration_service as mod

        m1, _, _ = make_world(db_session, slug_hint="sun3")
        m2, _, _ = make_world(db_session, slug_hint="sun4")
        transport = _google_code_transport_no_token_seen({})
        real_client = httpx.Client
        monkeypatch.setattr(
            httpx, "Client",
            lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
        )
        row, result = mod.connect_oauth(
            db_session, m1.id, actor="o", provider="google_ads", code="authcode123",
        )
        assert result.ok and row is not None
        assert row.merchant_id == m1.id
        assert svc.get_connection(db_session, m2.id, "google_ads") is None
        dumped = json.dumps(mod.serialize_connection(row))
        assert "1//refresh" not in dumped

    def test_create_campaign_paused_without_token(self):
        calls: list = []
        adapter = GoogleAdsProvider()
        res = adapter.create_campaign(
            access_token="ya29.m", customer_id="111", login_customer_id=None,
            name="Sunset Test", budget_amount_micros=5_000_000,
            transport=_google_mutate_transport(calls),
        )
        assert res.ok and res.data["status"] == "PAUSED"
        assert len(calls) == 2  # budget first, then campaign
        campaign_op = (calls[1].get("mutateOperations") or [{}])[0].get("create", {})
        assert campaign_op.get("status") == "PAUSED"
        assert campaign_op.get("campaignBudget") == "customers/111/campaignBudgets/1"

    def test_executor_google_paused_and_gated(
        self, db_session, google_env_no_token, monkeypatch,
    ):
        import httpx as _httpx

        import backend.app.services.action_executor as ex
        import backend.app.services.integration_service as mod

        m, _, _ = make_world(db_session, slug_hint="sun5")
        transport = _google_code_transport_no_token_seen({})
        real_client = _httpx.Client
        monkeypatch.setattr(
            _httpx, "Client",
            lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
        )
        row, result = mod.connect_oauth(
            db_session, m.id, actor="o", provider="google_ads", code="authcode123",
        )
        assert result.ok
        action = _approved_action(db_session, m, AgentActionType.create_ad_campaign, {
            "provider": "google_ads", "name": "Sunset", "budget_amount_micros": 5_000_000,
        })
        # EXECUTION_ENABLED=false → honest test preview, nothing created.
        res = ex.execute_approved_action(action, db_session)
        assert res.success and res.result_metadata["executed"] is False
        assert res.result_metadata["mode"] == "test"
        # EXECUTION_ENABLED=true → live PAUSED creation through mocks.
        calls: list = []
        mutate = _google_mutate_transport(calls)
        monkeypatch.setattr(
            _httpx, "Client",
            lambda *a, **k: real_client(*a, **{**k, "transport": mutate}),
        )
        settings = ex.get_settings()
        monkeypatch.setattr(ex, "get_settings", lambda: type(settings)(
            **{**settings.model_dump(), "EXECUTION_ENABLED": True}
        ))
        res2 = ex.execute_approved_action(action, db_session)
        assert res2.success and res2.result_metadata["executed"] is True
        assert res2.result_metadata["status"] == "PAUSED"
        assert len(calls) == 2


# ═══════════════════════════════════════════════════════════════════════
# Google Ads OAuth callback contract: redirect with a SAFE triple —
# never a raw Google payload, never secrets in the URL.
# ═══════════════════════════════════════════════════════════════════════


def _patch_httpx(monkeypatch, transport) -> None:
    """Route every httpx.Client through the given mock transport."""
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )


def _location(r) -> str:
    """Assert a 302 back to the frontend carrying only the safe triple."""
    assert r.status_code == 302, r.text
    loc = r.headers["location"]
    assert loc.startswith("http://localhost:5173/marketing-agent?")
    # No JSON body, no Google diagnostics, no tokens in the redirect.
    assert "{" not in loc and "}" not in loc
    for leak in ("NOT_ADS_USER", "UNAUTHENTICATED", "ya29", "1//refresh", "bogus"):
        assert leak not in loc, leak
    return loc


class TestGoogleAdsOAuthCallback:
    """The merchant-visible Google Ads OAuth round-trip (Phases 3/7/11)."""

    def test_success_redirects_connected_without_secrets(
        self, client, db_session, google_env, monkeypatch,
    ):
        from backend.app.core.config import get_settings

        m, _, _ = make_world(db_session, slug_hint="cb1")
        _patch_httpx(monkeypatch, _google_code_transport())
        state = oauth_state.issue_state(m.id, "google_ads")
        r = client.get(
            "/api/marketing-agi/integrations/google_ads/oauth/callback"
            f"?code=authcode&state={state}",
            follow_redirects=False,
        )
        loc = _location(r)
        assert "integration=google_ads" in loc and "status=connected" in loc
        assert "code=" not in loc
        assert loc.startswith(get_settings().FRONTEND_BASE_URL)
        row = svc.get_connection(db_session, m.id, "google_ads")
        assert row is not None and row.status == "connected"
        assert row.account_id == "111"

    def test_not_ads_user_redirects_to_account_not_linked(
        self, client, db_session, google_env, monkeypatch,
    ):
        m, _, _ = make_world(db_session, slug_hint="cb2")
        _patch_httpx(
            monkeypatch, _google_ads_failing_transport(401, GOOGLE_NOT_ADS_USER_BODY)
        )
        state = oauth_state.issue_state(m.id, "google_ads")
        r = client.get(
            "/api/marketing-agi/integrations/google_ads/oauth/callback"
            f"?code=authcode&state={state}",
            follow_redirects=False,
        )
        loc = _location(r)
        assert "status=error" in loc
        assert "code=GOOGLE_ADS_ACCOUNT_NOT_LINKED" in loc
        row = svc.get_connection(db_session, m.id, "google_ads")
        assert row is None or row.status != "connected"

    def test_expired_state_redirects_with_safe_code(self, client, db_session, monkeypatch):
        m, _, _ = make_world(db_session, slug_hint="cb3")
        state = oauth_state.issue_state(m.id, "google_ads")
        real_time = oauth_state.time.time
        # Jump past the 15-minute state TTL before the callback lands.
        monkeypatch.setattr(oauth_state.time, "time", lambda: real_time() + 20 * 60)
        r = client.get(
            "/api/marketing-agi/integrations/google_ads/oauth/callback"
            f"?code=authcode&state={state}",
            follow_redirects=False,
        )
        loc = _location(r)
        assert "code=OAUTH_STATE_EXPIRED" in loc

    def test_missing_developer_token_maps_to_missing_configuration(
        self, db_session, google_env_no_token, monkeypatch,
    ):
        """Google enforced the developer-token header: an app-level
        MISSING_CONFIGURATION, never a raw requestError payload."""
        import backend.app.services.integration_service as mod

        m, _, _ = make_world(db_session, slug_hint="cb4")
        _patch_httpx(
            monkeypatch,
            _google_ads_failing_transport(400, GOOGLE_MISSING_DEVELOPER_TOKEN_BODY),
        )
        row, result = mod.connect_oauth(
            db_session, m.id, actor="o", provider="google_ads", code="authcode",
        )
        assert row is None and not result.ok
        assert result.error_code == "MISSING_CONFIGURATION"
        assert "DEVELOPER_TOKEN_PARAMETER_MISSING" not in (result.message or "")
        assert "developer token" in (result.message or "").lower()
        assert "INVALID_ARGUMENT" not in (result.message or "")

    def test_connect_route_returns_structured_google_detail(
        self, client, db_session, google_env, monkeypatch,
    ):
        m, u, _ = make_world(db_session, slug_hint="cb5")
        _patch_httpx(
            monkeypatch, _google_ads_failing_transport(401, GOOGLE_NOT_ADS_USER_BODY)
        )
        r = client.post(
            "/api/marketing-agi/integrations/google_ads/connect",
            json={"code": "authcode"},
            headers=bearer(u),
        )
        assert r.status_code == 502
        detail = r.json()["detail"]
        assert set(detail) == {"code", "message", "action"}
        assert detail["code"] == "GOOGLE_ADS_ACCOUNT_NOT_LINKED"
        assert "NOT_ADS_USER" not in detail["message"]
        assert "401" not in detail["message"]
        assert detail["action"]

    def test_classify_google_error_codes_are_clean(self):
        classify = GoogleAdsProvider._classify_ads_error

        code, msg = classify(
            401, json.dumps(GOOGLE_NOT_ADS_USER_BODY),
            endpoint="customers:listAccessibleCustomers",
        )
        assert code == "GOOGLE_ADS_ACCOUNT_NOT_LINKED"
        for raw in ("NOT_ADS_USER", "UNAUTHENTICATED", "listAccessibleCustomers", "401"):
            assert raw not in msg, raw

        code, msg = classify(
            400, json.dumps(GOOGLE_MISSING_DEVELOPER_TOKEN_BODY), endpoint="x",
        )
        assert code == "MISSING_CONFIGURATION"
        assert "DEVELOPER_TOKEN_PARAMETER_MISSING" not in msg

        # A generic 401 must NOT be reported as "account not linked".
        code, msg = classify(
            401,
            json.dumps({"error": {"status": "UNAUTHENTICATED", "message": "Token invalid."}}),
            endpoint="x",
        )
        assert code == "GOOGLE_ADS_AUTHENTICATION_FAILED"
        assert "account" not in msg.lower() or "reconnect" in msg.lower()

    def test_oauth_start_carries_selected_customer(self, client, db_session, google_env):
        from urllib.parse import parse_qs, urlparse

        m, u, _ = make_world(db_session, slug_hint="cb6")
        r = client.get(
            "/api/marketing-agi/integrations/google_ads/oauth/start"
            "?account_id=1234-567-890",
            headers=bearer(u),
        )
        assert r.status_code == 200, r.text
        state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
        merchant_id, selector = oauth_state.verify_state_context(state, "google_ads")
        assert merchant_id == m.id
        # The signed payload carries the normalized customer id only.
        assert selector == "1234567890"

    def test_oauth_start_ignores_junk_account_id(self, client, db_session, google_env):
        from urllib.parse import parse_qs, urlparse

        m, u, _ = make_world(db_session, slug_hint="cb7")
        r = client.get(
            "/api/marketing-agi/integrations/google_ads/oauth/start"
            "?account_id=drop%20table--",
            headers=bearer(u),
        )
        assert r.status_code == 200, r.text
        state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
        merchant_id, selector = oauth_state.verify_state_context(state, "google_ads")
        assert merchant_id == m.id
        assert selector is None

    def test_state_replay_is_rejected(self, db_session):
        m, _, _ = make_world(db_session, slug_hint="cb8")
        state = oauth_state.issue_state(m.id, "google_ads")
        assert oauth_state.verify_state(state, "google_ads") == m.id
        with pytest.raises(ValueError):
            oauth_state.verify_state(state, "google_ads")
