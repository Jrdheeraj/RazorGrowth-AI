"""
Cloudflare Workers AI failure-classification and no-retry-storm guarantees.

Every test here is mocked at the OpenAI-SDK boundary. No live
Cloudflare call is made anywhere in this module.

Coverage:
  · Cloudflare daily-allocation exhaustion (429 / code 4006) -> quota_exhausted
  · the exact TPD-exhaustion response observed in production -> quota_exhausted
  · daily quota exhaustion is NOT retried (the actual defect this fixes)
  · transient RPM/TPM throttling IS retried and honours Retry-After
  · a Retry-After far in the future ends the loop instead of stalling
  · auth / model-access / malformed-request errors fail fast
  · backoff carries jitter (no lockstep stampede)
  · the raised LLMError carries a category and leaks no secret
  · Designer Agent reports the category and creates no records on failure
  · image generation never consults the LLM
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai
import pytest

from backend.app.ai.llm.provider import (
    CloudflareProvider,
    LLMError,
    LLMFailureCategory,
    RETRYABLE_CATEGORIES,
    SUPPORTED_LLM_PROVIDERS,
    classify_llm_failure,
    describe_llm_failure,
    resolve_llm_provider,
)

FAKE_KEY = "cf_fake_token_DO_NOT_LEAK_1234567890"
FAKE_ACCOUNT = "0123456789abcdef0123456789abcdef"
CF_URL = (
    f"https://api.cloudflare.com/client/v4/accounts/{FAKE_ACCOUNT}"
    "/ai/v1/chat/completions"
)


# ── Fixtures / builders ──────────────────────────────────────────────────

def _completion(content: str = '{"ok": true}') -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(total_tokens=42),
    )


def _api_error(cls, status: int, message: str = "", *, headers=None, body=None):
    """Build a genuine openai SDK exception with a real status + body."""
    request = httpx.Request("POST", CF_URL)
    if body is None:
        body = {"error": {"message": message, "type": "tokens",
                          "code": "rate_limit_exceeded"}} if message else None
    response = httpx.Response(status, headers=headers or {}, request=request)
    if body is not None:
        response = httpx.Response(status, headers=headers or {}, json=body, request=request)
    return cls("boom", response=response, body=body)


# The verbatim failure captured live from Groq during the earlier
# investigation that introduced this classification layer. The logic is
# provider-neutral and still applies to any OpenAI-compatible 429; Cloudflare's
# own envelope is pinned separately in TestCloudflareDailyAllocationClassification.
TPD_MESSAGE = (
    "Rate limit reached for model `openai/gpt-oss-120b` in organization "
    "`org_01k24cvd71emk961dhdgrdtv4h` service tier `on_demand` on tokens per "
    "day (TPD): Limit 200000, Used 200001, Requested 1, try again in 21m0.789s."
)


# The verbatim failure captured live from Cloudflare Workers AI.
CLOUDFLARE_DAILY_ALLOCATION = (
    "AiError: AiError: you have used up your daily free allocation of "
    "10,000 neurons, please upgrade to Cloudflare's Workers Paid plan "
    "if you would like to continue usage."
)


def _cloudflare_daily_allocation_exhausted():
    """Cloudflare's real quota envelope: 429 + errors[].code == 4006."""
    request = httpx.Request("POST", CF_URL)
    body = {
        "success": False,
        "errors": [{"code": 4006, "message": CLOUDFLARE_DAILY_ALLOCATION}],
        "result": {},
        "messages": [],
    }
    response = httpx.Response(429, json=body, request=request)
    return openai.RateLimitError("Error code: 429", response=response, body=body)


def _tpd_exhausted():
    return _api_error(
        openai.RateLimitError, 429, TPD_MESSAGE, headers={"retry-after": "1263"}
    )


def _tpm_throttled():
    return _api_error(
        openai.RateLimitError, 429,
        "Rate limit reached for model on tokens per minute (TPM): Limit 12000, "
        "Used 12001, Requested 4000, try again in 6s.",
        headers={"retry-after": "6"},
    )


def _provider(**kwargs) -> CloudflareProvider:
    defaults = dict(api_key=FAKE_KEY, account_id=FAKE_ACCOUNT,
                    timeout=5, max_retries=2, max_tokens=999)
    defaults.update(kwargs)
    return CloudflareProvider(**defaults)


def _generate(p):
    return p.generate("sys", "usr")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Classification
# ─────────────────────────────────────────────────────────────────────────────

class TestFailureClassification:
    def test_real_tpd_exhaustion_is_quota_exhausted(self):
        assert classify_llm_failure(_tpd_exhausted()) == LLMFailureCategory.QUOTA_EXHAUSTED

    def test_tpm_throttle_is_rate_limited(self):
        assert classify_llm_failure(_tpm_throttled()) == LLMFailureCategory.RATE_LIMITED

    def test_rpm_throttle_is_rate_limited(self):
        exc = _api_error(openai.RateLimitError, 429,
                         "Rate limit reached on requests per minute (RPM): Limit 30")
        assert classify_llm_failure(exc) == LLMFailureCategory.RATE_LIMITED

    def test_bare_429_still_counts_as_throttling(self):
        exc = _api_error(openai.RateLimitError, 429, "Rate limit reached")
        assert classify_llm_failure(exc) == LLMFailureCategory.RATE_LIMITED

    def test_quota_exhaustion_is_not_retryable(self):
        assert LLMFailureCategory.QUOTA_EXHAUSTED not in RETRYABLE_CATEGORIES

    def test_auth_error(self):
        exc = _api_error(openai.AuthenticationError, 401, "Invalid API Key")
        assert classify_llm_failure(exc) == LLMFailureCategory.AUTH

    def test_model_not_entitled(self):
        exc = _api_error(openai.PermissionDeniedError, 403, "not permitted for this key")
        assert classify_llm_failure(exc) == LLMFailureCategory.MODEL_UNAVAILABLE

    def test_retired_model_404(self):
        exc = _api_error(openai.NotFoundError, 404, "no such model")
        assert classify_llm_failure(exc) == LLMFailureCategory.MODEL_UNAVAILABLE

    def test_malformed_request_is_its_own_category(self):
        exc = _api_error(openai.BadRequestError, 400, "unsupported response_format")
        assert classify_llm_failure(exc) == LLMFailureCategory.INVALID_REQUEST

    def test_server_error_is_transient(self):
        exc = _api_error(openai.InternalServerError, 500, "server error")
        assert classify_llm_failure(exc) == LLMFailureCategory.TRANSIENT

    def test_timeout_is_transient(self):
        exc = openai.APITimeoutError(request=httpx.Request("POST", CF_URL))
        assert classify_llm_failure(exc) == LLMFailureCategory.TIMEOUT

    def test_unrecognised_exception_fails_fast(self):
        """An unknown exception is more often our bug than the provider's."""
        assert LLMFailureCategory.UNKNOWN not in RETRYABLE_CATEGORIES


# ─────────────────────────────────────────────────────────────────────────────
# 2. No retry storm on an exhausted daily quota  (the actual defect)
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyQuotaIsNotRetried:
    def test_exhausted_quota_makes_exactly_one_request(self):
        """THE regression test.

        Before the fix this made 3 requests and slept 40s against a quota that
        resets in 21 minutes — three guaranteed failures and a stalled agent.
        """
        p = _provider(max_retries=2)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_tpd_exhausted()) as mock_create, \
             patch("backend.app.ai.llm.provider.time.sleep") as mock_sleep:
            with pytest.raises(LLMError):
                _generate(p)
        assert mock_create.call_count == 1, "a dead daily quota must not be retried"
        assert mock_sleep.call_count == 0, "must not sleep on an exhausted quota"

    def test_exhausted_quota_reports_the_category(self):
        p = _provider()
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_tpd_exhausted()), \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError) as ei:
                _generate(p)
        assert ei.value.category == LLMFailureCategory.QUOTA_EXHAUSTED
        assert ei.value.retryable is False

    def test_exhausted_quota_surfaces_the_reset_time(self):
        p = _provider()
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_tpd_exhausted()), \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError) as ei:
                _generate(p)
        assert ei.value.retry_after == pytest.approx(1263, abs=5)

    def test_error_names_the_service_and_says_not_to_retry(self):
        p = _provider()
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_tpd_exhausted()), \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError) as ei:
                _generate(p)
        msg = str(ei.value)
        assert "quota_exhausted" in msg
        copy = describe_llm_failure(ei.value.category, ei.value.retry_after)
        assert "daily token quota" in copy
        assert "will not help" in copy

    def test_last_call_stats_show_no_retries(self):
        p = _provider(max_retries=2)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_tpd_exhausted()), \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError):
                _generate(p)
        assert p.last_call_stats["attempts"] == 1
        assert p.last_call_stats["retries"] == 0
        assert p.last_call_stats["retry_delay_ms"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Transient throttling IS retried, and honours Retry-After
# ─────────────────────────────────────────────────────────────────────────────

class TestTransientThrottlingIsRetried:
    def test_tpm_throttle_recovers_within_the_retry_budget(self):
        p = _provider(max_retries=2)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=[_tpm_throttled(), _completion("ok")]) as mc, \
             patch("backend.app.ai.llm.provider.time.sleep") as ms:
            assert _generate(p) == "ok"
        assert mc.call_count == 2
        assert ms.call_count == 1

    def test_retry_after_hint_is_honoured(self):
        """A 6s Retry-After must be slept for ~6s, not the default 1s."""
        p = _provider(max_retries=2)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=[_tpm_throttled(), _completion("ok")]), \
             patch("backend.app.ai.llm.provider.time.sleep") as ms:
            _generate(p)
        assert ms.call_args_list[0].args[0] == pytest.approx(6, abs=0.01)

    def test_sustained_throttling_still_gives_up(self):
        p = _provider(max_retries=2)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_tpm_throttled()) as mc, \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError) as ei:
                _generate(p)
        assert mc.call_count == 3  # initial + 2 retries, then honest failure
        assert ei.value.category == LLMFailureCategory.RATE_LIMITED

    def test_a_retry_after_far_in_the_future_ends_the_loop(self):
        """A 21-minute hint must not stall the agent; it must be reported."""
        exc = _api_error(openai.RateLimitError, 429, "Rate limit reached",
                         headers={"retry-after": "1263"})
        p = _provider(max_retries=3)
        with patch.object(p._client.chat.completions, "create", side_effect=exc) as mc, \
             patch("backend.app.ai.llm.provider.time.sleep") as ms:
            with pytest.raises(LLMError):
                _generate(p)
        assert mc.call_count == 1
        assert ms.call_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Auth / model-access errors fail fast without retrying
# ─────────────────────────────────────────────────────────────────────────────

class TestNonRetryableFailures:
    @pytest.mark.parametrize(
        "factory, expected",
        [
            (lambda: _api_error(openai.AuthenticationError, 401, "Invalid API Key"),
             LLMFailureCategory.AUTH),
            (lambda: _api_error(openai.PermissionDeniedError, 403, "no access"),
             LLMFailureCategory.MODEL_UNAVAILABLE),
            (lambda: _api_error(openai.NotFoundError, 404, "gone"),
             LLMFailureCategory.MODEL_UNAVAILABLE),
            (lambda: _api_error(openai.BadRequestError, 400, "bad params"),
             LLMFailureCategory.INVALID_REQUEST),
        ],
    )
    def test_makes_exactly_one_request(self, factory, expected):
        p = _provider(max_retries=3)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=factory()) as mc, \
             patch("backend.app.ai.llm.provider.time.sleep") as ms:
            with pytest.raises(LLMError) as ei:
                _generate(p)
        assert mc.call_count == 1, f"{expected} must not be retried"
        assert ms.call_count == 0
        assert ei.value.category == expected
        assert ei.value.retryable is False

    def test_bad_credential_copy_names_the_setting(self):
        copy = describe_llm_failure(LLMFailureCategory.AUTH)
        assert "CLOUDFLARE_API_TOKEN" in copy
        assert "GROQ" not in copy


# ─────────────────────────────────────────────────────────────────────────────
# 5. Backoff jitter (no lockstep stampede)
# ─────────────────────────────────────────────────────────────────────────────

class TestBackoffJitter:
    def _waits(self):
        """Collect the sleeps for a sequence of non-429 transient errors."""
        p = _provider(max_retries=4)
        waits: list[float] = []
        err = _api_error(openai.InternalServerError, 500, "server error")
        with patch.object(p._client.chat.completions, "create", side_effect=err), \
             patch("backend.app.ai.llm.provider.time.sleep", side_effect=waits.append):
            with pytest.raises(LLMError):
                _generate(p)
        return waits

    def test_waits_are_jittered_not_identical(self):
        waits = self._waits()
        assert len(waits) == 4
        # Full jitter => values vary. Deterministic backoff would repeat.
        assert len(set(waits)) > 1, f"backoff must be jittered, got {waits}"

    def test_waits_stay_within_the_exponential_ceiling(self):
        waits = self._waits()
        for i, w in enumerate(waits):
            assert 0 <= w <= float(2 ** i) + 1e-6, f"wait {w} exceeds ceiling at {i}"

    def test_a_429_hint_is_not_jittered_down(self):
        """An explicit Retry-After is a contract; don't shorten it by jitter."""
        p = _provider(max_retries=2)
        waits: list[float] = []
        with patch.object(p._client.chat.completions, "create",
                          side_effect=[_tpm_throttled(), _completion("ok")]), \
             patch("backend.app.ai.llm.provider.time.sleep",
                   side_effect=waits.append):
            _generate(p)
        assert waits[0] == pytest.approx(6, abs=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# 6. The raised error is safe and diagnostic
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorSafety:
    def test_never_leaks_the_api_key(self):
        p = _provider()
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_tpd_exhausted()), \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError) as ei:
                _generate(p)
        blob = f"{ei.value} {ei.value.category} {ei.value.retryable} {ei.value.model}"
        assert FAKE_KEY not in blob

    def test_never_propagates_the_raw_provider_payload(self):
        """The org id and limit figures stay in the log, out of the exception."""
        p = _provider()
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_tpd_exhausted()), \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError) as ei:
                _generate(p)
        assert "org_01k24cvd71emk961dhdgrdtv4h" not in str(ei.value)
        assert "200000" not in str(ei.value)

    def test_carries_provider_and_model(self):
        p = _provider()
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_tpd_exhausted()), \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError) as ei:
                _generate(p)
        assert ei.value.provider == "cloudflare"
        assert ei.value.model == p._model
        assert ei.value.status_code == 429

    def test_every_category_has_human_copy(self):
        for cat in (
            LLMFailureCategory.QUOTA_EXHAUSTED,
            LLMFailureCategory.RATE_LIMITED,
            LLMFailureCategory.AUTH,
            LLMFailureCategory.MODEL_UNAVAILABLE,
            LLMFailureCategory.INVALID_REQUEST,
            LLMFailureCategory.TIMEOUT,
            LLMFailureCategory.TRANSIENT,
            LLMFailureCategory.UNKNOWN,
        ):
            copy = describe_llm_failure(cat)
            assert copy and len(copy) > 20, f"{cat} has no usable copy"
            assert FAKE_KEY not in copy

    def test_default_llm_error_still_constructs(self):
        """Back-compat: LLMError('x') must keep working for existing callers."""
        err = LLMError("x")
        assert str(err) == "x"
        assert err.category == LLMFailureCategory.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# 7. Image generation must never consult the LLM
# ─────────────────────────────────────────────────────────────────────────────

class TestImagePathIsLLMFree:
    def test_cloudflare_generator_has_no_llm_dependency(self):
        import inspect

        from backend.app.integrations import cloudflare_image as cfi

        src = inspect.getsource(cfi)
        for token in ("generate_structured", "build_llm_provider", "chat/completions"):
            assert token not in src, f"image provider must not reference {token}"

    def test_designer_service_generation_references_no_llm(self):
        import inspect

        from backend.app.services.designer_service import DesignerService

        src = inspect.getsource(DesignerService.request_image_generation)
        for token in ("ctx.llm", "generate_structured", "build_llm_provider"):
            assert token not in src, f"image generation must not reference {token}"

    def test_generation_works_with_no_llm_configured(self):
        """An LLM failure cannot block image generation."""
        import base64

        from backend.app.integrations.cloudflare_image import CloudflareImageGenerator

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "result": {"image": base64.b64encode(b"\xff\xd8\xff\xd9").decode()},
                    "success": True, "errors": [], "messages": [],
                },
            )

        gen = CloudflareImageGenerator(
            account_id="acct", api_token="tok",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        assert gen.generate("a scene").data  # no LLM in the path at all


# ─────────────────────────────────────────────────────────────────────────────
# 9. One shared provider resolver  (the config-discrepancy fix)
# ─────────────────────────────────────────────────────────────────────────────

class _FakeSettings:
    def __init__(self, *, provider, cf_token="", cf_account=FAKE_ACCOUNT,
                 generic="", model="m", cf_model="@cf/zai-org/glm-4.7-flash"):
        self.LLM_PROVIDER = provider
        self.CLOUDFLARE_API_TOKEN = cf_token
        self.CLOUDFLARE_ACCOUNT_ID = cf_account
        self.LLM_API_KEY = generic
        self.LLM_MODEL = model
        self.CLOUDFLARE_TEXT_MODEL = cf_model
        # Read by the call sites when building the provider.
        self.LLM_REQUEST_TIMEOUT = 5
        self.LLM_MAX_RETRIES = 0
        self.LLM_MAX_TOKENS = 64


class TestSharedProviderResolution:
    """Three call sites used to disagree about which provider was live."""

    def test_unsupported_provider_name_falls_back_to_real_cf_credentials(self):
        """A stale provider NAME must not cost us a working credential."""
        r = resolve_llm_provider(
            _FakeSettings(provider="openrouter", cf_token="cf_real", generic="")
        )
        assert r is not None
        assert r.name == "cloudflare"
        assert r.model == "@cf/zai-org/glm-4.7-flash"
        assert r.account_id == FAKE_ACCOUNT
        assert r.used_fallback is True

    def test_the_resolved_name_is_always_buildable(self):
        """Never hand the factory a name it would reject."""
        for provider in ("openrouter", "anthropic", "", "  ", "groq-typo"):
            r = resolve_llm_provider(
                _FakeSettings(provider=provider, cf_token="cf_x", generic="")
            )
            assert r is not None, f"{provider!r} should still resolve via Cloudflare"
            assert r.name in SUPPORTED_LLM_PROVIDERS, f"{r.name!r} is not buildable"

    def test_explicit_supported_provider_with_its_key_wins(self):
        r = resolve_llm_provider(
            _FakeSettings(provider="openai", cf_token="", generic="sk-o",
                           model="gpt-4o")
        )
        assert (r.name, r.api_key, r.model) == ("openai", "sk-o", "gpt-4o")
        assert r.used_fallback is False

    def test_explicit_cloudflare_is_not_flagged_as_a_fallback(self):
        r = resolve_llm_provider(
            _FakeSettings(provider="cloudflare", cf_token="cf_g")
        )
        assert r.name == "cloudflare"
        assert r.used_fallback is False

    def test_no_key_anywhere_resolves_to_none(self):
        assert resolve_llm_provider(
            _FakeSettings(provider="openrouter", cf_token="", generic="")
        ) is None

    def test_unsupported_name_without_any_key_is_none(self):
        assert resolve_llm_provider(
            _FakeSettings(provider="openrouter", cf_token="  ", generic="  ")
        ) is None

    def test_cloudflare_needs_both_credentials_not_just_a_token(self):
        """Half a Cloudflare config is not a usable provider."""
        assert resolve_llm_provider(
            _FakeSettings(provider="cloudflare", cf_token="cf_x",
                           cf_account="")
        ) is None
        assert resolve_llm_provider(
            _FakeSettings(provider="cloudflare", cf_token="")
        ) is None

    def test_builds_a_real_provider(self):
        r = resolve_llm_provider(
            _FakeSettings(provider="openrouter", cf_token=FAKE_KEY)
        )
        built = r.build(timeout=5, max_retries=0, max_tokens=64)
        assert isinstance(built, CloudflareProvider)
        assert built.provider_name == "cloudflare"
        assert FAKE_ACCOUNT in str(built._client.base_url)

    def test_never_leaks_the_key_into_a_repr(self):
        """A repr lands in tracebacks and logs, so it must not carry the key."""
        r = resolve_llm_provider(
            _FakeSettings(provider="openrouter", cf_token=FAKE_KEY)
        )
        assert FAKE_KEY not in f"{r!r}"
        assert FAKE_KEY not in describe_llm_failure(LLMFailureCategory.AUTH)

    def test_a_traceback_cannot_expose_the_key(self):
        r = resolve_llm_provider(
            _FakeSettings(provider="openrouter", cf_token=FAKE_KEY)
        )
        try:
            raise RuntimeError(f"provider resolved: {r!r}")
        except RuntimeError:
            import traceback

            assert FAKE_KEY not in traceback.format_exc()

    def test_all_call_sites_agree_on_the_provider(self):
        """The regression that mattered: three routes, one answer.

        The two call sites bind ``get_settings`` differently, so BOTH patch
        targets are needed:
          * ``routes/ai.py`` imports it at module level -> patch the route's
            own name,
          * ``routes/designer.py::_audit_llm`` imports it *inside* the function
            -> patch the source module, which it re-reads on every call.

        Patching only ``backend.app.core.config.get_settings`` used to look
        correct but silently left the module-level import reading the real
        cached singleton, so this test passed for the wrong reason (whatever
        the developer's local .env held) rather than the one it claims.
        """
        from backend.app.api.routes.ai import _get_llm
        from backend.app.api.routes.designer import _audit_llm

        settings = _FakeSettings(provider="openrouter", cf_token=FAKE_KEY)
        with patch(
            "backend.app.api.routes.ai.get_settings", return_value=settings
        ), patch(
            "backend.app.core.config.get_settings", return_value=settings
        ):
            assert type(_get_llm()) is CloudflareProvider
            assert type(_audit_llm()) is CloudflareProvider


# ─────────────────────────────────────────────────────────────────────────────
# 8. Designer Agent failure handling
# ─────────────────────────────────────────────────────────────────────────────

class TestDesignerAgentFailureHandling:
    def _run_with(self, exc):
        """Run the Designer's brief parse with a failing LLM.

        Uses the real `db_session` fixture so the context is genuine; the LLM
        is the only thing stubbed.
        """
        import uuid

        from backend.app.agents.designer_agent import DesignerAgent
        from backend.app.agents.base import AgentContext, AgentResult

        agent = DesignerAgent()

        class _Boom:
            last_call_stats = {"attempts": 3, "retries": 2}

            def generate_structured(self, *a, **kw):
                raise exc

        ctx = AgentContext(db=self.db, merchant_id=uuid.uuid4(), llm=_Boom())
        result = AgentResult(agent_name="designer")
        spec = agent._parse_brief(ctx, result, {"objective": "o"})
        return spec, result

    @pytest.fixture(autouse=True)
    def _needs_db(self, db_session):
        self.db = db_session

    def test_quota_failure_records_the_category(self):
        spec, result = self._run_with(
            LLMError("x", category=LLMFailureCategory.QUOTA_EXHAUSTED,
                     retry_after=1263, retryable=False)
        )
        assert spec is None, "a failed brief must never be fabricated"
        assert "brief_generation_failed:quota_exhausted" in result.errors

    def test_failure_does_not_dump_a_raw_payload_into_activity(self):
        _, result = self._run_with(
            LLMError("LLM call failed: quota_exhausted",
                     category=LLMFailureCategory.QUOTA_EXHAUSTED)
        )
        joined = " ".join(result.errors)
        assert FAKE_KEY not in joined
        assert "org_01k24" not in joined

    @pytest.mark.parametrize(
        "category",
        [
            LLMFailureCategory.QUOTA_EXHAUSTED,
            LLMFailureCategory.RATE_LIMITED,
            LLMFailureCategory.AUTH,
            LLMFailureCategory.MODEL_UNAVAILABLE,
        ],
    )
    def test_no_llm_configured_is_still_reported(self, category):
        spec, result = self._run_with(LLMError("x", category=category))
        assert spec is None
        assert any(e.startswith("brief_generation_failed:") for e in result.errors)

    def test_a_failed_brief_makes_the_run_failed_not_completed(self, monkeypatch):
        """The workspace must never report work that was not produced."""
        import uuid

        from backend.app.agents.base import AgentContext
        from backend.app.agents.designer_agent import DesignerAgent

        class _Boom:
            last_call_stats = {"attempts": 1, "retries": 0}

            def generate_structured(self, *a, **kw):
                raise LLMError("x", category=LLMFailureCategory.QUOTA_EXHAUSTED)

        # Ground the run: with no observations the agent honestly refuses for a
        # different reason and never reaches the LLM at all.
        monkeypatch.setattr(
            DesignerAgent,
            "_gather_observations",
            lambda self, ctx, merchant_id, objective: {
                "objective": objective or "Refresh the creative",
                "grounded_fact_count": 1,
                "radar_signals": [{"id": "s1", "title": "measured"}],
                "radar_opportunities": [],
                "segments": [],
                "rag": {"status": "ok", "verified_facts": [{"id": "f1", "text": "m"}]},
                "marketing_findings": {},
                "product_findings": {},
            },
        )

        agent = DesignerAgent()
        ctx = AgentContext(db=self.db, merchant_id=uuid.uuid4(), llm=_Boom(),
                           mode="growth_team")
        result = agent.execute(ctx)
        assert result.status == "failed", "a run that produced no brief must not read as completed"
        assert "brief_generation_failed:quota_exhausted" in result.errors
        assert result.output.get("brief_persisted") is False


# ─────────────────────────────────────────────────────────────────────────────
# 1b. Cloudflare's real daily-allocation envelope
# ─────────────────────────────────────────────────────────────────────────────

class TestCloudflareDailyAllocationClassification:
    """The exact 429 Cloudflare returns when the daily allocation is spent.

    This is the failure that actually occurred against this account, so it is
    pinned against the verbatim payload rather than a paraphrase. The property
    under test is that an exhausted DAILY allocation is never mistaken for a
    transient per-minute throttle: the two look identical on the wire (both
    HTTP 429) but only one can be helped by retrying.
    """

    def test_verified_against_the_real_envelope_shape(self):
        exc = _cloudflare_daily_allocation_exhausted()
        assert exc.status_code == 429
        assert exc.body["errors"][0]["code"] == 4006

    def test_classified_as_quota_exhausted_not_rate_limited(self):
        assert (
            classify_llm_failure(_cloudflare_daily_allocation_exhausted())
            == LLMFailureCategory.QUOTA_EXHAUSTED
        )

    def test_not_retryable(self):
        assert (
            LLMFailureCategory.QUOTA_EXHAUSTED not in RETRYABLE_CATEGORIES
        )

    def test_makes_exactly_one_request_and_never_sleeps(self):
        p = _provider(max_retries=3)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_cloudflare_daily_allocation_exhausted()) as mc, \
             patch("backend.app.ai.llm.provider.time.sleep") as ms:
            with pytest.raises(LLMError) as ei:
                _generate(p)
        assert mc.call_count == 1, "an exhausted daily allocation must not be retried"
        assert ms.call_count == 0
        assert ei.value.category == LLMFailureCategory.QUOTA_EXHAUSTED
        assert ei.value.retryable is False
        assert ei.value.provider == "cloudflare"

    def test_does_not_propagate_the_provider_payload(self):
        """The account id and allocation figures stay in the log, not the error."""
        p = _provider()
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_cloudflare_daily_allocation_exhausted()), \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError) as ei:
                _generate(p)
        blob = f"{ei.value} {ei.value.category} {ei.value.retryable}"
        assert "neurons" not in blob
        assert "4006" not in blob
        assert FAKE_ACCOUNT not in blob
        assert FAKE_KEY not in blob

    def test_user_copy_says_waiting_will_not_help(self):
        copy = describe_llm_failure(LLMFailureCategory.QUOTA_EXHAUSTED)
        assert "quota" in copy.lower()
        assert "will not help" in copy

    def test_a_plain_429_is_still_treated_as_transient_throttling(self):
        """The two must stay distinguishable: bare 429 retries, 4006 does not."""
        assert (
            classify_llm_failure(_tpm_throttled()) == LLMFailureCategory.RATE_LIMITED
        )
        assert LLMFailureCategory.RATE_LIMITED in RETRYABLE_CATEGORIES
