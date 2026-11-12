"""Shared data loading utilities and threshold constants."""

from pathlib import Path
from typing import TypedDict

import pandas as pd

RAW_DIR = Path(__file__).parent.parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent.parent / "data" / "processed"
FIGURES_DIR = Path(__file__).parent.parent.parent / "results" / "figures"


def load_raw_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load stations and measurements from raw parquet files."""
    stations = pd.read_parquet(RAW_DIR / "stations.parquet")
    measurements = pd.read_parquet(RAW_DIR / "measurements.parquet")
    measurements["timestamp"] = pd.to_datetime(measurements["timestamp"], utc=True)
    return stations, measurements


def short_name(name: str) -> str:
    """Remove Hebrew prefix for cleaner station labels."""
    return name.replace("תחנה:", "")


# Israeli 1-hour air quality standards (ppm)
ISRAEL_THRESHOLDS: dict[str, float] = {
    "co": 26.0,
    "no2": 0.106,
    "o3": 0.082,
    "so2": 0.134,
}


class WHOThreshold(TypedDict):
    """WHO guideline with averaging window."""

    value: float
    window_hours: int
    label: str


# WHO 2021 guidelines with averaging windows (ppm)
WHO_THRESHOLDS: dict[str, WHOThreshold] = {
    "co": {
        "value": 4.0,
        "window_hours": 24,
        "label": "WHO 24h (4 ppm)",
    },
    "no2": {
        "value": 0.013,
        "window_hours": 24,
        "label": "WHO annual (0.013 ppm, 24h avg)",
    },
    "o3": {
        "value": 0.051,
        "window_hours": 8,
        "label": "WHO 8h (0.051 ppm)",
    },
    "so2": {
        "value": 0.015,
        "window_hours": 24,
        "label": "WHO 24h (0.015 ppm)",
    },
}
