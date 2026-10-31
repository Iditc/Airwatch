from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Pollutant(str, Enum):
    PM25 = "pm25"
    PM10 = "pm10"
    NO2 = "no2"
    SO2 = "so2"
    CO = "co"
    O3 = "o3"


class DetectionMethod(str, Enum):
    ISOLATION_FOREST = "isolation_forest"
    AUTOENCODER = "autoencoder"
    ZSCORE = "zscore"
    GNN = "gnn"
    ENSEMBLE = "ensemble"


class AnomalyEvent(BaseModel):
    """A detected anomaly at a monitoring station."""

    event_id: str = Field(description="Unique anomaly event identifier")
    station_id: str = Field(description="Monitoring station identifier")
    station_name: str = Field(description="Human-readable station name")
    timestamp: datetime = Field(description="When the anomaly was detected")
    pollutant: Pollutant
    value: float = Field(description="Measured pollutant value")
    baseline_value: float = Field(description="Expected normal value")
    anomaly_score: float = Field(ge=0.0, le=1.0, description="Score from 0 (normal) to 1 (extreme)")
    severity: Severity
    detection_method: DetectionMethod
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class AnomalyBatch(BaseModel):
    """A batch of anomaly events from a detection run."""

    run_id: str
    timestamp: datetime
    events: list[AnomalyEvent]
    stations_checked: int
    total_anomalies: int
