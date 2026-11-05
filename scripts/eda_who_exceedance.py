"""Monthly count of WHO threshold exceedances using rolling averages."""

from pathlib import Path
from typing import TypedDict

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FIGURES_DIR = Path(__file__).parent.parent / "results" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path(__file__).parent.parent / "data" / "raw"


class WHOThreshold(TypedDict):
    value: float
    window_hours: int
    label: str


# WHO 2021 guidelines with averaging windows (all in ppm)
WHO_THRESHOLDS: dict[str, WHOThreshold] = {
    "co": {
        "value": 4,
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


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load stations and measurements from parquet."""
    stations = pd.read_parquet(DATA_DIR / "stations.parquet")
    measurements = pd.read_parquet(DATA_DIR / "measurements.parquet")
    measurements["timestamp"] = pd.to_datetime(measurements["timestamp"], utc=True)
    return stations, measurements


def short_name(name: str) -> str:
    """Remove prefix for cleaner labels."""
    return name.replace("תחנה:", "")


def compute_rolling_exceedances(measurements: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    """Compute rolling average exceedances per station/pollutant."""
    df = measurements.merge(stations[["station_id", "name"]], on="station_id", how="left")
    df["short"] = df["name"].apply(short_name)

    all_exceedances = []

    for pollutant in sorted(df["pollutant"].unique()):
        who = WHO_THRESHOLDS[pollutant]
        window = who["window_hours"]
        threshold = who["value"]
        subset = df[df["pollutant"] == pollutant]

        for station, group in subset.groupby("short"):
            group = group.sort_values("timestamp").set_index("timestamp")
            rolling_avg = (
                group["value"].rolling(f"{window}h", min_periods=max(1, window // 2)).mean()
            )
            exceeded = rolling_avg[rolling_avg > threshold]

            if exceeded.empty:
                continue

            exc_df = exceeded.reset_index()
            exc_df["year_month"] = exc_df["timestamp"].dt.to_period("M").astype(str)
            exc_df["pollutant"] = pollutant
            exc_df["short"] = station
            all_exceedances.append(exc_df)

    if not all_exceedances:
        return pd.DataFrame(columns=["timestamp", "value", "year_month", "pollutant", "short"])
    return pd.concat(all_exceedances, ignore_index=True)


def plot_who_exceedance(
    exceedances: pd.DataFrame, measurements: pd.DataFrame, stations: pd.DataFrame
) -> None:
    """Bar chart of monthly WHO exceedance counts per station."""
    df = measurements.merge(stations[["station_id", "name"]], on="station_id", how="left")
    df["short"] = df["name"].apply(short_name)
    df["year_month"] = df["timestamp"].dt.to_period("M").astype(str)

    pollutants = sorted(df["pollutant"].unique())
    fig, axes = plt.subplots(2, 2, figsize=(18, 12))

    for ax, pollutant in zip(axes.flat, pollutants, strict=False):
        who = WHO_THRESHOLDS[pollutant]
        all_months = sorted(df[df["pollutant"] == pollutant]["year_month"].unique())

        exc_poll = exceedances[exceedances["pollutant"] == pollutant]
        if exc_poll.empty:
            ax.set_title(
                f"{pollutant.upper()} — {who['label']}\nNo exceedances",
                fontweight="bold",
            )
            ax.set_xticks(range(len(all_months)))
            ax.set_xticklabels(all_months, rotation=45, ha="right", fontsize=7)
            ax.set_ylabel("Exceedance Count")
            continue

        counts = exc_poll.groupby(["year_month", "short"]).size().reset_index(name="count")

        station_names = sorted(counts["short"].unique())
        n_stations = len(station_names)
        colors = plt.cm.tab10(np.linspace(0, 1, max(n_stations, 1)))

        bar_width = 0.8 / max(n_stations, 1)
        month_idx = {m: i for i, m in enumerate(all_months)}

        for s_i, station in enumerate(station_names):
            s_data = counts[counts["short"] == station]
            x_positions = [
                month_idx[m] + s_i * bar_width - 0.4 + bar_width / 2 for m in s_data["year_month"]
            ]
            ax.bar(
                x_positions,
                s_data["count"],
                width=bar_width,
                label=station,
                color=colors[s_i],
            )

        ax.set_xticks(range(len(all_months)))
        ax.set_xticklabels(all_months, rotation=45, ha="right", fontsize=7)
        ax.set_ylabel("Exceedance Count")
        ax.set_title(
            f"{pollutant.upper()} — {who['label']}",
            fontweight="bold",
        )
        ax.legend(fontsize=7, loc="best")
        ax.grid(axis="y", alpha=0.3)

    plt.suptitle(
        "Monthly WHO Threshold Exceedances (Rolling Avg) per Station",
        fontsize=16,
        fontweight="bold",
    )
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "monthly_who_exceedance.png", dpi=150)
    plt.close()
    print("Saved: monthly_who_exceedance.png")


def print_summary(exceedances: pd.DataFrame) -> None:
    """Print WHO exceedance summary."""
    print("=" * 60)
    print("WHO THRESHOLD EXCEEDANCE SUMMARY (ROLLING AVG)")
    print("=" * 60)

    for pollutant in sorted(WHO_THRESHOLDS.keys()):
        who = WHO_THRESHOLDS[pollutant]
        exc = exceedances[exceedances["pollutant"] == pollutant]
        n_exc = len(exc)

        print(f"\n{pollutant.upper()} — {who['label']}")
        print(f"  Window: {who['window_hours']}h rolling average")
        print(f"  Total exceedances: {n_exc:,}")

        if n_exc > 0:
            per_station = exc.groupby("short").size().sort_values(ascending=False)
            for station, count in per_station.items():
                print(f"  {station:25s}: {count:,}")


def main() -> None:
    stations, measurements = load_data()

    print("Computing rolling averages... (this may take a moment)")
    exceedances = compute_rolling_exceedances(measurements, stations)

    print_summary(exceedances)
    print()
    plot_who_exceedance(exceedances, measurements, stations)
    print(f"Figures saved to {FIGURES_DIR}")


if __name__ == "__main__":
    main()
