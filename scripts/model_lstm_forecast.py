"""LSTM forecasting — predict threshold exceedance in next N hours.

Usage:
    python scripts/model_lstm_forecast.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, Dataset

from src.data.loader import PROCESSED_DIR

FIGURES_DIR = Path("results/figures")
MODELS_DIR = Path("results/models")

POLLUTANTS = ["no2", "o3"]
HORIZONS = [1, 2, 4, 6, 12, 24]

POLLUTANT_LABEL: dict[str, str] = {
    "no2": "label_who",
    "o3": "label_who",
}

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

SEQ_LEN = 24
HIDDEN_SIZE = 64
NUM_LAYERS = 2
DROPOUT = 0.3
BATCH_SIZE = 256
LR = 0.0005
MAX_EPOCHS = 80
PATIENCE = 10
TRAIN_FRAC = 0.6
VAL_FRAC = 0.2


class ForecastDataset(Dataset):  # type: ignore[type-arg]
    def __init__(self, features: np.ndarray, targets: np.ndarray, seq_len: int):
        self.features = features
        self.targets = targets
        self.seq_len = seq_len

    def __len__(self) -> int:
        return len(self.features) - self.seq_len

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        x = self.features[idx : idx + self.seq_len]
        y = self.targets[idx + self.seq_len - 1]
        return torch.tensor(x, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)


class LSTMClassifier(nn.Module):
    def __init__(self, input_size: int, hidden_size: int, num_layers: int, dropout: float):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]
        out = self.dropout(last_hidden)
        return self.fc(out).squeeze(-1)


def load_features() -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED_DIR / "features.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def create_forecast_target(
    df: pd.DataFrame,
    horizon_hours: int,
    label_col: str,
) -> pd.Series:
    df = df.sort_values("timestamp")
    target = pd.Series(0, index=df.index, dtype=int)

    for (_, _), group in df.groupby(["station_id", "pollutant"]):
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
            preceding = (timestamps > exc_time - horizon_ns) & (timestamps < exc_time)
            target.loc[idx[preceding]] = 1

    return target


def temporal_split(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("timestamp")
    n = len(df)
    train_end = int(n * TRAIN_FRAC)
    val_end = int(n * (TRAIN_FRAC + VAL_FRAC))
    return (
        df.iloc[:train_end].copy(),
        df.iloc[train_end:val_end].copy(),
        df.iloc[val_end:].copy(),
    )


def find_best_threshold(
    y_true: np.ndarray,
    y_proba: np.ndarray,
) -> tuple[float, float]:
    best_f1, best_t = -1.0, 0.5
    for t in np.arange(0.05, 0.80, 0.01):
        preds = (y_proba >= t).astype(int)
        f1 = f1_score(y_true, preds, zero_division=0)
        if f1 > best_f1:
            best_f1 = f1
            best_t = float(t)
    return best_t, best_f1


def train_lstm(
    train_loader: DataLoader,  # type: ignore[type-arg]
    val_loader: DataLoader,  # type: ignore[type-arg]
    input_size: int,
    pos_weight: float,
) -> LSTMClassifier:
    model = LSTMClassifier(input_size, HIDDEN_SIZE, NUM_LAYERS, DROPOUT)
    criterion = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos_weight))
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=5
    )

    best_val_loss = float("inf")
    best_state = model.state_dict()
    epochs_no_improve = 0

    for epoch in range(MAX_EPOCHS):
        model.train()
        train_loss = 0.0
        for x_batch, y_batch in train_loader:
            optimizer.zero_grad()
            logits = model(x_batch)
            loss = criterion(logits, y_batch)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item() * len(y_batch)
        train_loss /= len(train_loader.dataset)

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for x_batch, y_batch in val_loader:
                logits = model(x_batch)
                loss = criterion(logits, y_batch)
                val_loss += loss.item() * len(y_batch)
        val_loss /= len(val_loader.dataset)

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1

        if (epoch + 1) % 10 == 0:
            print(
                f"    Epoch {epoch + 1}/{MAX_EPOCHS}  "
                f"train_loss={train_loss:.4f}  val_loss={val_loss:.4f}"
            )

        if epochs_no_improve >= PATIENCE:
            print(f"    Early stop at epoch {epoch + 1}")
            break

    model.load_state_dict(best_state)
    return model


def predict_proba(
    model: LSTMClassifier,
    loader: DataLoader,  # type: ignore[type-arg]
) -> np.ndarray:
    model.eval()
    all_proba = []
    with torch.no_grad():
        for x_batch, _ in loader:
            logits = model(x_batch)
            proba = torch.sigmoid(logits).numpy()
            all_proba.append(proba)
    return np.concatenate(all_proba)


def get_targets_for_loader(
    loader: DataLoader,  # type: ignore[type-arg]
) -> np.ndarray:
    all_y = []
    for _, y_batch in loader:
        all_y.append(y_batch.numpy())
    return np.concatenate(all_y)


def run_pollutant(
    pollutant: str,
    df: pd.DataFrame,
    feature_cols: list[str],
) -> dict[int, dict]:
    label_col = POLLUTANT_LABEL[pollutant]
    pdf = df[df["pollutant"] == pollutant].copy()
    train, val, test = temporal_split(pdf)
    train_tail = train.iloc[int(len(train) * 0.8) :]

    scaler = StandardScaler()
    train_filled = train[feature_cols].fillna(0)
    scaler.fit(train_filled)
    train_feat = np.nan_to_num(scaler.transform(train_filled), nan=0.0)
    val_feat = np.nan_to_num(scaler.transform(val[feature_cols].fillna(0)), nan=0.0)
    test_feat = np.nan_to_num(scaler.transform(test[feature_cols].fillna(0)), nan=0.0)
    tt_feat = np.nan_to_num(scaler.transform(train_tail[feature_cols].fillna(0)), nan=0.0)

    input_size = len(feature_cols)
    results: dict[int, dict] = {}

    for horizon in HORIZONS:
        print(f"\n  --- {pollutant.upper()} {horizon}h ---")

        y_train = create_forecast_target(train, horizon, label_col).values
        y_val = create_forecast_target(val, horizon, label_col).values
        y_test = create_forecast_target(test, horizon, label_col).values
        y_tt = create_forecast_target(train_tail, horizon, label_col).values

        train_pos = y_train.sum()
        if train_pos < 10:
            print(f"    Skip: only {train_pos} positive samples in train")
            continue
        val_pos = y_val.sum()
        if val_pos < 5:
            print(f"    Skip: only {val_pos} positive samples in val")
            continue

        pos_weight = min((len(y_train) - train_pos) / max(train_pos, 1), 20.0)

        train_ds = ForecastDataset(train_feat, y_train, SEQ_LEN)
        val_ds = ForecastDataset(val_feat, y_val, SEQ_LEN)
        test_ds = ForecastDataset(test_feat, y_test, SEQ_LEN)
        tt_ds = ForecastDataset(tt_feat, y_tt, SEQ_LEN)

        train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
        val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE)
        test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE)
        tt_loader = DataLoader(tt_ds, batch_size=BATCH_SIZE)

        pct = 100 * train_pos / len(y_train)
        print(f"    Train: {len(train_ds):,} seqs, {train_pos:,} pos ({pct:.1f}%)")
        print(f"    Val: {len(val_ds):,} seqs  |  Test: {len(test_ds):,} seqs")

        model = train_lstm(train_loader, val_loader, input_size, pos_weight)

        proba_val = predict_proba(model, val_loader)
        proba_test = predict_proba(model, test_loader)
        proba_tt = predict_proba(model, tt_loader)

        y_val_seq = get_targets_for_loader(val_loader)
        y_test_seq = get_targets_for_loader(test_loader)
        y_tt_seq = get_targets_for_loader(tt_loader)

        t_val, f1_val = find_best_threshold(y_val_seq, proba_val)
        t_tt, f1_tt = find_best_threshold(y_tt_seq, proba_tt)
        best_t = t_val if f1_val >= f1_tt else t_tt
        source = "val" if f1_val >= f1_tt else "train-tail"

        pred_test = (proba_test >= best_t).astype(int)
        test_f1 = f1_score(y_test_seq, pred_test, zero_division=0)
        test_p = precision_score(y_test_seq, pred_test, zero_division=0)
        test_r = recall_score(y_test_seq, pred_test, zero_division=0)
        cm = confusion_matrix(y_test_seq, pred_test)

        print(f"    Threshold: {best_t:.2f} ({source})")
        print(f"    Test: F1={test_f1:.4f}  P={test_p:.4f}  R={test_r:.4f}")
        print(f"    {cm}")

        model_path = MODELS_DIR / f"lstm_{pollutant}_{horizon}h.pt"
        torch.save(model.state_dict(), model_path)

        results[horizon] = {
            "f1": test_f1,
            "precision": test_p,
            "recall": test_r,
            "cm": cm,
            "threshold": best_t,
            "source": source,
        }

        # Val results
        pred_val = (proba_val >= best_t).astype(int)
        val_f1 = f1_score(y_val_seq, pred_val, zero_division=0)
        val_p = precision_score(y_val_seq, pred_val, zero_division=0)
        val_r = recall_score(y_val_seq, pred_val, zero_division=0)
        results[horizon]["val_f1"] = val_f1
        results[horizon]["val_precision"] = val_p
        results[horizon]["val_recall"] = val_r
        results[horizon]["val_cm"] = confusion_matrix(y_val_seq, pred_val)

    return results


def plot_results(
    all_results: dict[str, dict[int, dict]],
    split_name: str,
) -> Path:
    n_pollutants = len(all_results)
    max_horizons = max(len(hr) for hr in all_results.values())
    fig, axes = plt.subplots(
        n_pollutants,
        max_horizons,
        figsize=(5 * max_horizons, 4.5 * n_pollutants),
    )
    if n_pollutants == 1:
        axes = axes[np.newaxis, :]
    if max_horizons == 1:
        axes = axes[:, np.newaxis]

    fig.suptitle(
        f"LSTM Forecasting — {split_name}",
        fontsize=16,
        fontweight="bold",
        y=1.02,
    )

    for row, (pollutant, horizon_results) in enumerate(all_results.items()):
        label_col = POLLUTANT_LABEL[pollutant]
        for col, (horizon, res) in enumerate(horizon_results.items()):
            ax = axes[row, col]
            cm_key = "val_cm" if "Val" in split_name else "cm"
            cm_data = res[cm_key]
            im = ax.imshow(cm_data, cmap="Purples", interpolation="nearest")
            f1_key = "val_f1" if "Val" in split_name else "f1"
            p_key = "val_precision" if "Val" in split_name else "precision"
            r_key = "val_recall" if "Val" in split_name else "recall"
            ax.set_title(
                f"{pollutant.upper()} ({label_col}) — {horizon}h\n"
                f"F1={res[f1_key]:.3f}  P={res[p_key]:.3f}  R={res[r_key]:.3f}",
                fontsize=10,
            )
            ax.set_xlabel("Predicted")
            ax.set_ylabel("Actual")
            ax.set_xticks([0, 1])
            ax.set_yticks([0, 1])
            ax.set_xticklabels(["Normal", "Alert"])
            ax.set_yticklabels(["Normal", "Alert"])
            for i in range(2):
                for j in range(2):
                    val = cm_data[i, j]
                    color = "white" if val > cm_data.max() * 0.5 else "black"
                    ax.text(j, i, f"{val:,}", ha="center", va="center", color=color)
            fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

        for col in range(len(horizon_results), max_horizons):
            axes[row, col].set_visible(False)

    fig.tight_layout()
    path = FIGURES_DIR / f"lstm_forecast_{split_name.lower().replace(' ', '_')}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved: {path}")
    return path


def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    df = load_features()
    feature_cols = FEATURE_COLS

    all_test_results: dict[str, dict[int, dict]] = {}

    for pollutant in POLLUTANTS:
        print(f"\n{'=' * 60}")
        print(f"  {pollutant.upper()} — {POLLUTANT_LABEL[pollutant]}")
        print(f"{'=' * 60}")
        results = run_pollutant(pollutant, df, feature_cols)
        if results:
            all_test_results[pollutant] = results

    if all_test_results:
        plot_results(all_test_results, "Test")
        plot_results(all_test_results, "Validation")

    print(f"\n{'=' * 60}")
    print("FINAL SUMMARY — LSTM Forecasting")
    print(f"{'=' * 60}")
    print(f"{'Poll':<6} {'H':<5} {'F1':<8} {'P':<8} {'R':<8} {'Thr':<6} {'Src'}")
    print("-" * 55)
    for pollutant, horizon_results in all_test_results.items():
        for horizon, res in horizon_results.items():
            print(
                f"{pollutant.upper():<6} {horizon}h{'':<3} "
                f"{res['f1']:.4f}  {res['precision']:.4f}  {res['recall']:.4f}  "
                f"{res['threshold']:.2f}   {res['source']}"
            )

    print("\nDone.")


if __name__ == "__main__":
    main()
