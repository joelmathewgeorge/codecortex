"""
Shared data layer for the NASA C-MAPSS turbofan degradation dataset.

Both training and inference import from here, so the feature engineering is defined
exactly once. If train and serve computed features differently the model would score
live telemetry against a different feature space than it learned, which produces
confident nonsense.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

# Sensor readings stop carrying information about failure beyond this horizon: an engine
# at 200 cycles from failure looks identical to one at 300. Capping the label stops the
# model from burning capacity trying to separate two indistinguishable states, and is the
# standard piecewise-linear RUL target used on this dataset.
RUL_CAP = 125

SETTING_COLS = ["setting1", "setting2", "setting3"]
SENSOR_COLS = [f"sensor{i}" for i in range(1, 22)]
RAW_COLS = SETTING_COLS + SENSOR_COLS

# Rolling window lengths in cycles. The short window tracks the current state, the long
# window tracks the established trend; the gap between them is the degradation signal.
SHORT_WINDOW = 5
LONG_WINDOW = 20

DEFAULT_DATASET_ROOT = Path(
    r"C:\Users\rohit\Downloads\Datasets\01_NASA_CMAPSS_predictive_maintenance\CMAPSSData"
)


def dataset_root() -> Path:
    """Resolve the C-MAPSS directory, allowing an env override for other machines."""
    return Path(os.environ.get("CMAPSS_DIR", DEFAULT_DATASET_ROOT))


def load_subset(subset: str, split: str, root: Path | None = None) -> pd.DataFrame:
    """
    Load one C-MAPSS file.

    Args:
        subset: "FD001" through "FD004"
        split: "train" or "test"
        root: directory holding the C-MAPSS text files

    Returns:
        DataFrame with columns unit, cycle, setting1-3, sensor1-21, plus a `subset` tag.
    """
    root = root or dataset_root()
    path = root / f"{split}_{subset}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Could not find {path}. Set the CMAPSS_DIR environment variable to the "
            "directory containing train_FD001.txt."
        )

    # The files are space separated and several rows carry trailing whitespace, which
    # pandas would otherwise read as two phantom all-NaN columns.
    df = pd.read_csv(path, sep=r"\s+", header=None, engine="python")
    df = df.dropna(axis=1, how="all")
    df.columns = ["unit", "cycle"] + RAW_COLS
    df["subset"] = subset

    # Engine ids restart at 1 in every subset, so they must be namespaced before the
    # subsets are concatenated or engines from different fleets would merge into one.
    df["uid"] = subset + "_" + df["unit"].astype(str)
    return df.sort_values(["uid", "cycle"]).reset_index(drop=True)


def load_true_rul(subset: str, root: Path | None = None) -> pd.Series:
    """Load ground-truth RUL for a test subset, indexed by engine uid."""
    root = root or dataset_root()
    path = root / f"RUL_{subset}.txt"
    values = pd.read_csv(path, sep=r"\s+", header=None).iloc[:, 0]
    index = [f"{subset}_{i}" for i in range(1, len(values) + 1)]
    return pd.Series(values.to_numpy(), index=index, name="true_rul")


def add_training_rul(df: pd.DataFrame) -> pd.DataFrame:
    """
    Label each row with capped RUL.

    Training engines run to failure, so the final recorded cycle is the failure point and
    RUL is simply how many cycles remain until it.
    """
    df = df.copy()
    failure_cycle = df.groupby("uid")["cycle"].transform("max")
    df["rul"] = (failure_cycle - df["cycle"]).clip(upper=RUL_CAP)
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Turn raw per-cycle readings into features describing each engine's trajectory.

    A single snapshot cannot distinguish a healthy engine that naturally runs hot from a
    degrading one, because engines leave the factory with different baselines. What
    separates them is movement over time, so alongside the raw values we derive:

      - rolling mean, to suppress the sensor noise the dataset is documented to contain
      - rolling std, since erratic readings themselves indicate wear
      - drift from the engine's own first cycle, which cancels its individual baseline
      - short-window minus long-window mean, a cheap slope estimate

    Every window uses min_periods=1 so a partially filled window is computed the same way
    during training and during live streaming. That keeps a freshly launched drone with
    two cycles of history on the same footing as cycle 2 of a training engine.
    """
    df = df.sort_values(["uid", "cycle"]).reset_index(drop=True)
    grouped = df.groupby("uid", sort=False)

    features = {"cycle": df["cycle"]}
    for col in RAW_COLS:
        series = df[col]
        short_mean = grouped[col].transform(
            lambda s: s.rolling(SHORT_WINDOW, min_periods=1).mean()
        )
        long_mean = grouped[col].transform(
            lambda s: s.rolling(LONG_WINDOW, min_periods=1).mean()
        )
        short_std = grouped[col].transform(
            lambda s: s.rolling(SHORT_WINDOW, min_periods=1).std()
        )

        features[col] = series
        features[f"{col}_mean{SHORT_WINDOW}"] = short_mean
        features[f"{col}_mean{LONG_WINDOW}"] = long_mean
        # A window of one cycle has no spread; 0 is the truthful value, not missing data.
        features[f"{col}_std{SHORT_WINDOW}"] = short_std.fillna(0.0)
        features[f"{col}_drift"] = series - grouped[col].transform("first")
        features[f"{col}_trend"] = short_mean - long_mean

    return pd.DataFrame(features, index=df.index)


def drop_constant_columns(X: pd.DataFrame, tol: float = 1e-8) -> list[str]:
    """
    Identify columns that never vary and therefore cannot explain anything.

    Several C-MAPSS sensors are logged at a fixed value for an entire subset. Keeping them
    only dilutes the random feature sampling each tree performs.
    """
    keep = [c for c in X.columns if float(X[c].std(skipna=True) or 0.0) > tol]
    return keep


def rul_to_health(rul: np.ndarray | float) -> np.ndarray | float:
    """
    Map predicted RUL in cycles onto a 0-100 health score.

    The scale is anchored to RUL_CAP, the same horizon the model was trained against, so
    100 means "at or beyond the furthest point the data can distinguish" rather than an
    invented maximum lifespan.
    """
    health = np.clip(np.asarray(rul, dtype=float) / RUL_CAP * 100.0, 0.0, 100.0)
    return float(health) if np.isscalar(rul) or health.ndim == 0 else health


def health_status(health: float) -> str:
    """Bucket a health score into an operational recommendation."""
    if health >= 75:
        return "healthy"
    if health >= 50:
        return "monitor"
    if health >= 25:
        return "service_soon"
    return "ground_now"
