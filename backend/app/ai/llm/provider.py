"""
LLM provider implementations.

Providers:
  - CloudflareProvider — Cloudflare Workers AI chat completions
                         (OpenAI-compatible endpoint; the platform default)
  - OpenAIProvider     — OpenAI chat completions

Cloudflare Workers AI is the single centralized text-LLM provider for the whole
application. Because its `/v1/chat/completions` route is OpenAI-compatible,
`CloudflareProvider` subclasses `OpenAIProvider` and only retargets the SDK
client at the account-scoped base URL. There is therefore ONE request path,
ONE retry policy, ONE JSON-mode path and ONE Pydantic validation path — no
second framework and no duplicated client logic anywhere in the codebase.

Every feature that needs text generation resolves its client through
`resolve_llm_provider()` and builds it with `ResolvedLLM.build()`, so no agent,
route or worker can reach a provider that the resolver did not select.

ENDPOINT (Cloudflare's documented OpenAI-compatible surface)
-----------------------------------------------------------
    POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions
    Authorization: Bearer {api_token}

Production-hardened (shared):
  - configurable timeout (LLM_REQUEST_TIMEOUT)
  - automatic retry on transient errors (LLM_MAX_RETRIES)
  - structured JSON output mode for generate_structured()
  - context-safe logging (API key never logged)
  - LLMError / LLMValidationError for all failure paths
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from backend.app.ai.llm.base import BaseLLMProvider

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# Transient error types that warrant a retry
_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = ()  # populated lazily


class LLMFailureCategory:
    """Stable, machine-readable reasons an LLM call can fail.

    Callers (agents, API routes, the frontend) key off these rather than off
    an exception class name, because the same HTTP status means different
    things depending on *which* limit was hit.
    """

    #: Requests/minute or tokens/minute throttling — transient, worth retrying.
    RATE_LIMITED = "rate_limited"
    #: Daily/weekly token quota spent. Retrying cannot help until it resets.
    QUOTA_EXHAUSTED = "quota_exhausted"
    #: Missing/rejected credential. Retrying cannot help.
    AUTH = "auth"
    #: Model unknown, retired or not granted for this key. Retrying cannot help.
    MODEL_UNAVAILABLE = "model_unavailable"
    #: Malformed request (bad params, unsupported response_format, ...).
    INVALID_REQUEST = "invalid_request"
    #: The provider timed out. Transient.
    TIMEOUT = "timeout"
    #: 5xx or connection failure. Transient.
    TRANSIENT = "transient"
    #: Not recognised. Treated as transient-but-bounded.
    UNKNOWN = "unknown"


#: Categories where a retry can plausibly succeed. Everything else fails fast:
#: retrying an exhausted daily quota just burns wall-clock and quota-adjacent
#: requests while guaranteeing the same answer.
#:
#: UNKNOWN is deliberately NOT retryable. An unrecognised exception is far more
#: often a bug in the caller than a blip in the provider, and blindly repeating
#: it can duplicate side effects. Fail fast and let the logs name it.
RETRYABLE_CATEGORIES = frozenset(
    {
        LLMFailureCategory.RATE_LIMITED,
        LLMFailureCategory.TIMEOUT,
        LLMFailureCategory.TRANSIENT,
    }
)

#: A Retry-After larger than this means the provider is telling us to come back
#: much later (e.g. a daily quota resetting in ~21 minutes). Blocking an agent
#: run for that long is worse than failing honestly, so we surface the reset
#: time to the caller instead of sleeping through it.
MAX_RETRY_DELAY_SECONDS = 20.0


class LLMError(Exception):
    """Raised when the LLM provider returns an error or times out.

    Carries a `category` so callers can tell a rate limit from an exhausted
    daily quota from a bad credential, plus `retry_after` so the UI can say
    when a retry is worth attempting.

    The message is deliberately built from the classification only. The raw
    provider payload is logged at the provider layer and never propagated,
    because it can carry request echoes and account identifiers.
    """

    def __init__(
        self,
        message: str,
        *,
        category: str = LLMFailureCategory.UNKNOWN,
        retryable: bool = False,
        retry_after: float | None = None,
        provider: str | None = None,
        model: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.retry_after = retry_after
        self.provider = provider
        self.model = model
        self.status_code = status_code


class LLMValidationError(Exception):
    """Raised when LLM output fails Pydantic schema validation."""


def describe_llm_failure(category: str, retry_after: float | None = None) -> str:
    """A short, actionable, secret-free sentence for a failure category.

    Says which service failed and whether retrying is worth it, because those
    are the two things an operator actually needs to know. Never includes the
    provider payload, the model output, or any credential material.
    """
    if category == LLMFailureCategory.QUOTA_EXHAUSTED:
        when = ""
        if retry_after and retry_after > 0:
            when = f" It resets in about {int(retry_after // 60) + 1} minutes."
        return (
            "The AI provider's daily token quota is exhausted."
            f"{when} Retrying now will not help - wait for the quota to reset."
        )
    if category == LLMFailureCategory.RATE_LIMITED:
        when = (
            f" The provider asked to wait about {int(retry_after)} seconds."
            if retry_after and retry_after > 0
            else ""
        )
        return f"The AI provider is rate limiting this workspace.{when} Try again shortly."
    if category == LLMFailureCategory.AUTH:
        return (
            "The AI provider rejected the configured credential. "
            "Check CLOUDFLARE_API_TOKEN (and CLOUDFLARE_ACCOUNT_ID) before "
            "running again."
        )
    if category == LLMFailureCategory.MODEL_UNAVAILABLE:
        return (
            "The configured AI model is unavailable or not entitled for this key. "
            "Check CLOUDFLARE_TEXT_MODEL and the account's Workers AI model access."
        )
    if category == LLMFailureCategory.INVALID_REQUEST:
        return (
            "The AI provider rejected the request as malformed. "
            "This is a configuration or model-capability problem, not a quota one."
        )
    if category == LLMFailureCategory.TIMEOUT:
        return "The AI provider did not respond in time. Try again."
    if category == LLMFailureCategory.TRANSIENT:
        return "The AI provider is temporarily unavailable. Try again shortly."
    return "The AI provider returned an unexpected error. Try again."


# Upper bound for a single retry wait, even when the provider asks for
# more via Retry-After. Keeps 429 backoff bounded: we degrade honestly
# instead of stalling an agent run for a minute on a hosted-model limit.
# (Defined above alongside LLMFailureCategory.)

# Floor for structured (JSON-mode) generations. Reasoning models emit their
# deliberation BEFORE the JSON body, so a caller-supplied budget that only
# covers the answer runs out mid-deliberation and the provider rejects the
# truncated output ("failed to validate JSON"). Rather than have every
# call site remember that, structured calls are floored here. Cheap
# non-reasoning models simply stop early, so this costs nothing for them.
MIN_STRUCTURED_TOKENS = 900


# OpenAI-compatible providers report WHICH limit was hit in the error *message*
# rather than in a distinct HTTP status — a per-minute throttle and an
# exhausted daily allocation are both a 429. Matching on the message is
# therefore the only way to tell "slow down for a few seconds" apart from
# "your daily quota is gone", and they need opposite handling.
#
# ORDER MATTERS. The quota patterns are deliberately listed first: Cloudflare's
# daily-allocation message is a 429 that also carries generic limit wording, so
# a rate-limit pattern matched first would make an exhausted daily quota look
# transient and we would keep burning requests against a limit that cannot lift.
_LIMIT_PATTERNS: tuple[tuple[str, str], ...] = (
    # -- Cloudflare Workers AI daily allocation (API error code 4006) --------
    (
        r"daily free allocation|neurons|exceeded your current quota",
        LLMFailureCategory.QUOTA_EXHAUSTED,
    ),
    # -- OpenAI-style named quotas -------------------------------------------
    (r"tokens per day|\(tpd\)|per-day", LLMFailureCategory.QUOTA_EXHAUSTED),
    (r"requests per day|\(rpd\)", LLMFailureCategory.QUOTA_EXHAUSTED),
    # -- Cloudflare capacity queue / generic throttling ------------------------
    (
        r"tokens per minute|\(tpm\)|requests per minute|\(rpm\)"
        r"|too many requests|rate limit|capacity",
        LLMFailureCategory.RATE_LIMITED,
    ),
)

#: Cloudflare's numeric error code for "daily free allocation exhausted".
#: Matched as a bare token so it stays recognised even if the message wording
#: changes. Presence alone is decisive — this limit cannot be retried away.
_CLOUDFLARE_QUOTA_CODE = re.compile(r'"code"\s*:\s*4006|\bcode\b\D{0,3}4006', re.I)


def _provider_message(exc: Exception) -> str:
    """Extract the provider's error text, best-effort. Never raises.

    Handles the two envelope shapes actually in play:
      * OpenAI-style — ``{"error": {"message": "..."}}``
      * Cloudflare   — ``{"success": false, "errors": [{"code":..,"message":..}]}``
    """
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str):
                return msg
        if isinstance(err, str):
            return err
        # Cloudflare's plural `errors` list.
        errors = body.get("errors")
        if isinstance(errors, list):
            parts = [
                str(e.get("message"))
                for e in errors
                if isinstance(e, dict) and isinstance(e.get("message"), str)
            ]
            if parts:
                return " ".join(parts)
    text = str(exc)
    return text


def _status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def classify_llm_failure(exc: Exception) -> str:
    """Map a provider exception onto an :class:`LLMFailureCategory`.

    HTTP status alone is insufficient: a 429 may mean a per-minute throttle
    (retryable) or an exhausted daily quota (not retryable), and they need
    opposite handling. Status narrows the field; the message disambiguates.
    """
    try:
        import openai
    except ImportError:  # pragma: no cover - openai is a hard dependency
        return LLMFailureCategory.UNKNOWN

    if isinstance(exc, openai.APITimeoutError):
        return LLMFailureCategory.TIMEOUT
    if isinstance(exc, openai.AuthenticationError):
        return LLMFailureCategory.AUTH
    if isinstance(exc, openai.PermissionDeniedError):
        # Key is valid but not entitled to this model.
        return LLMFailureCategory.MODEL_UNAVAILABLE
    if isinstance(exc, openai.NotFoundError):
        return LLMFailureCategory.MODEL_UNAVAILABLE
    if isinstance(exc, openai.BadRequestError):
        return LLMFailureCategory.INVALID_REQUEST
    if isinstance(exc, openai.InternalServerError):
        return LLMFailureCategory.TRANSIENT
    if isinstance(exc, openai.APIConnectionError):
        return LLMFailureCategory.TRANSIENT
    if isinstance(exc, openai.RateLimitError):
        message = _provider_message(exc).lower()
        # Cloudflare's daily free allocation (API error code 4006) also arrives
        # as a 429 but cannot be retried away. Checked first so it never
        # degrades into "rate limited, try again" and burns what is left.
        body = getattr(exc, "body", None)
        if _CLOUDFLARE_QUOTA_CODE.search(
            json.dumps(body, default=str) if body is not None else ""
        ):
            return LLMFailureCategory.QUOTA_EXHAUSTED
        for pattern, category in _LIMIT_PATTERNS:
            if re.search(pattern, message):
                return category
        # A 429 with no recognisable limit name is still throttling.
        return LLMFailureCategory.RATE_LIMITED

    status = _status_code(exc)
    if status == 429:
        return LLMFailureCategory.RATE_LIMITED
    if status in (401, 403):
        return LLMFailureCategory.AUTH
    if status == 404:
        return LLMFailureCategory.MODEL_UNAVAILABLE
    if status == 400:
        return LLMFailureCategory.INVALID_REQUEST
    if status is not None and 500 <= status < 600:
        return LLMFailureCategory.TRANSIENT
    return LLMFailureCategory.UNKNOWN


def _is_retryable(exc: Exception) -> bool:
    """True only for failures a bounded retry can plausibly fix."""
    return classify_llm_failure(exc) in RETRYABLE_CATEGORIES


def _is_rate_limited(exc: Exception) -> bool:
    """True only for HTTP 429 rate-limit responses."""
    try:
        import openai
        return isinstance(exc, openai.RateLimitError)
    except ImportError:
        return False


def _retry_after_seconds(exc: Exception, default: float) -> float:
    """Read the provider's ``Retry-After`` hint, if it supplies a usable one.

    Returns ``default`` when no usable hint is present. The cap is applied by
    the caller rather than here, because a hint far larger than the cap means
    "come back much later" and should end the attempt loop, not be silently
    shortened into a guaranteed second failure.
    """
    if _is_rate_limited(exc):
        try:
            response = getattr(exc, "response", None)
            headers = getattr(response, "headers", None) or {}
            raw = headers.get("retry-after") or headers.get("Retry-After")
            if raw is not None:
                hinted = float(str(raw).strip().rstrip("s"))
                if hinted >= 0:
                    return hinted
        except (TypeError, ValueError, AttributeError):
            pass
    return default


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI chat completions provider with production safeguards.

    - Timeout enforced via httpx_timeout on every request.
    - Retries up to `max_retries` times on transient errors with
      exponential back-off (1s, 2s).
    - JSON mode for generate_structured() — always valid JSON output.
    - API key is never logged.
    - Per-call stats on `last_call_stats` (attempts, retries,
      rate_limited, retry_delay_ms) — safe metadata only, no prompts,
      keys, or response content.
    """

    #: Safe, stable identifier used in logs and error payloads.
    PROVIDER_NAME = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: int = 60,
        max_retries: int = 2,
        max_tokens: int = 2048,
        base_url: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required. Run: pip install openai")

        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        #: Safe identifier for diagnostics — the provider name, never the key.
        self.provider_name = self.PROVIDER_NAME
        self.last_call_stats: dict = {
            "attempts": 0, "retries": 0, "rate_limited": False,
            "retry_delay_ms": 0, "latency_ms": 0, "request_id": None,
            "prompt_tokens": None, "completion_tokens": None,
            "total_tokens": None,
        }
        client_kwargs: dict = {"api_key": api_key, "timeout": float(timeout)}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = OpenAI(**client_kwargs)
        log.info(
            "%s initialised. model=%s timeout=%ds max_retries=%d",
            type(self).__name__, model, timeout, max_retries,
        )

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        return self._call_with_retry(
            self._do_generate,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens or self._max_tokens,
            json_mode=False,
        )

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[T],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> T:
        json_instruction = (
            f"\n\nRespond ONLY with valid JSON that matches this schema:\n"
            f"{json.dumps(schema.model_json_schema(), indent=2)}"
        )
        raw = self._call_with_retry(
            self._do_generate,
            system_prompt=system_prompt + json_instruction,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max(MIN_STRUCTURED_TOKENS, max_tokens or self._max_tokens),
            json_mode=True,
        )
        try:
            return schema.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            log.error("LLM output failed schema validation: %s", exc)
            raise LLMValidationError(f"LLM output validation failed: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _do_generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        kwargs: dict = dict(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        started = time.monotonic()
        response = self._client.chat.completions.create(**kwargs)
        self.last_call_stats["latency_ms"] = int((time.monotonic() - started) * 1000)
        # Request correlation. Cloudflare returns a per-completion id in the
        # envelope; it is a safe identifier (no credentials, no prompt text)
        # and is what makes a specific call traceable in the dashboard.
        request_id = getattr(response, "id", None)
        if isinstance(request_id, str) and request_id:
            self.last_call_stats["request_id"] = request_id
        usage = getattr(response, "usage", None)
        if usage is not None:
            # Counts only — never the content the tokens were spent on.
            self.last_call_stats["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
            self.last_call_stats["completion_tokens"] = getattr(
                usage, "completion_tokens", None
            )
            self.last_call_stats["total_tokens"] = getattr(usage, "total_tokens", None)

        content = response.choices[0].message.content or ""
        log.debug(
            "LLM call completed. provider=%s model=%s tokens=%s latency_ms=%s",
            self.provider_name,
            self._model,
            response.usage.total_tokens if response.usage else "?",
            self.last_call_stats["latency_ms"],
        )
        return content

    def _call_with_retry(self, fn, **kwargs) -> str:
        attempts = 0
        retries = 0
        rate_limited = False
        retry_delay_ms = 0
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            attempts = attempt + 1
            try:
                out = fn(**kwargs)
                self.last_call_stats = {
                    **self.last_call_stats,
                    "attempts": attempts, "retries": retries,
                    "rate_limited": rate_limited,
                    "retry_delay_ms": retry_delay_ms,
                }
                return out
            except Exception as exc:
                last_exc = exc
                category = classify_llm_failure(exc)
                if _is_rate_limited(exc):
                    rate_limited = True

                if category not in RETRYABLE_CATEGORIES or attempt >= self._max_retries:
                    break

                # Exponential backoff with full jitter. Without jitter, every
                # agent that hit the same limit retries in lockstep and
                # reproduces the stampede that caused it.
                wait = _retry_after_seconds(exc, default=float(2 ** attempt))
                if wait > MAX_RETRY_DELAY_SECONDS:
                    # The provider is asking for a wait far longer than a
                    # request should block. Honouring it by sleeping would
                    # stall the agent for the same guaranteed failure.
                    log.warning(
                        "LLM %s (attempt %d/%d) needs %.0fs — too long to retry "
                        "inline; surfacing instead",
                        category, attempt + 1, self._max_retries + 1, wait,
                    )
                    break
                if category != LLMFailureCategory.RATE_LIMITED:
                    wait = random.uniform(0, wait)  # jitter only our own backoff

                retry_delay_ms += int(wait * 1000)
                retries += 1
                log.warning(
                    "LLM transient error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, self._max_retries + 1, wait, category,
                )
                time.sleep(wait)

        self.last_call_stats = {
            **self.last_call_stats,
            "attempts": attempts, "retries": retries,
            "rate_limited": rate_limited, "retry_delay_ms": retry_delay_ms,
        }

        category = classify_llm_failure(last_exc) if last_exc else LLMFailureCategory.UNKNOWN
        retry_after = (
            _retry_after_seconds(last_exc, default=0.0) or None
            if last_exc is not None and _is_rate_limited(last_exc)
            else None
        )

        # The provider's own words stay in the log (never in the message) so a
        # merchant-facing error can name the cause without echoing a payload
        # that may contain request echoes or account identifiers.
        if last_exc is not None:
            log.error(
                "LLM call failed after %d attempt(s): category=%s status=%s "
                "provider_detail=%s",
                attempts, category, _status_code(last_exc),
                _provider_message(last_exc)[:300],
            )
        else:  # pragma: no cover - defensive
            log.error("LLM call failed after %d attempt(s): no exception recorded", attempts)

        raise LLMError(
            f"LLM call failed: {category}",
            category=category,
            retryable=category in RETRYABLE_CATEGORIES and attempts <= self._max_retries,
            retry_after=retry_after,
            provider=self.provider_name,
            model=self._model,
            status_code=_status_code(last_exc) if last_exc else None,
        ) from last_exc


class CloudflareProvider(OpenAIProvider):
    """
    Cloudflare Workers AI chat-completions provider — the platform default.

    Cloudflare exposes a documented OpenAI-compatible
    ``/ai/v1/chat/completions`` route, so this provider reuses the entire
    OpenAIProvider request/retry/validation path and only retargets the SDK
    client at the account-scoped base URL. Timeout, bounded retry with
    exponential back-off, max_tokens, JSON mode and Pydantic validation behave
    exactly as for every other provider. The API token is never logged.

    ENDPOINT
        https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1

    MODEL
        Defaults to ``@cf/zai-org/glm-4.7-flash``: 131,072-token context,
        documented function-calling support, and ``response_format`` for
        structured output. It is a *reasoning* model, which is why structured
        calls are floored at ``MIN_STRUCTURED_TOKENS`` — see that constant.

    NOT TO BE CONFUSED WITH THE IMAGE PROVIDER
        ``backend/app/integrations/cloudflare_image.py`` is the FLUX
        text-to-image path and stays entirely separate. Image generation never
        routes through this class and never depends on a successful LLM call.
    """

    #: Cloudflare's OpenAI-compatible surface is account-scoped, so the base
    #: URL cannot be a class constant — it is derived from the account id.
    API_ROOT = "https://api.cloudflare.com/client/v4/accounts"
    DEFAULT_MODEL = "@cf/zai-org/glm-4.7-flash"
    PROVIDER_NAME = "cloudflare"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        timeout: int = 60,
        max_retries: int = 2,
        max_tokens: int = 2048,
        account_id: str | None = None,
    ) -> None:
        resolved_model = model or self.DEFAULT_MODEL
        super().__init__(
            api_key=api_key,
            model=resolved_model,
            timeout=timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
            base_url=self.build_base_url(account_id),
        )

    @classmethod
    def build_base_url(cls, account_id: str | None) -> str:
        """Derive the account-scoped OpenAI-compatible base URL.

        Raises ``ValueError`` when the account id is missing: a Cloudflare
        client without an account cannot address any model, and silently
        building ``.../accounts//ai/v1`` would turn a configuration mistake
        into a confusing 404 on every single request.
        """
        account = (account_id or "").strip()
        if not account:
            raise ValueError(
                "CLOUDFLARE_ACCOUNT_ID is required to build the Workers AI "
                "text-LLM client"
            )
        return f"{cls.API_ROOT}/{account}/ai/v1"

    @property
    def capabilities(self) -> dict[str, bool]:
        """What this provider can actually do, for honest feature reporting."""
        return {
            "streaming": True,
            "json_mode": True,
            "tool_calls": True,
        }


def build_llm_provider(
    provider: str,
    api_key: str,
    model: str,
    timeout: int = 60,
    max_retries: int = 2,
    max_tokens: int = 2048,
    account_id: str | None = None,
) -> BaseLLMProvider:
    """
    Factory — construct the configured LLM provider.

    Supported: cloudflare · openai
    """
    normalized = provider.lower()
    if normalized == "openai":
        return OpenAIProvider(
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
        )
    if normalized == "cloudflare":
        return CloudflareProvider(
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
            account_id=account_id,
        )
    raise ValueError(
        f"Unsupported LLM_PROVIDER: {provider!r}. Supported: cloudflare, openai"
    )


#: Provider names this codebase can actually build. Anything else in
#: LLM_PROVIDER is stale configuration and must not be handed to the factory.
SUPPORTED_LLM_PROVIDERS = frozenset({"cloudflare", "openai"})


@dataclass(frozen=True)
class ResolvedLLM:
    """The provider actually selected, and why."""

    name: str
    #: Never rendered. A dataclass repr lands in tracebacks, logs and test
    #: failure output, so a credential must not be a printable field.
    api_key: str = field(repr=False)
    model: str
    #: Cloudflare only. Required by CloudflareProvider to scope the base URL
    #: to an account. Safe to print — it is an identifier, not a secret, and
    #: it is what makes a Cloudflare misconfiguration diagnosable.
    account_id: str = ""
    #: True when a usable credential was found even though LLM_PROVIDER named
    #: something this codebase cannot build. Worth logging — it means the
    #: config is misleading.
    used_fallback: bool = False

    def __repr__(self) -> str:
        # Explicit, so a future field addition cannot re-expose the key.
        return (
            f"ResolvedLLM(name={self.name!r}, model={self.model!r}, "
            f"account_id={'set' if self.account_id else 'unset'!r}, "
            f"used_fallback={self.used_fallback!r})"
        )

    def build(
        self,
        *,
        timeout: int = 60,
        max_retries: int = 2,
        max_tokens: int = 2048,
    ) -> BaseLLMProvider:
        return build_llm_provider(
            provider=self.name,
            api_key=self.api_key,
            model=self.model,
            timeout=timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
            account_id=self.account_id or None,
        )


def resolve_llm_provider(settings) -> ResolvedLLM | None:
    """Pick the LLM the whole application should use, from real configuration.

    THIS IS THE ONLY PROVIDER SELECTION POINT IN THE CODEBASE.
    Agents, API routes, workers and the Designer auxiliary helper all resolve
    through here, so no feature can end up talking to a provider that the rest
    of the application does not know about.

    WHY THIS EXISTS
    ---------------
    Several call sites each re-implemented "which key and model?" and disagreed
    with each other. One resolver removes the disagreement.

    Rules, in order:

      1. ``LLM_PROVIDER=cloudflare`` (the platform default) with BOTH
         ``CLOUDFLARE_ACCOUNT_ID`` and ``CLOUDFLARE_API_TOKEN`` wins, and uses
         ``CLOUDFLARE_TEXT_MODEL``. Both credentials are required: without an
         account id the endpoint cannot address a model at all.
      2. ``LLM_PROVIDER=openai`` with ``LLM_API_KEY`` wins, using ``LLM_MODEL``.
      3. A Cloudflare deployment whose ``LLM_PROVIDER`` names something the
         factory cannot build still uses the Cloudflare credentials — a stale
         provider *name* must not cost us a working key. Logged as a warning.
      4. Otherwise ``None``, which callers turn into an honest "not configured"
         state rather than a runtime error.

    NEVER falls back to a provider whose credentials were not configured, never
    invents a provider, and never returns a name the factory would reject.
    There is deliberately NO second provider behind this one: a deployment that
    configured nothing gets ``None`` and degrades honestly, rather than being
    silently pointed at a different vendor's API.
    """
    def _text(value) -> str:
        """Only a real string counts as configured.

        Stubs and partially-built settings objects hand back truthy
        non-strings; treating those as a configured credential would silently
        "resolve" a provider that does not exist.
        """
        return value.strip() if isinstance(value, str) else ""

    configured = _text(settings.LLM_PROVIDER).lower()
    cf_account = _text(getattr(settings, "CLOUDFLARE_ACCOUNT_ID", ""))
    cf_token = _text(getattr(settings, "CLOUDFLARE_API_TOKEN", ""))
    cf_model = _text(getattr(settings, "CLOUDFLARE_TEXT_MODEL", ""))
    generic_key = _text(getattr(settings, "LLM_API_KEY", ""))
    generic_model = _text(getattr(settings, "LLM_MODEL", ""))

    # -- 1/3. Cloudflare: the named provider, or the only real credential -----
    cf_configured = bool(cf_account and cf_token)
    if cf_configured and (
        configured == "cloudflare" or configured not in SUPPORTED_LLM_PROVIDERS
    ):
        if configured not in SUPPORTED_LLM_PROVIDERS:
            log.warning(
                "LLM_PROVIDER=%r is not a supported provider (supported: %s); "
                "using the configured Cloudflare Workers AI credentials instead. "
                "Set LLM_PROVIDER=cloudflare to remove this ambiguity.",
                settings.LLM_PROVIDER,
                ", ".join(sorted(SUPPORTED_LLM_PROVIDERS)),
            )
        return ResolvedLLM(
            name="cloudflare",
            api_key=cf_token,
            model=cf_model or CloudflareProvider.DEFAULT_MODEL,
            account_id=cf_account,
            used_fallback=configured != "cloudflare",
        )

    # -- 2. Explicitly named supported provider with its own generic key ------
    if configured in SUPPORTED_LLM_PROVIDERS and generic_key:
        return ResolvedLLM(
            name=configured,
            api_key=generic_key,
            model=generic_model,
        )

    if configured == "cloudflare" and not cf_configured:
        # Named Cloudflare but incomplete. Say exactly which piece is missing
        # rather than returning a half-built client that 404s on every call.
        missing = []
        if not cf_account:
            missing.append("CLOUDFLARE_ACCOUNT_ID")
        if not cf_token:
            missing.append("CLOUDFLARE_API_TOKEN")
        log.error(
            "LLM_PROVIDER=cloudflare but %s not configured",
            " and ".join(missing),
        )

    return None
