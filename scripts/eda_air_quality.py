"""EDA script for Israeli air quality data."""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

FIGURES_DIR = Path(__file__).parent.parent / "results" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path(__file__).parent.parent / "data" / "raw"


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load stations and measurements from parquet."""
    stations = pd.read_parquet(DATA_DIR / "stations.parquet")
    measurements = pd.read_parquet(DATA_DIR / "measurements.parquet")
    measurements["timestamp"] = pd.to_datetime(measurements["timestamp"], utc=True)
    return stations, measurements


def print_basic_stats(stations: pd.DataFrame, measurements: pd.DataFrame) -> None:
    """Print dataset overview."""
    print("=" * 60)
    print("DATASET OVERVIEW")
    print("=" * 60)
    print(f"Stations: {len(stations)}")
    print(f"Measurements: {len(measurements):,}")
    print(f"Date range: {measurements['timestamp'].min()} to {measurements['timestamp'].max()}")
    print(f"Stations with data: {measurements['station_id'].nunique()}")
    print(f"Pollutants: {measurements['pollutant'].unique().tolist()}")
    print()

    print("Measurements per pollutant:")
    print(measurements["pollutant"].value_counts().to_string())
    print()

    print("Measurements per station:")
    station_counts = measurements.groupby("station_id").size().reset_index(name="count")
    station_counts = station_counts.merge(
        stations[["station_id", "name"]], on="station_id", how="left"
    )
    for _, row in station_counts.sort_values("count", ascending=False).iterrows():
        print(f"  {row['name']}: {row['count']:,}")
    print()

    print("Missing values:")
    print(measurements.isnull().sum().to_string())
    print()

    print("Value statistics per pollutant:")
    print(measurements.groupby("pollutant")["value"].describe().round(2).to_string())


def plot_measurements_per_station(measurements: pd.DataFrame, stations: pd.DataFrame) -> None:
    """Bar chart of measurement counts per station."""
    counts = measurements.groupby("station_id").size().reset_index(name="count")
    counts = counts.merge(stations[["station_id", "name"]], on="station_id", how="left")
    counts = counts.sort_values("count", ascending=True)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(counts["name"], counts["count"], color="steelblue")
    ax.set_xlabel("Number of Measurements")
    ax.set_title("Measurements per Station")
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "measurements_per_station.png", dpi=150)
    plt.close()
    print("Saved: measurements_per_station.png")


def plot_pollutant_distributions(measurements: pd.DataFrame) -> None:
    """Histogram of values per pollutant."""
    pollutants = measurements["pollutant"].unique()
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    for ax, pollutant in zip(axes.flat, sorted(pollutants), strict=False):
        data = measurements[measurements["pollutant"] == pollutant]["value"]
        ax.hist(data, bins=50, color="steelblue", edgecolor="white", alpha=0.8)
        ax.set_title(f"{pollutant.upper()} Distribution")
        ax.set_xlabel(
            f"Value ({measurements[measurements['pollutant'] == pollutant]['unit'].iloc[0]})"
        )
        ax.set_ylabel("Count")

    plt.suptitle("Pollutant Value Distributions", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "pollutant_distributions.png", dpi=150)
    plt.close()
    print("Saved: pollutant_distributions.png")


def plot_time_series(measurements: pd.DataFrame) -> None:
    """Daily average time series per pollutant."""
    measurements = measurements.copy()
    measurements["date"] = measurements["timestamp"].dt.date

    daily = measurements.groupby(["date", "pollutant"])["value"].mean().reset_index()
    daily["date"] = pd.to_datetime(daily["date"])

    pollutants = sorted(daily["pollutant"].unique())
    fig, axes = plt.subplots(len(pollutants), 1, figsize=(14, 3 * len(pollutants)), sharex=True)

    for ax, pollutant in zip(axes, pollutants, strict=False):
        subset = daily[daily["pollutant"] == pollutant]
        ax.plot(subset["date"], subset["value"], linewidth=0.8, color="steelblue")
        ax.set_ylabel(pollutant.upper())
        ax.grid(alpha=0.3)

    axes[-1].set_xlabel("Date")
    plt.suptitle("Daily Average Pollutant Levels", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "time_series_daily.png", dpi=150)
    plt.close()
    print("Saved: time_series_daily.png")


def plot_hourly_pattern(measurements: pd.DataFrame) -> None:
    """Average value by hour of day per pollutant."""
    measurements = measurements.copy()
    measurements["hour"] = measurements["timestamp"].dt.hour

    hourly = measurements.groupby(["hour", "pollutant"])["value"].mean().reset_index()

    fig, ax = plt.subplots(figsize=(10, 6))
    for pollutant in sorted(hourly["pollutant"].unique()):
        subset = hourly[hourly["pollutant"] == pollutant]
        ax.plot(subset["hour"], subset["value"], marker="o", markersize=4, label=pollutant.upper())

    ax.set_xlabel("Hour of Day")
    ax.set_ylabel("Average Value")
    ax.set_title("Average Pollutant Levels by Hour of Day")
    ax.set_xticks(range(0, 24))
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "hourly_pattern.png", dpi=150)
    plt.close()
    print("Saved: hourly_pattern.png")


def plot_correlation_heatmap(measurements: pd.DataFrame) -> None:
    """Correlation between pollutants (using hourly averages)."""
    measurements = measurements.copy()
    measurements["hour_bucket"] = measurements["timestamp"].dt.floor("h")

    pivot = measurements.pivot_table(
        index=["station_id", "hour_bucket"],
        columns="pollutant",
        values="value",
        aggfunc="mean",
    )

    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(
        pivot.corr(),
        annot=True,
        fmt=".2f",
        cmap="RdBu_r",
        center=0,
        ax=ax,
        vmin=-1,
        vmax=1,
    )
    ax.set_title("Pollutant Correlation (Hourly Averages)")
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "pollutant_correlation.png", dpi=150)
    plt.close()
    print("Saved: pollutant_correlation.png")


def plot_boxplots(measurements: pd.DataFrame) -> None:
    """Box plots per pollutant to see outliers."""
    pollutants = sorted(measurements["pollutant"].unique())
    fig, axes = plt.subplots(1, len(pollutants), figsize=(14, 5))

    for ax, pollutant in zip(axes, pollutants, strict=False):
        data = measurements[measurements["pollutant"] == pollutant]["value"]
        ax.boxplot(data, vert=True)
        ax.set_title(pollutant.upper())
        ax.set_ylabel("Value")

    plt.suptitle("Pollutant Value Distributions (Box Plots)", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "boxplots.png", dpi=150)
    plt.close()
    print("Saved: boxplots.png")


def main() -> None:
    stations, measurements = load_data()
    print_basic_stats(stations, measurements)

    print("\n" + "=" * 60)
    print("GENERATING PLOTS")
    print("=" * 60)
    plot_measurements_per_station(measurements, stations)
    plot_pollutant_distributions(measurements)
    plot_time_series(measurements)
    plot_hourly_pattern(measurements)
    plot_correlation_heatmap(measurements)
    plot_boxplots(measurements)
    print(f"\nAll figures saved to {FIGURES_DIR}")


if __name__ == "__main__":
    main()
