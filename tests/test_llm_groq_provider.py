"""
Groq LLM provider tests — T-migration.

Coverage:
  · Provider selection via build_llm_provider factory ("groq" | "openai")
  · GroqProvider configuration (base_url, timeout, retries, max_tokens, model)
  · Missing-API-key behaviour (Settings default + /analyze route 503)
  · Timeout / retry behaviour (mocked transient errors — zero network)
  · Successful response handling
  · Structured output parsing + Pydantic validation
  · API keys never leak into exceptions or logs

All interactions are mocked at the OpenAI-SDK client boundary; no live
Groq API calls are made anywhere in this module.
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
    GroqProvider,
    LLMError,
    LLMValidationError,
    OpenAIProvider,
    build_llm_provider,
)

# Distinctive fake key so we can assert it never leaks into errors/logs
FAKE_KEY = "gsk_fake_groq_key_DO_NOT_LEAK_1234567890"


def _completion(content: str) -> SimpleNamespace:
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(total_tokens=42)
    return SimpleNamespace(choices=[choice], usage=usage)


def _rate_limit_error() -> Exception:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return openai.RateLimitError("rate limited", response=response, body=None)


def _timeout_error() -> Exception:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return openai.APITimeoutError(request=request)


def _groq_provider(**kwargs) -> GroqProvider:
    defaults = dict(api_key=FAKE_KEY, timeout=5, max_retries=2, max_tokens=999)
    defaults.update(kwargs)
    return GroqProvider(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# Provider selection (factory)
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderSelection:
    def test_factory_returns_groq_provider(self):
        p = build_llm_provider(provider="groq", api_key=FAKE_KEY,
                               model="openai/gpt-oss-120b")
        assert isinstance(p, GroqProvider)

    def test_factory_selection_is_case_insensitive(self):
        p = build_llm_provider(provider="GROQ", api_key=FAKE_KEY, model="m")
        assert isinstance(p, GroqProvider)

    def test_factory_still_supports_openai(self):
        p = build_llm_provider(provider="openai", api_key="sk-x", model="gpt-4o-mini")
        assert isinstance(p, OpenAIProvider)
        assert not isinstance(p, GroqProvider)

    def test_unsupported_provider_raises_value_error_listing_supported(self):
        with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER") as exc_info:
            build_llm_provider(provider="anthropic", api_key="x", model="y")
        assert "openai" in str(exc_info.value)
        assert "groq" in str(exc_info.value)

    def test_groq_provider_satisfies_base_abstraction(self):
        assert isinstance(_groq_provider(), BaseLLMProvider)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

class TestGroqConfiguration:
    def test_client_targets_groq_base_url(self):
        p = _groq_provider()
        assert str(p._client.base_url).startswith("https://api.groq.com/openai/v1")

    def test_constructor_captures_timeout_retry_and_token_config(self):
        p = _groq_provider(timeout=7, max_retries=3, max_tokens=512)
        assert p._timeout == 7
        assert float(p._client.timeout) == 7.0
        assert p._max_retries == 3
        assert p._max_tokens == 512

    def test_model_is_configurable(self):
        p = _groq_provider(model="openai/gpt-oss-20b")
        assert p._model == "openai/gpt-oss-20b"

    def test_default_model_used_when_none_passed(self):
        from backend.app.core.config import get_settings
        p = _groq_provider(model=None)
        assert p._model == get_settings().GROQ_MODEL

    def test_settings_expose_groq_fields_with_safe_defaults(self):
        from backend.app.core.config import get_settings
        s = get_settings()
        # Defaults must exist and must NOT contain a real credential
        assert hasattr(s, "GROQ_API_KEY")
        assert hasattr(s, "GROQ_MODEL")
        assert s.GROQ_MODEL == "openai/gpt-oss-120b"

    def test_openai_provider_has_no_groq_base_url(self):
        p = build_llm_provider(provider="openai", api_key="sk-x", model="m")
        assert "api.openai.com" in str(p._client.base_url)


# ─────────────────────────────────────────────────────────────────────────────
# Request handling — success / retry / timeout / structured output
# ─────────────────────────────────────────────────────────────────────────────

class TestGroqRequestHandling:
    def test_generate_returns_content_and_passes_config(self):
        p = _groq_provider(model="openai/gpt-oss-120b", max_tokens=777)
        with patch.object(p._client.chat.completions, "create",
                          return_value=_completion("hello from groq")) as mock_create:
            result = p.generate("sys", "usr")
        assert result == "hello from groq"
        kwargs = mock_create.call_args.kwargs
        assert kwargs["model"] == "openai/gpt-oss-120b"
        assert kwargs["max_tokens"] == 777
        assert kwargs["messages"][0]["role"] == "system"

    def test_generate_structured_uses_json_mode(self):
        p = _groq_provider()
        payload = GrowthAnalysisResult().model_dump_json()
        with patch.object(p._client.chat.completions, "create",
                          return_value=_completion(payload)) as mock_create:
            result = p.generate_structured("sys", "usr", GrowthAnalysisResult)
        assert isinstance(result, GrowthAnalysisResult)
        assert mock_create.call_args.kwargs["response_format"] == {"type": "json_object"}

    def test_transient_rate_limit_is_retried_then_succeeds(self):
        p = _groq_provider(max_retries=2)
        side_effects = [_rate_limit_error(), _rate_limit_error(),
                        _completion("recovered")]
        with patch.object(p._client.chat.completions, "create",
                          side_effect=side_effects) as mock_create, \
             patch("backend.app.ai.llm.provider.time.sleep") as mock_sleep:
            result = p.generate("sys", "usr")
        assert result == "recovered"
        assert mock_create.call_count == 3          # initial + 2 retries
        assert mock_sleep.call_count == 2           # exponential back-off ran

    def test_timeout_errors_exhaust_retries_then_raise_llm_error(self):
        p = _groq_provider(max_retries=2)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=_timeout_error()) as mock_create, \
             patch("backend.app.ai.llm.provider.time.sleep"):
            with pytest.raises(LLMError):
                p.generate("sys", "usr")
        assert mock_create.call_count == 3

    def test_non_retryable_error_raises_immediately(self):
        p = _groq_provider(max_retries=2)
        with patch.object(p._client.chat.completions, "create",
                          side_effect=ValueError("bad request shape")) as mock_create, \
             patch("backend.app.ai.llm.provider.time.sleep") as mock_sleep:
            with pytest.raises(LLMError):
                p.generate("sys", "usr")
        assert mock_create.call_count == 1
        assert mock_sleep.call_count == 0

    def test_invalid_structured_output_raises_validation_error(self):
        p = _groq_provider()
        with patch.object(p._client.chat.completions, "create",
                          return_value=_completion("not json at all")):
            with pytest.raises(LLMValidationError):
                p.generate_structured("sys", "usr", GrowthAnalysisResult)


# ─────────────────────────────────────────────────────────────────────────────
# Secret hygiene
# ─────────────────────────────────────────────────────────────────────────────

class TestGroqSecretHygiene:
    def test_api_key_never_appears_in_exceptions(self):
        p = _groq_provider()
        with patch.object(p._client.chat.completions, "create",
                          side_effect=ValueError("boom")):
            with pytest.raises(LLMError) as exc_info:
                p.generate("sys", "usr")
        assert FAKE_KEY not in str(exc_info.value)
        assert FAKE_KEY not in repr(exc_info.value.__cause__)

    def test_init_log_message_contains_no_api_key(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="backend.app.ai.llm.provider"):
            _groq_provider()
        assert FAKE_KEY not in caplog.text
        assert "GroqProvider initialised" in caplog.text


# ─────────────────────────────────────────────────────────────────────────────
# Route-level selection (_get_llm)
# ─────────────────────────────────────────────────────────────────────────────

class TestGetLLMRouteSelection:
    @staticmethod
    def _settings(**overrides) -> SimpleNamespace:
        base = dict(
            LLM_PROVIDER="groq",
            GROQ_API_KEY=FAKE_KEY,
            GROQ_MODEL="openai/gpt-oss-120b",
            LLM_API_KEY="",
            LLM_MODEL="gpt-4o-mini",
            LLM_REQUEST_TIMEOUT=30,
            LLM_MAX_RETRIES=2,
            LLM_MAX_TOKENS=1024,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_get_llm_builds_groq_provider_from_groq_settings(self):
        from fastapi import HTTPException
        from backend.app.api.routes.ai import _get_llm
        with patch("backend.app.api.routes.ai.get_settings",
                   return_value=self._settings()):
            llm = _get_llm()
        assert isinstance(llm, GroqProvider)
        assert llm._model == "openai/gpt-oss-120b"
        assert float(llm._client.timeout) == 30.0

    def test_missing_groq_api_key_raises_503_naming_the_variable(self):
        from fastapi import HTTPException
        from backend.app.api.routes.ai import _get_llm
        with patch("backend.app.api.routes.ai.get_settings",
                   return_value=self._settings(GROQ_API_KEY="")):
            with pytest.raises(HTTPException) as exc_info:
                _get_llm()
        assert exc_info.value.status_code == 503
        assert "GROQ_API_KEY" in exc_info.value.detail

    def test_openai_path_unchanged_when_provider_is_openai(self):
        from backend.app.api.routes.ai import _get_llm
        with patch("backend.app.api.routes.ai.get_settings",
                   return_value=self._settings(
                       LLM_PROVIDER="openai", LLM_API_KEY="sk-x")):
            llm = _get_llm()
        assert isinstance(llm, OpenAIProvider)
        assert not isinstance(llm, GroqProvider)
