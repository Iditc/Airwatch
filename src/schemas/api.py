from datetime import datetime

from pydantic import BaseModel, Field


class StationInfo(BaseModel):
    """Metadata for a monitoring station."""

    station_id: str
    name: str
    city: str
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


class HealthStatus(BaseModel):
    """Health check response for the API."""

    status: str = "ok"
    version: str
    timestamp: datetime
    stations_monitored: int
    last_detection_run: datetime | None = None
