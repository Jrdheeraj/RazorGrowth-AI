"""Authoritative external-execution policy — ONE switch, ONE meaning.

WHY THIS MODULE EXISTS
----------------------
``EXECUTION_ENABLED`` was interpreted in three places with three different
rules:

  * ``integrations/mcp/policy.py``   — blocks an external write whenever it
    is off (any environment);
  * ``services/action_service.py``   — blocked it only when ``is_production``;
  * ``services/action_executor.py``  — blocked it again, per executor.

Those rules disagree. Under ``APP_ENV=development`` the action service would
wave a write through to an executor that then refused it, and the operator
saw two different answers to "why did my campaign not send?" depending on
which layer answered.

Every gate now reads this module. It cannot be bypassed by a caller that
simply forgot to check, and it always produces a remediation string.

DEFAULT IS OFF. Execution stays disabled unless an operator explicitly
enables it, in every environment. Nothing here weakens a control: the
approval gate, tenant scope, integration connection and provider credential
checks are separate and unchanged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

#: Values accepted as an explicit "yes". Anything else fails closed.
_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off", ""})

REMEDIATION = (
    "Set EXECUTION_ENABLED=true in the backend environment and restart the "
    "backend. Development and test defaults stay off deliberately; this is "
    "the only switch that permits an external write."
)


@dataclass(frozen=True)
class ExecutionState:
    """One authoritative answer about external execution."""

    enabled: bool
    #: Empty when enabled; otherwise why, and what to do about it.
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return not self.enabled


def parse_execution_flag(raw: str | None) -> bool:
    """Parse the flag, failing CLOSED on anything ambiguous.

    A typo (``EXECUTION_ENABLED=treu``) must never be read as permission to
    email real customers, so unknown values resolve to disabled.
    """
    if raw is None:
        return False
    value = str(raw).strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    # Unknown / malformed → fail closed.
    return False


def external_execution_state(
    *,
    enabled: bool | None = None,
    raw_value: str | None = None,
) -> ExecutionState:
    """Resolve the single authoritative execution state.

    ``enabled`` / ``raw_value`` are test seams; production callers pass
    neither and read the configured setting.
    """
    if raw_value is not None:
        on = parse_execution_flag(raw_value)
    elif enabled is not None:
        on = bool(enabled)
    else:
        from backend.app.core.config import get_settings

        on = bool(get_settings().EXECUTION_ENABLED)

    if on:
        return ExecutionState(enabled=True)
    return ExecutionState(enabled=False, reason=REMEDIATION)


def is_external_execution_enabled() -> bool:
    """Boolean convenience wrapper for call sites that only need the gate."""
    return external_execution_state().enabled


def describe_blocking_reason(
    *, enabled: bool | None = None, raw_value: str | None = None
) -> str:
    """The actionable reason, for an error message or a UI hint."""
    state = external_execution_state(enabled=enabled, raw_value=raw_value)
    return state.reason if state.blocked else ""


__all__ = [
    "ExecutionState",
    "REMEDIATION",
    "describe_blocking_reason",
    "external_execution_state",
    "is_external_execution_enabled",
    "parse_execution_flag",
]