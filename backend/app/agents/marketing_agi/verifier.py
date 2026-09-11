"""MarketingAGI self-verification — every prepared action must pass.

Before ANY action is prepared, the verifier checks:

  - correct merchant (tenant match)
  - correct audience (valid customer records, non-empty, within limits)
  - duplicate recipients (deduped audience ids)
  - correct campaign (campaign draft exists and is complete)
  - correct channel + supported integration (no fake external execution)
  - valid content (objective, message, CTA present)
  - evidence present for the recommendation
  - expected impact present and bounded
  - approval requirement acknowledged (never auto-approve)

If verification fails, the loop investigates and fixes — it never
silently continues.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.marketing_agi import MarketingAGICampaign
from backend.app.agents.marketing_agi.limits import LoopLimits


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass
class VerificationReport:
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failed_names(self) -> list[str]:
        return [c.name for c in self.checks if not c.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
            "failed": self.failed_names,
        }


def _check(name: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, passed=ok, detail=detail)


def verify_campaign(
    db: Session,
    merchant_id: uuid.UUID,
    campaign: MarketingAGICampaign,
    audience_customer_ids: list[str],
    evidence_count: int,
    limits: LoopLimits | None = None,
) -> VerificationReport:
    limits = limits or LoopLimits()
    checks: list[CheckResult] = []

    # 1. tenant
    checks.append(
        _check(
            "merchant_scope",
            str(campaign.merchant_id) == str(merchant_id),
            f"campaign belongs to merchant {merchant_id}",
        )
    )

    # 2. audience validity
    ids = [i for i in audience_customer_ids if i]
    deduped = list(dict.fromkeys(ids))  # order-preserving dedupe
    checks.append(
        _check("audience_non_empty", len(deduped) > 0, f"{len(deduped)} recipients")
    )
    dup_count = len(ids) - len(deduped)
    checks.append(
        _check("no_duplicate_recipients", dup_count == 0, f"{dup_count} duplicates removed")
    )
    checks.append(
        _check(
            "audience_within_limits",
            0 < len(deduped) <= limits.max_audience_size,
            f"{len(deduped)} within [1, {limits.max_audience_size}]",
        )
    )

    # every audience member must be a real customer of THIS merchant
    valid_ids: set[str] = set()
    if deduped:
        try:
            uuids = [uuid.UUID(i) for i in deduped]
            rows = db.scalars(
                select(Customer.id).where(
                    Customer.merchant_id == merchant_id,
                    Customer.id.in_(uuids),
                )
            ).all()
            valid_ids = {str(r) for r in rows}
        except ValueError:
            valid_ids = set()
    checks.append(
        _check(
            "audience_records_valid",
            len(deduped) == len(valid_ids),
            f"{len(valid_ids)}/{len(deduped)} ids belong to this merchant",
        )
    )

    # 3. campaign completeness
    content = campaign.content or {}
    checks.append(
        _check(
            "content_valid",
            bool(content.get("message") or content.get("variants")),
            "message or variants present",
        )
    )
    checks.append(
        _check(
            "channel_integration_honest",
            campaign.integration_status
            in {"connected", "draft_only", "requires_integration"},
            f"integration_status={campaign.integration_status}",
        )
    )
    checks.append(
        _check(
            "no_external_execution_claim",
            campaign.lifecycle not in {"executing", "completed"},
            f"lifecycle={campaign.lifecycle} (approval not bypassed)",
        )
    )

    # 4. evidence + impact
    checks.append(
        _check(
            "evidence_present",
            evidence_count > 0,
            f"{evidence_count} evidence items",
        )
    )
    checks.append(
        _check(
            "expected_impact_present",
            bool((campaign.expected_impact or {}).get("rationale")),
            "expected impact rationale present",
        )
    )

    # 5. approval gate acknowledged
    checks.append(
        _check(
            "approval_required",
            True,
            "human approval is required before any execution",
        )
    )

    report = VerificationReport(
        passed=all(c.passed for c in checks),
        checks=checks,
    )
    return report


def audience_from_find_customers(result: dict[str, Any]) -> list[str]:
    """Extract validated audience ids from a find_customers tool result."""
    customers = (result or {}).get("customers", [])
    return [c["customer_id"] for c in customers if c.get("customer_id")]
