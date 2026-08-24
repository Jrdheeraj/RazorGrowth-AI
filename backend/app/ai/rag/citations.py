"""
Evidence / citation builder.

Converts raw RetrievedItem lists into structured evidence that gets
attached to AI insights. No fabrication — every evidence item must
trace back to a real retrieved chunk.
"""
from __future__ import annotations

from backend.app.ai.rag.context import RetrievedContext, RetrievedItem
from backend.app.ai.llm.models import EvidenceItem


INSUFFICIENT_EVIDENCE_THRESHOLD = 2  # fewer than this many items = insufficient


def build_evidence_items(context: RetrievedContext) -> list[EvidenceItem]:
    """Convert retrieved chunks into EvidenceItem list for AI output."""
    evidence = []
    for item in context.items:
        evidence.append(
            EvidenceItem(
                source_type=item.source_type,
                source_id=item.source_id,
                description=item.content[:300],
                relevance=f"Retrieved with similarity {item.similarity:.3f}" if item.similarity else "Keyword match",
            )
        )
    return evidence


def is_sufficient(contexts: list[RetrievedContext]) -> bool:
    """Return True if there is enough evidence across all contexts."""
    total_items = sum(len(c.items) for c in contexts)
    return total_items >= INSUFFICIENT_EVIDENCE_THRESHOLD


def summarise_evidence(contexts: list[RetrievedContext]) -> str:
    """Return a concise human-readable summary of what was retrieved."""
    if not contexts:
        return "No evidence retrieved."
    parts = []
    for ctx in contexts:
        if ctx.items:
            types = list({item.source_type for item in ctx.items})
            parts.append(
                f"Query '{ctx.query[:60]}': {len(ctx.items)} items "
                f"({', '.join(types)})"
            )
    return "; ".join(parts) if parts else "No evidence retrieved."
