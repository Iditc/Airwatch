"""AirWatch REST API — air quality data and anomaly detection endpoints."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from src.data.loader import ISRAEL_THRESHOLDS, WHO_THRESHOLDS, short_name
from src.schemas.anomaly import AnomalyEvent
from src.schemas.api import AQIReading, HealthStatus, StationInfo

DATA_DIR = Path(__file__).parent.parent.parent / "data"
EVENTS_DIR = DATA_DIR / "events"

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    stations_df = pd.read_parquet(DATA_DIR / "raw" / "stations.parquet")
    stations_df["station_id"] = stations_df["station_id"].astype(str)
    _state["stations"] = stations_df

    measurements = pd.read_parquet(DATA_DIR / "processed" / "measurements_clean.parquet")
    measurements["timestamp"] = pd.to_datetime(measurements["timestamp"], utc=True)
    _state["measurements"] = measurements
    _state["active_ids"] = measurements["station_id"].unique().tolist()

    yield
    _state.clear()


app = FastAPI(
    title="AirWatch API",
    description="Real-time air quality monitoring and anomaly detection for Israel",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    return HealthStatus(
        status="ok",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
        stations_monitored=len(_state["active_ids"]),
    )


@app.get("/stations", response_model=list[StationInfo])
async def get_stations() -> list[StationInfo]:
    df = _state["stations"]
    active = df[df["station_id"].isin(_state["active_ids"])]
    return [
        StationInfo(
            station_id=str(row["station_id"]),
            name=short_name(row["name"]),
            city=row.get("city", "Unknown") or "Unknown",
            latitude=row["latitude"],
            longitude=row["longitude"],
            pollutants=row["pollutants"].split(",")
            if isinstance(row["pollutants"], str)
            else row["pollutants"],
        )
        for _, row in active.iterrows()
    ]


@app.get("/readings", response_model=list[AQIReading])
async def get_readings(
    station_id: str = Query(..., description="Station ID"),
    pollutant: str | None = Query(None, description="Filter by pollutant"),
    limit: int = Query(200, ge=1, le=5000),
) -> list[AQIReading]:
    df = _state["measurements"]
    mask = df["station_id"] == station_id
    if pollutant:
        mask &= df["pollutant"] == pollutant
    subset = df[mask].sort_values("timestamp", ascending=False).head(limit)

    return [
        AQIReading(
            station_id=row["station_id"],
            timestamp=row["timestamp"],
            pollutant=row["pollutant"],
            value=row["value"],
            unit=row["unit"],
        )
        for _, row in subset.iterrows()
    ]


@app.get("/anomalies", response_model=list[AnomalyEvent])
async def get_anomalies() -> list[AnomalyEvent]:
    events: list[AnomalyEvent] = []
    if EVENTS_DIR.exists():
        for f in sorted(EVENTS_DIR.glob("*.json"), reverse=True):
            data = json.loads(f.read_text(encoding="utf-8"))
            for item in data:
                events.append(AnomalyEvent(**item))
    return events


@app.get("/thresholds")
async def get_thresholds() -> dict[str, Any]:
    return {"israel": ISRAEL_THRESHOLDS, "who": WHO_THRESHOLDS}
