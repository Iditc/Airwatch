"""AirWatch REST API — air quality data and anomaly detection endpoints."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from src.data.database import get_connection
from src.data.loader import ISRAEL_THRESHOLDS, WHO_THRESHOLDS
from src.schemas.anomaly import AnomalyEvent
from src.schemas.api import (
    AQIReading,
    ExceedanceIsrael,
    ExceedanceWHO,
    HealthStatus,
    StationInfo,
)

EVENTS_DIR = Path(__file__).parent.parent.parent / "data" / "events"


app = FastAPI(
    title="AirWatch API",
    description="Real-time air quality monitoring and anomaly detection for Israel",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(DISTINCT station_id) FROM measurements").fetchone()[0]
    conn.close()
    return HealthStatus(
        status="ok",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
        stations_monitored=count,
    )


@app.get("/stations", response_model=list[StationInfo])
async def get_stations() -> list[StationInfo]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT station_id, short_name, city, latitude, longitude, pollutants "
        "FROM stations WHERE station_id IN (SELECT DISTINCT station_id FROM measurements)"
    ).fetchall()
    conn.close()
    return [
        StationInfo(
            station_id=r["station_id"],
            name=r["short_name"] or r["station_id"],
            city=r["city"] or "Unknown",
            latitude=r["latitude"],
            longitude=r["longitude"],
            pollutants=r["pollutants"].split(",") if r["pollutants"] else [],
        )
        for r in rows
    ]


@app.get("/readings", response_model=list[AQIReading])
async def get_readings(
    station_id: str = Query(..., description="Station ID"),
    pollutant: str | None = Query(None, description="Filter by pollutant"),
    limit: int = Query(200, ge=1, le=5000),
) -> list[AQIReading]:
    conn = get_connection()
    sql = (
        "SELECT station_id, timestamp, pollutant, value, unit "
        "FROM measurements WHERE station_id = ?"
    )
    params: list = [station_id]
    if pollutant:
        sql += " AND pollutant = ?"
        params.append(pollutant)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [
        AQIReading(
            station_id=r["station_id"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
            pollutant=r["pollutant"],
            value=r["value"],
            unit=r["unit"],
        )
        for r in rows
    ]


@app.get("/exceedances/israel", response_model=list[ExceedanceIsrael])
async def get_exceedances_israel(
    station_id: str | None = Query(None, description="Filter by station"),
    pollutant: str | None = Query(None, description="Filter by pollutant"),
    severity: str | None = Query(None, description="Filter by severity (low/medium/high)"),
    limit: int = Query(200, ge=1, le=5000),
) -> list[ExceedanceIsrael]:
    conn = get_connection()
    sql = "SELECT * FROM exceedances_israel WHERE 1=1"
    params: list = []
    if station_id:
        sql += " AND station_id = ?"
        params.append(station_id)
    if pollutant:
        sql += " AND pollutant = ?"
        params.append(pollutant)
    if severity:
        sql += " AND severity = ?"
        params.append(severity)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [
        ExceedanceIsrael(
            id=r["id"],
            measurement_id=r["measurement_id"],
            station_id=r["station_id"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
            pollutant=r["pollutant"],
            value=r["value"],
            threshold=r["threshold"],
            ratio=r["ratio"],
            severity=r["severity"],
        )
        for r in rows
    ]


@app.get("/exceedances/who", response_model=list[ExceedanceWHO])
async def get_exceedances_who(
    station_id: str | None = Query(None, description="Filter by station"),
    pollutant: str | None = Query(None, description="Filter by pollutant"),
    severity: str | None = Query(None, description="Filter by severity (low/medium/high)"),
    limit: int = Query(200, ge=1, le=5000),
) -> list[ExceedanceWHO]:
    conn = get_connection()
    sql = "SELECT * FROM exceedances_who WHERE 1=1"
    params: list = []
    if station_id:
        sql += " AND station_id = ?"
        params.append(station_id)
    if pollutant:
        sql += " AND pollutant = ?"
        params.append(pollutant)
    if severity:
        sql += " AND severity = ?"
        params.append(severity)
    sql += " ORDER BY window_end DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [
        ExceedanceWHO(
            id=r["id"],
            station_id=r["station_id"],
            window_end=datetime.fromisoformat(r["window_end"]),
            pollutant=r["pollutant"],
            window_hours=r["window_hours"],
            avg_value=r["avg_value"],
            threshold=r["threshold"],
            ratio=r["ratio"],
            severity=r["severity"],
        )
        for r in rows
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
