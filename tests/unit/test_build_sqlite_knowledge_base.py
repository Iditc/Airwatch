import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from scripts.build_sqlite_knowledge_base import build_database
from src.knowledge_base.retrieval import retrieve_knowledge
from src.schemas.knowledge_retrieval import KnowledgeRetrievalRequest


@pytest.fixture
def exports(tmp_path: Path) -> Path:
    evidence = {
        "id": "ev1",
        "source_id": "src-1",
        "claim": "An observed PM10 change.",
        "locator": "Table 1",
        "evidence_type": "field_observation",
        "verification_status": "verified",
        "verification_note": "Synthetic evidence.",
    }
    records = {
        "cases": {
            "id": "case-1",
            "kind": "historical_event",
            "category": "dust",
            "title": "Example past event",
            "country": "IL",
            "region": "Example region",
            "start_date": "2020-02-01",
            "end_date": "2020-02-01",
            "source_url": "https://example.org/event",
            "pollutants": ["pm10"],
            "summary": "Example dust event.",
            "investigation_hint": "Check regional spread.",
            "expected_signals": [],
            "contradicting_signals": [],
            "required_context": [],
        },
        "mechanism_sources": {
            "source_id": "src-1",
            "title": "Example source",
            "url": "https://example.org/research",
            "doi": "",
            "record_ids": ["mech-1"],
        },
        "mechanisms": {
            "id": "mech-1",
            "title": "Dust transport",
            "topic": "transport",
            "pollutants": ["pm10"],
            "summary": "Dust was observed.",
            "mechanism_explanation": "Winds transport dust.",
            "applicability": {
                "geographic_scope": "regional",
                "countries": ["IL"],
                "regions": [],
                "seasons": [],
                "station_types": [],
                "transfer_limitations": [],
            },
            "review_status": "verified",
            "evidence": [evidence],
            "source_ids": ["src-1"],
            "expected_signals": [],
            "contradicting_signals": [],
            "required_context": [],
            "quantitative_findings": [
                {
                    "pollutant": "pm10",
                    "finding": "Example PM10 concentration",
                    "value": 20,
                    "unit": "µg/m³",
                    "statistic": "mean",
                    "scope": "Example site",
                    "evidence_id": "ev1",
                }
            ],
        },
        "diagnostic_inputs": {
            "id": "in-station-time-series",
            "name": "Matched station time series",
            "schema_availability": "additional_data_required",
            "availability_at_event_time": "unknown",
            "source_ids": ["src-1"],
        },
        "diagnostic_checks": {
            "id": "check-1",
            "title": "Is the pattern regional?",
            "pollutants": ["pm10"],
            "review_status": "verified",
            "trigger_pattern": "PM10 rise",
            "procedure": ["Compare nearby stations."],
            "mechanism_ids": ["mech-1"],
            "input_ids": ["in-station-time-series"],
            "interpretations": [
                {"explanation": "Regional dust", "basis": "synthesis", "evidence_ids": ["ev1"]}
            ],
            "evidence": [evidence],
        },
    }
    directory = tmp_path / "exports"
    directory.mkdir()
    for dataset, record in records.items():
        path = directory / f"air_pollution_{dataset}.json"
        path.write_text(json.dumps([record], ensure_ascii=False), encoding="utf-8")
    return directory


def test_build_preserves_payload_and_links_and_can_be_repeated(exports: Path) -> None:
    destination = exports.parent / "knowledge.sqlite3"
    for _ in range(2):
        counts = build_database(exports, destination)
        assert len(counts) == 5 and set(counts.values()) == {1}
    original = (exports / "air_pollution_mechanism_sources.json").read_bytes()
    with closing(sqlite3.connect(destination)) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (1,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM mechanisms").fetchone() == (1,)
        indexed_doi, payload = db.execute(
            "SELECT doi, payload_json FROM research_sources"
        ).fetchone()
        assert indexed_doi is None
        assert json.loads(payload) == json.loads(original)[0]
        assert db.execute(
            "SELECT sha256, record_count FROM import_manifest WHERE file_name = ?",
            ("air_pollution_mechanism_sources.json",),
        ).fetchone() == (hashlib.sha256(original).hexdigest(), 1)
        assert db.execute(
            """
            SELECT i.id, s.url, e.locator
            FROM mechanism_pollutants p
            JOIN mechanism_diagnostic_checks c ON c.mechanism_id = p.mechanism_id
            JOIN diagnostic_check_inputs l ON l.check_id = c.check_id
            JOIN diagnostic_inputs i ON i.id = l.input_id
            JOIN diagnostic_check_evidence e ON e.check_id = c.check_id
            JOIN research_sources s ON s.source_id = e.source_id
            WHERE p.pollutant = ?
        """,
            ("pm10",),
        ).fetchone() == ("in-station-time-series", "https://example.org/research", "Table 1")


@pytest.mark.parametrize(
    ("dataset", "field", "value", "message"),
    [
        ("diagnostic_checks", "input_ids", ["missing"], "FOREIGN KEY constraint failed"),
        ("mechanisms", "pollutants", ["pm10", "pm10"], "duplicate reference"),
        ("mechanism_sources", "record_ids", [], "record_ids must match"),
    ],
)
def test_invalid_export_preserves_existing_database(
    exports: Path, dataset: str, field: str, value: list[str], message: str
) -> None:
    destination = exports.parent / "knowledge.sqlite3"
    build_database(exports, destination)
    previous = destination.read_bytes()
    path = exports / f"air_pollution_{dataset}.json"
    rows = json.loads(path.read_bytes())
    rows[0][field] = value
    path.write_text(json.dumps(rows), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        build_database(exports, destination)
    assert destination.read_bytes() == previous


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("value", True, "must be a JSON number"),
        ("evidence_id", "missing", "unknown evidence ID"),
    ],
)
def test_invalid_quantitative_finding_is_rejected(
    exports: Path, field: str, value: Any, message: str
) -> None:
    path = exports / "air_pollution_mechanisms.json"
    rows = json.loads(path.read_bytes())
    rows[0]["quantitative_findings"][0][field] = value
    path.write_text(json.dumps(rows), encoding="utf-8")
    destination = exports.parent / "knowledge.sqlite3"
    with pytest.raises(ValueError, match=message):
        build_database(exports, destination)
    assert not destination.exists()


def retrieval_request(pollutant: str = "pm10", **context: Any) -> KnowledgeRetrievalRequest:
    return KnowledgeRetrievalRequest.model_validate(
        {
            "event": {
                "event_id": "example-event",
                "station_id": "station-1",
                "station_name": "Example station",
                "timestamp": "2026-02-01T07:00:00Z",
                "pollutant": pollutant,
                "value": 70,
                "baseline_value": 35,
                "anomaly_score": 0.8,
                "severity": "high",
                "detection_method": "zscore",
                "latitude": 32,
                "longitude": 35,
            },
            "region": "example region",
            **context,
        }
    )


def test_retrieval_ranks_relevant_history_and_resolves_citations(exports: Path) -> None:
    path = exports / "air_pollution_cases.json"
    local = json.loads(path.read_bytes())[0]
    path.write_text(
        json.dumps(
            [
                local,
                {**local, "id": "case-0", "region": "Other region"},
                {**local, "id": "case-other", "pollutants": ["no2"]},
            ]
        ),
        encoding="utf-8",
    )
    destination = exports.parent / "knowledge.sqlite3"
    build_database(exports, destination)

    result = retrieve_knowledge(destination, retrieval_request(), limit=1)
    assert [item.record_id for item in result.historical_matches] == ["case-1"]
    assert "Same region: example region" in result.historical_matches[0].matched_on
    (mechanism,) = result.mechanism_matches
    assert mechanism.evidence[0].source_url == "https://example.org/research"
    (check,) = mechanism.diagnostic_checks
    assert check.evidence[0].locator == "Table 1"
    assert check.required_inputs[0].status == "missing"

    empty = retrieve_knowledge(destination, retrieval_request("o3"))
    assert empty.historical_matches == [] and empty.mechanism_matches == []


def test_retrieval_prefers_matching_direction_and_defaults_to_ten_results(exports: Path) -> None:
    path = exports / "air_pollution_cases.json"
    example = json.loads(path.read_bytes())[0]
    opposite = {**example, "documented_changes": [{"pollutant": "pm10", "direction": "decrease"}]}
    matching = {
        **example,
        "id": "matching-direction",
        "region": "Another region",
        "start_date": "2020-01-01",
        "end_date": "2020-01-01",
        "documented_changes": [
            {"pollutant": "pm10", "direction": "increase"},
            {"pollutant": "no2", "direction": "decrease"},
        ],
    }
    unknown = [{**example, "id": f"unknown-{index}"} for index in range(9)]
    path.write_text(json.dumps([opposite, matching, *unknown]), encoding="utf-8")
    destination = exports.parent / "knowledge.sqlite3"
    build_database(exports, destination)

    result = retrieve_knowledge(destination, retrieval_request())
    assert len(result.historical_matches) == 10
    assert result.historical_matches[0].record_id == "matching-direction"
    assert "Documented pm10 increase" in result.historical_matches[0].matched_on
    expanded = retrieve_knowledge(destination, retrieval_request(), limit=11)
    assert expanded.historical_matches[-1].record_id == opposite["id"]


@pytest.mark.parametrize(
    ("neighbor_period", "neighbor_end", "status", "first_mechanism"),
    [
        (300, 45, "available", "mech-1"),
        (600, 45, "missing", "winter-mechanism"),
        (300, 20, "available", "winter-mechanism"),
    ],
)
def test_retrieval_checks_neighbor_series_comparability(
    exports: Path, neighbor_period: int, neighbor_end: int, status: str, first_mechanism: str
) -> None:
    mechanism_path = exports / "air_pollution_mechanisms.json"
    dust = json.loads(mechanism_path.read_bytes())[0]
    winter = {
        **dust,
        "id": "winter-mechanism",
        "applicability": {**dust["applicability"], "seasons": ["winter"]},
    }
    mechanism_path.write_text(json.dumps([dust, winter]), encoding="utf-8")
    source_path = exports / "air_pollution_mechanism_sources.json"
    sources = json.loads(source_path.read_bytes())
    sources[0]["record_ids"].append("winter-mechanism")
    source_path.write_text(json.dumps(sources), encoding="utf-8")
    check_path = exports / "air_pollution_diagnostic_checks.json"
    checks = json.loads(check_path.read_bytes())
    checks[0]["id"] = "dc-dust-vs-local-pm"
    check_path.write_text(json.dumps(checks), encoding="utf-8")

    destination = exports.parent / "knowledge.sqlite3"
    build_database(exports, destination)
    primary = {
        "station_id": "station-1",
        "pollutant": "pm10",
        "unit": "µg/m³",
        "averaging_period_seconds": 300,
        "measurements": [
            {"timestamp": "2026-02-01T06:50:00Z", "value": 32},
            {"timestamp": "2026-02-01T06:55:00Z", "value": 61},
        ],
    }
    neighbor = {
        **primary,
        "station_id": "station-2",
        "averaging_period_seconds": neighbor_period,
        "measurements": [
            {"timestamp": "2026-02-01T06:50:00Z", "value": 32},
            {"timestamp": "2026-02-01T06:55:00Z", "value": neighbor_end},
        ],
    }
    request = retrieval_request(recent_measurement_series=[primary, neighbor])
    result = retrieve_knowledge(destination, request)
    assert result.mechanism_matches[0].record_id == first_mechanism
    mechanism = next(item for item in result.mechanism_matches if item.record_id == "mech-1")
    check = mechanism.diagnostic_checks[0]
    assert check.check_id == "dc-dust-vs-local-pm"
    assert check.required_inputs[0].status == status


def test_retrieval_opens_database_read_only(tmp_path: Path) -> None:
    nonexistent = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
        retrieve_knowledge(nonexistent, retrieval_request())
    assert not nonexistent.exists()
