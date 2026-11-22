"""NASA FIRMS client — fetch active fire hotspots near Israeli stations."""

import csv
import io
import math
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
ISRAEL_BBOX = "34,29,36,34"  # west,south,east,north
SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"]


def get_map_key() -> str:
    key = os.environ.get("FIRMS_MAP_KEY", "")
    if not key:
        msg = "FIRMS_MAP_KEY not set in .env"
        raise ValueError(msg)
    return key


def fetch_hotspots(
    days: int = 2,
    bbox: str = ISRAEL_BBOX,
    sources: list[str] | None = None,
) -> list[dict[str, str]]:
    """Fetch fire hotspots from FIRMS API. Returns list of CSV row dicts."""
    key = get_map_key()
    sources = sources or SOURCES
    client = httpx.Client(timeout=30)
    all_rows: list[dict[str, str]] = []

    for source in sources:
        url = f"{FIRMS_BASE}/{key}/{source}/{bbox}/{days}"
        resp = client.get(url)
        resp.raise_for_status()

        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            row["source"] = source
            all_rows.append(row)

    client.close()
    return all_rows


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearby_fires(
    hotspots: list[dict[str, str]],
    station_lat: float,
    station_lon: float,
    radius_km: float = 50.0,
) -> list[dict[str, str | float]]:
    """Filter hotspots within radius_km of a station, sorted by distance."""
    nearby: list[dict[str, str | float]] = []
    for h in hotspots:
        lat = float(h["latitude"])
        lon = float(h["longitude"])
        dist = haversine_km(station_lat, station_lon, lat, lon)
        if dist <= radius_km:
            nearby.append({**h, "distance_km": round(dist, 1)})
    nearby.sort(key=lambda x: float(x["distance_km"]))
    return nearby
