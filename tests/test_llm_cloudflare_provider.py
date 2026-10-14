"""
Cloudflare Workers AI text-LLM provider tests.

Coverage (inherited from the previous provider-specific suite and extended):
  · Provider selection via build_llm_provider factory ("cloudflare" | "openai")
  · CloudflareProvider configuration (account-scoped base_url, timeout,
    retries, max_tokens, model) and the account-id requirement
  · Missing-credential behaviour (Settings defaults + /api/ai 503)
  · Timeout / retry behaviour (mocked transient errors — zero network)
  · Successful response handling + usage/request-correlation metadata
  · Structured output parsing + Pydantic validation
  · Cloudflare's DAILY ALLOCATION limit (429 / code 4006) is classified as
    quota-exhausted and is NEVER retried — the single most important
    no-retry-storm guarantee for this provider
  · No provider fallback and no secret leakage

All interactions are mocked at the OpenAI-SDK client boundary; no live
Cloudflare API calls are made anywhere in this module. Live verification is a
separate, explicitly-labelled concern (see scripts/verify_cloudflare_llm.py).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai
import pytest

from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.ai.llm.models import GrowthAnalysisResult
from backend.app.ai.llm.provider import (
    CloudflareProvider,
    LLMError,
    LLMFailureCategory,
    LLMValidationError,
    OpenAIProvider,
    build_llm_provider,
)

# Distinctive fake credential so we can assert it never leaks into errors/logs.
FAKE_KEY = "cf_fake_token_DO_NOT_LEAK_1234567890"
FAKE_ACCOUNT = "0123456789abcdef0123456789abcdef"


def _completion(content: str, *, request_id: str = "cf-req-1",
                total_tokens: int = 42) -> SimpleNamespace:
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(total_tokens=total_tokens, prompt_tokens=10,
                            completion_tokens=total_tokens - 10)
    return SimpleNamespace(choices=[choice], usage=usage, id=request_id)


def _cf_request() -> httpx.Request:
    return httpx.Request(
        "POST",
        f"https://api.cloudflare.com/client/v4/accounts/{FAKE_ACCOUNT}"
        "/ai/v1/chat/completions",
    )


def _rate_limit_error() -> Exception:
    """A plain per-minute throttle: transient, worth a bounded retry."""
    response = httpx.Response(429, request=_cf_request())
    return openai.RateLimitError("rate limited", response=response, body=None)


def _cloudflare_quota_error() -> Exception:
    """Cloudflare's daily free allocation exhausted (verbatim envelope shape).

    Real payload captured from the live endpoint:
        HTTP 429, success=false, errors[0].code = 4006,
        message mentions the daily free allocation and neurons.
    This is NOT retryable: it can only lift at the next UTC daily reset.
    """
    response = httpx.Response(429, request=_cf_request())
    body = {
        "success": False,
        "errors": [{
            "code": 4006,
            "message": (
                "AiError: AiError: you have used up your daily free allocation "
                "of 10,000 neurons, please upgrade to Cloudflare's Workers "
                "Paid plan if you would like to continue usage."
            ),
        }],
        "result": {},
        "messages": [],
    }
    return openai.RateLimitError("Error code: 429", response=response, body=body)


def _auth_error() -> Exception:
    response = httpx.Response(401, request=_cf_request())
    return openai.AuthenticationError("bad token", response=response, body=None)


def _model_unavailable_error() -> Exception:
    """A model that does not exist / is not entitled — must not be retried."""
    response = httpx.Response(404, request=_cf_request())
    body = {"success": False,
            "errors": [{"code": 7003, "message": "no such model"}]}
    return openai.NotFoundError("not found", response=response, body=body)


def _timeout_error() -> Exception:
    return openai.APITimeoutError(request=_cf_request())


def _cf_provider(**kwargs) -> CloudflareProvider:
    defaults = dict(api_key=FAKE_KEY, account_id=FAKE_ACCOUNT, timeout=5,
                    max_retries=2, max_tokens=999)
    defaults.update(kwargs)
    return CloudflareProvider(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# Provider selection (factory)
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderSelection:
    def test_factory_returns_cloudflare_provider(self):
        p = build_llm_provider(provider="cloudflare", api_key=FAKE_KEY,
                               model="@cf/zai-org/glm-4.7-flash",
                               account_id=FAKE_ACCOUNT)
        assert isinstance(p, CloudflareProvider)

    def test_factory_selection_is_case_insensitive(self):
        p = build_llm_provider(provider="CLOUDFLARE", api_key=FAKE_KEY,
                               model="m", account_id=FAKE_ACCOUNT)
        assert isinstance(p, CloudflareProvider)

    def test_factory_still_supports_openai(self):
        p = build_llm_provider(provider="openai", api_key="sk-x",
                               model="gpt-4o-mini")
        assert isinstance(p, OpenAIProvider)
        assert not isinstance(p, CloudflareProvider)

    def test_unsupported_provider_raises_value_error_listing_supported(self):
        with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER") as exc_info:
            build_llm_provider(provider="anthropic", api_key="x", model="y")
        message = str(exc_info.value)
        assert "openai" in message
        assert "cloudflare" in message

    def test_removed_groq_provider_is_gone(self):
        """Groq is removed: the factory must refuse it, not fall back."""
        import backend.app.ai.llm.provider as provider_mod

        assert not hasattr(provider_mod, "GroqProvider")
        with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
            build_llm_provider(provider="groq", api_key="x", model="y")

    def test_cloudflare_provider_satisfies_base_abstraction(self):
        assert isinstance(_cf_provider(), BaseLLMProvider)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

class TestCloudflareConfiguration:
    def test_client_targets_account_scoped_cloudflare_base_url(self):
        p = _cf_provider()
        url = str(p._client.base_url)
        assert url.startswith(
            "https://api.cloudflare.com/client/v4/accounts/"
        )
        assert FAKE_ACCOUNT in url
        assert url.rstrip("/").endswith("/ai/v1")

    def test_base_url_is_derived_from_account_id(self):
        assert CloudflareProvider.build_base_url("acct-1") == (
            "https://api.cloudflare.com/client/v4/accounts/acct-1/ai/v1"
        )

    @pytest.mark.parametrize("missing", [None, "", "   "])
    def test_missing_account_id_fails_loudly_at_construction(self, missing):
        """A Cloudflare client without an account cannot address any model.

        Failing at construction beats building ``.../accounts//ai/v1`` and
        turning a config mistake into a confusing 404 on every request.
        """
        with pytest.raises(ValueError, match="CLOUDFLARE_ACCOUNT_ID"):
            CloudflareProvider(api_key=FAKE_KEY, account_id=missing)

    def test_constructor_captures_timeout_retry_and_token_config(self):
        p = _cf_provider(timeout=7, max_retries=3, max_tokens=512)
        assert p._timeout == 7
        assert float(p._client.timeout) == 7.0
        assert p._max_retries == 3
        assert p._max_tokens == 512

    def test_model_is_configurable(self):
        p = _cf_provider(model="@cf/meta/llama-3.1-8b-instruct")
        assert p._model == "@cf/meta/llama-3.1-8b-instruct"

    def test_default_model_used_when_none_passed(self):
        p = _cf_provider(model=None)
        assert p._model == CloudflareProvider.DEFAULT_MODEL
        assert p._model == "@cf/zai-org/glm-4.7-flash"

    def test_provider_name_is_cloudflare(self):
        assert _cf_provider().provider_name == "cloudflare"

    def test_settings_expose_cloudflare_text_fields_with_safe_defaults(self):
        from backend.app.core.config import get_settings

        s = get_settings()
        assert hasattr(s, "CLOUDFLARE_TEXT_MODEL")
        assert hasattr(s, "CLOUDFLARE_ACCOUNT_ID")
        assert hasattr(s, "CLOUDFLARE_API_TOKEN")
        # The default model name is a public identifier, not a credential.
        assert s.CLOUDFLARE_TEXT_MODEL == "@cf/zai-org/glm-4.7-flash"

    def test_settings_no_longer_expose_groq_fields(self):
        from backend.app.core.config import get_settings

        s = get_settings()
        assert not hasattr(s, "GROQ_API_KEY")
        assert not hasattr(s, "GROQ_MODEL")

    def test_default_llm_provider_is_cloudflare(self):
        from backend.app.core.config import get_settings

        assert get_settings().LLM_PROVIDER == "cloudflare"

    def test_openai_provider_has_no_cloudflare_base_url(self):
        p = build_llm_provider(provider="openai", api_key="sk-x", model="m")
        assert "api.openai.com" in str(p._client.base_url)


# ─────────────────────────────────────────────────────────────────────────────
# Request handling — success / retry / timeout / structured output
# ─────────────────────────────────────────────────────────────────────────────

class TestCloudflareRequestHandling:
    def test_generate_returns_content_and_passes_config(self):
        p = _cf_provider(model="@cf/zai-org/glm-4.7-flash", max_tokens=777)
        with patch.object(p._client.chat.completions, "create",
                          return_value=_completion("hello from cloudflare")) as mc:
            result = p.generate("sys", "usr")
        assert result == "hello from cloudflare"
        kwargs = mc.call_args.kwargs
        assert kwargs["model"] == "@cf/zai-org/glm-4.7-flash"
        assert kwargs["max_tokens"] == 777
        assert kwargs["messages"][0]["role"] == "system"
        assert kwargs["messages"][1]["role"] == "user"

    def test_generate_structured_uses_json_mode(self):
        p = _cf_provider()
        payload = GrowthAnalysisResult().model_dump_json()
        with patch.object(p._client.chat.completions, "create",
                          return_value=_completion(payload)) as mc:
            result = p.generate_structured("sys", "usr", GrowthAnalysisResult)
        assert isinstance(result, GrowthAnalysisResult)
        assert mc.call_args.kwargs["response_format"] == {"type": "json_object"}

    def test_usage_and_request_id_are_captured(self):
        """Request correlation + usage metadata, without any prompt content."""
        p = _cf_provider()
        with patch.object(p._client.chat.completions, "create",
                          return_value=_completion("ok", request_id="cf-abc",
                                                  total_tokens=57)):
            p.generate("sys", "usr")
        stats = p.last_call_stats
        assert stats["request_id"] == "cf-abc"
        assert stats["total_tokens"] == 57
        assert stats["prompt_tokens"] == 10
        assert stats["completion_tokens"] == 47
        assert stats["attempts"] == 1
        # Safety: stats must never carry the prompt or the credential.
        assert FAKE_KEY not in str(stats)
        assert "sys" not in str(stats)

    def test_transient_rate_limit_is_retried_then_succeeds(self):
        p = _cf_provider(max_retries=2)
        side_effects = [_rate_limit_error(), _rate_limit_error(),
                        _completion("recovered")]
        with patch.object(p._client.chat.completions, "create",
                          side_effect=side_effects) as mc, \
             patch("backend.app.ai.llm.provider.time.sleep") as ms:
            result = p.generate("sys", "usr")
        assert result == "recovered"
        assert mc.call_count == 3          # initial + 2 retries
        assert ms.call_count == 2          # exponential back-off ran

    def test_timeout_errors_exhaust_retries_then_raise_llm_error(self):
        p = _cf_provider(max_retries=2)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_timeout_error()) as mc, \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError):
                p.generate("sys", "usr")
        assert mc.call_count == 3

    def test_non_retryable_error_raises_immediately(self):
        p = _cf_provider(max_retries=2)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=ValueError("bad request shape")) as mc, \
             patch("backend.app.ai.llm.provider.time.sleep") as ms:
            with pytest.raises(LLMError):
                p.generate("sys", "usr")
        assert mc.call_count == 1
        assert ms.call_count == 0

    def test_invalid_structured_output_raises_validation_error(self):
        p = _cf_provider()
        with patch.object(p._client.chat.completions, "create",
                          return_value=_completion("not json at all")):
            with pytest.raises(LLMValidationError):
                p.generate_structured("sys", "usr", GrowthAnalysisResult)


# ─────────────────────────────────────────────────────────────────────────────
# Cloudflare limit handling — the daily-allocation guarantee
# ─────────────────────────────────────────────────────────────────────────────

class TestCloudflareDailyAllocation:
    """Cloudflare's free allocation is finite and resets daily.

    The critical property: an exhausted daily allocation must NOT be retried.
    Retrying burns the remaining allocation against a limit that cannot lift
    before the next UTC reset, and it would resubmit an expensive agent
    workflow repeatedly for a guaranteed failure.
    """

    def test_daily_allocation_is_classified_as_quota_exhausted(self):
        from backend.app.ai.llm.provider import classify_llm_failure

        category = classify_llm_failure(_cloudflare_quota_error())
        assert category == LLMFailureCategory.QUOTA_EXHAUSTED
        assert category not in frozenset({"rate_limited", "transient"})

    def test_daily_allocation_is_never_retried(self):
        p = _cf_provider(max_retries=3)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_cloudflare_quota_error()) as mc, \
             patch("backend.app.ai.llm.provider.time.sleep") as ms:
            with pytest.raises(LLMError) as exc_info:
                p.generate("sys", "usr")
        assert mc.call_count == 1, "exhausted daily quota must not be retried"
        assert ms.call_count == 0
        assert exc_info.value.category == LLMFailureCategory.QUOTA_EXHAUSTED
        assert exc_info.value.retryable is False

    def test_quota_message_is_sanitized_for_the_caller(self):
        p = _cf_provider()
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_cloudflare_quota_error()), \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError) as exc_info:
                p.generate("sys", "usr")
        # The user-facing message must name the category only — never the
        # provider payload, the account id or the prompt.
        assert "LLM call failed" in str(exc_info.value)
        assert "neurons" not in str(exc_info.value)
        assert FAKE_ACCOUNT not in str(exc_info.value)
        assert FAKE_KEY not in str(exc_info.value)

    def test_quota_error_carries_provider_and_model_for_diagnostics(self):
        p = _cf_provider()
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_cloudflare_quota_error()), \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError) as exc_info:
                p.generate("sys", "usr")
        assert exc_info.value.provider == "cloudflare"
        assert exc_info.value.model == CloudflareProvider.DEFAULT_MODEL

    def test_auth_error_is_not_retried_and_is_classified_as_auth(self):
        from backend.app.ai.llm.provider import classify_llm_failure

        assert classify_llm_failure(_auth_error()) == LLMFailureCategory.AUTH
        p = _cf_provider(max_retries=3)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_auth_error()) as mc, \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError):
                p.generate("sys", "usr")
        assert mc.call_count == 1

    def test_unknown_model_is_not_retried(self):
        from backend.app.ai.llm.provider import classify_llm_failure

        category = classify_llm_failure(_model_unavailable_error())
        assert category == LLMFailureCategory.MODEL_UNAVAILABLE
        p = _cf_provider(max_retries=3)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_model_unavailable_error()) as mc, \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError):
                p.generate("sys", "usr")
        assert mc.call_count == 1

    def test_failure_description_names_cloudflare_config_not_groq(self):
        from backend.app.ai.llm.provider import describe_llm_failure

        assert "CLOUDFLARE_API_TOKEN" in describe_llm_failure(
            LLMFailureCategory.AUTH)
        assert "CLOUDFLARE_TEXT_MODEL" in describe_llm_failure(
            LLMFailureCategory.MODEL_UNAVAILABLE)
        assert "GROQ" not in describe_llm_failure(LLMFailureCategory.AUTH)
        assert "GROQ" not in describe_llm_failure(
            LLMFailureCategory.MODEL_UNAVAILABLE)


# ─────────────────────────────────────────────────────────────────────────────
# Structured-generation token floor (MIN_STRUCTURED_TOKENS)
# ─────────────────────────────────────────────────────────────────────────────

class TestStructuredTokenFloor:
    """Why the floor exists.

    ``@cf/zai-org/glm-4.7-flash`` is a documented *reasoning* model: it spends
    deliberation tokens BEFORE emitting the JSON body. A caller budget that
    only covers the answer runs out mid-deliberation and the truncated output
    fails JSON validation — the agent then silently loses that decision. The
    floor raises small caller budgets to a safe floor inside
    ``generate_structured`` only; it costs nothing when the answer is short
    (a cap, not a charge).
    """

    def test_small_caller_budget_is_floored_for_structured_calls(self):
        p = _cf_provider(max_tokens=64)
        payload = GrowthAnalysisResult().model_dump_json()
        with patch.object(p._client.chat.completions, "create",
                          return_value=_completion(payload)) as mc:
            p.generate_structured(
                "sys", "usr", GrowthAnalysisResult, max_tokens=60
            )
        assert mc.call_args.kwargs["max_tokens"] >= 900

    def test_large_caller_budget_is_preserved(self):
        p = _cf_provider()
        payload = GrowthAnalysisResult().model_dump_json()
        with patch.object(p._client.chat.completions, "create",
                          return_value=_completion(payload)) as mc:
            p.generate_structured(
                "sys", "usr", GrowthAnalysisResult, max_tokens=1400
            )
        assert mc.call_args.kwargs["max_tokens"] == 1400

    def test_plain_generate_budget_is_untouched_by_the_floor(self):
        p = _cf_provider(max_tokens=777)
        with patch.object(p._client.chat.completions, "create",
                          return_value=_completion("hi")) as mc:
            p.generate("sys", "usr")
        assert mc.call_args.kwargs["max_tokens"] == 777


# ─────────────────────────────────────────────────────────────────────────────
# Secret hygiene
# ─────────────────────────────────────────────────────────────────────────────

class TestCloudflareSecretHygiene:
    def test_api_key_never_appears_in_exceptions(self):
        p = _cf_provider()
        with patch.object(p._client.chat.completions, "create",
                          side_effect=ValueError("boom")):
            with pytest.raises(LLMError) as exc_info:
                p.generate("sys", "usr")
        assert FAKE_KEY not in str(exc_info.value)
        assert FAKE_KEY not in repr(exc_info.value.__cause__)

    def test_init_log_message_contains_no_api_key(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="backend.app.ai.llm.provider"):
            _cf_provider()
        assert FAKE_KEY not in caplog.text
        assert "CloudflareProvider initialised" in caplog.text

    def test_logfilter_redacts_the_cloudflare_token(self, monkeypatch):
        """The shared token must be redacted on every logging path."""
        from backend.app.core import logfilter

        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", FAKE_KEY)
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        try:
            f = logfilter.SecretRedactingFilter()
            assert FAKE_KEY in f._secrets
        finally:
            get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────────────
# Route-level selection (_get_llm)
# ─────────────────────────────────────────────────────────────────────────────

class TestGetLLMRouteSelection:
    @staticmethod
    def _settings(**overrides) -> SimpleNamespace:
        base = dict(
            LLM_PROVIDER="cloudflare",
            CLOUDFLARE_ACCOUNT_ID=FAKE_ACCOUNT,
            CLOUDFLARE_API_TOKEN=FAKE_KEY,
            CLOUDFLARE_TEXT_MODEL="@cf/zai-org/glm-4.7-flash",
            LLM_API_KEY="",
            LLM_MODEL="gpt-4o-mini",
            LLM_REQUEST_TIMEOUT=30,
            LLM_MAX_RETRIES=2,
            LLM_MAX_TOKENS=1024,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_get_llm_builds_cloudflare_provider_from_cloudflare_settings(self):
        from backend.app.api.routes.ai import _get_llm

        with patch("backend.app.api.routes.ai.get_settings",
                   return_value=self._settings()):
            llm = _get_llm()
        assert isinstance(llm, CloudflareProvider)
        assert llm._model == "@cf/zai-org/glm-4.7-flash"
        assert float(llm._client.timeout) == 30.0

    def test_missing_cloudflare_credentials_raise_503_naming_the_variable(self):
        from fastapi import HTTPException

        from backend.app.api.routes.ai import _get_llm

        with patch("backend.app.api.routes.ai.get_settings",
                   return_value=self._settings(CLOUDFLARE_API_TOKEN="")):
            with pytest.raises(HTTPException) as exc_info:
                _get_llm()
        assert exc_info.value.status_code == 503
        assert "CLOUDFLARE_API_TOKEN" in exc_info.value.detail

    def test_503_message_does_not_mention_removed_groq_variables(self):
        from fastapi import HTTPException

        from backend.app.api.routes.ai import _get_llm

        with patch("backend.app.api.routes.ai.get_settings",
                   return_value=self._settings(CLOUDFLARE_API_TOKEN="",
                                               CLOUDFLARE_ACCOUNT_ID="")):
            with pytest.raises(HTTPException) as exc_info:
                _get_llm()
        assert "GROQ" not in exc_info.value.detail.upper()

    def test_openai_path_unchanged_when_provider_is_openai(self):
        from backend.app.api.routes.ai import _get_llm

        with patch("backend.app.api.routes.ai.get_settings",
                   return_value=self._settings(
                       LLM_PROVIDER="openai", LLM_API_KEY="sk-x",
                       CLOUDFLARE_API_TOKEN="")):
            llm = _get_llm()
        assert isinstance(llm, OpenAIProvider)
        assert not isinstance(llm, CloudflareProvider)

    def test_no_silent_fallback_when_nothing_is_configured(self):
        """Unconfigured must be an honest 503, never a borrowed credential."""
        from fastapi import HTTPException

        from backend.app.api.routes.ai import _get_llm

        with patch("backend.app.api.routes.ai.get_settings",
                   return_value=self._settings(CLOUDFLARE_API_TOKEN="",
                                               CLOUDFLARE_ACCOUNT_ID="",
                                               LLM_API_KEY="")):
            with pytest.raises(HTTPException) as exc_info:
                _get_llm()
        assert exc_info.value.status_code == 503
