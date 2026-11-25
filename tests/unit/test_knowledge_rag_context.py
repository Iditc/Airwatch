import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.knowledge_base import rag
from src.schemas.knowledge_retrieval import KnowledgeRetrievalRequest, KnowledgeRetrievalResult


@pytest.fixture
def request_data() -> KnowledgeRetrievalRequest:
    return KnowledgeRetrievalRequest.model_validate(
        {
            "event": {
                "event_id": "example-event",
                "station_id": "example-station",
                "station_name": "Example station",
                "timestamp": "2026-11-18T09:00:00+02:00",
                "pollutant": "pm10",
                "value": 120,
                "baseline_value": 40,
                "anomaly_score": 0.9,
                "severity": "high",
                "detection_method": "zscore",
                "latitude": 32,
                "longitude": 35,
            }
        }
    )


@pytest.fixture
def result_data() -> KnowledgeRetrievalResult:
    evidence = {
        "evidence_id": "ev1",
        "claim": "A research finding from the retrieved source.",
        "source_id": "source-1",
        "source_title": "Example source",
        "source_url": "https://example.org/evidence",
        "locator": "Table 1",
        "verification_status": "partially_verified",
        "verification_note": "Scope limited to the study area.",
    }
    return KnowledgeRetrievalResult.model_validate(
        {
            "event_id": "example-event",
            "historical_matches": [
                {
                    "record_id": "case-1",
                    "kind": "historical_event",
                    "title": "Example event",
                    "region": "Example region",
                    "pollutants": ["pm10"],
                    "summary": "Example historical observation.",
                    "source_url": "https://example.org/historical",
                    "investigation_hint": "Compare compatible station measurements.",
                }
            ],
            "mechanism_matches": [
                {
                    "record_id": "mech-1",
                    "title": "Example mechanism",
                    "topic": "transport",
                    "pollutants": ["pm10"],
                    "summary": "Example dust mechanism.",
                    "mechanism_explanation": "Wind can transport particles.",
                    "applicability": {"geographic_scope": "regional"},
                    "review_status": "partially_verified",
                    "evidence": [evidence],
                    "diagnostic_checks": [
                        {
                            "check_id": "check-1",
                            "title": "Compare with other stations",
                            "trigger_pattern": "Multiple stations have a PM10 rise",
                            "procedure": ["Compare aligned measurements."],
                            "interpretations": [
                                {
                                    "explanation": "Transport is plausible",
                                    "basis": "synthesis",
                                    "evidence_ids": ["ev1"],
                                }
                            ],
                            "required_inputs": [
                                {
                                    "input_id": "series",
                                    "name": "Station series",
                                    "status": "missing",
                                },
                                {
                                    "input_id": "reading",
                                    "name": "Event reading",
                                    "status": "available",
                                },
                            ],
                            "evidence": [evidence],
                            "review_status": "partially_verified",
                        }
                    ],
                }
            ],
        }
    )


def test_context_preserves_citations_and_unresolved_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_data: KnowledgeRetrievalRequest,
    result_data: KnowledgeRetrievalResult,
) -> None:
    retrieval = Mock(return_value=result_data)
    monkeypatch.setattr(rag, "retrieve_knowledge", retrieval)
    context = rag.prepare_rag_context(tmp_path / "knowledge.sqlite3", request_data)
    retrieval.assert_called_once_with(tmp_path / "knowledge.sqlite3", request_data, limit=10)
    payload = json.loads(context.model_dump_json())
    assert context.request == request_data
    assert "system_prompt" not in payload
    assert "user_context" not in payload
    citation = context.citation_catalog["diagnostic:check-1:ev1"]
    assert citation.source_url == "https://example.org/evidence"
    assert citation.locator == "Table 1"
    assert citation.verification_status == "partially_verified"
    assert payload["unresolved_inputs"][0]["input_id"] == "series"
    assert payload["retrieval"]["event_id"] == request_data.event.event_id
    assert rag.RagContext.model_validate_json(context.model_dump_json()) == context


def test_empty_retrieval_produces_empty_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request_data: KnowledgeRetrievalRequest
) -> None:
    result = KnowledgeRetrievalResult(event_id=request_data.event.event_id)
    monkeypatch.setattr(rag, "retrieve_knowledge", Mock(return_value=result))
    context = rag.prepare_rag_context(tmp_path / "knowledge.sqlite3", request_data, limit=3)
    assert context.citation_catalog == {}
    assert context.unresolved_inputs == []
    assert json.loads(context.model_dump_json())["retrieval"]["mechanism_matches"] == []
