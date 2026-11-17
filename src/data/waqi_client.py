"""WAQI (World Air Quality Index) client for real-time AQI and PM2.5 data."""

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from src.schemas.api import AQIReading, StationInfo

logger = structlog.get_logger(__name__)

BASE_URL = "https://api.waqi.info"


class WAQIClient:
    """Client for the WAQI/AQICN API — real-time AQI for Israeli stations."""

    def __init__(self, api_token: str, timeout: float = 30.0) -> None:
        self.api_token = api_token
        self.client = httpx.Client(timeout=timeout)

    def _get(self, url: str) -> Any:
        resp = self.client.get(url)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if data.get("status") != "ok":
            msg = data.get("data", "Unknown error")
            raise ValueError(f"WAQI API error: {msg}")
        return data["data"]

    def search_stations(self, keyword: str = "israel") -> list[StationInfo]:
        url = f"{BASE_URL}/search/?keyword={keyword}&token={self.api_token}"
        results = self._get(url)
        stations: list[StationInfo] = []
        for item in results:
            station = item.get("station", {})
            geo = station.get("geo", [0, 0])
            uid = str(item.get("uid", ""))
            stations.append(
                StationInfo(
                    station_id=uid,
                    name=station.get("name", uid),
                    city="Israel",
                    latitude=float(geo[0]) if geo else 0.0,
                    longitude=float(geo[1]) if geo else 0.0,
                    pollutants=["pm25", "pm10", "no2", "o3", "so2", "co"],
                )
            )
        logger.info("waqi_search", keyword=keyword, stations=len(stations))
        return stations

    def get_station_feed(self, station_id: str) -> dict[str, Any]:
        url = f"{BASE_URL}/feed/@{station_id}/?token={self.api_token}"
        result = self._get(url)
        feed: dict[str, Any] = result
        return feed

    def get_readings(self, station_id: str) -> list[AQIReading]:
        feed = self.get_station_feed(station_id)

        iaqi = feed.get("iaqi", {})
        time_info = feed.get("time", {})
        ts_str = time_info.get("iso", "")
        try:
            ts = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            ts = datetime.now(timezone.utc)

        station_name = feed.get("city", {}).get("name", station_id)
        readings: list[AQIReading] = []

        pollutant_map = {
            "pm25": "pm25",
            "pm10": "pm10",
            "no2": "no2",
            "o3": "o3",
            "so2": "so2",
            "co": "co",
        }

        for key, pollutant_name in pollutant_map.items():
            if key in iaqi:
                val = iaqi[key].get("v")
                if val is not None:
                    readings.append(
                        AQIReading(
                            station_id=station_id,
                            timestamp=ts,
                            pollutant=pollutant_name,
                            value=float(val),
                            unit="AQI",
                        )
                    )

        logger.info(
            "waqi_readings",
            station=station_name,
            pollutants=len(readings),
        )
        return readings

    def get_all_israel_readings(self) -> list[AQIReading]:
        stations = self.search_stations("israel")
        all_readings: list[AQIReading] = []
        for station in stations:
            try:
                readings = self.get_readings(station.station_id)
                all_readings.extend(readings)
            except Exception:
                logger.warning("waqi_station_failed", station=station.station_id)
        logger.info("waqi_total", readings=len(all_readings), stations=len(stations))
        return all_readings

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "WAQIClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
