"""Monthly count of Israeli threshold exceedances per station."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FIGURES_DIR = Path(__file__).parent.parent / "results" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path(__file__).parent.parent / "data" / "raw"

ISRAEL_THRESHOLDS = {
    "co": 26,
    "no2": 0.106,
    "o3": 0.082,
    "so2": 0.134,
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


def plot_monthly_exceedance(measurements: pd.DataFrame, stations: pd.DataFrame) -> None:
    """Bar chart of monthly exceedance counts per station."""
    df = measurements.merge(stations[["station_id", "name"]], on="station_id", how="left")
    df["short"] = df["name"].apply(short_name)
    df["year_month"] = df["timestamp"].dt.to_period("M").astype(str)

    pollutants = sorted(df["pollutant"].unique())
    fig, axes = plt.subplots(2, 2, figsize=(18, 12))

    for ax, pollutant in zip(axes.flat, pollutants, strict=False):
        threshold = ISRAEL_THRESHOLDS[pollutant]
        subset = df[df["pollutant"] == pollutant]
        exceeded = subset[subset["value"] > threshold]

        if exceeded.empty:
            ax.set_title(
                f"{pollutant.upper()} — Israel 1h ({threshold} ppm)" f"\nNo exceedances",
                fontweight="bold",
            )
            all_months = sorted(subset["year_month"].unique())
            ax.set_xticks(range(len(all_months)))
            ax.set_xticklabels(all_months, rotation=45, ha="right", fontsize=7)
            ax.set_ylabel("Exceedance Count")
            continue

        counts = exceeded.groupby(["year_month", "short"]).size().reset_index(name="count")

        all_months = sorted(subset["year_month"].unique())
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
            f"{pollutant.upper()} — Israel 1h ({threshold} ppm)",
            fontweight="bold",
        )
        ax.legend(fontsize=7, loc="best")
        ax.grid(axis="y", alpha=0.3)

    plt.suptitle(
        "Monthly Israeli Threshold Exceedances per Station",
        fontsize=16,
        fontweight="bold",
    )
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "monthly_israel_exceedance.png", dpi=150)
    plt.close()
    print("Saved: monthly_israel_exceedance.png")


def print_summary(measurements: pd.DataFrame, stations: pd.DataFrame) -> None:
    """Print exceedance summary."""
    df = measurements.merge(stations[["station_id", "name"]], on="station_id", how="left")
    df["short"] = df["name"].apply(short_name)

    print("=" * 60)
    print("ISRAELI THRESHOLD EXCEEDANCE SUMMARY")
    print("=" * 60)

    for pollutant in sorted(df["pollutant"].unique()):
        threshold = ISRAEL_THRESHOLDS[pollutant]
        subset = df[df["pollutant"] == pollutant]
        exceeded = subset[subset["value"] > threshold]
        total = len(subset)
        n_exc = len(exceeded)

        print(f"\n{pollutant.upper()} (threshold: {threshold} ppm)")
        print(f"  Total: {n_exc} / {total:,} ({100*n_exc/total:.2f}%)")

        if n_exc > 0:
            per_station = exceeded.groupby("short").size().sort_values(ascending=False)
            for station, count in per_station.items():
                print(f"  {station:25s}: {count} exceedances")


def main() -> None:
    stations, measurements = load_data()
    print_summary(measurements, stations)
    print()
    plot_monthly_exceedance(measurements, stations)
    print(f"Figures saved to {FIGURES_DIR}")


if __name__ == "__main__":
    main()
