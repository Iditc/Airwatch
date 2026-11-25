"""Analyze missing data patterns in Israeli air quality measurements."""

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


def analyze_coverage(measurements: pd.DataFrame, stations: pd.DataFrame) -> None:
    """Print coverage stats per station and pollutant."""
    print("=" * 60)
    print("DATA COVERAGE ANALYSIS")
    print("=" * 60)

    date_min = measurements["timestamp"].min()
    date_max = measurements["timestamp"].max()
    total_days = (date_max - date_min).days
    print(f"Date range: {date_min.date()} to {date_max.date()} ({total_days} days)\n")

    combos = (
        measurements.groupby(["station_id", "pollutant"])
        .agg(
            count=("value", "size"),
            first=("timestamp", "min"),
            last=("timestamp", "max"),
        )
        .reset_index()
    )
    combos = combos.merge(stations[["station_id", "name"]], on="station_id", how="left")
    combos["active_days"] = (combos["last"] - combos["first"]).dt.days + 1
    combos["measurements_per_day"] = (combos["count"] / combos["active_days"]).round(1)

    print("Measurements per day (by station & pollutant):")
    for _, row in combos.sort_values(["name", "pollutant"]).iterrows():
        print(
            f"  {row['name']:30s} | {row['pollutant']:4s} | "
            f"{row['count']:6,} measurements | {row['measurements_per_day']:5.1f}/day | "
            f"{row['active_days']} active days"
        )
    print()


def find_gaps(measurements: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    """Find time gaps per station/pollutant pair."""
    all_gaps = []

    for (sid, poll), group in measurements.groupby(["station_id", "pollutant"]):
        timestamps = group["timestamp"].sort_values()
        diffs = timestamps.diff().dropna()

        median_interval = diffs.median()
        threshold = median_interval * 3

        large_gaps = diffs[diffs > threshold]
        for idx, gap in large_gaps.items():
            gap_start = (
                timestamps.loc[:idx].iloc[-2]
                if len(timestamps.loc[:idx]) >= 2
                else timestamps.iloc[0]
            )
            all_gaps.append(
                {
                    "station_id": sid,
                    "pollutant": poll,
                    "gap_start": gap_start,
                    "gap_hours": gap.total_seconds() / 3600,
                }
            )

    gaps_df = pd.DataFrame(all_gaps)
    if not gaps_df.empty:
        gaps_df = gaps_df.merge(stations[["station_id", "name"]], on="station_id", how="left")
    return gaps_df


def print_gap_stats(gaps_df: pd.DataFrame) -> None:
    """Print gap statistics."""
    print("=" * 60)
    print("GAP ANALYSIS (gaps > 3x median interval)")
    print("=" * 60)

    if gaps_df.empty:
        print("No significant gaps found.")
        return

    print(f"Total gaps found: {len(gaps_df)}")
    gap_min = gaps_df["gap_hours"].min()
    gap_max = gaps_df["gap_hours"].max()
    print(f"Gap duration range: {gap_min:.1f}h to {gap_max:.1f}h")
    print(f"Median gap: {gaps_df['gap_hours'].median():.1f}h")
    print(f"Gaps > 24h: {len(gaps_df[gaps_df['gap_hours'] > 24])}")
    print(f"Gaps > 7 days: {len(gaps_df[gaps_df['gap_hours'] > 168])}")
    print()

    print("Gaps per station:")
    per_station = gaps_df.groupby("name")["gap_hours"].agg(["count", "max", "median"])
    per_station.columns = ["num_gaps", "max_gap_hours", "median_gap_hours"]
    per_station = per_station.sort_values("num_gaps", ascending=False)
    for name, row in per_station.iterrows():
        print(
            f"  {name:30s} | {int(row['num_gaps']):4d} gaps | "
            f"max {row['max_gap_hours']:.0f}h | median {row['median_gap_hours']:.1f}h"
        )
    print()

    print("Gaps per pollutant:")
    per_poll = gaps_df.groupby("pollutant")["gap_hours"].agg(["count", "max", "median"])
    per_poll.columns = ["num_gaps", "max_gap_hours", "median_gap_hours"]
    for poll, row in per_poll.iterrows():
        print(
            f"  {poll:4s} | {int(row['num_gaps']):4d} gaps | "
            f"max {row['max_gap_hours']:.0f}h | median {row['median_gap_hours']:.1f}h"
        )
    print()


def plot_availability_heatmap(measurements: pd.DataFrame, stations: pd.DataFrame) -> None:
    """Heatmap of data availability per station per month."""
    df = measurements.copy()
    df["year_month"] = df["timestamp"].dt.to_period("M")

    pivot = df.groupby(["station_id", "year_month"]).size().reset_index(name="count")
    pivot = pivot.merge(stations[["station_id", "name"]], on="station_id", how="left")
    pivot["year_month_str"] = pivot["year_month"].astype(str)

    matrix = pivot.pivot_table(index="name", columns="year_month_str", values="count", fill_value=0)

    fig, ax = plt.subplots(figsize=(16, 6))
    sns.heatmap(
        matrix,
        cmap="YlOrRd",
        ax=ax,
        linewidths=0.5,
        cbar_kws={"label": "Number of measurements"},
    )
    ax.set_title("Data Availability per Station per Month", fontsize=14, fontweight="bold")
    ax.set_xlabel("Month")
    ax.set_ylabel("")
    plt.xticks(rotation=45, ha="right", fontsize=9)
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "data_availability_heatmap.png", dpi=150)
    plt.close()
    print("Saved: data_availability_heatmap.png")


def plot_gap_distribution(gaps_df: pd.DataFrame) -> None:
    """Histogram of gap durations."""
    if gaps_df.empty:
        print("No gaps to plot.")
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    axes[0].hist(gaps_df["gap_hours"], bins=50, color="steelblue", edgecolor="white", alpha=0.8)
    axes[0].set_xlabel("Gap Duration (hours)")
    axes[0].set_ylabel("Count")
    axes[0].set_title("All Gaps")
    axes[0].axvline(x=24, color="red", linestyle="--", alpha=0.7, label="24h")
    axes[0].axvline(x=168, color="red", linestyle=":", alpha=0.7, label="7 days")
    axes[0].legend()

    short_gaps = gaps_df[gaps_df["gap_hours"] <= 72]
    if not short_gaps.empty:
        axes[1].hist(
            short_gaps["gap_hours"], bins=40, color="steelblue", edgecolor="white", alpha=0.8
        )
        axes[1].set_xlabel("Gap Duration (hours)")
        axes[1].set_ylabel("Count")
        axes[1].set_title("Gaps ≤ 72h (zoom)")

    plt.suptitle("Distribution of Data Gaps", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "gap_distribution.png", dpi=150)
    plt.close()
    print("Saved: gap_distribution.png")


def plot_pollutant_coverage(measurements: pd.DataFrame, stations: pd.DataFrame) -> None:
    """Heatmap of which pollutants each station measures."""
    pivot = measurements.groupby(["station_id", "pollutant"]).size().reset_index(name="count")
    pivot = pivot.merge(stations[["station_id", "name"]], on="station_id", how="left")
    matrix = pivot.pivot_table(index="name", columns="pollutant", values="count", fill_value=0)
    binary = (matrix > 0).astype(int)

    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(
        binary,
        annot=matrix.values,
        fmt=",",
        cmap=["#f0f0f0", "#3B82F6"],
        cbar=False,
        ax=ax,
        linewidths=1,
    )
    ax.set_title("Pollutant Coverage per Station", fontsize=14, fontweight="bold")
    ax.set_ylabel("")
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "pollutant_coverage.png", dpi=150)
    plt.close()
    print("Saved: pollutant_coverage.png")


def plot_measurement_frequency(measurements: pd.DataFrame, stations: pd.DataFrame) -> None:
    """Box plot of measurement intervals per station."""
    intervals = []
    for (sid, poll), group in measurements.groupby(["station_id", "pollutant"]):
        timestamps = group["timestamp"].sort_values()
        diffs = timestamps.diff().dropna().dt.total_seconds() / 3600
        diffs_clipped = diffs[diffs <= 24]
        if not diffs_clipped.empty:
            name = stations[stations["station_id"] == sid]["name"].iloc[0]
            for val in diffs_clipped.values:
                intervals.append({"station": name, "pollutant": poll, "interval_hours": val})

    intervals_df = pd.DataFrame(intervals)
    if intervals_df.empty:
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    order = intervals_df.groupby("station")["interval_hours"].median().sort_values().index
    sns.boxplot(data=intervals_df, x="station", y="interval_hours", ax=ax, order=order)
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha="right")
    ax.set_ylabel("Measurement Interval (hours)")
    ax.set_xlabel("")
    ax.set_title(
        "Measurement Frequency per Station (intervals ≤ 24h)", fontsize=14, fontweight="bold"
    )
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "measurement_frequency.png", dpi=150)
    plt.close()
    print("Saved: measurement_frequency.png")


def main() -> None:
    stations, measurements = load_data()
    analyze_coverage(measurements, stations)

    gaps_df = find_gaps(measurements, stations)
    print_gap_stats(gaps_df)

    print("\n" + "=" * 60)
    print("GENERATING PLOTS")
    print("=" * 60)
    plot_availability_heatmap(measurements, stations)
    plot_gap_distribution(gaps_df)
    plot_pollutant_coverage(measurements, stations)
    plot_measurement_frequency(measurements, stations)
    print(f"\nAll figures saved to {FIGURES_DIR}")


if __name__ == "__main__":
    main()
