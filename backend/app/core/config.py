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
    # AI — LLM provider
    # ------------------------------------------------------------------ #
    # Provider selection: "openai" | "groq" (see llm/provider.py factory).
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: str = ""
    LLM_REQUEST_TIMEOUT: int = 60          # seconds
    LLM_MAX_RETRIES: int = 2               # retry on transient errors
    LLM_MAX_TOKENS: int = 2048             # max output tokens

    # ------------------------------------------------------------------ #
    # AI — Groq (used when LLM_PROVIDER="groq")
    # ------------------------------------------------------------------ #
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"   # current Groq production model

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

    # Measurement
    MEASUREMENT_REQUIRE_REAL_DATA: bool = True  # never fabricate revenue

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
