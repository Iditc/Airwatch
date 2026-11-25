"""Retrieval quality checks against the local AirWatch knowledge base."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.knowledge_base.retrieval import retrieve_knowledge
from src.schemas.knowledge_retrieval import KnowledgeRetrievalRequest

DATABASE = Path(__file__).resolve().parents[2] / "data/knowledge_base/knowledge_base.sqlite3"


@dataclass(frozen=True)
class Scenario:
    name: str
    request: KnowledgeRetrievalRequest
    expected_check: str
    expected_inputs: dict[str, str]
    max_rank: int = 10
    expected_review_status: str = "verified"


def request_for(
    name: str,
    region: str,
    pollutant: str,
    unit: str,
    value: float,
    baseline: float,
    timestamp: str,
    coordinates: tuple[float, float],
    **context: Any,
) -> KnowledgeRetrievalRequest:
    return KnowledgeRetrievalRequest.model_validate(
        {
            "event": {
                "event_id": name,
                "station_id": "synthetic-1",
                "station_name": f"Example station in {region}",
                "timestamp": timestamp,
                "pollutant": pollutant,
                "value": value,
                "baseline_value": baseline,
                "anomaly_score": 0.85,
                "severity": "high",
                "detection_method": "zscore",
                "latitude": coordinates[0],
                "longitude": coordinates[1],
            },
            "region": region,
            "measurement_unit": unit,
            **context,
        }
    )


PM10_SERIES = [
    {
        "station_id": station,
        "pollutant": "pm10",
        "unit": "µg/m³",
        "averaging_period_seconds": 300,
        "measurements": [
            {"timestamp": f"2026-11-18T08:{minute}:00+02:00", "value": value}
            for minute, value in zip((45, 50, 55), values, strict=True)
        ],
    }
    for station, values in (("synthetic-1", (38, 62, 95)), ("synthetic-2", (34, 49, 72)))
]

SCENARIOS = [
    Scenario(
        "regional-pm10-rise",
        request_for(
            "regional-pm10-rise",
            "Tel Aviv",
            "pm10",
            "µg/m³",
            120,
            40,
            "2026-11-18T09:00:00+02:00",
            (32.0853, 34.7818),
            weather={"wind_speed_kmh": 12, "wind_direction": "W"},
            recent_measurement_series=PM10_SERIES,
        ),
        "dc-dust-vs-local-pm",
        {"in-station-time-series": "available"},
        max_rank=1,
    ),
    Scenario(
        "haifa-bay-so2-plume",
        request_for(
            "haifa-bay-so2-plume",
            "Haifa Bay",
            "so2",
            "ppb",
            38,
            4,
            "2026-04-20T07:00:00+03:00",
            (32.81, 35.03),
            weather={"wind_speed_kmh": 14, "wind_direction": "NW"},
        ),
        "dc-so2-source-attribution",
        {"in-stack-cems-data": "missing", "in-ship-activity": "unknown"},
        expected_review_status="partially_verified",
    ),
    Scenario(
        "single-station-co-change",
        request_for(
            "single-station-co-change",
            "Israel",
            "co",
            "ppm",
            0.44,
            0.26,
            "2026-02-11T06:00:00+02:00",
            (32.08, 34.79),
            weather={"humidity_pct": 93},
        ),
        "dc-co-small-anomaly-instrument-envelope",
        {"in-calibration-logs": "missing", "in-neighbor-station-readings": "missing"},
    ),
    Scenario(
        "spring-o3-rise",
        request_for(
            "spring-o3-rise",
            "Haifa",
            "o3",
            "ppb",
            70,
            43,
            "2026-04-18T13:00:00+03:00",
            (32.79, 34.99),
            weather={"wind_speed_kmh": 11, "wind_direction": "W"},
        ),
        "dc-activity-change-no2-o3",
        {"in-co-located-pollutants": "unknown", "in-traffic-activity": "unknown"},
    ),
    Scenario(
        "humid-pm25-rise",
        request_for(
            "humid-pm25-rise",
            "Israel",
            "pm25",
            "µg/m³",
            53,
            19,
            "2026-01-12T06:30:00+02:00",
            (31.25, 34.79),
            weather={"humidity_pct": 97, "temperature_c": 11},
        ),
        "dc-pm-humidity-volatility-by-instrument",
        {"in-instrument-type": "missing", "in-station-time-series": "missing"},
    ),
]


@pytest.fixture(scope="module")
def local_database() -> Path:
    if not DATABASE.is_file():
        pytest.skip("Build the local SQLite knowledge base to run retrieval quality checks.")
    return DATABASE


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[scenario.name for scenario in SCENARIOS])
def test_retrieval_quality(local_database: Path, scenario: Scenario) -> None:
    result = retrieve_knowledge(local_database, scenario.request)
    pollutant = scenario.request.event.pollutant
    assert result.historical_matches
    assert len(result.historical_matches) <= 10
    assert all(pollutant in match.pollutants for match in result.historical_matches)
    assert len(result.mechanism_matches) <= 10
    assert all(pollutant in match.pollutants for match in result.mechanism_matches)

    ranked_checks = [
        (rank, check)
        for rank, mechanism in enumerate(result.mechanism_matches, start=1)
        for check in mechanism.diagnostic_checks
    ]
    candidates = [
        (rank, check) for rank, check in ranked_checks if check.check_id == scenario.expected_check
    ]
    assert candidates, (scenario.expected_check, [check.check_id for _, check in ranked_checks])
    rank, check = candidates[0]
    assert rank <= scenario.max_rank
    assert check.review_status == scenario.expected_review_status
    assert all(
        item.locator and item.source_url.startswith(("https://", "http://"))
        for item in check.evidence
    )
    statuses = {item.input_id: item.status for item in check.required_inputs}
    assert {key: statuses.get(key) for key in scenario.expected_inputs} == scenario.expected_inputs
