"""
Model registry.

Importing this package guarantees that all ORM models are registered
against Base.metadata. Alembic's env.py and any script that needs the
full schema must import from here.

Import order matters: models with no FKs first, then dependents.
"""
from backend.app.models.enums import (  # noqa: F401
    AgentActionStatus,
    AgentActionType,
    ActorType,
    AuditEventType,
    CampaignStatus,
    CampaignType,
    Currency,
    CustomerSegment,
    MerchantStatus,
    OpportunityStatus,
    OpportunityType,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
)
from backend.app.models.merchant import Merchant  # noqa: F401
from backend.app.models.product import Product  # noqa: F401
from backend.app.models.customer import Customer  # noqa: F401
from backend.app.models.order import Order, OrderItem  # noqa: F401
from backend.app.models.payment import Payment  # noqa: F401
from backend.app.models.opportunity import GrowthOpportunity  # noqa: F401
from backend.app.models.campaign import Campaign  # noqa: F401
from backend.app.models.agent_action import AgentAction  # noqa: F401
from backend.app.models.audit_event import AuditEvent  # noqa: F401
from backend.app.models.knowledge import KnowledgeDocument, KnowledgeChunk  # noqa: F401
