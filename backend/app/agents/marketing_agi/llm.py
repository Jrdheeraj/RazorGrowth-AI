"""MarketingAGI LLM wiring — the centralized Cloudflare reasoning layer.

The Marketing Agent reasons through the platform's SINGLE shared text-LLM
provider. This module is a thin, provider-agnostic adapter: it resolves the
provider that `resolve_llm_provider()` selected from real configuration and
builds it through the one shared factory. It deliberately contains no client
logic, no model names and no provider names of its own — there is nothing
agent-specific about "which LLM are we using".

  1. A configured Cloudflare Workers AI deployment (the platform default)
     gets a ``CloudflareProvider`` with the centrally configured
     ``CLOUDFLARE_TEXT_MODEL``, reusing the shared factory — timeout, bounded
     retries, structured JSON output, Pydantic validation. No second LLM
     abstraction and no second retry policy.
  2. Otherwise it falls back to whatever ``resolve_llm_provider`` resolves
     (e.g. OpenAI) when one is genuinely configured.
  3. When no provider is configured at all it returns ``None``: the agent
     still runs its bounded deterministic workflow honestly and marks the run
     degraded — it never fabricates LLM reasoning, and it never silently
     reaches a different vendor.

The credential never leaves the backend: this module is imported only by
backend code (routes, workers). There is no VITE_-prefixed LLM credential and
no frontend path to the key.
"""
from __future__ import annotations

import logging

from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.core.config import get_settings

log = logging.getLogger(__name__)


def llm_identity() -> tuple[bool, str | None, str | None]:
    """Return (configured, provider, model) for the Marketing Agent.

    Delegates entirely to the shared resolver so this agent, the Product
    Agent, the API routes and the audit rows can never disagree about which
    provider and model are actually in use.
    """
    from backend.app.ai.llm.provider import resolve_llm_provider

    resolved = resolve_llm_provider(get_settings())
    if resolved is None:
        return False, None, None
    return True, resolved.name, resolved.model


def build_marketing_llm() -> BaseLLMProvider | None:
    """Build the Marketing Agent's reasoning LLM, or None when unconfigured.

    Reuses the shared provider factory; never raises for a missing key
    (returns None) but lets genuine factory errors propagate so a
    misconfigured provider is visible instead of silently deterministic.
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


__all__ = ["build_marketing_llm", "llm_identity"]
