"""Prepare retrieved records, citations and missing inputs for the Root Cause Agent."""

from typing import TYPE_CHECKING

from pydantic import BaseModel

from src.knowledge_base.retrieval import retrieve_knowledge
from src.schemas.knowledge_retrieval import (
    DiagnosticInputStatus,
    EventInputStatus,
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalResult,
    ReviewStatus,
)

if TYPE_CHECKING:
    from pathlib import Path


class ContextCitation(BaseModel):
    citation_id: str
    record_id: str
    source_title: str
    source_url: str
    claim: str
    source_id: str | None = None
    locator: str | None = None
    verification_status: ReviewStatus | None = None


def citation_catalog(result: "KnowledgeRetrievalResult") -> dict[str, ContextCitation]:
    catalog = {}
    for historical in result.historical_matches:
        citation_id = f"historical:{historical.record_id}"
        catalog[citation_id] = ContextCitation(
            citation_id=citation_id,
            record_id=historical.record_id,
            source_title=historical.title,
            source_url=historical.source_url,
            claim=historical.summary,
        )
    evidence_groups = [
        ("mechanism", mechanism.record_id, mechanism.evidence)
        for mechanism in result.mechanism_matches
    ]
    evidence_groups.extend(
        ("diagnostic", check.check_id, check.evidence)
        for mechanism in result.mechanism_matches
        for check in mechanism.diagnostic_checks
    )
    for kind, record_id, evidence in evidence_groups:
        for item in evidence:
            citation_id = f"{kind}:{record_id}:{item.evidence_id}"
            catalog[citation_id] = ContextCitation(
                citation_id=citation_id,
                record_id=record_id,
                source_title=item.source_title,
                source_url=item.source_url,
                claim=item.claim,
                source_id=item.source_id,
                locator=item.locator,
                verification_status=item.verification_status,
            )
    return catalog


def collect_unresolved_inputs(
    result: "KnowledgeRetrievalResult",
) -> list[DiagnosticInputStatus | EventInputStatus]:
    unresolved: dict[tuple[str, str], DiagnosticInputStatus | EventInputStatus] = {}
    for mechanism in result.mechanism_matches:
        for item in mechanism.required_context:
            if item.status != "available":
                unresolved.setdefault((item.name, item.status), item)
        for check in mechanism.diagnostic_checks:
            for diagnostic in check.required_inputs:
                if diagnostic.status != "available":
                    unresolved[diagnostic.input_id, diagnostic.status] = diagnostic
    return list(unresolved.values())


class RagContext(BaseModel):
    """Event context and retrieved evidence ready for the analysis agent."""

    event_id: str
    retrieval: KnowledgeRetrievalResult
    citation_catalog: dict[str, ContextCitation]
    unresolved_inputs: list[DiagnosticInputStatus | EventInputStatus]
    request: KnowledgeRetrievalRequest


def prepare_rag_context(
    database: "Path",
    request: "KnowledgeRetrievalRequest",
    *,
    limit: int = 10,
) -> RagContext:
    """Retrieve evidence and preserve its structured context for the analysis agent."""
    result = retrieve_knowledge(database, request, limit=limit)
    return RagContext(
        event_id=result.event_id,
        request=request,
        retrieval=result,
        citation_catalog=citation_catalog(result),
        unresolved_inputs=collect_unresolved_inputs(result),
    )
