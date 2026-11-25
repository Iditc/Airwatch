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
SOURCES = ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]
BUFFER_KM = 10.0

# Israel border polygon including Judea & Samaria — (lat, lon) pairs.
# Western/northern border from johan/world.geo.json, eastern border
# follows the Jordan River and Dead Sea western shore.
ISRAEL_POLYGON: list[tuple[float, float]] = [
    (32.709192, 35.719918),  # Golan south
    (32.393992, 35.545665),  # upper Jordan Valley
    (32.10, 35.57),  # central Jordan Valley
    (31.85, 35.55),  # lower Jordan Valley (Jericho)
    (31.78, 35.53),  # northern Dead Sea
    (31.50, 35.40),  # central Dead Sea
    (31.100066, 35.420918),  # southern Dead Sea
    (29.501326, 34.922603),  # Eilat
    (31.219361, 34.265433),  # coast near Gaza
    (31.548824, 34.556372),  # coast
    (31.605539, 34.488107),  # coast
    (32.072926, 34.752587),  # Tel Aviv coast
    (32.827376, 34.955417),  # Haifa coast
    (33.080539, 35.098457),  # northern border
    (33.090900, 35.126053),  # northern border
    (33.089040, 35.460709),  # northern border east
    (33.264275, 35.552797),  # northern tip
    (33.277426, 35.821101),  # Golan north
    (32.868123, 35.836397),  # Golan east
    (32.716014, 35.700798),  # Golan south-east
]


def _point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = polygon[i]
        yj, xj = polygon[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_to_segment_km(
    lat: float, lon: float, lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Minimum distance (km) from a point to a line segment."""
    dx = lon2 - lon1
    dy = lat2 - lat1
    if dx == 0.0 and dy == 0.0:
        return haversine_km(lat, lon, lat1, lon1)
    t = max(0.0, min(1.0, ((lon - lon1) * dx + (lat - lat1) * dy) / (dx * dx + dy * dy)))
    proj_lat = lat1 + t * dy
    proj_lon = lon1 + t * dx
    return haversine_km(lat, lon, proj_lat, proj_lon)


def is_in_israel(lat: float, lon: float, buffer_km: float = BUFFER_KM) -> bool:
    """Check if a point is inside Israel's border polygon or within buffer_km of it."""
    if _point_in_polygon(lat, lon, ISRAEL_POLYGON):
        return True
    n = len(ISRAEL_POLYGON)
    for i in range(n):
        lat1, lon1 = ISRAEL_POLYGON[i]
        lat2, lon2 = ISRAEL_POLYGON[(i + 1) % n]
        if _point_to_segment_km(lat, lon, lat1, lon1, lat2, lon2) <= buffer_km:
            return True
    return False


def get_map_key() -> str:
    key = os.environ.get("FIRMS_MAP_KEY", "")
    if not key:
        msg = "FIRMS_MAP_KEY not set in .env"
        raise ValueError(msg)
    return key


def fetch_hotspots(
    days: int = 5,
    bbox: str = ISRAEL_BBOX,
    sources: list[str] | None = None,
) -> list[dict[str, str]]:
    """Fetch fire hotspots from FIRMS API, filtered to Israel + 10 km buffer."""
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
            lat = float(row["latitude"])
            lon = float(row["longitude"])
            if not is_in_israel(lat, lon):
                continue
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
