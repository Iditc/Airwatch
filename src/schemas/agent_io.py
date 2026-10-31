from datetime import datetime

from pydantic import BaseModel, Field


class InvestigationRequest(BaseModel):
    """Input to the Investigation Agent — triggered by an anomaly event."""

    event_id: str
    station_id: str
    station_name: str
    timestamp: datetime
    pollutant: str
    value: float
    anomaly_score: float
    latitude: float
    longitude: float


class WeatherContext(BaseModel):
    """Weather conditions at the time of the anomaly."""

    temperature_c: float | None = None
    wind_speed_kmh: float | None = None
    wind_direction: str | None = None
    humidity_pct: float | None = None
    conditions: str | None = None


class NeighborStatus(BaseModel):
    """Status of a neighboring station during the anomaly."""

    station_id: str
    station_name: str
    distance_km: float
    value: float
    is_anomalous: bool


class InvestigationReport(BaseModel):
    """Output from the Investigation Agent."""

    event_id: str
    weather: WeatherContext | None = None
    neighbors: list[NeighborStatus] = Field(default_factory=list)
    is_localized: bool = Field(description="True if only this station is affected")
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(description="One-paragraph investigation summary")


class RootCauseAnalysis(BaseModel):
    """Output from the Root Cause Agent."""

    event_id: str
    probable_cause: str = Field(description="Most likely cause of the anomaly")
    known_source_match: str | None = Field(
        default=None, description="Matched known pollution source from knowledge base"
    )
    historical_match: str | None = Field(
        default=None, description="Similar historical event if found"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="Step-by-step reasoning")


class AlertPayload(BaseModel):
    """Output from the Alert Agent — sent to Slack/email."""

    event_id: str
    station_name: str
    severity: str
    title: str = Field(description="Short alert title")
    body: str = Field(description="Human-readable alert explanation")
    recommended_action: str | None = None
    timestamp: datetime
    dashboard_url: str | None = None
