"""Cloudflare Workers AI provider — FLUX.1 [schnell] text-to-image.

The ONLY outbound HTTP path for Designer Agent image generation.

ENDPOINT (verified against the official model page and its raw schemas)
----------------------------------------------------------------------
POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/
     @cf/black-forest-labs/flux-1-schnell
Authorization: Bearer {token}
Content-Type: application/json

Input schema is ``additionalProperties: false`` with exactly two properties::

    {"prompt": <string, 1..2048, required>, "steps": <int, max 8, default 4>}

The model's own documentation shows a ``curl`` example that also sends
``seed``. That example is WRONG against the published schema — ``seed`` is
not a declared property and ``additionalProperties`` is false, so sending it
risks a 400. This client therefore never sends ``seed``.

Response envelope (REST wraps the model output in ``result``)::

    {"result": {"image": "<base64 JPEG>"}, "success": true, "errors": [], "messages": []}

The Workers-binding examples in the docs show ``response.image`` directly;
that is the binding, which unwraps. REST does not.

ERROR HANDLING — WHY NOTHING RAW IS EVER RETURNED
-------------------------------------------------
Cloudflare error bodies can echo the prompt, and a prompt is derived from a
merchant's own brief. So no provider response body, header, token or URL is
logged or returned. Failures are collapsed into a small closed set of stable
codes, and the raw payload is discarded after being reduced to that code. The
prompt never appears in an exception message.
"""
from __future__ import annotations

import base64
import binascii
import logging
import re
from dataclasses import dataclass
from typing import Any, Final

import httpx

log = logging.getLogger(__name__)

MODEL: Final[str] = "@cf/black-forest-labs/flux-1-schnell"
PROVIDER_NAME: Final[str] = "cloudflare"
MODEL_LABEL: Final[str] = "cloudflare-flux-1-schnell"

API_ROOT: Final[str] = "https://api.cloudflare.com/client/v4/accounts"

#: Provider-published input bounds. Re-checked here so an oversized value is
#: refused locally instead of costing a round trip to be rejected.
PROMPT_MAX_CHARS: Final[int] = 2048
STEPS_MAX: Final[int] = 8
STEPS_DEFAULT: Final[int] = 4

#: Hard ceiling on the decoded image, independent of the configured limit.
#: Guards the base64 decode itself, which happens before any store call.
MAX_DECODED_BYTES: Final[int] = 8 * 1024 * 1024


class ImageGenerationError(RuntimeError):
    """A provider failure reduced to a stable, leak-free code.

    ``code`` is safe to log and to return in an API status field. ``message``
    is deliberately generic; it never embeds provider output or the prompt.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.safe_message = message


@dataclass(frozen=True)
class GeneratedImage:
    """Validated provider output, ready to store. Holds bytes, never a URL."""

    data: bytes
    provider: str
    model: str
    steps: int | None


@dataclass(frozen=True)
class ProviderAvailability:
    available: bool
    reason: str | None
    provider: str = PROVIDER_NAME


def validate_prompt(prompt: str) -> str:
    """Validate and normalise a prompt against the provider's own bounds."""
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    cleaned = " ".join(prompt.split()).strip()
    if not cleaned:
        raise ValueError("prompt must not be empty")
    if len(cleaned) > PROMPT_MAX_CHARS:
        raise ValueError(
            f"prompt is {len(cleaned)} characters, over the "
            f"{PROMPT_MAX_CHARS} character limit"
        )
    return cleaned


def validate_steps(steps: int | None) -> int | None:
    """``steps`` is optional; when supplied it must be 1..8."""
    if steps is None:
        return None
    if isinstance(steps, bool) or not isinstance(steps, int):
        raise ValueError("steps must be an integer")
    if steps < 1 or steps > STEPS_MAX:
        raise ValueError(f"steps must be between 1 and {STEPS_MAX}")
    return steps


def build_url(account_id: str, model: str = MODEL) -> str:
    """The model path segment contains an ``@`` and slashes and must NOT be
    re-encoded, so it is appended literally."""
    return f"{API_ROOT}/{account_id}/ai/run/{model}"


def provider_availability(
    *, enabled: bool, account_id: str, api_token: str
) -> ProviderAvailability:
    """Honest capability state.

    Never fabricates readiness: a missing flag or a missing credential yields
    ``available=False`` with a stated reason, and the dashboard reports
    ``unavailable`` rather than pretending a provider exists.
    """
    if not enabled:
        return ProviderAvailability(
            False,
            "Image generation is switched off (IMAGE_GENERATION_ENABLED=false).",
        )
    if not account_id.strip():
        return ProviderAvailability(
            False, "CLOUDFLARE_ACCOUNT_ID is not configured."
        )
    if not api_token.strip():
        return ProviderAvailability(
            False, "CLOUDFLARE_API_TOKEN is not configured."
        )
    return ProviderAvailability(True, None)


class CloudflareImageGenerator:
    """Minimal, stateless client for one model call."""

    def __init__(
        self,
        *,
        account_id: str,
        api_token: str,
        timeout_seconds: int = 60,
        max_retries: int = 2,
        max_bytes: int = 4 * 1024 * 1024,
        client: httpx.Client | None = None,
    ) -> None:
        self._account_id = account_id
        self._api_token = api_token
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._max_bytes = max_bytes
        # Injected in tests; otherwise a plain synchronous client.
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        if not getattr(self, "_owns_client", True):
            return
        try:
            self._client.close()
        except Exception:  # pragma: no cover - defensive
            pass

    def __enter__(self) -> "CloudflareImageGenerator":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def generate(
        self, prompt: str, *, steps: int | None = None
    ) -> GeneratedImage:
        """One image. Raises :class:`ImageGenerationError` with a safe code."""
        text = validate_prompt(prompt)
        step_count = validate_steps(steps)
        url = build_url(self._account_id)

        payload: dict[str, Any] = {"prompt": text}
        if step_count is not None:
            payload["steps"] = step_count

        # The prompt is deliberately absent from every log line and error.
        log.info(
            "cloudflare image generation requested (model=%s, steps=%s, prompt_chars=%d)",
            MODEL_LABEL,
            step_count,
            len(text),
        )

        response = self._post(url, payload)
        return self._decode(response, step_count)

    # ── internals ────────────────────────────────────────────────────────

    def _post(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # `response` always holds the LAST attempt's result, so a retry that
        # eventually succeeds is never discarded in favour of an earlier 5xx.
        response: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(
                    url, json=payload, headers=headers, timeout=self._timeout
                )
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    log.warning("cloudflare timeout, retrying (attempt %d)", attempt + 1)
                    continue
                raise ImageGenerationError(
                    "PROVIDER_TIMEOUT",
                    "The image provider did not respond in time.",
                ) from exc
            except httpx.HTTPError as exc:
                raise ImageGenerationError(
                    "PROVIDER_NETWORK_ERROR",
                    "The image provider could not be reached.",
                ) from exc

            retryable = response.status_code == 429 or response.status_code in (
                500, 502, 503, 504
            )
            if not retryable:
                break
            if attempt < self._max_retries:
                log.warning(
                    "cloudflare %d, retrying (attempt %d)",
                    response.status_code,
                    attempt + 1,
                )
                continue
            # Retries exhausted: classify and raise, never echo the body.
            if response.status_code == 429:
                raise ImageGenerationError(
                    "PROVIDER_RATE_LIMITED",
                    "The image provider is rate limiting this workspace.",
                )
            break

        assert response is not None  # loop always assigns or raises
        if response.status_code >= 400:
            log.error(
                "cloudflare image generation failed (status=%d)", response.status_code
            )
            if response.status_code in (401, 403):
                raise ImageGenerationError(
                    "PROVIDER_REJECTED",
                    "The image provider credentials were refused.",
                )
            code = (
                "PROVIDER_REJECTED"
                if response.status_code in (400, 404, 422)
                else "PROVIDER_ERROR"
            )
            message = (
                "The image provider rejected the request."
                if code == "PROVIDER_REJECTED"
                else "The image provider returned an error."
            )
            raise ImageGenerationError(code, message)

        return response

    def _decode(self, response: httpx.Response, steps: int | None) -> GeneratedImage:
        try:
            envelope = response.json()
        except ValueError as exc:
            raise ImageGenerationError(
                "PROVIDER_MALFORMED_RESPONSE",
                "The image provider returned an unreadable response.",
            ) from exc

        if not isinstance(envelope, dict) or not envelope.get("success", False):
            # Note: no errors[] detail, no request echo, nothing from the body.
            raise ImageGenerationError(
                "PROVIDER_ERROR",
                "The image provider reported a failure.",
            )

        result = envelope.get("result")
        if not isinstance(result, dict):
            raise ImageGenerationError(
                "PROVIDER_MALFORMED_RESPONSE",
                "The image provider returned no image payload.",
            )
        encoded = result.get("image")
        if not isinstance(encoded, str) or not encoded:
            raise ImageGenerationError(
                "PROVIDER_MALFORMED_RESPONSE",
                "The image provider returned no image payload.",
            )

        # Base64 decode with a size bound so a hostile body cannot force a huge
        # allocation before any other validation runs.
        approx_bytes = (len(encoded) * 3) // 4
        if approx_bytes > max(MAX_DECODED_BYTES, self._max_bytes):
            raise ImageGenerationError(
                "IMAGE_TOO_LARGE",
                "The generated image is larger than this workspace allows.",
            )

        # Tolerate a data: prefix if a provider ever adds one, and whitespace
        # in wrapped base64.
        payload = re.sub(r"\s+", "", encoded)
        if payload.startswith("data:"):
            _, _, payload = payload.partition(",")

        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImageGenerationError(
                "PROVIDER_MALFORMED_RESPONSE",
                "The image provider returned an unreadable image payload.",
            ) from exc

        if not data:
            raise ImageGenerationError(
                "PROVIDER_MALFORMED_RESPONSE",
                "The image provider returned an empty image payload.",
            )
        if len(data) > self._max_bytes:
            raise ImageGenerationError(
                "IMAGE_TOO_LARGE",
                "The generated image is larger than this workspace allows.",
            )

        return GeneratedImage(
            data=data, provider=PROVIDER_NAME, model=MODEL_LABEL, steps=steps
        )


__all__ = [
    "API_ROOT",
    "CloudflareImageGenerator",
    "GeneratedImage",
    "ImageGenerationError",
    "MODEL",
    "MODEL_LABEL",
    "PROMPT_MAX_CHARS",
    "PROVIDER_NAME",
    "ProviderAvailability",
    "STEPS_DEFAULT",
    "STEPS_MAX",
    "build_url",
    "provider_availability",
    "validate_prompt",
    "validate_steps",
]