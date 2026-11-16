"""Real-time AirWatch pipeline — fetch, predict, alert.

Usage:
    python scripts/run_pipeline.py                # single run
    python scripts/run_pipeline.py --interval 60  # poll every 60 minutes
"""

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import structlog

from src.data.loader import WHO_THRESHOLDS
from src.data.openaq_client import OpenAQClient
from src.data.weather_client import WeatherClient
from src.detection.forecast_service import ForecastService
from src.schemas.anomaly import AnomalyEvent

logger = structlog.get_logger(__name__)

EVENTS_DIR = Path("data/events")
LOOKBACK_HOURS = 48

LAG_HOURS = [1, 2, 3, 6, 12]

SEASON_MAP = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "fall",
    10: "fall",
    11: "fall",
}


def build_features(measurements: pd.DataFrame) -> pd.DataFrame:
    """Replicate the preprocessing feature pipeline on live data."""
    df = measurements.copy()
    df = df.sort_values("timestamp")

    df["hour"] = df["timestamp"].dt.hour
    df["is_weekend"] = df["timestamp"].dt.dayofweek.isin([4, 5]).astype(int)

    month = df["timestamp"].dt.month
    for m in range(1, 13):
        df[f"month_{m}"] = (month == m).astype(int)
    for d in range(7):
        df[f"dow_{d}"] = (df["timestamp"].dt.dayofweek == d).astype(int)

    season = month.map(SEASON_MAP)
    for s in ["spring", "summer", "fall", "winter"]:
        df[f"season_{s}"] = (season == s).astype(int)

    df["is_holiday"] = 0
    df["is_bonfire_day"] = 0
    df["is_no_traffic_day"] = 0

    for window in [3, 6, 12, 24]:
        grp = df.groupby(["station_id", "pollutant"])["value"]
        w = window
        df[f"rolling_mean_{w}h"] = grp.transform(
            lambda x, _w=w: x.rolling(_w, min_periods=1).mean()
        )
        df[f"rolling_std_{w}h"] = grp.transform(
            lambda x, _w=w: x.rolling(_w, min_periods=1).std().fillna(0)
        )

    df["rate_of_change"] = df.groupby(["station_id", "pollutant"])["value"].diff().fillna(0)

    for lag in LAG_HOURS:
        col = f"value_lag_{lag}h"
        df[col] = df.groupby(["station_id", "pollutant"])["value"].shift(lag)
        df[f"value_diff_{lag}h"] = df["value"] - df[col]
    lag_cols = [c for c in df.columns if c.startswith("value_lag_") or c.startswith("value_diff_")]
    df[lag_cols] = df[lag_cols].fillna(0)

    for pollutant, cfg in WHO_THRESHOLDS.items():
        mask = df["pollutant"] == pollutant
        window = cfg["window_hours"]
        threshold = cfg["value"]
        w = window
        rolling = (
            df.loc[mask]
            .groupby("station_id")["value"]
            .transform(lambda x, _w=w: x.rolling(_w, min_periods=1).mean())
        )
        df.loc[mask, "label_who"] = (rolling > threshold).astype(int)

    df["label_who"] = df.get("label_who", pd.Series(0, index=df.index)).fillna(0).astype(int)

    z_grp = df.groupby(["station_id", "pollutant"])["value"]
    z_mean = z_grp.transform("mean")
    z_std = z_grp.transform("std").replace(0, 1)
    df["label_zscore"] = ((df["value"] - z_mean).abs() / z_std > 3).astype(int)

    return df


def fetch_latest_data(
    openaq: OpenAQClient,
    stations: list[dict],
    lookback_hours: int = LOOKBACK_HOURS,
) -> pd.DataFrame:
    """Fetch recent measurements from OpenAQ for all stations."""
    now = datetime.now(timezone.utc)
    date_from = now - timedelta(hours=lookback_hours)

    all_readings: list[dict] = []
    for station in stations:
        sid = station["station_id"]
        sensors = openaq.get_sensor_ids(int(sid))
        for _pollutant, sensor_id in sensors.items():
            readings = openaq.get_measurements(
                sensor_id=sensor_id,
                station_id=sid,
                date_from=date_from,
                date_to=now,
                limit=lookback_hours * 2,
            )
            for r in readings:
                all_readings.append(
                    {
                        "station_id": r.station_id,
                        "timestamp": r.timestamp,
                        "pollutant": r.pollutant,
                        "value": r.value,
                    }
                )

    if not all_readings:
        return pd.DataFrame()

    df = pd.DataFrame(all_readings)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    logger.info("fetched_live_data", readings=len(df), stations=len(stations))
    return df


def enrich_weather(
    weather: WeatherClient,
    df: pd.DataFrame,
    stations: list[dict],
) -> pd.DataFrame:
    """Add weather columns to measurements dataframe."""
    weather_rows = []
    for station in stations:
        try:
            w = weather.get_current(
                latitude=station["latitude"],
                longitude=station["longitude"],
                station_id=station["station_id"],
            )
            weather_rows.append(
                {
                    "station_id": station["station_id"],
                    "temperature_c": w.temperature_c,
                    "wind_speed_kmh": w.wind_speed_kmh,
                    "humidity_pct": w.humidity_pct,
                    "rain_mm": w.rain_mm,
                }
            )
        except Exception:
            logger.warning("weather_fetch_failed", station=station["station_id"])

    if weather_rows:
        wdf = pd.DataFrame(weather_rows)
        df = df.merge(wdf, on="station_id", how="left")
    return df


def save_events(events: list[AnomalyEvent]) -> Path:
    """Save anomaly events to JSON for downstream agents."""
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = EVENTS_DIR / f"forecast_alerts_{ts}.json"
    data = [e.model_dump(mode="json") for e in events]
    path.write_text(json.dumps(data, indent=2, default=str))
    logger.info("saved_events", path=str(path), count=len(data))
    return path


def run_once(
    openaq: OpenAQClient,
    weather: WeatherClient,
    forecast: ForecastService,
    stations: list[dict],
) -> list[AnomalyEvent]:
    """Single pipeline cycle: fetch → features → predict → emit."""
    logger.info("pipeline_cycle_start")

    raw = fetch_latest_data(openaq, stations)
    if raw.empty:
        logger.warning("no_data_fetched")
        return []

    raw = enrich_weather(weather, raw, stations)

    features = build_features(raw)

    latest = features.groupby(["station_id", "pollutant"]).tail(1)

    stations_meta = {s["station_id"]: s for s in stations}
    events = forecast.run_inference(latest, stations_meta)

    if events:
        save_events(events)
        for e in events:
            logger.info(
                "ALERT",
                station=e.station_name,
                pollutant=e.pollutant.value,
                severity=e.severity.value,
                score=f"{e.anomaly_score:.2f}",
                value=e.value,
            )
    else:
        logger.info("no_alerts")

    return events


def load_stations_from_cache() -> list[dict]:
    """Load station metadata from raw data or fetch fresh."""
    stations_path = Path("data/raw/stations.parquet")
    if stations_path.exists():
        df = pd.read_parquet(stations_path)
        result: list[dict] = df.to_dict("records")
        return result
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="AirWatch real-time pipeline")
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Poll interval in minutes (0 = single run)",
    )
    parser.add_argument("--api-key", type=str, default="", help="OpenAQ API key")
    args = parser.parse_args()

    stations = load_stations_from_cache()
    if not stations:
        print("No station data found. Run the data fetch script first.")
        return

    print(f"Loaded {len(stations)} stations")
    print("Loading forecast models...")
    forecast = ForecastService(pollutants=["no2", "o3"])

    openaq = OpenAQClient(api_key=args.api_key)
    weather_client = WeatherClient()

    try:
        if args.interval > 0:
            print(f"\nStarting continuous pipeline (every {args.interval} min)...")
            print("Press Ctrl+C to stop.\n")
            while True:
                events = run_once(openaq, weather_client, forecast, stations)
                print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {len(events)} alerts")
                time.sleep(args.interval * 60)
        else:
            print("\nRunning single pipeline cycle...")
            events = run_once(openaq, weather_client, forecast, stations)
            print(f"\nDone. {len(events)} alerts generated.")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        openaq.close()
        weather_client.close()


if __name__ == "__main__":
    main()
