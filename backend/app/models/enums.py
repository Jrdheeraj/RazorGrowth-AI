"""
Domain enumerations.

Centralising all controlled-vocabulary types here prevents magic strings
from proliferating across the codebase. Every column that uses an enum
must reference this module.
"""
from __future__ import annotations

import enum


class MerchantStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    closed = "closed"


class Currency(str, enum.Enum):
    INR = "INR"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class CustomerSegment(str, enum.Enum):
    new = "new"
    returning = "returning"
    vip = "vip"
    at_risk = "at_risk"
    churned = "churned"


class OrderStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    paid = "paid"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"
    refunded = "refunded"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    authorised = "authorised"
    captured = "captured"
    failed = "failed"
    refunded = "refunded"


class PaymentProvider(str, enum.Enum):
    razorpay = "razorpay"
    synthetic = "synthetic"


class OpportunityType(str, enum.Enum):
    upsell = "upsell"
    cross_sell = "cross_sell"
    campaign = "campaign"
    checkout_optimization = "checkout_optimization"
    failed_payment_recovery = "failed_payment_recovery"


class OpportunityStatus(str, enum.Enum):
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    executing = "executing"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class CampaignType(str, enum.Enum):
    email = "email"
    sms = "sms"
    push = "push"
    discount = "discount"


class CampaignStatus(str, enum.Enum):
    draft = "draft"
    scheduled = "scheduled"
    running = "running"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class AgentActionType(str, enum.Enum):
    send_campaign = "send_campaign"
    create_discount = "create_discount"
    retry_payment = "retry_payment"
    generate_opportunity = "generate_opportunity"


class AgentActionStatus(str, enum.Enum):
    requested = "requested"
    approved = "approved"
    rejected = "rejected"
    executing = "executing"
    completed = "completed"
    failed = "failed"


class ActorType(str, enum.Enum):
    system = "system"
    ai_agent = "ai_agent"
    merchant_user = "merchant_user"


class AuditEventType(str, enum.Enum):
    opportunity_created = "opportunity_created"
    opportunity_approved = "opportunity_approved"
    opportunity_rejected = "opportunity_rejected"
    action_requested = "action_requested"
    action_approved = "action_approved"
    action_started = "action_started"
    action_completed = "action_completed"
    action_failed = "action_failed"
    payment_created = "payment_created"
    payment_succeeded = "payment_succeeded"
    payment_failed = "payment_failed"
    seed_applied = "seed_applied"
    # Phase 3 additions
    ingestion_started = "ingestion_started"
    ingestion_completed = "ingestion_completed"
    ingestion_failed = "ingestion_failed"
    guardrail_evaluated = "guardrail_evaluated"
    guardrail_rejected = "guardrail_rejected"
    analysis_started = "analysis_started"
    analysis_completed = "analysis_completed"
    analysis_failed = "analysis_failed"
    retrieval_performed = "retrieval_performed"


class ApprovalStatus(str, enum.Enum):
    requires_approval = "requires_approval"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"
