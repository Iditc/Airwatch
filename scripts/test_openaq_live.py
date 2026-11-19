"""Quick test to verify OpenAQ API works with real data from Israel."""

import os
from pathlib import Path

from dotenv import load_dotenv

from src.data.openaq_client import OpenAQClient
from src.logging_config import setup_logging

setup_logging("INFO")
load_dotenv(Path(__file__).parent.parent / ".env")

api_key = os.environ.get("OPENAQ_API_KEY", "")
if not api_key or api_key == "your_key_here":
    print("ERROR: Set OPENAQ_API_KEY in .env")
    raise SystemExit(1)

with OpenAQClient(api_key=api_key) as client:
    print("\n1. Finding Israel country ID...")
    country_id = client.get_israel_country_id()
    print(f"   Israel ID: {country_id}")

    print("\n2. Fetching Israeli stations...")
    stations = client.get_stations(country_id=country_id)
    print(f"   Found {len(stations)} stations:")
    for s in stations[:10]:
        print(f"   - {s.name} ({s.city}) | {s.pollutants}")

    if stations:
        first = next((s for s in stations if len(s.pollutants) > 1), stations[0])
        print(f"\n3. Fetching sensors from {first.name}...")
        sensors = client.get_sensor_ids(location_id=int(first.station_id))
        print(f"   Sensors: {sensors}")

        if sensors:
            sensor_name, sensor_id = next(iter(sensors.items()))
            print(f"\n4. Fetching measurements for {sensor_name} (sensor {sensor_id})...")
            readings = client.get_measurements(
                sensor_id=sensor_id, station_id=first.station_id, limit=5
            )
            print(f"   Got {len(readings)} readings:")
            for r in readings:
                print(f"   - {r.timestamp} | {r.pollutant}: {r.value} {r.unit}")

print("\nDone!")
