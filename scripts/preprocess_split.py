"""Split data temporally into train/val/test and normalize."""

import joblib
import pandas as pd
from sklearn.preprocessing import StandardScaler

from src.data.loader import PROCESSED_DIR

TRAIN_FRAC = 0.6
VAL_FRAC = 0.2

FEATURE_COLS = [
    "value",
    "hour",
    "is_weekend",
    "is_holiday",
    "is_bonfire_day",
    "is_no_traffic_day",
    "season_fall",
    "season_spring",
    "season_summer",
    "season_winter",
    "dow_0",
    "dow_1",
    "dow_2",
    "dow_3",
    "dow_4",
    "dow_5",
    "dow_6",
    "month_1",
    "month_2",
    "month_3",
    "month_4",
    "month_5",
    "month_6",
    "month_7",
    "month_8",
    "month_9",
    "month_10",
    "month_11",
    "month_12",
    "rolling_mean_3h",
    "rolling_std_3h",
    "rolling_mean_6h",
    "rolling_std_6h",
    "rolling_mean_12h",
    "rolling_std_12h",
    "rolling_mean_24h",
    "rolling_std_24h",
    "rate_of_change",
]

LABEL_COLS = ["label_israel", "label_who", "label_zscore"]
META_COLS = ["timestamp", "station_id", "pollutant", "is_gap"]


def load_features() -> pd.DataFrame:
    """Load feature-engineered data."""
    df = pd.read_parquet(PROCESSED_DIR / "features.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def temporal_split(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split by row order (sorted by time): 60/20/20."""
    df = df.sort_values("timestamp")
    n = len(df)
    train_end = int(n * TRAIN_FRAC)
    val_end = int(n * (TRAIN_FRAC + VAL_FRAC))

    train = df.iloc[:train_end].copy()
    val = df.iloc[train_end:val_end].copy()
    test = df.iloc[val_end:].copy()
    return train, val, test


def normalize_features(
    train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, StandardScaler]:
    """Fit scaler on train only, transform all splits."""
    train[FEATURE_COLS] = train[FEATURE_COLS].fillna(0)
    val[FEATURE_COLS] = val[FEATURE_COLS].fillna(0)
    test[FEATURE_COLS] = test[FEATURE_COLS].fillna(0)

    scaler = StandardScaler()
    train[FEATURE_COLS] = scaler.fit_transform(train[FEATURE_COLS])
    val[FEATURE_COLS] = scaler.transform(val[FEATURE_COLS])
    test[FEATURE_COLS] = scaler.transform(test[FEATURE_COLS])
    return train, val, test, scaler


def print_summary(train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame) -> None:
    """Print split summary."""
    print("=" * 60)
    print("TRAIN / VAL / TEST SPLIT SUMMARY")
    print("=" * 60)

    for name, split in [("Train", train), ("Val", val), ("Test", test)]:
        t_min = split["timestamp"].min().date()
        t_max = split["timestamp"].max().date()
        gaps = split["is_gap"].sum()
        gap_pct = 100 * gaps / len(split)
        print(
            f"  {name:5s}: {len(split):>7,} rows | "
            f"{t_min} -> {t_max} | "
            f"gaps: {gaps} ({gap_pct:.1f}%)"
        )

    print(f"\n  Feature columns: {len(FEATURE_COLS)}")
    print(f"  Label columns: {LABEL_COLS}")

    print("\n  Anomaly counts per split:")
    for label in LABEL_COLS:
        counts = []
        for name, split in [("Train", train), ("Val", val), ("Test", test)]:
            counts.append(f"{name}={int(split[label].sum())}")
        print(f"    {label}: {', '.join(counts)}")


def main() -> None:
    print("Loading features...")
    df = load_features()

    print("Splitting by time...")
    train, val, test = temporal_split(df)

    print("Normalizing features...")
    train, val, test, scaler = normalize_features(train, val, test)

    print_summary(train, val, test)

    train.to_parquet(PROCESSED_DIR / "train.parquet", index=False)
    val.to_parquet(PROCESSED_DIR / "val.parquet", index=False)
    test.to_parquet(PROCESSED_DIR / "test.parquet", index=False)
    joblib.dump(scaler, PROCESSED_DIR / "scaler.joblib")

    print("\nSaved: train.parquet, val.parquet, test.parquet, scaler.joblib")
    print(f"  -> {PROCESSED_DIR}")


if __name__ == "__main__":
    main()
