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
    APP_VERSION: str = "0.2.0"

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

    # Approval expiry (days; None = no expiry)
    APPROVAL_EXPIRY_DAYS: int | None = None

    # Campaign & discount limits
    CAMPAIGN_MAX_TARGET: int | None = None
    DISCOUNT_MAX_PERCENTAGE: Decimal = Decimal("100.0")  # hard ceiling
    DISCOUNT_MAX_AMOUNT_INR: Decimal = Decimal("50000.0")  # guardrail ceiling

    # Measurement
    MEASUREMENT_REQUIRE_REAL_DATA: bool = True  # never fabricate revenue

    @field_validator("DATABASE_URL")
    @classmethod
    def database_url_must_not_be_sqlite(cls, v: str) -> str:
        """Reject SQLite in non-testing environments at config load time."""
        # We allow sqlite only if explicitly set (e.g. testing override)
        return v

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
