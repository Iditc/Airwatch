import time
from datetime import datetime
from typing import Any

import httpx
import structlog

from src.schemas.api import AQIReading, StationInfo

logger = structlog.get_logger(__name__)

BASE_URL = "https://api.openaq.org/v3"
ISRAEL_COUNTRY_CODE = "IL"


class OpenAQClient:
    """Client for the OpenAQ v3 API with retry logic and rate limiting."""

    def __init__(self, api_key: str, timeout: float = 30.0, max_retries: int = 3) -> None:
        self.api_key = api_key
        self.max_retries = max_retries
        self.client = httpx.Client(
            base_url=BASE_URL,
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request with retry logic."""
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.get(endpoint, params=params)
                response.raise_for_status()
                result: dict[str, Any] = response.json()
                return result
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (408, 429, 500, 502, 503, 504):
                    logger.warning(
                        "retryable_error",
                        status=e.response.status_code,
                        attempt=attempt,
                        endpoint=endpoint,
                    )
                    if attempt == self.max_retries:
                        raise
                    time.sleep(2**attempt)
                    continue
                logger.error("http_error", status=e.response.status_code, endpoint=endpoint)
                raise
            except httpx.RequestError as e:
                logger.warning("request_failed", attempt=attempt, error=str(e))
                if attempt == self.max_retries:
                    raise
                time.sleep(2**attempt)
        raise RuntimeError(f"Failed after {self.max_retries} retries: {endpoint}")

    def get_israel_country_id(self) -> int:
        """Find Israel's numeric country ID in OpenAQ."""
        data = self._get("/countries", params={"limit": 200})
        for country in data["results"]:
            if country["code"] == ISRAEL_COUNTRY_CODE:
                country_id: int = country["id"]
                logger.info("found_country", name=country["name"], id=country_id)
                return country_id
        raise ValueError(f"Country {ISRAEL_COUNTRY_CODE} not found in OpenAQ")

    def get_stations(self, country_id: int | None = None) -> list[StationInfo]:
        """Fetch all monitoring stations, optionally filtered by country."""
        params: dict[str, Any] = {"limit": 100}
        if country_id is not None:
            params["countries_id"] = country_id

        data = self._get("/locations", params=params)
        stations = []
        for loc in data["results"]:
            pollutants = [s["parameter"]["name"] for s in loc.get("sensors", [])]
            stations.append(
                StationInfo(
                    station_id=str(loc["id"]),
                    name=loc["name"],
                    city=loc.get("locality") or "Unknown",
                    latitude=loc["coordinates"]["latitude"],
                    longitude=loc["coordinates"]["longitude"],
                    pollutants=pollutants,
                )
            )
        logger.info("fetched_stations", count=len(stations))
        return stations

    def get_sensor_ids(self, location_id: int) -> dict[str, int]:
        """Get sensor IDs for a location, mapped by pollutant name."""
        data = self._get(f"/locations/{location_id}")
        sensors: dict[str, int] = {}
        for s in data["results"][0].get("sensors", []):
            sensors[s["parameter"]["name"]] = s["id"]
        logger.info("fetched_sensors", station=location_id, sensors=list(sensors.keys()))
        return sensors

    def get_measurements(
        self,
        sensor_id: int,
        station_id: str = "",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 1000,
    ) -> list[AQIReading]:
        """Fetch measurements for a specific sensor with pagination."""
        page_size = min(limit, 1000)
        collected = 0
        page = 1
        readings: list[AQIReading] = []

        while collected < limit:
            params: dict[str, Any] = {"limit": page_size, "page": page}
            if date_from:
                params["date_from"] = date_from.isoformat()
            if date_to:
                params["date_to"] = date_to.isoformat()

            data = self._get(f"/sensors/{sensor_id}/measurements", params=params)
            results = data["results"]
            if not results:
                break

            for m in results:
                if m["value"] is None:
                    continue
                readings.append(
                    AQIReading(
                        station_id=station_id,
                        timestamp=m["period"]["datetimeTo"]["utc"],
                        pollutant=m["parameter"]["name"],
                        value=m["value"],
                        unit=m["parameter"]["units"],
                    )
                )

            collected += len(results)
            if len(results) < page_size:
                break
            page += 1
            time.sleep(0.3)

        logger.info("fetched_measurements", sensor=sensor_id, count=len(readings))
        return readings

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self) -> "OpenAQClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
