"""Path A and Path B image generation, proven independently.

The Designer Agent can produce real images two different ways, and conflating
them is the failure this file exists to prevent:

  PATH A (LLM-assisted)
      Submit a design request -> the configured Cloudflare Workers AI LLM
      generates and validates a creative brief -> the brief is handed to
      Cloudflare FLUX -> the image is persisted and displayed. If the LLM
      fails, NO brief is
      reported, NO image is requested, and the direct-description fallback is
      offered.

  PATH B (direct)
      Enter an image description with no design project, no brief and no LLM
      call at all -> Cloudflare FLUX -> persisted through the same
      authentication, ownership and versioning rules. This is explicitly NOT
      a completed Designer Agent research run and is never labelled as one.

WHAT IS MOCKED
--------------
Every provider interaction is mocked. The ``flux`` fixture replaces the
``httpx`` module *inside* ``backend.app.integrations.cloudflare_image`` only,
so requests are captured without touching the network or spending quota. The
``llm_tripwire`` fixture makes ANY attempt to reach the LLM fail loudly, so
"Path B never calls the LLM provider" is an enforced fact rather than a
claim — if an LLM call were ever added, these tests would fail instead of
quietly passing.
"""
from __future__ import annotations

import base64
import json
import struct
import types
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext
from backend.app.agents.registry import AGENT_INSTANCES
from backend.app.core.config import get_settings
from backend.app.integrations import cloudflare_image
from backend.app.integrations.cloudflare_image import MODEL
from backend.app.models.designer import (
    CreativeBrief,
    DesignAsset,
    DesignAssetVersion,
)
from backend.app.models.enums import (
    Currency,
    DesignAssetKind,
    DesignReviewStatus,
    MerchantStatus,
)
from backend.app.models.merchant import Merchant
from backend.app.models.rendered_asset import RenderedAsset
from backend.app.schemas.designer import CreativeBriefSpec
from backend.app.services.designer_service import DesignerService

FLUX_URL_TAIL = "ai/run/@cf/black-forest-labs/flux-1-schnell"

#: Hosts that mean "an LLM call happened". Asserted empty in Path B.
# Hosts that could serve a TEXT LLM call. Cloudflare serves BOTH the text LLM
# (/ai/v1/chat/completions) and FLUX image generation (/ai/run/<model>) from
# api.cloudflare.com, so a host set alone can no longer separate them — the
# Path B assertions match on the LLM URL *path* instead. Kept here as the
# coarse allow-list for "is this plausibly an LLM host at all".
LLM_HOSTS = {"api.cloudflare.com", "openrouter.ai", "api.openai.com"}


# ── helpers ─────────────────────────────────────────────────────────────


def jpeg(width: int = 64, height: int = 48) -> bytes:
    """A structurally valid JPEG skeleton for the bounded parser under test."""
    out = bytearray(b"\xff\xd8")
    body = bytes([8]) + struct.pack(">HH", height, width) + bytes([1])
    body += bytes([1, 0x11, 0])
    out += b"\xff\xc0" + struct.pack(">H", len(body) + 2) + body
    sos = bytes([1, 1, 0x00, 0, 63, 0])
    out += b"\xff\xda" + struct.pack(">H", len(sos) + 2) + sos
    out += b"\x00" * 8 + b"\xff\xd9"
    return bytes(out)


def make_merchant(db_session: Session, tag: str) -> Merchant:
    m = Merchant(
        name=f"{tag} {uuid.uuid4().hex[:6]}",
        slug=f"{tag}-{uuid.uuid4().hex[:10]}",
        email=f"{tag}-{uuid.uuid4().hex[:6]}@example.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(m)
    db_session.commit()
    return m


def grounded_spec() -> CreativeBriefSpec:
    return CreativeBriefSpec(
        title="Summer refresh",
        objective="One coherent visual system for the seasonal campaign",
        project_type="campaign_creative",
        layout_direction="Hero-led single column",
        evidence=[{"statement": "12 failed payments", "basis": "observed"}],
    )


class BriefLLM:
    """A working Cloudflare stand-in: returns a valid, grounded brief."""

    provider = "cloudflare"
    model = "@cf/zai-org/glm-4.7-flash"

    def __init__(self) -> None:
        self.calls = 0

    def generate_structured(
        self, system, user, schema, *, temperature=0.0, max_tokens=2048
    ):
        self.calls += 1
        if schema is not CreativeBriefSpec:
            return schema.model_validate({"findings": []})
        return schema.model_validate(
            {
                "title": "Summer campaign refresh",
                "objective": "Give the seasonal campaign one coherent visual system",
                "project_type": "campaign_creative",
                "layout_direction": "Hero-led single column",
                "variants": [
                    {
                        "variant_key": "control",
                        "title": "Editorial",
                        "objective": "Baseline",
                        "rationale": "Current direction",
                        "evaluation_method": "A/B test",
                        "evidence_refs": [0],
                    }
                ],
                "evidence": [
                    {
                        "statement": "12 failed payment events in the window",
                        "basis": "observed",
                        "source": "growth_radar",
                        "value": 12,
                    }
                ],
                "confidence": 0.7,
            }
        )


class RateLimitedLLM:
    """A Cloudflare stand-in that reproduces the reported production failure.

    Carries a ``category`` exactly like the real provider so the agent's
    failure classification is exercised for real.
    """

    provider = "cloudflare"
    model = "@cf/zai-org/glm-4.7-flash"
    category = "rate_limit"

    def __init__(self) -> None:
        self.calls = 0

    def generate_structured(
        self, system, user, schema, *, temperature=0.0, max_tokens=2048
    ):
        self.calls += 1
        raise RuntimeError("RateLimitError: 429 from provider")


# ── fixtures ────────────────────────────────────────────────────────────


class _Flux:
    """Captures every request the real generator would have sent."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responder = None

    # -- introspection helpers --
    @property
    def hosts(self) -> set[str]:
        return {r.url.host for r in self.requests}

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]

    def only_request(self) -> httpx.Request:
        assert len(self.requests) == 1, (
            f"expected exactly one provider request, got {self.urls}"
        )
        return self.requests[0]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.responder is None:
            return self._ok()
        return self.responder(request)

    def _ok(self, image: bytes | None = None) -> httpx.Response:
        payload = {
            "result": {"image": base64.b64encode(image or jpeg()).decode("ascii")},
            "success": True,
            "errors": [],
            "messages": [],
        }
        return httpx.Response(200, json=payload)

    def respond_error(self, status: int = 500) -> None:
        self.responder = lambda _r: httpx.Response(status, json={"success": False})


@pytest.fixture()
def flux(monkeypatch) -> _Flux:
    """Mock only the image provider's HTTP client.

    The shim is bound into ``cloudflare_image``'s own module namespace, so the
    LLM provider, the FastAPI test client and the database are untouched.
    """
    recorder = _Flux()
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(*args, transport=httpx.MockTransport(recorder._handle), **kwargs)

    shim = types.SimpleNamespace(Client=factory)
    for name in ("Response", "TimeoutException", "HTTPError"):
        setattr(shim, name, getattr(httpx, name))
    monkeypatch.setattr(cloudflare_image, "httpx", shim)
    return recorder


@pytest.fixture()
def llm_tripwire(monkeypatch):
    """Make every route to an LLM provider explode if it is ever taken.

    Two independent tripwires:

      1. ``resolve_llm_provider`` — the single resolver every LLM entry point
         must go through.
      2. ``openai.OpenAI`` — the client Cloudflare is reached through. Catching this
         too means an LLM call cannot slip past via a direct construction.

    A Path B test that passed while either fired would be worthless, so the
    tripwire records and raises rather than silently tolerating.
    """
    hits: list[str] = []

    def refuse(name):
        def _boom(*a, **k):
            hits.append(name)
            raise AssertionError(
                f"Path B must not touch the LLM provider, but {name} was called"
            )

        return _boom

    from backend.app.ai.llm import provider as llm_provider

    monkeypatch.setattr(llm_provider, "resolve_llm_provider", refuse("resolve_llm_provider"))

    try:
        import openai
    except ImportError:  # pragma: no cover - openai is a declared dependency
        openai = None
    if openai is not None:
        monkeypatch.setattr(openai, "OpenAI", refuse("openai.OpenAI"))

    yield hits


@pytest.fixture()
def enabled(monkeypatch):
    """Real-looking Cloudflare credentials, image generation ON."""
    monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-path-test")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok-path-test-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def seed_radar_observation(db_session: Session, merchant: Merchant) -> None:
    """Give the agent the grounded observations it refuses to work without."""
    from backend.app.models.enums import SignalStatus
    from backend.app.models.growth_signal import GrowthSignal

    db_session.add(
        GrowthSignal(
            merchant_id=merchant.id,
            signal_key=f"sig-{uuid.uuid4().hex[:12]}",
            signal_type="payment_failures",
            status=SignalStatus.active,
            title="Payment failures rising",
            metric="failed_payment_events",
            current_value=12,
            comparison_value=8,
            change_percentage=50.0,
            window_days=30,
            confidence=0.8,
            detected_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()


def run_designer(db_session: Session, merchant: Merchant, llm, objective: str):
    agent = AGENT_INSTANCES["DesignerAgent"]
    ctx = AgentContext(
        db=db_session,
        merchant_id=merchant.id,
        mode="team",
        llm=llm,
        params={"phase": "work", "objective": objective},
    )
    return agent.execute(ctx)


# ── PATH A — LLM-assisted ───────────────────────────────────────────────


class TestPathALlmAssisted:
    """LLM succeeds -> brief -> Cloudflare FLUX -> stored, displayed image."""

    def test_brief_reaches_cloudflare_flux(self, db_session, enabled, flux):
        m = make_merchant(db_session, "path-a")
        seed_radar_observation(db_session, m)

        result = run_designer(db_session, m, BriefLLM(), "Refresh the campaign")

        assert result.status == "completed", result.errors
        assert result.output["brief_persisted"] is True

        req = flux.only_request()
        assert req.url.host == "api.cloudflare.com"
        assert req.url.path.endswith(FLUX_URL_TAIL), req.url.path
        assert MODEL in str(req.url)

    def test_request_carries_the_existing_account_and_token(self, db_session, enabled, flux):
        m = make_merchant(db_session, "path-a-auth")
        seed_radar_observation(db_session, m)

        run_designer(db_session, m, BriefLLM(), "Refresh the campaign")

        req = flux.only_request()
        assert "/accounts/acct-path-test/" in str(req.url)
        assert req.headers["Authorization"] == "Bearer tok-path-test-secret"
        assert req.headers["Content-Type"] == "application/json"

    def test_prompt_is_built_from_the_generated_brief(self, db_session, enabled, flux):
        m = make_merchant(db_session, "path-a-prompt")
        seed_radar_observation(db_session, m)

        run_designer(db_session, m, BriefLLM(), "Refresh the campaign")

        payload = json.loads(flux.only_request().content.decode())
        assert "coherent visual system" in payload["prompt"]
        assert "Hero-led single column" in payload["prompt"]

    def test_real_image_is_persisted_and_linked_to_the_brief(
        self, db_session, enabled, flux
    ):
        m = make_merchant(db_session, "path-a-store")
        seed_radar_observation(db_session, m)

        result = run_designer(db_session, m, BriefLLM(), "Refresh the campaign")
        state = result.output["image_generation"]

        assert state["status"] == "completed", state
        assert state["provider"] == "cloudflare"
        assert state["asset_reference"]

        ref = db_session.get(RenderedAsset, uuid.UUID(state["rendered_asset_id"]))
        assert ref is not None
        assert ref.image_bytes.startswith(b"\xff\xd8"), "real stored bytes"

        brief = db_session.get(CreativeBrief, uuid.UUID(result.output["brief_id"]))
        asset = db_session.get(DesignAsset, ref.asset_id)
        assert asset.brief_id == brief.id, "the image belongs to the generated brief"
        assert asset.kind is DesignAssetKind.rendered_image
        # A generated image is work for a human. Never auto-approved.
        assert asset.review_status is DesignReviewStatus.pending_review
        db_session.commit()

    def test_regeneration_preserves_earlier_versions(self, db_session, enabled, flux):
        m = make_merchant(db_session, "path-a-regen")
        seed_radar_observation(db_session, m)
        result = run_designer(db_session, m, BriefLLM(), "Refresh the campaign")

        first_ref = db_session.get(
            RenderedAsset, uuid.UUID(result.output["image_generation"]["rendered_asset_id"])
        )
        asset_id = first_ref.asset_id

        again = DesignerService(db_session).request_image_generation(
            m.id, asset_id, prompt="A bolder variant"
        )
        assert again["status"] == "completed", again

        versions = db_session.scalars(
            select(DesignAssetVersion)
            .where(DesignAssetVersion.asset_id == asset_id)
            .order_by(DesignAssetVersion.version)
        ).all()
        # direction, first image, regenerated image
        assert [v.version for v in versions] == [1, 2, 3]
        refs = db_session.scalars(
            select(RenderedAsset).where(RenderedAsset.asset_id == asset_id)
        ).all()
        assert len(refs) == 2, "both images retained; neither overwritten"
        assert first_ref.id in {r.id for r in refs}
        db_session.commit()

    # -- honesty: LLM failure --

    def test_llm_rate_limit_reports_failure_and_never_fabricates_a_brief(
        self, db_session, enabled, flux
    ):
        m = make_merchant(db_session, "path-a-llm-fail")
        seed_radar_observation(db_session, m)

        result = run_designer(db_session, m, RateLimitedLLM(), "Refresh the campaign")

        assert result.status == "failed", "a run with no brief is not a success"
        assert result.output["brief_persisted"] is False
        assert "brief_generation_failed" in " ".join(result.errors)
        assert any(e.startswith("brief_generation_failed:") for e in result.errors)
        assert "brief_id" not in result.output
        assert "project_id" not in result.output
        assert result.output.get("image_generation", {}).get("status") != "completed"

    def test_llm_failure_makes_no_image_request_at_all(self, db_session, enabled, flux):
        """No brief means no image. The provider is never contacted."""
        m = make_merchant(db_session, "path-a-llm-noimg")
        seed_radar_observation(db_session, m)

        run_designer(db_session, m, RateLimitedLLM(), "Refresh the campaign")

        assert flux.requests == [], (
            f"no brief was produced, so no image may be requested: {flux.urls}"
        )

    def test_llm_failure_still_offers_the_direct_fallback(
        self, db_session, enabled, flux, client
    ):
        """The brief failed, but a description alone can still render.

        This is the recovery the merchant is actually offered: the direct
        route works with no LLM in the loop at all.
        """
        m = make_merchant(db_session, "path-a-fallback")
        seed_radar_observation(db_session, m)
        result = run_designer(db_session, m, RateLimitedLLM(), "Refresh the campaign")
        assert result.status == "failed"

        resp = client.post(
            "/api/designer/image-generation",
            json={"prompt": "A calm editorial hero image, soft daylight"},
            params={"merchant_id": str(m.id)},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    # -- honesty: Cloudflare failure --

    def test_cloudflare_failure_keeps_the_real_brief_and_reports_the_failure(
        self, db_session, enabled, flux
    ):
        m = make_merchant(db_session, "path-a-cf-fail")
        seed_radar_observation(db_session, m)
        flux.respond_error(500)

        result = run_designer(db_session, m, BriefLLM(), "Refresh the campaign")

        state = result.output["image_generation"]
        assert state["status"] == "failed", state
        assert state.get("reason")
        assert state["asset_reference"] is None

        # The research is real and must survive a renderer outage.
        assert result.output["brief_persisted"] is True
        assert result.status == "completed", "an image outage is not a brief failure"
        brief = db_session.get(CreativeBrief, uuid.UUID(result.output["brief_id"]))
        assert brief is not None
        # And no image bytes were invented.
        assert (
            db_session.scalar(
                select(RenderedAsset).where(
                    RenderedAsset.asset_id.in_(
                        select(DesignAsset.id).where(
                            DesignAsset.brief_id == brief.id
                        )
                    )
                )
            )
            is None
        )
        db_session.commit()

    def test_cloudflare_rejected_credentials_are_reported_honestly(
        self, db_session, enabled, flux
    ):
        m = make_merchant(db_session, "path-a-cf-403")
        seed_radar_observation(db_session, m)
        flux.responder = lambda _r: httpx.Response(403, json={"success": False})

        result = run_designer(db_session, m, BriefLLM(), "Refresh the campaign")

        state = result.output["image_generation"]
        assert state["status"] == "failed"
        assert state["code"] == "PROVIDER_REJECTED"
        assert result.output["brief_persisted"] is True

    def test_image_generation_off_is_reported_not_faked(
        self, db_session, monkeypatch, flux
    ):
        monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "false")
        get_settings.cache_clear()
        try:
            m = make_merchant(db_session, "path-a-off")
            seed_radar_observation(db_session, m)
            result = run_designer(db_session, m, BriefLLM(), "Refresh the campaign")
        finally:
            get_settings.cache_clear()

        state = result.output["image_generation"]
        assert state["status"] == "unavailable"
        assert state["reason"]
        assert state["asset_reference"] is None
        assert flux.requests == [], "a disabled provider must never be called"
        assert result.output["brief_persisted"] is True


# ── PATH B — direct, no brief, no LLM ──────────────────────────────────


class TestPathBDirectNoLlm:
    """A description alone -> Cloudflare FLUX -> stored image. No LLM."""

    def test_no_llm_call_is_made(self, db_session, enabled, flux, llm_tripwire, client):
        m = make_merchant(db_session, "path-b-nollm")

        resp = client.post(
            "/api/designer/image-generation",
            json={"prompt": "A calm editorial hero image, soft daylight"},
            params={"merchant_id": str(m.id)},
        )

        assert resp.status_code == 200, resp.text
        assert llm_tripwire == [], "no LLM provider may be resolved or built"
        # Cloudflare serves BOTH modalities from one host, so a host-only check
        # cannot tell them apart. What must not appear is the text-LLM route:
        # the image path is /ai/run/<model>, the LLM path is /ai/v1/chat/...
        assert [u for u in flux.urls if "/ai/v1/" in u] == [], flux.urls
        assert flux.hosts == {"api.cloudflare.com"}, flux.hosts

    def test_request_goes_to_cloudflare_flux_with_real_credentials(
        self, db_session, enabled, flux, llm_tripwire, client
    ):
        m = make_merchant(db_session, "path-b-flux")

        client.post(
            "/api/designer/image-generation",
            json={"prompt": "A calm editorial hero image, soft daylight"},
            params={"merchant_id": str(m.id)},
        )

        req = flux.only_request()
        assert req.url.host == "api.cloudflare.com"
        assert req.url.path.endswith(FLUX_URL_TAIL), req.url.path
        assert "/accounts/acct-path-test/" in str(req.url)
        assert req.headers["Authorization"] == "Bearer tok-path-test-secret"

    def test_description_is_passed_straight_through(
        self, db_session, enabled, flux, llm_tripwire, client
    ):
        """No LLM rewrites the description — it is the prompt, verbatim."""
        m = make_merchant(db_session, "path-b-verbatim")
        description = "A warm, minimal product photo on a pale sand background"

        client.post(
            "/api/designer/image-generation",
            json={"prompt": description},
            params={"merchant_id": str(m.id)},
        )

        payload = json.loads(flux.only_request().content.decode())
        assert payload["prompt"] == description

    def test_works_before_any_design_asset_exists(
        self, db_session, enabled, flux, llm_tripwire, client
    ):
        """The whole point: no project, no brief, no prior asset required."""
        m = make_merchant(db_session, "path-b-fresh")
        svc = DesignerService(db_session)
        assert svc.list_projects(m.id) == []
        assert svc.list_assets(m.id) == []

        resp = client.post(
            "/api/designer/image-generation",
            json={"prompt": "A calm editorial hero image, soft daylight"},
            params={"merchant_id": str(m.id)},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
        db_session.rollback()

    def test_real_bytes_are_persisted_and_served(
        self, db_session, enabled, flux, llm_tripwire, client
    ):
        m = make_merchant(db_session, "path-bytes")

        resp = client.post(
            "/api/designer/image-generation",
            json={"prompt": "A calm editorial hero image, soft daylight"},
            params={"merchant_id": str(m.id)},
        )
        body = resp.json()
        assert body["status"] == "completed", body
        assert body["provider"] == "cloudflare"
        assert body["byte_size"] > 0

        img = client.get(
            f"/api/designer/rendered-assets/{body['rendered_asset_id']}/content",
            params={"merchant_id": str(m.id)},
        )
        assert img.status_code == 200
        assert img.content.startswith(b"\xff\xd8"), "real JPEG bytes over auth"
        assert img.headers["X-Image-SHA256"] == body["sha256"]
        db_session.rollback()

    def test_image_is_not_labelled_as_a_designer_agent_run(
        self, db_session, enabled, flux, llm_tripwire, client
    ):
        """A direct render is a direct render. It claims no research."""
        m = make_merchant(db_session, "path-b-label")

        client.post(
            "/api/designer/image-generation",
            json={"prompt": "A calm editorial hero image, soft daylight"},
            params={"merchant_id": str(m.id)},
        )

        svc = DesignerService(db_session)
        assert svc.list_briefs(m.id) == [], "no brief was invented"
        db_session.rollback()

    def test_description_is_required(self, db_session, enabled, flux, client):
        m = make_merchant(db_session, "path-b-empty")

        resp = client.post(
            "/api/designer/image-generation",
            json={},
            params={"merchant_id": str(m.id)},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert resp.json()["code"] == "INVALID_PROMPT"
        assert flux.requests == [], "an empty prompt costs no provider call"

    def test_respects_image_generation_enabled(
        self, db_session, monkeypatch, flux, llm_tripwire, client
    ):
        monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "false")
        get_settings.cache_clear()
        try:
            m = make_merchant(db_session, "path-b-off")
            resp = client.post(
                "/api/designer/image-generation",
                json={"prompt": "A calm editorial hero image"},
                params={"merchant_id": str(m.id)},
            )
        finally:
            get_settings.cache_clear()

        assert resp.status_code == 200
        assert resp.json()["status"] == "unavailable"
        assert resp.json()["reason"]
        assert flux.requests == [], "a disabled provider must never be called"
        db_session.rollback()

    def test_missing_credentials_are_reported_not_faked(
        self, db_session, monkeypatch, flux, llm_tripwire, client
    ):
        monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "true")
        # Pin the account explicitly so exactly ONE credential is missing and
        # the assertion does not depend on whatever the local .env happens to
        # contain (the suite blanks real credentials for safety).
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-path-test")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "")
        get_settings.cache_clear()
        try:
            m = make_merchant(db_session, "path-b-notoken")
            resp = client.post(
                "/api/designer/image-generation",
                json={"prompt": "A calm editorial hero image"},
                params={"merchant_id": str(m.id)},
            )
        finally:
            get_settings.cache_clear()

        body = resp.json()
        assert body["status"] == "unavailable"
        assert "CLOUDFLARE_API_TOKEN" in body["reason"]
        assert flux.requests == []
        db_session.rollback()

    def test_cloudflare_failure_is_reported_honestly(
        self, db_session, enabled, flux, llm_tripwire, client
    ):
        m = make_merchant(db_session, "path-b-cf-fail")
        flux.respond_error(429)

        resp = client.post(
            "/api/designer/image-generation",
            json={"prompt": "A calm editorial hero image"},
            params={"merchant_id": str(m.id)},
        )

        body = resp.json()
        assert body["status"] == "failed", body
        assert body["code"] == "PROVIDER_RATE_LIMITED"
        assert body["asset_reference"] is None
        # No prompt echoed back to the caller.
        assert "calm editorial" not in resp.text
        db_session.rollback()

    def test_malformed_provider_response_is_reported(
        self, db_session, enabled, flux, llm_tripwire, client
    ):
        m = make_merchant(db_session, "path-b-malformed")
        flux.responder = lambda _r: httpx.Response(
            200, json={"result": {"image": "not-base64!!"}, "success": True}
        )

        resp = client.post(
            "/api/designer/image-generation",
            json={"prompt": "A calm editorial hero image"},
            params={"merchant_id": str(m.id)},
        )

        body = resp.json()
        assert body["status"] == "failed"
        assert body["code"] == "PROVIDER_MALFORMED_RESPONSE"
        db_session.rollback()

    # -- authentication and ownership --

    def test_requires_authentication(self, db_session, enabled, flux, monkeypatch, client):
        monkeypatch.setenv("AUTH_MODE", "required")
        get_settings.cache_clear()
        try:
            resp = client.post(
                "/api/designer/image-generation",
                json={"prompt": "A calm editorial hero image"},
            )
        finally:
            get_settings.cache_clear()

        assert resp.status_code == 401
        assert flux.requests == [], "an unauthenticated call spends nothing"

    def test_cross_merchant_asset_is_refused(
        self, db_session, enabled, flux, client
    ):
        a = make_merchant(db_session, "path-b-a")
        b = make_merchant(db_session, "path-b-b")
        svc = DesignerService(db_session)
        project = svc.create_project(a.id, objective="A's project")
        brief = svc.store_brief(a.id, project, grounded_spec())
        asset = svc.add_asset(
            a.id,
            project,
            kind=DesignAssetKind.variant,
            title="A's asset",
            content={},
            brief_id=brief.id,
        )
        db_session.commit()

        resp = client.post(
            f"/api/designer/assets/{asset.id}/image-generation",
            json={"prompt": "borrow this"},
            params={"merchant_id": str(b.id)},
        )

        assert resp.status_code == 404, "no existence leak"
        assert flux.requests == [], "ownership is checked before any spend"
        db_session.rollback()

    def test_cross_merchant_image_cannot_be_fetched(
        self, db_session, enabled, flux, client
    ):
        a = make_merchant(db_session, "path-b-fetch-a")
        b = make_merchant(db_session, "path-b-fetch-b")
        resp = client.post(
            "/api/designer/image-generation",
            json={"prompt": "A calm editorial hero image"},
            params={"merchant_id": str(a.id)},
        )
        rid = resp.json()["rendered_asset_id"]

        stolen = client.get(
            f"/api/designer/rendered-assets/{rid}/content",
            params={"merchant_id": str(b.id)},
        )

        assert stolen.status_code == 404
        db_session.rollback()

    def test_regeneration_adds_a_version_and_keeps_the_old_image(
        self, db_session, enabled, flux, llm_tripwire, client
    ):
        m = make_merchant(db_session, "path-b-regen")
        svc = DesignerService(db_session)

        first = client.post(
            "/api/designer/image-generation",
            json={"prompt": "A calm editorial hero image"},
            params={"merchant_id": str(m.id)},
        ).json()
        first_ref = db_session.get(
            RenderedAsset, uuid.UUID(first["rendered_asset_id"])
        )
        asset_id = first_ref.asset_id

        second = svc.request_image_generation(
            m.id, asset_id, prompt="A bolder editorial hero image"
        )
        assert second["status"] == "completed", second

        refs = db_session.scalars(
            select(RenderedAsset).where(RenderedAsset.asset_id == asset_id)
        ).all()
        assert len(refs) == 2, "the first image is retained, not overwritten"
        assert first_ref.id in {r.id for r in refs}

        versions = db_session.scalars(
            select(DesignAssetVersion)
            .where(DesignAssetVersion.asset_id == asset_id)
            .order_by(DesignAssetVersion.version)
        ).all()
        # A direct asset starts with no version; each render appends one.
        assert [v.version for v in versions] == [1, 2]
        db_session.commit()

    def test_quota_exhaustion_is_reported_not_hidden(
        self, db_session, enabled, flux, llm_tripwire, client, monkeypatch
    ):
        m = make_merchant(db_session, "path-b-quota")
        monkeypatch.setenv("IMAGE_DAILY_QUOTA_PER_MERCHANT", "0")
        get_settings.cache_clear()
        try:
            resp = client.post(
                "/api/designer/image-generation",
                json={"prompt": "A calm editorial hero image"},
                params={"merchant_id": str(m.id)},
            )
        finally:
            get_settings.cache_clear()

        body = resp.json()
        assert body["status"] == "failed", "silently reporting 'available' would be a lie"
        assert body["code"] == "IMAGE_QUOTA_EXCEEDED"
        assert body["asset_reference"] is None
        db_session.rollback()


# ── the two paths stay distinct ─────────────────────────────────────────


class TestTripwireIsLive:
    """Guards the guard.

    ``llm_tripwire`` is what makes "Path B never calls the LLM" an enforced
    fact. If it ever stopped firing, every Path B assertion built on it would
    keep passing while proving nothing. These two tests fail loudly if that
    happens.
    """

    def test_resolver_tripwire_actually_fires(self, llm_tripwire):
        from backend.app.ai.llm.provider import resolve_llm_provider

        with pytest.raises(AssertionError, match="must not touch the LLM"):
            resolve_llm_provider(get_settings())
        assert llm_tripwire == ["resolve_llm_provider"]

    def test_openai_client_tripwire_actually_fires(self, llm_tripwire):
        openai = pytest.importorskip("openai")
        with pytest.raises(AssertionError, match="must not touch the LLM"):
            openai.OpenAI(api_key="whatever")
        assert llm_tripwire == ["openai.OpenAI"]


class TestPathsAreDistinct:
    def test_direct_path_creates_no_brief_and_no_debate_artefacts(
        self, db_session, enabled, flux, llm_tripwire, client
    ):
        m = make_merchant(db_session, "paths-distinct")

        client.post(
            "/api/designer/image-generation",
            json={"prompt": "A calm editorial hero image"},
            params={"merchant_id": str(m.id)},
        )

        svc = DesignerService(db_session)
        assert svc.list_briefs(m.id) == []
        # Exactly one asset, the one that owns the generated bytes.
        assert len(svc.list_assets(m.id)) == 1
        db_session.rollback()

    def test_assisted_path_records_the_llm_that_wrote_the_brief(
        self, db_session, enabled, flux
    ):
        m = make_merchant(db_session, "paths-llm-record")
        seed_radar_observation(db_session, m)

        result = run_designer(db_session, m, BriefLLM(), "Refresh the campaign")

        brief = db_session.get(CreativeBrief, uuid.UUID(result.output["brief_id"]))
        assert brief.llm_provider == "cloudflare", "the brief records its real author"
        db_session.commit()