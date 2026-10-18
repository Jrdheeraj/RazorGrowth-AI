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
    DesignAssetKind,
    DesignAssetStatus,
    DesignProjectStatus,
    DesignReviewStatus,
    ImageGenerationStatus,
    MembershipStatus,
    MerchantStatus,
    OpportunityStatus,
    OpportunityType,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
    UserRole,
    UserStatus,
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

# Phase 5 — Agentic Growth Intelligence
from backend.app.models.growth_signal import GrowthSignal  # noqa: F401
from backend.app.models.customer_insight import CustomerInsight  # noqa: F401
from backend.app.models.experiment import (  # noqa: F401
    Simulation,
    Experiment,
    ExperimentResult,
)
# Imported BEFORE agent_run: agent_runs.workflow_id references it.
from backend.app.models.agent_workflow import AgentWorkflowRun  # noqa: F401
from backend.app.models.agent_run import AgentRun  # noqa: F401
from backend.app.models.agent_memory import AgentMemory  # noqa: F401
from backend.app.models.handoff import AgentHandoff  # noqa: F401
from backend.app.models.personalization import PersonalizationDecision  # noqa: F401

# Phase 6 — Authentication, Multi-Tenancy & Production Security
from backend.app.models.user import User  # noqa: F401
from backend.app.models.membership import MerchantMembership  # noqa: F401

# Phase 7 — Recommendation & Approval
from backend.app.models.recommendation import Recommendation  # noqa: F401
from backend.app.models.approval import Approval  # noqa: F401
from backend.app.models.agent_debate import (  # noqa: F401
    AgentDebate,
    AgentTask,
    AgentFinding,
    AgentMessage,
)

# Marketing AGI — autonomous marketing employee (isolated module)
from backend.app.models.marketing_agi import (  # noqa: F401
    MarketingAGIRun,
    MarketingAGIEvent,
    MarketingAGICampaign,
    MarketingAGIHandoff,
    MarketingAGILearning,
)

# Marketing Agent integration hub (per-workspace provider connections)
from backend.app.models.integration_connection import (  # noqa: F401
    IntegrationConnection,
)

# Product AGI — autonomous product-growth employee (isolated module).
# Imported AFTER agent_actions because recommendations reference it.
from backend.app.models.product_agi import (  # noqa: F401
    ProductAgentRun,
    ProductAgentEvent,
    ProductAgentFinding,
    ProductAgentRecommendation,
)

# Designer Agent — the creative workspace. Imported AFTER agent_debates,
# agent_runs, growth_opportunities and agent_actions because projects and
# briefs reference all four by id.
from backend.app.models.designer import (  # noqa: F401
    CreativeBrief,
    DesignAsset,
    DesignAssetVersion,
    DesignProject,
)

# Rendered creative assets — image BYTES for a design asset version.
# Imported AFTER designer because every FK here targets design_assets or
# design_asset_versions.
from backend.app.models.rendered_asset import RenderedAsset  # noqa: F401
