import json
from typing import Any

import pytest
from pydantic import ValidationError

from scripts.build_historical_knowledge_base import KnowledgeRecord


@pytest.fixture
def record() -> dict[str, Any]:
    return {
        "id": "synthetic-monitoring-event",
        "kind": "historical_event",
        "category": "traffic",
        "title": "Synthetic monitoring event",
        "country": "IL",
        "region": "Example region",
        "pollutants": ["co"],
        "start_date": "2020-03-01",
        "end_date": "2020-03-02",
        "summary": "Example concentration decrease.",
        "investigation_hint": "Compare with upwind readings.",
        "expected_signals": ["A change at the downwind station"],
        "contradicting_signals": ["An earlier change at the upwind station"],
        "required_context": ["Wind direction"],
        "evidence_type": "ground_monitoring",
        "source_url": "https://example.com/monitoring",
        "documented_changes": [
            {
                "pollutant": "co",
                "direction": "decrease",
                "comparison": "Previous day",
                "measurement": {
                    "value": -10,
                    "unit": "%",
                    "quantity": "relative_change",
                    "aggregation_period": "Daily",
                    "statistic": "mean",
                },
            }
        ],
    }


def test_accepts_international_country(record: dict[str, Any]) -> None:
    record["country"] = "US"
    validated = KnowledgeRecord.model_validate_json(json.dumps(record), strict=True)
    assert json.loads(validated.model_dump_json())["country"] == "US"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("id", "Invalid ID", "id"),
        ("kind", "report", "kind"),
        ("category", "Invalid category", "category"),
        ("title", " ", "title"),
        ("country", "Israel", "country"),
        ("country", "il", "country"),
        ("country", None, "country"),
        ("region", " ", "region"),
        ("pollutants", [], "pollutants"),
        ("pollutants", ["co", "co"], "tags must be unique"),
        ("pollutants", ["no2"], "pollutant tagged in the record"),
        ("start_date", "2020-02-30", "start_date"),
        ("end_date", "2020-01-01", "Start date must be on or before end date"),
        ("summary", "", "summary"),
        ("investigation_hint", "", "investigation_hint"),
        ("expected_signals", [], "expected_signals"),
        ("contradicting_signals", [""], "contradicting_signals"),
        ("required_context", [], "required_context"),
        ("evidence_type", "rumor", "evidence_type"),
        ("source_url", "file:///report", "source_url"),
        ("source_location", {"latitude": 91}, "latitude"),
        ("observed_areas", [{"area": "", "observation_type": "unknown"}], "observed_areas"),
        ("temporal_pattern", "", "temporal_pattern"),
        ("documented_changes", [], "documented_changes"),
        ("weather_context", {}, "at least one observation"),
        ("weather_context", {"wind_direciton": "E"}, "wind_direciton"),
        ("weather_context", {"wind_speed_kmh": -5}, "wind_speed_kmh"),
        ("weather_context", {"humidity_pct": 101}, "humidity_pct"),
        ("weather_context", {"temperature_c": -274}, "temperature_c"),
        ("weather_context", {"wind_direction": "sideways"}, "wind_direction"),
        ("weather_context", {"conditions": ""}, "conditions"),
        ("neighbors", [], "neighbors"),
        ("extra_key", "unexpected", "extra_key"),
    ],
)
def test_rejects_invalid_record_fields(
    record: dict[str, Any], field: str, value: object, error: str
) -> None:
    record[field] = value
    with pytest.raises(ValidationError, match=error):
        KnowledgeRecord.model_validate_json(json.dumps(record), strict=True)


@pytest.mark.parametrize(
    ("target", "field", "value", "error"),
    [
        ("change", "direction", "increase", "agree with direction"),
        ("change", "station_name", " ", "station_name"),
        ("change", "area", " ", "area"),
        ("change", "comparison", None, "comparison baseline"),
        ("measurement", "value", 0, "agree with direction"),
        ("measurement", "unit", "ppb", "percent units"),
        ("measurement", "quantity", "mass", "quantity"),
        ("measurement", "operator", "greater_than", "exact values"),
        ("measurement", "averaging_minutes", 0, "averaging_minutes"),
        ("measurement", "aggregation_period", None, "averaging interval or aggregation period"),
        ("measurement", "statistic", "", "statistic"),
    ],
)
def test_rejects_invalid_documented_changes(
    record: dict[str, Any], target: str, field: str, value: object, error: str
) -> None:
    change = record["documented_changes"][0]
    fields = change if target == "change" else change["measurement"]
    fields[field] = value
    with pytest.raises(ValidationError, match=error):
        KnowledgeRecord.model_validate_json(json.dumps(record), strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("station_id", ""),
        ("station_name", " "),
        ("distance_km", -1),
        ("value", -1),
        ("is_anomalous", "true"),
        ("extra_key", "unexpected"),
    ],
)
def test_rejects_invalid_neighbor_fields(record: dict[str, Any], field: str, value: object) -> None:
    neighbor = {
        "station_id": "station-1",
        "station_name": "Nearby station",
        "distance_km": 2,
        "value": 40,
        "is_anomalous": False,
        field: value,
    }
    record["neighbors"] = [neighbor]
    with pytest.raises(ValidationError, match=field):
        KnowledgeRecord.model_validate_json(json.dumps(record), strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", 91),
        ("longitude", -181),
        ("description", ""),
        ("source_url", "file:///location"),
    ],
)
def test_rejects_invalid_source_location_fields(
    record: dict[str, Any], field: str, value: object
) -> None:
    record.pop("start_date")
    record.pop("end_date")
    record["kind"] = "pollution_source"
    record["source_location"] = {
        "latitude": 32,
        "longitude": 35,
        "description": "Synthetic source",
        "source_url": "https://example.com/source",
        field: value,
    }
    with pytest.raises(ValidationError, match=rf"source_location\.{field}"):
        KnowledgeRecord.model_validate_json(json.dumps(record), strict=True)
