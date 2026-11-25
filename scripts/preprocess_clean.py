"""Clean raw measurements: remove invalid values, interpolate small gaps."""

import pandas as pd

from src.data.loader import PROCESSED_DIR, load_raw_data

MAX_INTERP_HOURS = 3


def remove_invalid_values(df: pd.DataFrame) -> pd.DataFrame:
    """Remove negative, infinite, and NaN values."""
    before = len(df)
    df = df.replace([float("inf"), float("-inf")], float("nan"))
    df = df.dropna(subset=["value"])
    df = df[df["value"] >= 0]
    after = len(df)
    print(f"  Removed {before - after:,} invalid rows ({before:,} -> {after:,})")
    return df


def interpolate_small_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """Interpolate gaps up to MAX_INTERP_HOURS, mark larger gaps."""
    results = []

    for (_station_id, _pollutant), group in df.groupby(["station_id", "pollutant"]):
        group = group.sort_values("timestamp").copy()
        time_diff = group["timestamp"].diff()
        median_freq = time_diff.median()

        gap_threshold = (
            median_freq * MAX_INTERP_HOURS if median_freq else pd.Timedelta(hours=MAX_INTERP_HOURS)
        )
        group["is_gap"] = time_diff > gap_threshold

        group = group.set_index("timestamp")
        group["value"] = group["value"].interpolate(method="time", limit=MAX_INTERP_HOURS)
        group = group.reset_index()
        results.append(group)

    return pd.concat(results, ignore_index=True)


def print_summary(raw: pd.DataFrame, clean: pd.DataFrame) -> None:
    """Print cleaning summary statistics."""
    print("\n" + "=" * 60)
    print("CLEANING SUMMARY")
    print("=" * 60)
    print(f"  Raw rows:   {len(raw):,}")
    print(f"  Clean rows: {len(clean):,}")
    print(f"  Removed:    {len(raw) - len(clean):,}")

    gaps = clean["is_gap"].sum()
    print(f"  Large gaps (>{MAX_INTERP_HOURS}h): {gaps:,}")

    print("\n  Per pollutant:")
    for poll in sorted(clean["pollutant"].unique()):
        subset = clean[clean["pollutant"] == poll]
        n_gaps = subset["is_gap"].sum()
        print(f"    {poll.upper():4s}: {len(subset):,} rows, {n_gaps} gaps")


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading raw data...")
    _, measurements = load_raw_data()

    print("Removing invalid values...")
    clean = remove_invalid_values(measurements)

    print("Interpolating small gaps, marking large gaps...")
    clean = interpolate_small_gaps(clean)

    print_summary(measurements, clean)

    out_path = PROCESSED_DIR / "measurements_clean.parquet"
    clean.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
