"""Pydantic contracts for the Phase 6 authentication API."""
from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str) -> str:
    if not _EMAIL_RE.match(value):
        raise ValueError("INVALID_EMAIL")
    return value.lower().strip()


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str) -> str:
        return _validate_email(v)


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=1024)
    full_name: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str) -> str:
        return _validate_email(v)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None = None
    status: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class MembershipOut(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    role: str
    status: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None = None
    status: str
    memberships: list[MembershipOut]


class MerchantSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str


class AccessibleMerchantsResponse(BaseModel):
    merchants: list[MerchantSummary]


class CreateMembershipRequest(BaseModel):
    """Admin/owner operation: attach a user to the caller's merchant."""

    email: str = Field(..., min_length=3, max_length=320)
    role: str = Field(..., pattern="^(owner|admin|operator|analyst)$")
    # Only used when the target user does not exist yet. Must satisfy the
    # password policy; the recipient is expected to rotate it.
    initial_password: str | None = Field(default=None, min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str) -> str:
        return _validate_email(v)


class UpdateMembershipRequest(BaseModel):
    role: str | None = Field(default=None, pattern="^(owner|admin|operator|analyst)$")
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
