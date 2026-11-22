from datetime import datetime

from pydantic import BaseModel, Field


class StationInfo(BaseModel):
    """Metadata for a monitoring station."""

    station_id: str
    name: str
    city: str = "Unknown"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    pollutants: list[str] = Field(description="Pollutants measured at this station")


class AQIReading(BaseModel):
    """A single air quality measurement from a station."""

    station_id: str
    timestamp: datetime
    pollutant: str
    value: float = Field(ge=0)
    unit: str = Field(default="µg/m³")


class WeatherReading(BaseModel):
    """A weather measurement from IMS Envista."""

    station_id: str
    timestamp: datetime
    temperature_c: float | None = None
    wind_speed_kmh: float | None = None
    wind_direction: str | None = None
    humidity_pct: float | None = None
    rain_mm: float | None = None


class ExceedanceIsrael(BaseModel):
    """An Israeli Clean Air standard exceedance."""

    id: int
    measurement_id: int
    station_id: str
    timestamp: datetime
    pollutant: str
    value: float
    threshold: float
    ratio: float
    severity: str


class ExceedanceWHO(BaseModel):
    """A WHO 2021 guideline exceedance (rolling average)."""

    id: int
    station_id: str
    window_end: datetime
    pollutant: str
    window_hours: int
    avg_value: float
    threshold: float
    ratio: float
    severity: str


class AgentResult(BaseModel):
    """An agent investigation result linked to an exceedance."""

    id: int
    exceedance_type: str
    exceedance_id: int
    agent_type: str
    created_at: datetime
    result_json: str


class StationHealth(BaseModel):
    """Health status for a monitoring station."""

    station_id: str
    name: str
    last_reading: datetime | None = None
    hours_since_last: float | None = None
    total_readings: int = 0
    pollutants_active: list[str] = Field(default_factory=list)
    coverage_pct: float = Field(default=0.0, description="Data coverage over the last 7 days")


class HealthStatus(BaseModel):
    """Health check response for the API."""

    status: str = "ok"
    version: str
    timestamp: datetime
    stations_monitored: int
    last_detection_run: datetime | None = None
