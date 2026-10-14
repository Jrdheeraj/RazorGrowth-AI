"""Cloudflare FLUX.1 Schnell image generation — focused tests.

Every provider interaction here is MOCKED. ``httpx.MockTransport`` returns
canned responses, so no test touches the network and no test spends provider
quota. A live test exists but is opt-in via ``RAZORGROWTH_LIVE_IMAGE_TEST=1``
and reports itself when skipped (see ``test_live_provider_is_opt_in``).

Coverage maps to the guarantees that matter:

  * DISABLED BY DEFAULT and missing-credential behaviour, with no fake result
  * the request shape matches the provider's PUBLISHED schema (prompt/steps
    only — never ``seed``)
  * provider failure, malformed response, timeout and rate-limit handling
  * NO prompt, token or provider payload leaks into an error, status or log
  * quota enforcement, including the concurrency lock
  * authenticated, merchant-scoped retrieval and cross-merchant denial
  * asset + version + bytes land together, and append-only on regeneration
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import struct
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.integrations.cloudflare_image import (
    MODEL,
    MODEL_LABEL,
    PROMPT_MAX_CHARS,
    CloudflareImageGenerator,
    ImageGenerationError,
    build_url,
    provider_availability,
    validate_prompt,
    validate_steps,
)
from backend.app.models.designer import DesignAsset, DesignAssetVersion
from backend.app.models.enums import (
    Currency,
    DesignAssetKind,
    MerchantStatus,
)
from backend.app.models.merchant import Merchant
from backend.app.models.rendered_asset import RenderedAsset
from backend.app.schemas.designer import CreativeBriefSpec
from backend.app.services.design_asset_storage import (
    DesignAssetStorage,
    ImageNotFound,
    ImageQuotaExceeded,
    ImageStorageConflict,
    ImageValidationError,
    parse_jpeg,
)
from backend.app.services.designer_service import DesignerService

# ── helpers ─────────────────────────────────────────────────────────────


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


def jpeg(width: int = 64, height: int = 48) -> bytes:
    """A structurally valid JPEG skeleton.

    Enough for the bounded parser to walk the marker chain and read SOF0,
    which is all it inspects. It is never decoded as pixels anywhere.
    """
    out = bytearray(b"\xff\xd8")
    body = bytes([8]) + struct.pack(">HH", height, width) + bytes([1])
    body += bytes([1, 0x11, 0])
    out += b"\xff\xc0" + struct.pack(">H", len(body) + 2) + body
    sos = bytes([1, 1, 0x00, 0, 63, 0])
    out += b"\xff\xda" + struct.pack(">H", len(sos) + 2) + sos
    out += b"\x00" * 8 + b"\xff\xd9"
    return bytes(out)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def envelope(image_b64: str) -> dict:
    return {"result": {"image": image_b64}, "success": True, "errors": [], "messages": []}


def grounded_spec() -> CreativeBriefSpec:
    return CreativeBriefSpec(
        title="Summer refresh",
        objective="One coherent visual system",
        project_type="campaign_creative",
        evidence=[{"statement": "12 failed payments", "basis": "observed"}],
    )


def seed_asset(db_session: Session, merchant: Merchant) -> DesignAsset:
    """A real design asset, created through the existing service path.

    Returns the asset only. Note ``add_asset`` already writes version 1, so
    storage tests must use :func:`seed_asset_with_version` rather than adding
    another version=1 row.
    """
    return seed_asset_with_version(db_session, merchant)[0]


def seed_asset_with_version(
    db_session: Session, merchant: Merchant
) -> tuple[DesignAsset, DesignAssetVersion]:
    """An asset plus its existing immutable version, both committed."""
    svc = DesignerService(db_session)
    project = svc.create_project(merchant.id, objective="Refresh the creative")
    brief = svc.store_brief(merchant.id, project, grounded_spec())
    asset = svc.add_asset(
        merchant.id,
        project,
        kind=DesignAssetKind.variant,
        title="Editorial variant",
        content={"title": "Editorial"},
        brief_id=brief.id,
    )
    db_session.commit()
    version = db_session.scalar(
        select(DesignAssetVersion).where(DesignAssetVersion.asset_id == asset.id)
    )
    assert version is not None, "add_asset must have written version 1"
    return asset, version


def generator_with(handler, **kw) -> CloudflareImageGenerator:
    """A client backed by a mock transport. ``handler`` receives the request."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CloudflareImageGenerator(
        account_id=kw.pop("account_id", "acct-test"),
        api_token=kw.pop("api_token", "tok-test"),
        client=client,
        **kw,
    )


def fake_generator(image: bytes | None = None, *, error: Exception | None = None):
    """A stand-in generator that never performs I/O."""

    class _Fake:
        def __init__(self):
            self.calls: list[tuple[str, int | None]] = []

        def generate(self, prompt: str, *, steps: int | None = None):
            self.calls.append((prompt, steps))
            if error is not None:
                raise error
            return type(
                "Img",
                (),
                {
                    "data": image if image is not None else jpeg(),
                    "provider": "cloudflare",
                    "model": MODEL_LABEL,
                    "steps": steps,
                },
            )()

        def close(self):
            pass

    return _Fake()


def _next_version(db_session: Session, merchant_id, asset_id, version: int) -> DesignAssetVersion:
    """Add a fresh immutable version, committed, for quota scenarios."""
    v = DesignAssetVersion(
        merchant_id=merchant_id, asset_id=asset_id, version=version, content={}
    )
    db_session.add(v)
    db_session.commit()
    return v


@pytest.fixture()
def enabled(monkeypatch):
    """Settings with image generation ON and placeholder credentials."""
    monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-test")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok-test-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def disabled(monkeypatch):
    """The shipped default: OFF."""
    monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "false")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-test")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok-test-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── 1. capability / enablement ──────────────────────────────────────────


class TestEnablement:
    def test_disabled_by_default_in_settings(self):
        """The SHIPPED defaults must be OFF with no credentials required.

        Asserted against the declared field defaults, not the loaded instance:
        a developer's local .env legitimately overrides these, and that must not
        be able to change what the code ships with.
        """
        from backend.app.core.config import Settings

        fields = Settings.model_fields
        assert fields["IMAGE_GENERATION_ENABLED"].default is False
        assert fields["CLOUDFLARE_ACCOUNT_ID"].default == ""
        assert fields["CLOUDFLARE_API_TOKEN"].default == ""

    def test_disabled_reports_unavailable_with_reason(self, disabled):
        av = provider_availability(
            enabled=False, account_id="acct", api_token="tok"
        )
        assert av.available is False
        assert av.reason and "IMAGE_GENERATION_ENABLED" in av.reason

    def test_missing_account_id_is_not_ready(self):
        av = provider_availability(enabled=True, account_id="", api_token="tok")
        assert av.available is False
        assert "CLOUDFLARE_ACCOUNT_ID" in (av.reason or "")

    def test_missing_token_is_not_ready(self):
        av = provider_availability(enabled=True, account_id="acct", api_token="  ")
        assert av.available is False
        assert "CLOUDFLARE_API_TOKEN" in (av.reason or "")

    def test_no_credential_means_no_fake_success(self, db_session, disabled):
        merchant = make_merchant(db_session, "imgen-off")
        svc = DesignerService(db_session)
        asset = seed_asset(db_session, merchant)
        out = svc.request_image_generation(merchant.id, asset.id)
        assert out["status"] == "unavailable"
        assert out["asset_reference"] is None
        # No bytes, and the asset was not promoted to a rendered image.
        db_session.rollback()
        assert (
            db_session.scalar(
                select(RenderedAsset).where(
                    RenderedAsset.merchant_id == merchant.id
                )
            )
            is None
        )

    def test_enabled_but_unconfigured_service_is_unavailable(
        self, db_session, monkeypatch
    ):
        monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "true")
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "")
        get_settings.cache_clear()
        try:
            merchant = make_merchant(db_session, "imgen-nocred")
            svc = DesignerService(db_session)
            assert svc.image_generation_status()["status"] == "unavailable"
        finally:
            get_settings.cache_clear()


# ── 2. request shape matches the PUBLISHED schema ──────────────────────


class TestRequestShape:
    def test_url_is_verbatim_and_unencoded(self):
        url = build_url("abc123")
        assert url == (
            "https://api.cloudflare.com/client/v4/accounts/abc123/ai/run/"
            "@cf/black-forest-labs/flux-1-schnell"
        )
        # The model segment keeps its literal @ and slashes.
        assert MODEL in url

    def test_only_prompt_is_sent_when_steps_omitted(self, enabled):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            seen["auth"] = request.headers.get("authorization")
            seen["url"] = str(request.url)
            return httpx.Response(200, json=envelope(b64(jpeg())))

        gen = generator_with(handler)
        gen.generate("a warm studio scene")
        assert set(seen["body"]) == {"prompt"}
        assert seen["body"]["prompt"] == "a warm studio scene"

    def test_never_sends_seed(self, enabled):
        """The published schema sets additionalProperties:false and has no
        `seed`. The provider's own curl example is wrong; we must not copy it."""
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=envelope(b64(jpeg())))

        generator_with(handler).generate("x", steps=6)
        assert "seed" not in seen["body"]
        assert set(seen["body"]) <= {"prompt", "steps"}

    def test_steps_forwarded_when_supplied(self, enabled):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=envelope(b64(jpeg())))

        generator_with(handler).generate("x", steps=8)
        assert seen["body"]["steps"] == 8

    def test_bearer_header_present_and_correct(self, enabled):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=envelope(b64(jpeg())))

        generator_with(handler, api_token="tok-secret").generate("x")
        assert seen["auth"] == "Bearer tok-secret"

    def test_prompt_whitespace_normalised(self, enabled):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=envelope(b64(jpeg())))

        generator_with(handler).generate("  a   warm \n scene  ")
        assert seen["body"]["prompt"] == "a warm scene"

    # bounds
    def test_prompt_at_limit_accepted(self):
        assert len(validate_prompt("a" * PROMPT_MAX_CHARS)) == PROMPT_MAX_CHARS

    def test_prompt_over_limit_refused(self):
        with pytest.raises(ValueError, match="character limit"):
            validate_prompt("a" * (PROMPT_MAX_CHARS + 1))

    def test_empty_prompt_refused(self):
        with pytest.raises(ValueError):
            validate_prompt("   ")

    def test_steps_bounds_enforced(self):
        assert validate_steps(None) is None
        assert validate_steps(1) == 1
        assert validate_steps(8) == 8
        for bad in (0, 9, -1, 100, True, 1.5, "4"):
            with pytest.raises(ValueError):
                validate_steps(bad)  # type: ignore[arg-type]


# ── 3. response decoding ────────────────────────────────────────────────


class TestResponseDecoding:
    def test_happy_path_returns_bytes(self, enabled):
        payload = jpeg(120, 90)
        gen = generator_with(lambda r: httpx.Response(200, json=envelope(b64(payload))))
        out = gen.generate("a scene")
        assert out.data == payload
        assert out.provider == "cloudflare"
        assert out.model == MODEL_LABEL

    def test_data_uri_prefix_tolerated(self, enabled):
        payload = jpeg()
        raw = f"data:image/jpeg;base64,{b64(payload)}"
        gen = generator_with(lambda r: httpx.Response(200, json=envelope(raw)))
        assert gen.generate("x").data == payload

    def test_success_false_is_an_error(self, enabled):
        body = {"success": False, "errors": [{"message": "boom"}], "messages": []}
        gen = generator_with(lambda r: httpx.Response(200, json=body))
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code == "PROVIDER_ERROR"

    def test_missing_result_is_malformed(self, enabled):
        gen = generator_with(lambda r: httpx.Response(200, json={"success": True}))
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code == "PROVIDER_MALFORMED_RESPONSE"

    def test_missing_image_key_is_malformed(self, enabled):
        gen = generator_with(
            lambda r: httpx.Response(200, json={"success": True, "result": {}})
        )
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code == "PROVIDER_MALFORMED_RESPONSE"

    def test_non_json_body_is_malformed(self, enabled):
        gen = generator_with(lambda r: httpx.Response(200, content=b"<html>nope</html>"))
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code == "PROVIDER_MALFORMED_RESPONSE"

    def test_invalid_base64_is_malformed(self, enabled):
        gen = generator_with(
            lambda r: httpx.Response(200, json=envelope("!!!not-base64!!!"))
        )
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code == "PROVIDER_MALFORMED_RESPONSE"

    def test_empty_payload_refused(self, enabled):
        gen = generator_with(lambda r: httpx.Response(200, json=envelope("")))
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code == "PROVIDER_MALFORMED_RESPONSE"

    def test_oversize_payload_refused_before_store(self, enabled):
        huge = base64.b64encode(b"\xff\xd8" + b"A" * 5000).decode()
        gen = generator_with(
            lambda r: httpx.Response(200, json=envelope(huge)), max_bytes=1024
        )
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code == "IMAGE_TOO_LARGE"


# ── 4. provider failure modes ───────────────────────────────────────────


class TestProviderFailures:
    def test_timeout_maps_to_stable_code(self, enabled):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        gen = generator_with(handler, max_retries=0)
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code == "PROVIDER_TIMEOUT"

    def test_network_error_maps_to_stable_code(self, enabled):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route", request=request)

        gen = generator_with(handler)
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code == "PROVIDER_NETWORK_ERROR"

    def test_rate_limited_maps_to_stable_code(self, enabled):
        gen = generator_with(
            lambda r: httpx.Response(429, json={"errors": [{"message": "slow down"}]}),
            max_retries=0,
        )
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code == "PROVIDER_RATE_LIMITED"

    def test_5xx_retries_then_fails(self, enabled):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503, json={"errors": []})

        gen = generator_with(handler, max_retries=2)
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code == "PROVIDER_ERROR"
        assert calls["n"] == 3, "must retry exactly max_retries times"

    def test_transient_5xx_then_success(self, enabled):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(502, json={"errors": []})
            return httpx.Response(200, json=envelope(b64(jpeg())))

        assert generator_with(handler, max_retries=2).generate("x").data
        assert calls["n"] == 2

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_client_errors_refused(self, enabled, status):
        gen = generator_with(
            lambda r: httpx.Response(status, json={"errors": []}), max_retries=0
        )
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert exc.value.code in ("PROVIDER_REJECTED", "PROVIDER_ERROR")

    def test_bad_credentials_give_a_specific_message(self, enabled):
        gen = generator_with(
            lambda r: httpx.Response(401, json={"errors": []}), max_retries=0
        )
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert "credentials" in exc.value.safe_message.lower()


# ── 5. secret / prompt leakage ─────────────────────────────────────────


class TestNoLeakage:
    SECRET = "sk-super-secret-token-value"
    PROMPT = "confidential brand direction for Acme Private Holdings"

    def test_prompt_absent_from_every_error(self, enabled):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={"success": False, "errors": [{"message": f"bad: {self.PROMPT}"}]},
            )

        gen = generator_with(handler, max_retries=0)
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate(self.PROMPT)
        blob = f"{exc.value} {exc.value.code} {exc.value.safe_message}"
        assert self.PROMPT not in blob

    def test_provider_body_never_reaches_the_message(self, enabled):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500, json={"success": False, "errors": [{"message": "INTERNAL_STACK"}]}
            )

        gen = generator_with(handler, max_retries=0)
        with pytest.raises(ImageGenerationError) as exc:
            gen.generate("x")
        assert "INTERNAL_STACK" not in exc.value.safe_message

    def test_token_absent_from_error_and_logs(self, enabled, caplog):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"errors": []})

        gen = generator_with(handler, api_token=self.SECRET, max_retries=0)
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(ImageGenerationError) as exc:
                gen.generate("x")
        assert self.SECRET not in exc.value.safe_message
        assert self.SECRET not in caplog.text

    def test_prompt_absent_from_logs_on_success(self, enabled, caplog):
        secret_prompt = "a rare distinctive prompt string 98765"
        gen = generator_with(lambda r: httpx.Response(200, json=envelope(b64(jpeg()))))
        with caplog.at_level(logging.DEBUG):
            gen.generate(secret_prompt)
        assert secret_prompt not in caplog.text

    def test_availability_never_echoes_credentials(self):
        for acct, tok in (("acct", "tok"), ("", "tok"), ("acct", "")):
            av = provider_availability(enabled=True, account_id=acct, api_token=tok)
            assert "tok" not in (av.reason or "")


# ── 6. bounded JPEG validation (no Pillow) ─────────────────────────────


class TestJpegValidation:
    def test_reads_dimensions(self):
        info = parse_jpeg(jpeg(1024, 768), max_pixels=4194304, max_width=2048, max_height=2048)
        assert (info.width, info.height) == (1024, 768)
        assert info.sha256 == hashlib.sha256(jpeg(1024, 768)).hexdigest()

    @pytest.mark.parametrize(
        "payload",
        [
            b"",
            b"<html>502 Bad Gateway</html>",
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
            b"\xff\xd8",                        # SOI only
            b"\x00\x01\x02\x03" * 8,            # no SOI
            b"\xff\xd8\xff\xd9",                # no SOF
            b"\xff\xd8\xff\xc0\xff\xff\x08\x00\x10\x00\x10\x01\x01\x11\x00\xff\xd9",
        ],
    )
    def test_malformed_payloads_refused(self, payload):
        with pytest.raises(ImageValidationError):
            parse_jpeg(payload, max_pixels=4194304, max_width=2048, max_height=2048)

    def test_dimension_ceiling_enforced(self):
        with pytest.raises(ImageValidationError, match="exceed"):
            parse_jpeg(jpeg(4096, 64), max_pixels=4194304, max_width=2048, max_height=2048)

    def test_pixel_budget_enforced(self):
        with pytest.raises(ImageValidationError):
            parse_jpeg(
                jpeg(2000, 2000), max_pixels=1000, max_width=2048, max_height=2048
            )

    def test_boundary_dimensions_accepted(self):
        parse_jpeg(jpeg(2048, 2048), max_pixels=4194304, max_width=2048, max_height=2048)


# ── 7. storage: transaction, quota, isolation ──────────────────────────


def storage(db, **kw) -> DesignAssetStorage:
    base = dict(
        max_bytes=4 * 1024 * 1024,
        daily_quota=5,
        daily_storage_quota_bytes=8 * 1024 * 1024,
        max_pixels=4194304,
        max_width=2048,
        max_height=2048,
    )
    base.update(kw)
    return DesignAssetStorage(db, **base)


class TestStorage:
    """Bytes and metadata land together, are quota-bounded, and are
    merchant-scoped on every read."""

    def test_store_then_read_roundtrip(self, db_session):
        m = make_merchant(db_session, "store-ok")
        asset, version = seed_asset_with_version(db_session, m)
        payload = jpeg(200, 100)
        st = storage(db_session)
        ref = st.store(
            m.id, asset_id=asset.id, version_id=version.id,
            data=payload, provider="cloudflare", model=MODEL_LABEL, steps=4,
        )
        db_session.commit()
        got_ref, got = st.read_bytes(m.id, ref.id)
        assert got == payload
        assert got_ref.sha256 == ref.sha256
        assert (got_ref.width, got_ref.height) == (200, 100)

    def test_metadata_matches_bytes(self, db_session):
        m = make_merchant(db_session, "store-meta")
        asset, version = seed_asset_with_version(db_session, m)
        payload = jpeg()
        st = storage(db_session)
        ref = st.store(
            m.id, asset_id=asset.id, version_id=version.id, data=payload,
            provider="cloudflare", model=MODEL_LABEL, steps=None,
        )
        db_session.commit()
        row = db_session.get(RenderedAsset, ref.id)
        assert row.byte_size == len(payload)
        assert row.sha256 == hashlib.sha256(payload).hexdigest()
        assert bytes(row.image_bytes) == payload
        assert row.content_type == "image/jpeg"

    def test_ref_dict_carries_metadata_but_never_bytes(self, db_session):
        m = make_merchant(db_session, "store-ref")
        asset, version = seed_asset_with_version(db_session, m)
        ref = storage(db_session).store(
            m.id, asset_id=asset.id, version_id=version.id, data=jpeg(),
            provider="cloudflare", model=MODEL_LABEL, steps=2,
        )
        db_session.commit()
        d = ref.as_dict()
        assert d["width"] and d["height"] and d["sha256"]
        assert "image_bytes" not in d and "bytes" not in d

    def test_non_jpeg_never_persisted(self, db_session):
        m = make_merchant(db_session, "store-bad")
        asset, version = seed_asset_with_version(db_session, m)
        with pytest.raises(ImageValidationError):
            storage(db_session).store(
                m.id, asset_id=asset.id, version_id=version.id,
                data=b"<html>not an image</html>", provider="cloudflare",
                model=MODEL_LABEL, steps=None,
            )
        db_session.rollback()
        assert (
            db_session.scalar(
                select(RenderedAsset).where(RenderedAsset.merchant_id == m.id)
            )
            is None
        ), "a refused payload must leave no row"

    def test_oversize_refused_and_not_stored(self, db_session):
        m = make_merchant(db_session, "store-big")
        asset, version = seed_asset_with_version(db_session, m)
        with pytest.raises(ImageValidationError):
            storage(db_session, max_bytes=10).store(
                m.id, asset_id=asset.id, version_id=version.id, data=jpeg(),
                provider="cloudflare", model=MODEL_LABEL, steps=None,
            )
        db_session.rollback()
        assert (
            db_session.scalar(
                select(RenderedAsset).where(RenderedAsset.merchant_id == m.id)
            )
            is None
        )

    def test_one_image_per_version(self, db_session):
        m = make_merchant(db_session, "store-unique")
        asset, version = seed_asset_with_version(db_session, m)
        st = storage(db_session)
        st.store(
            m.id, asset_id=asset.id, version_id=version.id, data=jpeg(),
            provider="cloudflare", model=MODEL_LABEL, steps=None,
        )
        db_session.commit()
        with pytest.raises(ImageStorageConflict):
            st.store(
                m.id, asset_id=asset.id, version_id=version.id, data=jpeg(32, 32),
                provider="cloudflare", model=MODEL_LABEL, steps=None,
            )

    def test_daily_count_quota_enforced(self, db_session):
        m = make_merchant(db_session, "store-quota-n")
        asset, _ = seed_asset_with_version(db_session, m)
        st = storage(db_session, daily_quota=2)
        # Two fresh versions per iteration so the (asset_id, version) unique
        # constraint never masks the quota check.
        for n in range(2):
            v = _next_version(db_session, m.id, asset.id, n + 2)
            st.store(
                m.id, asset_id=asset.id, version_id=v.id, data=jpeg(),
                provider="cloudflare", model=MODEL_LABEL, steps=None,
            )
            db_session.commit()
        v = _next_version(db_session, m.id, asset.id, 90)
        with pytest.raises(ImageQuotaExceeded) as exc:
            st.store(
                m.id, asset_id=asset.id, version_id=v.id, data=jpeg(),
                provider="cloudflare", model=MODEL_LABEL, steps=None,
            )
        assert exc.value.scope == "daily generation"

    def test_daily_storage_quota_enforced(self, db_session):
        m = make_merchant(db_session, "store-quota-b")
        asset, version = seed_asset_with_version(db_session, m)
        with pytest.raises(ImageQuotaExceeded) as exc:
            storage(db_session, daily_storage_quota_bytes=10).store(
                m.id, asset_id=asset.id, version_id=version.id, data=jpeg(),
                provider="cloudflare", model=MODEL_LABEL, steps=None,
            )
        assert exc.value.scope == "daily storage"

    def test_quota_is_per_merchant(self, db_session):
        a = make_merchant(db_session, "quota-a")
        b = make_merchant(db_session, "quota-b")
        asset_a, version_a = seed_asset_with_version(db_session, a)
        st = storage(db_session, daily_quota=1)
        st.store(
            a.id, asset_id=asset_a.id, version_id=version_a.id, data=jpeg(),
            provider="cloudflare", model=MODEL_LABEL, steps=None,
        )
        db_session.commit()
        # A different merchant is unaffected by A's usage.
        asset_b, version_b = seed_asset_with_version(db_session, b)
        st.store(
            b.id, asset_id=asset_b.id, version_id=version_b.id, data=jpeg(),
            provider="cloudflare", model=MODEL_LABEL, steps=None,
        )
        db_session.commit()
        assert st.usage_today(b.id)["images"] == 1

    def test_advisory_lock_key_is_stable_and_merchant_specific(self):
        """Two merchants must never share a quota lock, and the same
        merchant must always get the same key so the lock actually works."""
        from backend.app.services.design_asset_storage import _advisory_key

        a, b = uuid.uuid4(), uuid.uuid4()
        assert _advisory_key("image-quota", a) == _advisory_key("image-quota", a)
        assert _advisory_key("image-quota", a) != _advisory_key("image-quota", b)
        assert _advisory_key("image-quota", a) != _advisory_key("other", a)
        for k in (_advisory_key("image-quota", a), _advisory_key("other", b)):
            assert 0 <= k <= 0x7FFF_FFFF_FFFF_FFFF

    def test_cross_merchant_read_refused(self, db_session):
        a = make_merchant(db_session, "iso-a")
        b = make_merchant(db_session, "iso-b")
        asset, version = seed_asset_with_version(db_session, a)
        st = storage(db_session)
        ref = st.store(
            a.id, asset_id=asset.id, version_id=version.id, data=jpeg(),
            provider="cloudflare", model=MODEL_LABEL, steps=None,
        )
        db_session.commit()
        with pytest.raises(ImageNotFound):
            st.read_bytes(b.id, ref.id)
        with pytest.raises(ImageNotFound):
            st.get_ref(b.id, ref.id)

    def test_missing_id_is_same_error_as_foreign_id(self, db_session):
        """Identical error for 'absent' and 'someone else's' so the endpoint
        cannot be used to probe for other tenants' ids."""
        a = make_merchant(db_session, "probe-a")
        b = make_merchant(db_session, "probe-b")
        st = storage(db_session)
        with pytest.raises(ImageNotFound) as absent:
            st.get_ref(a.id, uuid.uuid4())
        with pytest.raises(ImageNotFound) as foreign:
            st.get_ref(b.id, uuid.uuid4())
        assert str(absent.value).startswith("RENDERED_ASSET_NOT_FOUND")
        assert str(foreign.value).startswith("RENDERED_ASSET_NOT_FOUND")

    def test_listing_is_merchant_scoped(self, db_session):
        a = make_merchant(db_session, "list-a")
        b = make_merchant(db_session, "list-b")
        asset, version = seed_asset_with_version(db_session, a)
        storage(db_session).store(
            a.id, asset_id=asset.id, version_id=version.id, data=jpeg(),
            provider="cloudflare", model=MODEL_LABEL, steps=None,
        )
        db_session.commit()
        assert storage(db_session).list_for_merchant(a.id)
        assert storage(db_session).list_for_merchant(b.id) == []
        assert storage(db_session).list_for_asset(b.id, asset.id) == []

    def test_usage_today_counts_only_this_merchant(self, db_session):
        a = make_merchant(db_session, "usage-a")
        b = make_merchant(db_session, "usage-b")
        asset, version = seed_asset_with_version(db_session, a)
        payload = jpeg()
        storage(db_session).store(
            a.id, asset_id=asset.id, version_id=version.id, data=payload,
            provider="cloudflare", model=MODEL_LABEL, steps=None,
        )
        db_session.commit()
        assert storage(db_session).usage_today(a.id) == {
            "images": 1, "bytes": len(payload)
        }
        assert storage(db_session).usage_today(b.id) == {"images": 0, "bytes": 0}
# ── 8. service: full success path and version semantics ────────────────


class TestServiceGeneration:
    def test_success_persists_asset_version_and_bytes(self, db_session, enabled):
        m = make_merchant(db_session, "svc-ok")
        asset = seed_asset(db_session, m)
        payload = jpeg(320, 240)
        svc = DesignerService(db_session)
        gen = fake_generator(payload)
        out = svc.request_image_generation(
            m.id, asset.id, prompt="a warm scene", steps=4, generator=gen
        )
        db_session.commit()

        assert out["status"] == "completed"
        assert out["provider"] == "cloudflare"
        assert out["width"] == 320 and out["height"] == 240
        assert out["byte_size"] == len(payload)
        assert out["asset_reference"], "a real reference only on real success"

        row = db_session.get(RenderedAsset, uuid.UUID(out["rendered_asset_id"]))
        assert row is not None
        assert bytes(row.image_bytes) == payload
        assert row.merchant_id == m.id
        assert row.asset_id == asset.id
        assert row.version_id == uuid.UUID(out["version_id"])

        refreshed = db_session.get(DesignAsset, asset.id)
        assert refreshed.kind == DesignAssetKind.rendered_image
        # Never auto-approved: a human still reviews it.
        assert refreshed.review_status.value == "pending_review"

    def test_prompt_defaults_to_the_brief_objective(self, db_session, enabled):
        m = make_merchant(db_session, "svc-default")
        asset = seed_asset(db_session, m)
        gen = fake_generator(jpeg())
        DesignerService(db_session).request_image_generation(
            m.id, asset.id, generator=gen
        )
        db_session.commit()
        assert gen.calls, "a prompt must have been supplied"
        assert gen.calls[0][0], "the default prompt must not be empty"

    def test_regeneration_creates_a_new_version_and_keeps_old_bytes(
        self, db_session, enabled
    ):
        m = make_merchant(db_session, "svc-append")
        asset = seed_asset(db_session, m)
        svc = DesignerService(db_session)

        first = jpeg(64, 48)
        out1 = svc.request_image_generation(
            m.id, asset.id, prompt="first", generator=fake_generator(first)
        )
        db_session.commit()
        first_ref = uuid.UUID(out1["rendered_asset_id"])

        second = jpeg(128, 96)
        out2 = svc.request_image_generation(
            m.id, asset.id, prompt="second", generator=fake_generator(second)
        )
        db_session.commit()
        second_ref = uuid.UUID(out2["rendered_asset_id"])

        assert first_ref != second_ref
        assert out1["version_id"] != out2["version_id"]
        # The earlier bytes are untouched — append-only preserved.
        st = storage(db_session)
        assert st.read_bytes(m.id, first_ref)[1] == first
        assert st.read_bytes(m.id, second_ref)[1] == second
        versions = db_session.scalars(
            select(DesignAssetVersion)
            .where(DesignAssetVersion.asset_id == asset.id)
            .order_by(DesignAssetVersion.version)
        ).all()
        assert len(versions) >= 2

    def test_provider_failure_stores_nothing(self, db_session, enabled):
        m = make_merchant(db_session, "svc-fail")
        asset = seed_asset(db_session, m)
        gen = fake_generator(error=ImageGenerationError("PROVIDER_TIMEOUT", "timed out"))
        out = DesignerService(db_session).request_image_generation(
            m.id, asset.id, prompt="x", generator=gen
        )
        db_session.rollback()
        assert out["status"] == "failed"
        assert out["asset_reference"] is None
        assert (
            db_session.scalar(
                select(RenderedAsset).where(RenderedAsset.merchant_id == m.id)
            )
            is None
        )

    def test_non_jpeg_from_provider_stores_nothing(self, db_session, enabled):
        m = make_merchant(db_session, "svc-notjpeg")
        asset = seed_asset(db_session, m)
        gen = fake_generator(b"<html>oops</html>")
        out = DesignerService(db_session).request_image_generation(
            m.id, asset.id, prompt="x", generator=gen
        )
        db_session.rollback()
        assert out["status"] != "completed"
        assert (
            db_session.scalar(
                select(RenderedAsset).where(RenderedAsset.merchant_id == m.id)
            )
            is None
        )

    def test_invalid_prompt_never_calls_the_provider(self, db_session, enabled):
        m = make_merchant(db_session, "svc-badprompt")
        asset = seed_asset(db_session, m)
        gen = fake_generator(jpeg())
        out = DesignerService(db_session).request_image_generation(
            m.id, asset.id, prompt="x" * 5000, generator=gen
        )
        db_session.rollback()
        assert out["status"] == "failed"
        assert out["code"] == "INVALID_PROMPT"
        assert gen.calls == [], "an invalid prompt must not spend provider quota"

    def test_quota_exhausted_is_reported_not_bypassed(self, db_session, enabled):
        m = make_merchant(db_session, "svc-quota")
        asset = seed_asset(db_session, m)
        svc = DesignerService(db_session)
        svc._storage = lambda: storage(db_session, daily_quota=0)  # type: ignore[method-assign]
        out = svc.request_image_generation(
            m.id, asset.id, prompt="x", generator=fake_generator(jpeg())
        )
        db_session.rollback()
        assert out["status"] != "completed"
        assert out["asset_reference"] is None

    def test_cross_merchant_generation_refused(self, db_session, enabled):
        a = make_merchant(db_session, "xmer-a")
        b = make_merchant(db_session, "xmer-b")
        asset = seed_asset(db_session, a)
        gen = fake_generator(jpeg())
        from backend.app.services.designer_service import DesignerNotFound

        with pytest.raises(DesignerNotFound):
            DesignerService(db_session).request_image_generation(
                b.id, asset.id, prompt="x", generator=gen
            )
        assert gen.calls == [], "ownership must be checked before any spend"


# ── 9. HTTP surface: authenticated, merchant-scoped, never public ──────


class TestRenderedAssetRoutes:
    """Image bytes are reachable ONLY through an authenticated, tenant-scoped
    route. There is no static mount and no public URL."""

    @pytest.fixture()
    def owner_and_image(self, db_session):
        """One merchant with a stored image, plus a second merchant.

        Committed, because the TestClient uses a different session over the
        same database.
        """
        a = make_merchant(db_session, "http-a")
        b = make_merchant(db_session, "http-b")
        asset, version = seed_asset_with_version(db_session, a)
        payload = jpeg(96, 64)
        ref = storage(db_session).store(
            a.id, asset_id=asset.id, version_id=version.id, data=payload,
            provider="cloudflare", model=MODEL_LABEL, steps=4,
            created_by="agent:DesignerAgent",
        )
        db_session.commit()
        return {"a": a, "b": b, "asset": asset, "ref": ref, "payload": payload}

    def test_owner_can_fetch_their_image(self, client, owner_and_image):
        resp = client.get(
            f"/api/designer/rendered-assets/{owner_and_image['ref'].id}/content",
            params={"merchant_id": str(owner_and_image["a"].id)},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/jpeg")
        assert resp.content == owner_and_image["payload"]
        # Private, never a shared-cache public entry.
        assert "private" in resp.headers.get("cache-control", "")
        assert "nosniff" in resp.headers.get("x-content-type-options", "")

    def test_response_carries_a_verifiable_digest(self, client, owner_and_image):
        resp = client.get(
            f"/api/designer/rendered-assets/{owner_and_image['ref'].id}/content",
            params={"merchant_id": str(owner_and_image["a"].id)},
        )
        assert (
            resp.headers["x-image-sha256"]
            == hashlib.sha256(owner_and_image["payload"]).hexdigest()
        )

    def test_cross_merchant_fetch_is_404(self, client, owner_and_image):
        """A foreign merchant gets the same 404 as a missing id, so the route
        cannot be used to discover that an image exists."""
        resp = client.get(
            f"/api/designer/rendered-assets/{owner_and_image['ref'].id}/content",
            params={"merchant_id": str(owner_and_image["b"].id)},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "RENDERED_ASSET_NOT_FOUND"

    def test_missing_image_is_404(self, client, owner_and_image):
        resp = client.get(
            f"/api/designer/rendered-assets/{uuid.uuid4()}/content",
            params={"merchant_id": str(owner_and_image["a"].id)},
        )
        assert resp.status_code == 404

    def test_malformed_id_is_400(self, client, owner_and_image):
        resp = client.get(
            "/api/designer/rendered-assets/not-a-uuid/content",
            params={"merchant_id": str(owner_and_image["a"].id)},
        )
        assert resp.status_code == 400

    def test_listing_is_scoped_and_metadata_only(self, client, owner_and_image):
        own = client.get(
            "/api/designer/rendered-assets",
            params={"merchant_id": str(owner_and_image["a"].id)},
        )
        assert own.status_code == 200
        body = own.json()
        assert body["total"] == 1
        assert body["usage_today"]["images"] == 1
        entry = body["assets"][0]
        assert entry["sha256"] and entry["width"] == 96
        # Metadata only: the listing must never carry the payload.
        assert "image_bytes" not in entry and "data" not in entry

        other = client.get(
            "/api/designer/rendered-assets",
            params={"merchant_id": str(owner_and_image["b"].id)},
        )
        assert other.json()["total"] == 0

    def test_generation_endpoint_requires_authentication(self, client, owner_and_image, monkeypatch):
        """No credentials at all -> refused, not served.

        The suite runs with AUTH_MODE=optional, which deliberately permits an
        anonymous fallback so other tests can work. Production runs
        AUTH_MODE=required, so the auth mode is tightened here to prove the
        route is genuinely gated rather than relying on that test-only mode.
        """
        monkeypatch.setenv("AUTH_MODE", "required")
        get_settings.cache_clear()
        try:
            assert client.get("/api/designer/rendered-assets").status_code == 401
            assert (
                client.get(
                    f"/api/designer/rendered-assets/{owner_and_image['ref'].id}/content"
                ).status_code
                == 401
            )
        finally:
            get_settings.cache_clear()

    def test_generation_endpoint_is_not_anonymous(self, client, owner_and_image, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "required")
        get_settings.cache_clear()
        try:
            resp = client.post(
                f"/api/designer/assets/{owner_and_image['asset'].id}/image-generation",
                json={},
            )
            assert resp.status_code == 401
        finally:
            get_settings.cache_clear()

    def test_every_rendered_asset_route_is_dependency_gated(self):
        """Protection comes from the shared tenant dependency, not ad-hoc checks.

        Asserted structurally — by the ORIGIN module of the resolved
        dependency — so a future refactor cannot quietly drop the dependency
        from one handler. Matching on module rather than name is deliberate:
        ``operator_ctx`` is itself a ``Depends(...)`` wrapper, so its
        ``__name__`` is an implementation detail.
        """
        import inspect

        from backend.app.api.deps import __name__ as deps_module
        from backend.app.api.routes import designer as designer_routes

        checked = 0
        for r in designer_routes.router.routes:
            if "rendered" not in r.path and "image-generation" not in r.path:
                continue
            gated = False
            for name, p in inspect.signature(r.endpoint).parameters.items():
                if p.default is inspect.Parameter.empty:
                    continue
                target = getattr(p.default, "dependency", None)
                if callable(target) and getattr(target, "__module__", "") == deps_module:
                    gated = True
                    break
            assert gated, f"{r.path} is not gated by a backend.app.api.deps dependency"
            checked += 1
        assert checked >= 4

    def test_status_reports_unavailable_when_disabled(self, client, disabled, db_session):
        m = make_merchant(db_session, "http-status")
        db_session.commit()
        body = client.get(
            "/api/designer/image-generation", params={"merchant_id": str(m.id)}
        ).json()
        assert body["status"] == "unavailable"
        assert body["asset_reference"] is None

    def test_cross_merchant_generate_is_404(self, client, enabled, owner_and_image):
        resp = client.post(
            f"/api/designer/assets/{owner_and_image['asset'].id}/image-generation",
            json={},
            params={"merchant_id": str(owner_and_image["b"].id)},
        )
        assert resp.status_code == 404

    def test_generate_with_invalid_steps_is_422(self, client, enabled, owner_and_image):
        resp = client.post(
            f"/api/designer/assets/{owner_and_image['asset'].id}/image-generation",
            json={"steps": 99},
            params={"merchant_id": str(owner_and_image["a"].id)},
        )
        assert resp.status_code == 422

    def test_generate_with_oversize_prompt_is_422(self, client, enabled, owner_and_image):
        resp = client.post(
            f"/api/designer/assets/{owner_and_image['asset'].id}/image-generation",
            json={"prompt": "x" * 3000},
            params={"merchant_id": str(owner_and_image["a"].id)},
        )
        assert resp.status_code == 422


# ── 10. live provider test is opt-in ───────────────────────────────────


def test_live_provider_is_opt_in():
    """A live call is never made by the suite.

    If RAZORGROWTH_LIVE_IMAGE_TEST is not set, this asserts only that the
    live path stays disabled — and says so, rather than pretending to have
    run against Cloudflare.
    """
    if os.environ.get("RAZORGROWTH_LIVE_IMAGE_TEST") != "1":
        pytest.skip(
            "live Cloudflare call not requested "
            "(set RAZORGROWTH_LIVE_IMAGE_TEST=1 to run it)"
        )
    s = get_settings()
    if not s.IMAGE_GENERATION_ENABLED or not s.CLOUDFLARE_ACCOUNT_ID:
        pytest.skip("live test requested but image generation is not configured")
    with CloudflareImageGenerator(
        account_id=s.CLOUDFLARE_ACCOUNT_ID,
        api_token=s.CLOUDFLARE_API_TOKEN,
        timeout_seconds=s.IMAGE_REQUEST_TIMEOUT_SECONDS,
    ) as gen:
        out = gen.generate("a plain grey square, flat colour")
    assert out.data.startswith(b"\xff\xd8")
    print(
        f"\n[live] generated {len(out.data)} bytes via {out.provider}/{out.model}"
    )
