from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from src.schemas.agent_io import AlertPayload, InvestigationReport, WeatherContext
from src.schemas.anomaly import AnomalyEvent, DetectionMethod, Pollutant, Severity
from src.schemas.api import AQIReading, HealthStatus, StationInfo


def _make_anomaly_event(**overrides: Any) -> AnomalyEvent:
    defaults: dict[str, Any] = {
        "event_id": "evt_001",
        "station_id": "haifa_01",
        "station_name": "Haifa Nesher",
        "timestamp": datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
        "pollutant": Pollutant.PM25,
        "value": 85.0,
        "baseline_value": 25.0,
        "anomaly_score": 0.92,
        "severity": Severity.HIGH,
        "detection_method": DetectionMethod.ENSEMBLE,
        "latitude": 32.79,
        "longitude": 35.04,
    }
    defaults.update(overrides)
    return AnomalyEvent(**defaults)


class TestAnomalyEvent:
    def test_valid_event(self) -> None:
        event = _make_anomaly_event()
        assert event.station_id == "haifa_01"
        assert event.anomaly_score == 0.92

    def test_score_must_be_between_0_and_1(self) -> None:
        with pytest.raises(ValidationError):
            _make_anomaly_event(anomaly_score=1.5)

    def test_score_zero_is_valid(self) -> None:
        event = _make_anomaly_event(anomaly_score=0.0)
        assert event.anomaly_score == 0.0

    def test_invalid_latitude(self) -> None:
        with pytest.raises(ValidationError):
            _make_anomaly_event(latitude=100.0)

    def test_invalid_pollutant(self) -> None:
        with pytest.raises(ValidationError):
            _make_anomaly_event(pollutant="invalid_gas")


class TestInvestigationReport:
    def test_valid_report(self) -> None:
        report = InvestigationReport(
            event_id="evt_001",
            weather=WeatherContext(temperature_c=28.5, wind_speed_kmh=15.0),
            is_localized=True,
            confidence=0.85,
            summary="Anomaly is localized to Haifa Nesher station.",
        )
        assert report.is_localized is True
        assert report.weather is not None
        assert report.weather.temperature_c == 28.5

    def test_report_without_weather(self) -> None:
        report = InvestigationReport(
            event_id="evt_001",
            is_localized=False,
            confidence=0.5,
            summary="Insufficient data for full investigation.",
        )
        assert report.weather is None
        assert report.neighbors == []


class TestAlertPayload:
    def test_valid_alert(self) -> None:
        alert = AlertPayload(
            event_id="evt_001",
            station_name="Haifa Nesher",
            severity="high",
            title="High PM2.5 detected in Haifa",
            body="PM2.5 levels reached 85 µg/m³, 3.4x above normal.",
            timestamp=datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
        )
        assert "Haifa" in alert.title


class TestAPISchemas:
    def test_station_info(self) -> None:
        station = StationInfo(
            station_id="haifa_01",
            name="Haifa Nesher",
            city="Haifa",
            latitude=32.79,
            longitude=35.04,
            pollutants=["pm25", "pm10", "no2"],
        )
        assert len(station.pollutants) == 3

    def test_aqi_reading_negative_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AQIReading(
                station_id="haifa_01",
                timestamp=datetime.now(tz=timezone.utc),
                pollutant="pm25",
                value=-5.0,
            )

    def test_health_status_defaults(self) -> None:
        health = HealthStatus(
            version="0.1.0",
            timestamp=datetime.now(tz=timezone.utc),
            stations_monitored=12,
        )
        assert health.status == "ok"
        assert health.last_detection_run is None
