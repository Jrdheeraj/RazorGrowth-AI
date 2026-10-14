"""LLM construction for the Product Agent.

Deliberately thin: it resolves the SAME centralized provider identity the rest
of the platform uses and delegates to the shared factory. There is no Product
Agent LLM client, no second SDK usage and no second retry policy.

``llm_identity`` is reused directly from the Marketing Agent module because it
is provider-agnostic: it delegates to the shared resolver, so Cloudflare
Workers AI (the platform default) is selected whenever it is configured,
otherwise the generic ``LLM_*`` settings apply, otherwise there is no LLM and
the agent runs its deterministic pipeline and reports ``llm_degraded``.
"""
from __future__ import annotations

import logging

from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.agents.marketing_agi.llm import llm_identity
from backend.app.core.config import get_settings

log = logging.getLogger(__name__)


def build_product_llm() -> BaseLLMProvider | None:
    """Build the shared LLM provider, or None when unconfigured.

    Returns None rather than raising when no provider is configured: the agent
    then runs its deterministic pipeline and reports ``llm_degraded``, which
    is honest. A genuinely misconfigured provider still raises, so a bad
    setting is loud instead of silently deterministic.
    """
    from backend.app.ai.llm.provider import resolve_llm_provider

    settings = get_settings()
    resolved = resolve_llm_provider(settings)
    if resolved is None:
        return None
    return resolved.build(
        timeout=settings.LLM_REQUEST_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
        max_tokens=settings.LLM_MAX_TOKENS,
    )


def build_embedding_provider_or_none():  # pragma: no cover - thin adapter
    """Embedding provider for research, or None when unavailable.

    Embeddings are a SEPARATE concern from the text-LLM migration: they are not
    text generation, they are not served by the chat-completions provider, and
    ``CLOUDFLARE_API_TOKEN`` is not assumed to carry a usable embeddings model.
    This keeps the existing generic ``LLM_API_KEY`` behaviour unchanged.
    """
    settings = get_settings()
    if not settings.LLM_API_KEY:
        return None
    try:
        from backend.app.ai.embeddings.provider import (
            build_embedding_provider as _build,
        )

        return _build(
            provider=settings.EMBEDDING_PROVIDER,
            api_key=settings.LLM_API_KEY,
            model=settings.EMBEDDING_MODEL,
        )
    except Exception:
        log.warning("Embedding provider unavailable; research falls back to tools")
        return None


__all__ = ["build_embedding_provider_or_none", "build_product_llm", "llm_identity"]
