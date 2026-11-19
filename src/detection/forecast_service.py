"""Real-time forecast service — loads XGBoost models, runs inference on live data."""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import joblib
import numpy as np
import pandas as pd
import structlog

if TYPE_CHECKING:
    import xgboost as xgb

from src.schemas.anomaly import AnomalyEvent, DetectionMethod, Pollutant, Severity

logger = structlog.get_logger(__name__)

MODELS_DIR = Path("results/models")

ALERT_HORIZONS = [1, 2, 4, 6]

POLLUTANT_ENUM = {
    "no2": Pollutant.NO2,
    "o3": Pollutant.O3,
    "co": Pollutant.CO,
    "so2": Pollutant.SO2,
}

SEVERITY_BY_HORIZON = {
    1: Severity.CRITICAL,
    2: Severity.HIGH,
    4: Severity.MEDIUM,
    6: Severity.MEDIUM,
}


class ForecastModel:
    """A loaded XGBoost model with its threshold and feature list."""

    def __init__(self, pollutant: str, horizon: int) -> None:
        self.pollutant = pollutant
        self.horizon = horizon

        model_path = MODELS_DIR / f"xgboost_{pollutant}_{horizon}h.joblib"
        meta_path = MODELS_DIR / f"xgboost_{pollutant}_{horizon}h_meta.joblib"

        self.model: xgb.XGBClassifier = joblib.load(model_path)  # type: ignore[name-defined]

        if meta_path.exists():
            meta = joblib.load(meta_path)
            self.threshold: float = meta["threshold"]
            self.features: list[str] = meta["features"]
        else:
            self.threshold = 0.5
            self.features = []

        logger.info(
            "loaded_model",
            pollutant=pollutant,
            horizon=horizon,
            threshold=self.threshold,
        )

    def predict(self, features: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        cols = self.features if self.features else features.columns.tolist()
        x = features[cols].values
        proba = self.model.predict_proba(x)[:, 1]
        preds = (proba >= self.threshold).astype(int)
        return preds, proba


class ForecastService:
    """Runs all forecast models on incoming data and emits anomaly events."""

    def __init__(
        self,
        pollutants: list[str] | None = None,
        horizons: list[int] | None = None,
    ) -> None:
        self.pollutants = pollutants or ["no2", "o3"]
        self.horizons = horizons or ALERT_HORIZONS
        self.models: dict[tuple[str, int], ForecastModel] = {}
        self._load_models()

    def _load_models(self) -> None:
        for pollutant in self.pollutants:
            for horizon in self.horizons:
                model_path = MODELS_DIR / f"xgboost_{pollutant}_{horizon}h.joblib"
                if not model_path.exists():
                    logger.warning("model_not_found", pollutant=pollutant, horizon=horizon)
                    continue
                self.models[(pollutant, horizon)] = ForecastModel(pollutant, horizon)
        logger.info("forecast_service_ready", models_loaded=len(self.models))

    def run_inference(
        self,
        features_df: pd.DataFrame,
        stations_meta: dict[str, dict],
    ) -> list[AnomalyEvent]:
        events: list[AnomalyEvent] = []

        for (pollutant, horizon), model in self.models.items():
            pdf = features_df[features_df["pollutant"] == pollutant]
            if pdf.empty:
                continue

            preds, probas = model.predict(pdf)

            alert_mask = preds == 1
            if not alert_mask.any():
                continue

            alert_rows = pdf[alert_mask]
            alert_probas = probas[alert_mask]

            for (_, row), proba in zip(alert_rows.iterrows(), alert_probas, strict=False):
                sid = str(row["station_id"])
                meta = stations_meta.get(sid, {})

                events.append(
                    AnomalyEvent(
                        event_id=f"fc-{uuid.uuid4().hex[:12]}",
                        station_id=sid,
                        station_name=meta.get("name", sid),
                        timestamp=datetime.now(timezone.utc),
                        pollutant=POLLUTANT_ENUM[pollutant],
                        value=float(row.get("value", 0)),
                        baseline_value=float(row.get("rolling_mean_24h", 0)),
                        anomaly_score=float(proba),
                        severity=SEVERITY_BY_HORIZON.get(horizon, Severity.MEDIUM),
                        detection_method=DetectionMethod.ENSEMBLE,
                        latitude=meta.get("latitude", 0.0),
                        longitude=meta.get("longitude", 0.0),
                    )
                )

        logger.info("inference_complete", alerts=len(events))
        return events
