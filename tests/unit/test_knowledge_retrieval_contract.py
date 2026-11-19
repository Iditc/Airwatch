from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.anomaly import AnomalyEvent, DetectionMethod, Pollutant, Severity
from src.schemas.knowledge_retrieval import (
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalResult,
    RetrievedEvidence,
    StationMeasurementSeries,
)


@pytest.fixture
def anomaly() -> AnomalyEvent:
    return AnomalyEvent(
        event_id="synthetic-event",
        station_id="station-1",
        station_name="Example station",
        timestamp=datetime(2026, 11, 18, 7, tzinfo=timezone.utc),
        pollutant=Pollutant.PM10,
        value=100,
        baseline_value=40,
        anomaly_score=0.8,
        severity=Severity.HIGH,
        detection_method=DetectionMethod.ZSCORE,
        latitude=32,
        longitude=35,
    )


def test_request_distinguishes_unsupplied_neighbors_from_empty_list(anomaly: AnomalyEvent) -> None:
    request = KnowledgeRetrievalRequest(event=anomaly)
    assert request.weather is None
    assert request.neighbors is None
    assert request.recent_measurement_series is None
    assert KnowledgeRetrievalRequest(event=anomaly, neighbors=[]).neighbors == []


def test_request_accepts_event_and_neighbor_measurement_series(anomaly: AnomalyEvent) -> None:
    request = KnowledgeRetrievalRequest.model_validate(
        {
            "event": anomaly,
            "recent_measurement_series": [
                {
                    "station_id": anomaly.station_id,
                    "pollutant": "pm10",
                    "unit": "µg/m³",
                    "averaging_period_seconds": 300,
                    "measurements": [
                        {"timestamp": "2026-11-18T06:50:00Z", "value": 35},
                        {"timestamp": "2026-11-18T06:55:00Z", "value": 92},
                    ],
                },
                {
                    "station_id": "station-2",
                    "pollutant": "pm10",
                    "unit": "µg/m³",
                    "averaging_period_seconds": 300,
                    "measurements": [
                        {
                            "timestamp": "2026-11-18T06:55:00Z",
                            "value": 38,
                            "quality_flag": "provisional",
                        }
                    ],
                },
            ],
        }
    )
    series = request.recent_measurement_series
    assert series is not None
    assert [item.station_id for item in series] == [anomaly.station_id, "station-2"]
    assert series[1].measurements[0].quality_flag == "provisional"
    assert KnowledgeRetrievalRequest.model_validate_json(request.model_dump_json()) == request


def test_series_rejects_duplicate_instants_with_different_time_zones() -> None:
    with pytest.raises(ValidationError, match="timestamps must be strictly increasing"):
        StationMeasurementSeries.model_validate(
            {
                "station_id": "station-2",
                "pollutant": "pm10",
                "unit": "µg/m³",
                "measurements": [
                    {"timestamp": "2026-11-18T06:50:00Z", "value": 38},
                    {"timestamp": "2026-11-18T08:50:00+02:00", "value": 39},
                ],
            }
        )


@pytest.mark.parametrize(
    ("field", "value"), [("value", float("nan")), ("baseline_value", float("inf"))]
)
def test_request_rejects_nonfinite_event_measurements(
    anomaly: AnomalyEvent, field: str, value: float
) -> None:
    event = anomaly.model_copy(update={field: value})
    with pytest.raises(ValidationError, match="measurement and baseline must be finite"):
        KnowledgeRetrievalRequest(event=event)


def test_result_accepts_no_matches() -> None:
    result = KnowledgeRetrievalResult(event_id="synthetic-event")
    assert result.historical_matches == []
    assert result.mechanism_matches == []


def test_result_json_preserves_citations_and_missing_inputs() -> None:
    evidence = RetrievedEvidence(
        evidence_id="ev1",
        claim="Synthetic claim about PM10.",
        source_id="source-1",
        source_title="Example source",
        source_url="https://example.org/source",
        locator="Table 1",
        verification_status="partially_verified",
        verification_note="Example evidence has limited scope.",
    )
    result = KnowledgeRetrievalResult.model_validate(
        {
            "event_id": "synthetic-event",
            "historical_matches": [
                {
                    "record_id": "example-event",
                    "kind": "historical_event",
                    "title": "Example dust event",
                    "region": "Example region",
                    "pollutants": ["pm10"],
                    "summary": "An example dated observation.",
                    "source_url": "https://example.org/historical",
                    "start_date": "2020-01-01",
                    "investigation_hint": "Check station coverage.",
                    "matched_on": ["PM10"],
                }
            ],
            "mechanism_matches": [
                {
                    "record_id": "example-mechanism",
                    "title": "Example regional dust",
                    "topic": "transport",
                    "pollutants": ["pm10"],
                    "summary": "An example mechanism.",
                    "mechanism_explanation": "Winds transport dust across the area.",
                    "applicability": {"geographic_scope": "regional"},
                    "review_status": "partially_verified",
                    "evidence": [evidence],
                    "diagnostic_checks": [
                        {
                            "check_id": "example-check",
                            "title": "Compare particle fractions",
                            "trigger_pattern": "PM10 rise",
                            "procedure": ["Compare co-located measurements."],
                            "interpretations": [
                                {
                                    "explanation": "Regional dust",
                                    "basis": "synthesis",
                                    "evidence_ids": ["ev1"],
                                }
                            ],
                            "required_inputs": [
                                {
                                    "input_id": "pm25",
                                    "name": "Co-located PM2.5",
                                    "status": "missing",
                                }
                            ],
                            "evidence": [evidence],
                            "review_status": "partially_verified",
                        }
                    ],
                }
            ],
        }
    )
    restored = KnowledgeRetrievalResult.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.historical_matches[0].record_id == "example-event"
    check = restored.mechanism_matches[0].diagnostic_checks[0]
    assert check.required_inputs[0].status == "missing"
    assert check.evidence[0].verification_status == "partially_verified"
    assert check.evidence[0].locator == "Table 1"
