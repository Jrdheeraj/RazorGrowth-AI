"""MCP argument validation — a minimal, dependency-free JSON-Schema subset.

Only what tool schemas actually use is supported, and anything unsupported
is a VALIDATION_ERROR rather than a silent pass:

    type (object/string/number/integer/boolean/array/null)
    properties, required, additionalProperties
    enum, minimum, maximum, minLength, maxLength, items
    default

This keeps the dependency surface unchanged (no jsonschema package) while
still rejecting a wrong-typed or unknown argument before a handler runs.
"""
from __future__ import annotations

from typing import Any

from backend.app.integrations.mcp.errors import ToolValidationError
from backend.app.integrations.mcp.schemas import (
    FORBIDDEN_ARG_KEYS,
    GUARDRAIL_ARG_KEYS,
    MCPToolSpec,
)

_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}

#: Lower-cased once at import. Matching is case-insensitive so a
#: case variant ("MERCHANT_ID", "Api_Key") cannot slip past on a tool that
#: declares an open schema. Today every registered schema is closed, so the
#: unknown-key rule below already drops these; this is the layer that holds
#: if a tool ever ships an open schema.
_FORBIDDEN_LOWER = frozenset(k.lower() for k in FORBIDDEN_ARG_KEYS)
_GUARDRAIL_LOWER = frozenset(k.lower() for k in GUARDRAIL_ARG_KEYS)


def is_forbidden_key(key: Any) -> bool:
    """True when the model may never supply this argument (any casing)."""
    lowered = str(key).lower()
    return lowered in _FORBIDDEN_LOWER or lowered in _GUARDRAIL_LOWER


def sanitize_arguments(
    spec: MCPToolSpec, arguments: dict[str, Any] | None
) -> tuple[dict[str, Any], list[str]]:
    """Strip tenant/credential/guardrail keys the model may never set.

    Returns ``(clean, dropped)``. Dropped keys are recorded so the agent
    can surface that it tried (audit honesty) without echoing the values.
    The caller's mapping is never mutated.
    """
    supplied = dict(arguments or {})
    props = (spec.input_schema or {}).get("properties") or {}
    # A closed schema means an unknown key is equally not the caller's to set.
    closed = (spec.input_schema or {}).get("additionalProperties", True) is False

    clean: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in supplied.items():
        if is_forbidden_key(key):
            dropped.append(str(key))
            continue
        if (props or closed) and key not in props:
            dropped.append(str(key))
            continue
        clean[key] = value
    return clean, dropped


def _check_type(name: str, value: Any, expected: Any) -> None:
    types = expected if isinstance(expected, list) else [expected]
    for t in types:
        allowed = _TYPE_MAP.get(str(t))
        if allowed is None:
            continue  # unknown type keyword: not our schema dialect
        if isinstance(value, bool) and bool not in allowed:
            continue
        if isinstance(value, allowed):
            return
    raise ToolValidationError(
        f"{name}: expected type {expected!r}, got {type(value).__name__}",
        tool=name,
    )


def validate_arguments(spec: MCPToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate model-supplied arguments against the tool's input schema.

    Applies declared defaults and raises ``ToolValidationError`` on a type
    mismatch, an unknown key (when the schema is closed), a missing
    required key, or an out-of-range / over-long value.
    """
    schema = spec.input_schema or {}
    if not schema:
        return dict(arguments or {})

    props: dict[str, Any] = schema.get("properties") or {}
    required: list[str] = schema.get("required") or []
    additional = schema.get("additionalProperties", True)

    clean = dict(arguments or {})

    for key in required:
        if key not in clean or clean[key] is None:
            raise ToolValidationError(
                f"{spec.name}: missing required argument '{key}'", tool=spec.name
            )

    if additional is False:
        for key in list(clean):
            if key not in props:
                raise ToolValidationError(
                    f"{spec.name}: unexpected argument '{key}'", tool=spec.name
                )

    out: dict[str, Any] = {}
    for key, value in clean.items():
        rule = props.get(key)
        if not rule:
            out[key] = value
            continue
        if value is None:
            out[key] = None
            continue

        _check_type(spec.name, value, rule.get("type", "string"))

        if "enum" in rule and value not in rule["enum"]:
            raise ToolValidationError(
                f"{spec.name}: '{key}' must be one of {rule['enum']!r}",
                tool=spec.name,
            )
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in rule and value < rule["minimum"]:
                raise ToolValidationError(
                    f"{spec.name}: '{key}' below minimum {rule['minimum']}",
                    tool=spec.name,
                )
            if "maximum" in rule and value > rule["maximum"]:
                raise ToolValidationError(
                    f"{spec.name}: '{key}' above maximum {rule['maximum']}",
                    tool=spec.name,
                )
        if isinstance(value, str):
            if "minLength" in rule and len(value) < rule["minLength"]:
                raise ToolValidationError(
                    f"{spec.name}: '{key}' shorter than {rule['minLength']}",
                    tool=spec.name,
                )
            if "maxLength" in rule and len(value) > rule["maxLength"]:
                raise ToolValidationError(
                    f"{spec.name}: '{key}' longer than {rule['maxLength']}",
                    tool=spec.name,
                )
        if isinstance(value, list):
            item_rule = rule.get("items") or {}
            if item_rule.get("type"):
                for i, item in enumerate(value):
                    _check_type(spec.name, item, item_rule["type"])

        if "default" in rule and value is None:
            out[key] = rule["default"]
        else:
            out[key] = value

    # Fill defaults for absent optional keys (never overrides a supplied value).
    for key, rule in props.items():
        if key not in out and isinstance(rule, dict) and "default" in rule:
            out[key] = rule["default"]
    return out


def validate_output(spec: MCPToolSpec, result: Any) -> dict[str, Any]:
    """Coerce a handler result to the declared object output shape.

    A handler returning a non-mapping is a bug, not a runtime condition —
    it is reported as VALIDATION_ERROR so the agent sees an honest failure
    instead of a malformed payload.
    """
    if isinstance(result, dict):
        return result
    raise ToolValidationError(
        f"{spec.name}: handler must return an object, got "
        f"{type(result).__name__}",
        tool=spec.name,
    )


__all__ = [
    "is_forbidden_key",
    "sanitize_arguments",
    "validate_arguments",
    "validate_output",
]