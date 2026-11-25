"""Open-Meteo weather client for enriching air quality data."""

from datetime import datetime
from typing import Any

import httpx
import structlog

from src.schemas.api import WeatherReading

logger = structlog.get_logger(__name__)

BASE_URL = "https://api.open-meteo.com/v1"

HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "precipitation",
]


class WeatherClient:
    """Client for Open-Meteo API — free, no auth required."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.client = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def get_hourly(
        self,
        latitude: float,
        longitude: float,
        date_from: datetime,
        date_to: datetime,
        station_id: str = "",
    ) -> list[WeatherReading]:
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(HOURLY_VARS),
            "start_date": date_from.strftime("%Y-%m-%d"),
            "end_date": date_to.strftime("%Y-%m-%d"),
            "timezone": "Asia/Jerusalem",
        }
        resp = self.client.get("/forecast", params=params)
        resp.raise_for_status()
        data = resp.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        readings: list[WeatherReading] = []
        for i, ts in enumerate(times):
            readings.append(
                WeatherReading(
                    station_id=station_id,
                    timestamp=datetime.fromisoformat(ts),
                    temperature_c=hourly["temperature_2m"][i],
                    wind_speed_kmh=hourly["wind_speed_10m"][i],
                    wind_direction=str(hourly["wind_direction_10m"][i]),
                    humidity_pct=hourly["relative_humidity_2m"][i],
                    rain_mm=hourly["precipitation"][i],
                )
            )
        logger.info(
            "fetched_weather",
            station=station_id,
            count=len(readings),
            start=date_from.date().isoformat(),
            end=date_to.date().isoformat(),
        )
        return readings

    def get_current(
        self,
        latitude: float,
        longitude: float,
        station_id: str = "",
    ) -> WeatherReading:
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(HOURLY_VARS),
            "timezone": "Asia/Jerusalem",
        }
        resp = self.client.get("/forecast", params=params)
        resp.raise_for_status()
        data = resp.json()
        c = data["current"]
        return WeatherReading(
            station_id=station_id,
            timestamp=datetime.fromisoformat(c["time"]),
            temperature_c=c["temperature_2m"],
            wind_speed_kmh=c["wind_speed_10m"],
            wind_direction=str(c["wind_direction_10m"]),
            humidity_pct=c["relative_humidity_2m"],
            rain_mm=c["precipitation"],
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "WeatherClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
