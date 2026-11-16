"""XGBoost forecasting — predict threshold exceedance in next N hours.

Usage:
    python scripts/model_xgboost_forecast.py          # fast run with default params
    python scripts/model_xgboost_forecast.py --tune    # run hyperparameter tuning first
"""

import argparse
import itertools
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

from src.data.loader import PROCESSED_DIR

FIGURES_DIR = Path("results/figures")
MODELS_DIR = Path("results/models")

POLLUTANTS = ["no2", "o3", "co", "so2"]
HORIZONS = [1, 2, 3, 4, 6, 8, 12, 24]

POLLUTANT_LABEL = {
    "no2": "label_who",
    "o3": "label_who",
    "co": "label_zscore",
    "so2": "label_zscore",
}

DEFAULT_PARAMS = {
    "n_estimators": 300,
    "max_depth": 6,
    "learning_rate": 0.1,
    "min_child_weight": 1,
    "subsample": 0.7,
    "colsample_bytree": 0.9,
    "early_stopping_rounds": 30,
}

TUNE_GRID_MAX_DEPTH = [4, 6, 8, 10]
TUNE_GRID_LR = [0.01, 0.05, 0.1]
TUNE_GRID_MCW = [1, 5, 10]
TUNE_GRID_SS = [0.7, 0.9]
TUNE_GRID_CS = [0.7, 0.9]

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

LAG_HOURS = [1, 2, 3, 6, 12]

TRAIN_FRAC = 0.6
VAL_FRAC = 0.2


def load_features() -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED_DIR / "features.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def add_lag_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Add lagged value columns per station+pollutant group."""
    df = df.sort_values("timestamp")
    lag_cols: list[str] = []

    for lag in LAG_HOURS:
        col = f"value_lag_{lag}h"
        df[col] = df.groupby(["station_id", "pollutant"])["value"].shift(lag)
        lag_cols.append(col)

        col_diff = f"value_diff_{lag}h"
        df[col_diff] = df["value"] - df[col]
        lag_cols.append(col_diff)

    df[lag_cols] = df[lag_cols].fillna(0)
    return df, lag_cols


def create_forecast_target_fast(
    df: pd.DataFrame,
    horizon_hours: int,
    label_col: str = "label_who",
) -> pd.Series:
    """Vectorized: rolling backward from exceedance marks preceding rows."""
    df = df.sort_values("timestamp")
    target = pd.Series(0, index=df.index, dtype=int)

    for (_station, _pollutant), group in df.groupby(["station_id", "pollutant"]):
        group = group.sort_values("timestamp")
        timestamps = group["timestamp"].values
        labels = group[label_col].values
        idx = group.index

        exceedance_mask = labels == 1
        if not exceedance_mask.any():
            continue

        horizon_ns = np.timedelta64(horizon_hours, "h")
        for exc_pos in np.where(exceedance_mask)[0]:
            exc_time = timestamps[exc_pos]
            window_start = exc_time - horizon_ns
            preceding = (timestamps > window_start) & (timestamps < exc_time)
            target.loc[idx[preceding]] = 1

    return target


def temporal_split(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("timestamp")
    n = len(df)
    train_end = int(n * TRAIN_FRAC)
    val_end = int(n * (TRAIN_FRAC + VAL_FRAC))
    return df.iloc[:train_end].copy(), df.iloc[train_end:val_end].copy(), df.iloc[val_end:].copy()


def train_xgboost(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    params: dict | None = None,
) -> xgb.XGBClassifier:
    pos_count = y_train.sum()
    neg_count = len(y_train) - pos_count
    scale = neg_count / max(pos_count, 1)

    p = {**DEFAULT_PARAMS, **(params or {})}

    model = xgb.XGBClassifier(
        n_estimators=p["n_estimators"],
        max_depth=p["max_depth"],
        learning_rate=p["learning_rate"],
        min_child_weight=p["min_child_weight"],
        subsample=p["subsample"],
        colsample_bytree=p["colsample_bytree"],
        scale_pos_weight=scale,
        eval_metric="aucpr",
        early_stopping_rounds=p["early_stopping_rounds"],
        random_state=42,
        verbosity=0,
    )
    model.fit(
        x_train,
        y_train,
        eval_set=[(x_val, y_val)],
        verbose=False,
    )
    return model


def evaluate(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    label_name: str,
) -> dict:
    f1 = f1_score(y_true, y_pred, zero_division=0)
    precision = precision_score(y_true, y_pred, zero_division=0)
    recall = recall_score(y_true, y_pred, zero_division=0)
    cm = confusion_matrix(y_true, y_pred)

    print(f"\n  {label_name}")
    print(f"  F1={f1:.4f}  Precision={precision:.4f}  Recall={recall:.4f}")
    print(f"  Predicted: {y_pred.sum():,} | Actual: {y_true.sum():,}")
    print(f"  {cm}")
    return {"f1": f1, "precision": precision, "recall": recall, "cm": cm}


def find_best_threshold(
    y_true: np.ndarray,
    y_proba: np.ndarray,
) -> tuple[float, float]:
    """Search probability thresholds to maximize F1."""
    best_f1 = -1.0
    best_t = 0.5
    for t in np.arange(0.05, 0.80, 0.01):
        preds = (y_proba >= t).astype(int)
        f1 = f1_score(y_true, preds, zero_division=0)
        if f1 > best_f1:
            best_f1 = f1
            best_t = float(t)
    return best_t, best_f1


def tune_hyperparameters(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    x_train_tail: np.ndarray,
    y_train_tail: np.ndarray,
) -> dict:
    """Grid search over TUNE_GRID, return best params dict."""
    combos = list(
        itertools.product(
            TUNE_GRID_MAX_DEPTH,
            TUNE_GRID_LR,
            TUNE_GRID_MCW,
            TUNE_GRID_SS,
            TUNE_GRID_CS,
        )
    )
    print(f"  Tuning: {len(combos)} combinations...")

    pos = y_train.sum()
    scale = (len(y_train) - pos) / max(pos, 1)

    best_score = -1.0
    best_params: dict = {}
    for i, (md, lr, mcw, ss, cs) in enumerate(combos, 1):
        model = xgb.XGBClassifier(
            n_estimators=500,
            max_depth=md,
            learning_rate=lr,
            min_child_weight=mcw,
            subsample=ss,
            colsample_bytree=cs,
            scale_pos_weight=scale,
            eval_metric="aucpr",
            early_stopping_rounds=30,
            random_state=42,
            verbosity=0,
        )
        model.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)

        pv = model.predict_proba(x_val)[:, 1]
        _, vf1 = find_best_threshold(y_val, pv)

        pt = model.predict_proba(x_train_tail)[:, 1]
        _, tf1 = find_best_threshold(y_train_tail, pt)

        score = max(vf1, tf1)
        if score > best_score:
            best_score = score
            best_params = dict(
                max_depth=md,
                learning_rate=lr,
                min_child_weight=mcw,
                subsample=ss,
                colsample_bytree=cs,
                n_estimators=500,
                early_stopping_rounds=30,
            )

        if i % 24 == 0:
            print(f"    {i}/{len(combos)} — best so far: {best_score:.4f}")

    print(f"  Best params: {best_params} (score={best_score:.4f})")
    return best_params


def select_threshold(
    model: xgb.XGBClassifier,
    val_features: np.ndarray,
    y_val: np.ndarray,
    train_tail_features: np.ndarray,
    y_train_tail: np.ndarray,
) -> tuple[float, str]:
    """Pick the better threshold source (val or train-tail)."""
    proba_val = model.predict_proba(val_features)[:, 1]
    proba_tt = model.predict_proba(train_tail_features)[:, 1]

    best_t_val, best_f1_val = find_best_threshold(y_val, proba_val)
    best_t_tt, best_f1_tt = find_best_threshold(y_train_tail, proba_tt)

    if best_f1_val >= best_f1_tt:
        return best_t_val, f"val (t={best_t_val:.2f}, F1={best_f1_val:.3f})"
    return best_t_tt, f"train-tail (t={best_t_tt:.2f}, F1={best_f1_tt:.3f})"


def plot_results(
    all_results: dict[str, dict[int, dict]],
    split_name: str,
) -> Path:
    n_pollutants = len(all_results)
    horizons_in_results = list(next(iter(all_results.values())).keys())
    n_horizons = len(horizons_in_results)
    fig, axes = plt.subplots(
        n_pollutants,
        n_horizons,
        figsize=(5 * n_horizons, 4.5 * n_pollutants),
    )
    if n_pollutants == 1:
        axes = axes[np.newaxis, :]
    if n_horizons == 1:
        axes = axes[:, np.newaxis]
    fig.suptitle(
        f"XGBoost Forecasting — {split_name}",
        fontsize=16,
        fontweight="bold",
        y=1.02,
    )

    for row, (pollutant, horizon_results) in enumerate(all_results.items()):
        label_col = POLLUTANT_LABEL[pollutant]
        for col, (horizon, res) in enumerate(horizon_results.items()):
            ax = axes[row, col]
            cm = res["cm"]
            im = ax.imshow(cm, cmap="Purples", interpolation="nearest")
            ax.set_title(
                f"{pollutant.upper()} ({label_col}) — {horizon}h ahead\n"
                f"F1={res['f1']:.3f} | P={res['precision']:.3f} | R={res['recall']:.3f}",
                fontsize=10,
            )
            ax.set_xlabel("Predicted")
            ax.set_ylabel("Actual")
            ax.set_xticks([0, 1])
            ax.set_yticks([0, 1])
            ax.set_xticklabels(["Normal", "Exceedance"])
            ax.set_yticklabels(["Normal", "Exceedance"])
            for i in range(2):
                for j in range(2):
                    color = "white" if cm[i, j] > cm.max() / 2 else "black"
                    ax.text(
                        j,
                        i,
                        f"{cm[i, j]:,}",
                        ha="center",
                        va="center",
                        color=color,
                        fontsize=13,
                    )
            fig.colorbar(im, ax=ax)

    plt.tight_layout()
    path = FIGURES_DIR / f"xgboost_forecast_{split_name.lower()}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {path}")
    return path


def run_pollutant(
    df: pd.DataFrame,
    pollutant: str,
    lag_cols: list[str],
    do_tune: bool = False,
) -> tuple[dict, dict]:
    label_col = POLLUTANT_LABEL[pollutant]
    pdf = df[df["pollutant"] == pollutant].copy()
    train, val, test = temporal_split(pdf)
    train_tail = train.iloc[int(len(train) * 0.8) :]

    all_features = FEATURE_COLS + lag_cols
    print(f"  Target label: {label_col}")
    print(f"  Samples — train: {len(train):,}  val: {len(val):,}  test: {len(test):,}")
    print(f"  Features: {len(all_features)} ({len(FEATURE_COLS)} base + {len(lag_cols)} lag)")

    val_results: dict[int, dict] = {}
    test_results: dict[int, dict] = {}

    for horizon in HORIZONS:
        print(f"\n  --- Horizon: {horizon}h ---")

        print("  Creating target...", end=" ")
        y_train = create_forecast_target_fast(train, horizon, label_col)
        y_val = create_forecast_target_fast(val, horizon, label_col)
        y_test = create_forecast_target_fast(test, horizon, label_col)
        y_tt = create_forecast_target_fast(train_tail, horizon, label_col)
        print(f"train={y_train.sum():,}  val={y_val.sum():,}  test={y_test.sum():,} positives")

        if y_train.sum() < 10 or y_val.sum() < 5:
            print(f"  SKIPPED — not enough positives (train={y_train.sum()}, val={y_val.sum()})")
            continue

        x_train = train[all_features].values
        x_val = val[all_features].values
        x_test = test[all_features].values
        x_tt = train_tail[all_features].values

        params = None
        if do_tune:
            params = tune_hyperparameters(
                x_train,
                y_train.values,
                x_val,
                y_val.values,
                x_tt,
                y_tt.values,
            )

        print("  Training XGBoost...")
        model = train_xgboost(x_train, y_train.values, x_val, y_val.values, params)

        best_t, source = select_threshold(
            model,
            x_val,
            y_val.values,
            x_tt,
            y_tt.values,
        )
        print(f"  Threshold: {best_t:.2f} from {source}")

        proba_val = model.predict_proba(x_val)[:, 1]
        proba_test = model.predict_proba(x_test)[:, 1]
        pred_val = (proba_val >= best_t).astype(int)
        pred_test = (proba_test >= best_t).astype(int)

        print("\n  Validation:")
        val_results[horizon] = evaluate(y_val.values, pred_val, f"{horizon}h (t={best_t:.2f})")

        print("\n  Test:")
        test_results[horizon] = evaluate(y_test.values, pred_test, f"{horizon}h (t={best_t:.2f})")

        model_path = MODELS_DIR / f"xgboost_{pollutant}_{horizon}h.joblib"
        joblib.dump(model, model_path)
        if params:
            joblib.dump(params, MODELS_DIR / f"xgboost_{pollutant}_{horizon}h_params.joblib")

    return val_results, test_results


def main() -> None:
    parser = argparse.ArgumentParser(description="XGBoost exceedance forecasting")
    parser.add_argument("--tune", action="store_true", help="Run hyperparameter tuning")
    args = parser.parse_args()

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading features...")
    df = load_features()

    print("Adding lag features...")
    df, lag_cols = add_lag_features(df)
    print(f"  Added {len(lag_cols)} lag columns: {lag_cols}")

    if args.tune:
        print("\n*** HYPERPARAMETER TUNING ENABLED ***\n")

    all_val: dict[str, dict[int, dict]] = {}
    all_test: dict[str, dict[int, dict]] = {}

    for pollutant in POLLUTANTS:
        print(f"\n{'#' * 60}")
        print(f"  POLLUTANT: {pollutant.upper()}")
        print(f"{'#' * 60}")

        val_results, test_results = run_pollutant(df, pollutant, lag_cols, args.tune)
        all_val[pollutant] = val_results
        all_test[pollutant] = test_results

    if all_val:
        plot_results(all_val, "Validation")
    if all_test:
        plot_results(all_test, "Test")

    print("\n" + "=" * 70)
    print("SUMMARY — Test Results")
    print("=" * 70)
    print(
        f"{'Pollutant':<10} {'Label':<14} {'Horizon':<8} {'F1':<8} {'Precision':<10} {'Recall':<8}"
    )
    print("-" * 70)
    for pollutant, horizon_results in all_test.items():
        label_col = POLLUTANT_LABEL[pollutant]
        for horizon, res in horizon_results.items():
            print(
                f"{pollutant.upper():<10} {label_col:<14} {horizon}h{'':<5} "
                f"{res['f1']:.3f}   {res['precision']:.3f}     {res['recall']:.3f}"
            )

    print("\nDone.")


if __name__ == "__main__":
    main()
