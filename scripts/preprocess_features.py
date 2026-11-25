"""Feature engineering: time features, rolling stats, anomaly labels."""

from datetime import date

import pandas as pd

from src.data.loader import (
    ISRAEL_THRESHOLDS,
    PROCESSED_DIR,
    WHO_THRESHOLDS,
)

ROLLING_WINDOWS = [3, 6, 12, 24]

# Israeli holidays/events that affect air quality (Aug 2017 – Apr 2019)
SPECIAL_DAYS: dict[str, list[date]] = {
    "yom_kippur": [date(2017, 9, 30), date(2018, 9, 19)],
    "lag_baomer": [date(2018, 5, 3)],
    "independence_day": [date(2018, 4, 19)],
    "rosh_hashana": [
        date(2017, 9, 21),
        date(2017, 9, 22),
        date(2018, 9, 10),
        date(2018, 9, 11),
    ],
    "sukkot": [
        date(2017, 10, 5),
        date(2017, 10, 6),
        date(2018, 9, 24),
        date(2018, 9, 25),
    ],
    "passover": [
        date(2018, 3, 31),
        date(2018, 4, 6),
        date(2019, 4, 20),
        date(2019, 4, 26),
    ],
    "shavuot": [date(2018, 5, 20)],
}


def load_clean_data() -> pd.DataFrame:
    """Load cleaned measurements."""
    df = pd.read_parquet(PROCESSED_DIR / "measurements_clean.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add temporal features from timestamp."""
    df["hour"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["month"] = df["timestamp"].dt.month
    df["is_weekend"] = df["day_of_week"].isin([4, 5]).astype(int)

    month_to_season = {
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
    df["season"] = df["month"].map(month_to_season)

    season_dummies = pd.get_dummies(df["season"], prefix="season").astype(int)
    dow_dummies = pd.get_dummies(df["day_of_week"], prefix="dow").astype(int)
    month_dummies = pd.get_dummies(df["month"], prefix="month").astype(int)

    df = pd.concat([df, season_dummies, dow_dummies, month_dummies], axis=1)
    df = df.drop(columns=["season", "day_of_week", "month"])

    df = _add_special_days(df)
    return df


def _add_special_days(df: pd.DataFrame) -> pd.DataFrame:
    """Add binary features for Israeli holidays and events."""
    df_date = df["timestamp"].dt.date
    all_special = set()
    for dates in SPECIAL_DAYS.values():
        all_special.update(dates)

    df["is_holiday"] = df_date.isin(all_special).astype(int)
    df["is_bonfire_day"] = df_date.isin(SPECIAL_DAYS["lag_baomer"]).astype(int)
    df["is_no_traffic_day"] = df_date.isin(SPECIAL_DAYS["yom_kippur"]).astype(int)
    return df


def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add rolling mean and std for each window size."""
    results = []

    for (_station_id, _pollutant), group in df.groupby(["station_id", "pollutant"]):
        group = group.sort_values("timestamp").copy()

        for window in ROLLING_WINDOWS:
            col_mean = f"rolling_mean_{window}h"
            col_std = f"rolling_std_{window}h"
            group[col_mean] = group["value"].rolling(window, min_periods=1).mean()
            group[col_std] = group["value"].rolling(window, min_periods=1).std()

        group["rate_of_change"] = group["value"].diff()

        gap_mask = group["is_gap"].fillna(False)
        rolling_cols = [
            c for c in group.columns if c.startswith("rolling_") or c == "rate_of_change"
        ]
        for col in rolling_cols:
            group.loc[gap_mask, col] = float("nan")

        results.append(group)

    return pd.concat(results, ignore_index=True)


def add_anomaly_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Add binary anomaly labels based on different criteria."""
    df["label_israel"] = 0
    for pollutant, threshold in ISRAEL_THRESHOLDS.items():
        mask = (df["pollutant"] == pollutant) & (df["value"] > threshold)
        df.loc[mask, "label_israel"] = 1

    df["label_who"] = 0
    results = []
    for (_station_id, pollutant), group in df.groupby(["station_id", "pollutant"]):
        if pollutant not in WHO_THRESHOLDS:
            continue
        group = group.sort_values("timestamp").copy()
        who = WHO_THRESHOLDS[pollutant]
        window = who["window_hours"]
        rolling_avg = group["value"].rolling(window, min_periods=max(1, window // 2)).mean()
        group.loc[rolling_avg > who["value"], "label_who"] = 1
        results.append(group)
    df = pd.concat(results, ignore_index=True)

    df["label_zscore"] = 0
    for (_station_id, _pollutant), group in df.groupby(["station_id", "pollutant"]):
        mean = group["value"].mean()
        std = group["value"].std()
        if std > 0:
            zscore = ((group["value"] - mean) / std).abs()
            df.loc[zscore.index[zscore > 3], "label_zscore"] = 1

    return df


def print_summary(df: pd.DataFrame) -> None:
    """Print feature engineering summary."""
    print("=" * 60)
    print("FEATURE ENGINEERING SUMMARY")
    print("=" * 60)
    print(f"  Total rows: {len(df):,}")
    print(f"  Features:   {len(df.columns)}")
    print(f"  Columns:    {list(df.columns)}")

    print("\n  Anomaly labels:")
    for label in ["label_israel", "label_who", "label_zscore"]:
        count = df[label].sum()
        pct = 100 * count / len(df)
        print(f"    {label}: {count:,} ({pct:.2f}%)")

    nan_cols = df.isnull().sum()
    nan_cols = nan_cols[nan_cols > 0]
    if len(nan_cols) > 0:
        print(f"\n  Columns with NaN: {dict(nan_cols)}")


def main() -> None:
    print("Loading clean data...")
    df = load_clean_data()

    print("Adding time features...")
    df = add_time_features(df)

    print("Adding rolling features...")
    df = add_rolling_features(df)

    print("Adding anomaly labels...")
    df = add_anomaly_labels(df)

    print_summary(df)

    out_path = PROCESSED_DIR / "features.parquet"
    df.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
