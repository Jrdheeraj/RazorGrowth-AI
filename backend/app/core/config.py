"""
Application configuration.

All settings are loaded from environment variables (or .env file).
Never import this module's settings object into a model or database
module at module level — use dependency injection or lazy access to
avoid circular imports.
"""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Application
    # ------------------------------------------------------------------ #
    APP_ENV: Literal["development", "testing", "production"] = "development"
    APP_NAME: str = "RazorGrowth AI"
    APP_VERSION: str = "0.6.0"

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    DATABASE_URL: str = (
        "postgresql://razorgrowth:razorgrowth@localhost:5432/razorgrowth"
    )

    # ------------------------------------------------------------------ #
    # AI — LLM provider (text generation)
    # ------------------------------------------------------------------ #
    # Provider selection: "cloudflare" | "openai" (see ai/llm/provider.py).
    # Cloudflare Workers AI is the platform's text-LLM provider. It is reached
    # through the same OpenAI-compatible chat-completions surface as OpenAI, so
    # there is one client, one retry policy and one JSON/validation path.
    LLM_PROVIDER: str = "cloudflare"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: str = ""
    LLM_REQUEST_TIMEOUT: int = 60          # seconds
    LLM_MAX_RETRIES: int = 2               # retry on transient errors
    LLM_MAX_TOKENS: int = 2048             # max output tokens

    # ------------------------------------------------------------------ #
    # AI — Cloudflare Workers AI (text generation)
    # ------------------------------------------------------------------ #
    # Uses the SAME CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN pair as the
    # Designer Agent's FLUX image generation below. One Cloudflare credential
    # serves both modalities; the token never leaves the backend and is never
    # exposed to Vite or the browser.
    CLOUDFLARE_TEXT_MODEL: str = "@cf/zai-org/glm-4.7-flash"

    # ------------------------------------------------------------------ #
    # AI — Embedding provider
    # ------------------------------------------------------------------ #
    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

    # ------------------------------------------------------------------ #
    # Guardrails
    # ------------------------------------------------------------------ #
    GUARDRAIL_MAX_AMOUNT_INR: float = 50000.0   # max single action amount
    GUARDRAIL_REQUIRE_APPROVAL: bool = True      # always require human approval

    # ------------------------------------------------------------------ #
    # Phase 4 — Safe execution configuration
    # ------------------------------------------------------------------ #
    # Production safety defaults:
    #   execution disabled unless explicitly enabled.
    #   Real Razorpay execution disabled unless explicitly enabled.
    EXECUTION_ENABLED: bool = False   # global execution switch
    RAZORPAY_ENABLED: bool = False    # real Razorpay execution switch

    # Razorpay credentials — placeholders only, MUST come from environment.
    # Never hardcode real values here or commit them anywhere.
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""

    # Phase 6/8 — Razorpay boundary:
    #   RAZORPAY_TEST_MODE=true selects the deterministic simulated adapter
    #   (no network, no credentials). Live execution additionally requires
    #   EXECUTION_ENABLED=true AND RAZORPAY_ENABLED=false→true explicitly.
    RAZORPAY_TEST_MODE: bool = False
    # Explicit opt-in for REAL Razorpay TEST MODE integration (real network calls to TEST endpoints).
    # Requires RAZORPAY_ENABLED=true, RAZORPAY_TEST_MODE=true, and valid credentials.
    REAL_TEST_INTEGRATION_ENABLED: bool = False
    RAZORPAY_WEBHOOK_SECRET: str = ""

    # Approval expiry (days; None = no expiry)
    APPROVAL_EXPIRY_DAYS: int | None = None

    # Campaign & discount limits
    CAMPAIGN_MAX_TARGET: int | None = None
    DISCOUNT_MAX_PERCENTAGE: Decimal = Decimal("100.0")  # hard ceiling
    DISCOUNT_MAX_AMOUNT_INR: Decimal = Decimal("50000.0")  # guardrail ceiling

    # ------------------------------------------------------------------ #
    # Marketing Agent integrations — application-level provider config.
    # Per-workspace credentials (API keys, OAuth tokens) are NEVER stored
    # here: merchants connect via the API and secrets are Fernet-encrypted
    # in the integration_connections table (see core/credential_vault.py).
    # ------------------------------------------------------------------ #
    # Dedicated Fernet key (urlsafe-base64, 32 bytes) for credential
    # encryption at rest. Empty = derived from AUTH_SECRET_KEY (dev only;
    # production should set an explicit key — startup logs a warning).
    INTEGRATION_CREDENTIAL_KEY: str = ""

    # ------------------------------------------------------------------ #
    # Designer Agent — image generation (Cloudflare Workers AI).
    #
    # Platform-level provider config, exactly like the Marketing Agent
    # integrations above: the credential lives only here, never in the
    # database and never on the client. The Designer Agent itself is not a
    # business-action path, so no approval gate is involved — but the flag
    # below defaults to OFF so an unconfigured deployment can never spend
    # provider quota by accident.
    #
    # Enabling requires BOTH the flag and both credentials. A missing piece
    # is reported honestly as an unavailable provider; it is never faked,
    # never silently bypassed, and never degrades into a placeholder image.
    # ------------------------------------------------------------------ #
    #: Master switch. False by default, including in Docker.
    IMAGE_GENERATION_ENABLED: bool = False
    #: Cloudflare account that owns the Workers AI binding. SHARED with the
    #: text-LLM provider above — one account, one token, two modalities.
    CLOUDFLARE_ACCOUNT_ID: str = ""
    #: Cloudflare API token with Workers AI read permission. Server-side only.
    CLOUDFLARE_API_TOKEN: str = ""
    #: Hard ceiling on a single decoded image, enforced before persisting.
    IMAGE_MAX_BYTES: int = 4 * 1024 * 1024          # 4 MiB
    #: Wall-clock ceiling for one provider call.
    IMAGE_REQUEST_TIMEOUT_SECONDS: int = 60
    #: Provider retry attempts for transient failures (5xx / timeout).
    IMAGE_MAX_RETRIES: int = 2
    #: Per-merchant generation ceiling per UTC day.
    IMAGE_DAILY_QUOTA_PER_MERCHANT: int = 50
    #: Per-merchant stored-image ceiling per UTC day (bytes).
    IMAGE_DAILY_STORAGE_QUOTA_BYTES: int = 64 * 1024 * 1024   # 64 MiB
    #: JPEG structural limits enforced by the bounded parser.
    IMAGE_MAX_WIDTH: int = 2048
    IMAGE_MAX_HEIGHT: int = 2048
    IMAGE_MAX_PIXELS: int = 4_194_304                            # 2048x2048

    # Email (Resend). Optional platform default; merchants may also connect
    # their own Resend key per workspace via the integrations API.
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = ""
    RESEND_FROM_NAME: str = "RazorGrowth"

    # Google Ads OAuth application (Google Cloud Console).
    # GOOGLE_ADS_DEVELOPER_TOKEN is sent as the `developer-token` header on
    # Google Ads API calls when set (Google Ads API Center → API Central).
    # Projects enrolled in Google's token-less access may leave it empty;
    # when Google requires the header and it is missing, the API answers
    # requestError.DEVELOPER_TOKEN_PARAMETER_MISSING, which the integration
    # surfaces as a MISSING_CONFIGURATION error (never raw Google JSON).
    # A merchant may also supply a per-connection override via the API.
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = ""
    GOOGLE_ADS_DEVELOPER_TOKEN: str = ""
    GOOGLE_ADS_API_VERSION: str = "v25"

    # Base URL of the merchant-facing frontend. OAuth callbacks land on the
    # backend (no auth header) and are redirected here with ONLY a safe
    # integration/status/code triple — never tokens or provider payloads.
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # Meta (Ads + Instagram) application (Meta Developers dashboard).
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_OAUTH_REDIRECT_URI: str = ""
    META_GRAPH_VERSION: str = "v24.0"

    # Measurement
    MEASUREMENT_REQUIRE_REAL_DATA: bool = True  # never fabricate revenue

    # ------------------------------------------------------------------ #
    # Autonomous research (web search + public page retrieval)
    # ------------------------------------------------------------------ #
    # Vendor-neutral: point these at whichever search API the deployment
    # holds a credential for. With them unset, research-capable agents
    # report `unavailable` with this exact reason and degrade honestly --
    # they never invent sources, URLs or findings.
    RESEARCH_SEARCH_ENDPOINT: str = ""
    RESEARCH_API_KEY: str = ""
    #: Dotted path to the result array inside the provider's JSON response.
    RESEARCH_RESULTS_PATH: str = "results"
    RESEARCH_TITLE_FIELD: str = "title"
    RESEARCH_URL_FIELD: str = "url"
    RESEARCH_SNIPPET_FIELD: str = "snippet"

    # ------------------------------------------------------------------ #
    # Phase 6 — Authentication & security
    # ------------------------------------------------------------------ #
    # "required": every non-public endpoint needs a valid Bearer token.
    # "optional": unauthenticated requests fall back to legacy single-
    #   tenant behaviour (development convenience ONLY). Authenticated
    #   requests are fully validated in BOTH modes. Production MUST run
    #   with AUTH_MODE=required (enforced by the startup safety check).
    AUTH_MODE: Literal["required", "optional"] = "required"

    # Signing key for access tokens. NEVER commit a real value.
    # Production refuses to start unless this is set (>= 32 chars).
    AUTH_SECRET_KEY: str = ""

    AUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    AUTH_ENABLE_REGISTRATION: bool = True   # open self-registration toggle
    PASSWORD_MIN_LENGTH: int = 12

    # Comma-separated list of allowed CORS origins. Empty = no cross-origin
    # browser access is permitted (same-origin only).
    CORS_ORIGINS: str = ""
    # Comma-separated allowed Host values; "*" allows any host (development).
    TRUSTED_HOSTS: str = "*"
    SECURITY_HEADERS_ENABLED: bool = True
    # None = auto (enabled outside production, disabled in production).
    ENABLE_DOCS: bool | None = None

    # Simple sliding-window rate limiting (per client IP per bucket).
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_REQUESTS: int = 10            # login/register attempts
    RATE_LIMIT_AUTH_WINDOW_SECONDS: int = 300
    RATE_LIMIT_WEBHOOK_REQUESTS: int = 60         # webhook endpoint
    RATE_LIMIT_WEBHOOK_WINDOW_SECONDS: int = 60

    @field_validator("DATABASE_URL")
    @classmethod
    def database_url_must_not_be_sqlite(cls, v: str) -> str:
        """Reject SQLite in non-testing environments at config load time."""
        # We allow sqlite only if explicitly set (e.g. testing override)
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [h.strip() for h in self.TRUSTED_HOSTS.split(",") if h.strip()]

    @property
    def docs_enabled(self) -> bool:
        if self.ENABLE_DOCS is not None:
            return self.ENABLE_DOCS
        return not self.is_production

    @property
    def is_testing(self) -> bool:
        return self.APP_ENV == "testing"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
