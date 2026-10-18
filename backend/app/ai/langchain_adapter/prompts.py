"""
Prompt construction and context management for LangChain agents.

Provides structured prompt templates for all 14 agents with built-in tenant
isolation guardrails, context sanitization, and structured reasoning formats.
"""
from __future__ import annotations

import re
from typing import Any

from langchain_core.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)

# Common regexes to redact sensitive tokens from prompt context
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|auth[_-]?token|bearer)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-\.]{8,})['\"]?"),
    re.compile(r"(?i)(rzp_test_[a-zA-Z0-9]{14,}|rzp_live_[a-zA-Z0-9]{14,})"),
]


def sanitize_context_data(data: Any) -> Any:
    """Recursively sanitize context dictionaries to prevent secret leakage in prompts."""
    if isinstance(data, dict):
        sanitized: dict[str, Any] = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(term in k_lower for term in ("key", "secret", "token", "password", "credential")):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_context_data(v)
        return sanitized
    if isinstance(data, list):
        return [sanitize_context_data(item) for item in data]
    if isinstance(data, str):
        cleaned = data
        for pattern in _SECRET_PATTERNS:
            cleaned = pattern.sub(r"\1: [REDACTED]", cleaned)
        return cleaned
    return data


def build_agent_chat_prompt(
    system_instruction: str,
    user_instruction: str,
) -> ChatPromptTemplate:
    """Construct a LangChain ChatPromptTemplate with standard safety guardrails."""
    full_system = (
        "You are an expert AI growth agent operating on behalf of an authorized merchant "
        "on the RazorGrowth AI platform.\n"
        "Security & Tenancy Rules:\n"
        "1. Never request, generate, or accept credentials, secrets, or raw PII.\n"
        "2. Do not invent ungrounded business metrics or fake telemetry.\n"
        "3. Only recommend actions compliant with merchant policies; actions requiring consequential "
        "modifications must land in pending-approval status.\n\n"
        f"Agent Specific Responsibilities:\n{system_instruction}"
    )

    escaped_system = full_system.replace("{", "{{").replace("}", "}}")
    escaped_user = user_instruction.replace("{", "{{").replace("}", "}}")

    return ChatPromptTemplate.from_messages(
        [
            SystemMessagePromptTemplate.from_template(escaped_system),
            HumanMessagePromptTemplate.from_template(escaped_user),
        ]
    )

