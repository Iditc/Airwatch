"""Fetch historical air quality data from Israeli stations and save as parquet."""

import os
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.data.openaq_client import OpenAQClient
from src.logging_config import get_logger, setup_logging

setup_logging("INFO")
logger = get_logger(__name__)

load_dotenv(Path(__file__).parent.parent / ".env")

DATA_DIR = Path(__file__).parent.parent / "data" / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)

MAX_STATIONS = 10
MEASUREMENTS_PER_SENSOR = 10000
DELAY_BETWEEN_REQUESTS = 0.5


def fetch_all_stations(client: OpenAQClient) -> pd.DataFrame:
    """Fetch Israeli stations and return as DataFrame."""
    country_id = client.get_israel_country_id()
    stations = client.get_stations(country_id=country_id)

    rows = []
    for s in stations:
        rows.append(
            {
                "station_id": s.station_id,
                "name": s.name,
                "city": s.city,
                "latitude": s.latitude,
                "longitude": s.longitude,
                "pollutants": ",".join(s.pollutants),
                "num_pollutants": len(s.pollutants),
            }
        )

    df = pd.DataFrame(rows)
    logger.info("stations_fetched", count=len(df))
    return df


def fetch_measurements_for_station(
    client: OpenAQClient, station_id: str, station_name: str
) -> pd.DataFrame:
    """Fetch all sensor measurements for a single station."""
    sensors = client.get_sensor_ids(location_id=int(station_id))
    if not sensors:
        logger.warning("no_sensors", station=station_name)
        return pd.DataFrame()

    all_readings = []
    for pollutant, sensor_id in sensors.items():
        logger.info("fetching_sensor", station=station_name, pollutant=pollutant)
        try:
            readings = client.get_measurements(
                sensor_id=sensor_id,
                station_id=station_id,
                limit=MEASUREMENTS_PER_SENSOR,
            )
        except Exception:
            logger.warning("sensor_failed", station=station_name, pollutant=pollutant)
            continue
        for r in readings:
            all_readings.append(
                {
                    "station_id": r.station_id,
                    "timestamp": r.timestamp,
                    "pollutant": r.pollutant,
                    "value": r.value,
                    "unit": r.unit,
                }
            )
        time.sleep(DELAY_BETWEEN_REQUESTS)

    df = pd.DataFrame(all_readings)
    logger.info("station_measurements", station=station_name, rows=len(df))
    return df


def main() -> None:
    api_key = os.environ.get("OPENAQ_API_KEY", "")
    if not api_key or api_key == "your_key_here":
        print("ERROR: Set OPENAQ_API_KEY in .env")
        raise SystemExit(1)

    with OpenAQClient(api_key=api_key) as client:
        stations_df = fetch_all_stations(client)
        stations_path = DATA_DIR / "stations.parquet"
        stations_df.to_parquet(stations_path, index=False)
        print(f"Saved {len(stations_df)} stations to {stations_path}")

        top_stations = stations_df.nlargest(MAX_STATIONS, "num_pollutants")
        print(f"\nFetching measurements from top {MAX_STATIONS} stations:")
        for _, row in top_stations.iterrows():
            print(f"  - {row['name']} ({row['num_pollutants']} pollutants)")

        all_measurements = []
        for _, row in top_stations.iterrows():
            df = fetch_measurements_for_station(client, row["station_id"], row["name"])
            if not df.empty:
                all_measurements.append(df)
            time.sleep(DELAY_BETWEEN_REQUESTS)

        if all_measurements:
            measurements_df = pd.concat(all_measurements, ignore_index=True)
            measurements_path = DATA_DIR / "measurements.parquet"
            measurements_df.to_parquet(measurements_path, index=False)
            print(f"\nSaved {len(measurements_df)} measurements to {measurements_path}")
            print("\nSummary:")
            print(f"  Stations: {measurements_df['station_id'].nunique()}")
            print(f"  Pollutants: {measurements_df['pollutant'].unique().tolist()}")
            print(
                f"  Date range: {measurements_df['timestamp'].min()} to "
                f"{measurements_df['timestamp'].max()}"
            )
        else:
            print("\nNo measurements found!")


if __name__ == "__main__":
    main()
