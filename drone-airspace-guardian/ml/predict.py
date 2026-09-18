"""
Drone health inference.

Public surface:
    predict_health(sensor_row) -> float          health score 0-100
    HealthMonitor                                stateful, per-drone, recommended
    simulate_drone_telemetry(...)                stand-in telemetry for demos and tests

Why there are two prediction paths
----------------------------------
Degradation is a trend, not a value. Engines leave the factory with different baselines, so
one isolated reading cannot say whether a warm engine is failing or simply runs warm. The
model was therefore trained on rolling statistics and drift from each engine's own first
cycle.

`HealthMonitor` keeps that history and is what the backend should use for a live feed.
`predict_health` accepts a lone row because the interface calls for it; with no history the
rolling windows collapse to the single row and drift is zero, which is exactly the feature
pattern the model saw for cycle-1 rows during training. It is a valid input, but it carries
less evidence, so it reads optimistically. Feed history when you have it.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from cmapss import (
    LONG_WINDOW,
    RAW_COLS,
    build_features,
    health_status,
    rul_to_health,
)

MODEL_PATH = Path(__file__).with_name("rul_model.joblib")

_bundle = joblib.load(MODEL_PATH)
_model = _bundle["model"]
_feature_cols = _bundle["feature_cols"]
RUL_CAP = _bundle["rul_cap"]
MODEL_NAME = _bundle["model_name"]


# Healthy mean, healthy standard deviation, and total drift from healthy to worn out, per
# channel. Measured from the first and last 20 cycles of the real C-MAPSS FD001 training
# engines so simulated telemetry lands in the range the model was trained on. Channels with
# zero variance are constant in the real data and are held constant here too.
_SENSOR_PROFILE: dict[str, tuple[float, float, float]] = {
    "setting1": (0.0, 0.0022, 0.0),
    "setting2": (0.0, 0.0003, 0.0),
    "setting3": (100.0, 0.0, 0.0),
    "sensor1": (518.67, 0.0, 0.0),
    "sensor2": (642.3808, 0.3832, 1.1037),
    "sensor3": (1586.8398, 4.5839, 13.2064),
    "sensor4": (1402.7583, 5.9364, 22.1888),
    "sensor5": (14.62, 0.0, 0.0),
    "sensor6": (21.6095, 0.0021, 0.0005),
    "sensor7": (553.9506, 0.6236, -2.1101),
    "sensor8": (2388.0584, 0.0554, 0.1454),
    "sensor9": (9056.0069, 8.3512, 35.2219),
    "sensor10": (1.3, 0.0, 0.0),
    "sensor11": (47.3525, 0.1788, 0.6781),
    "sensor12": (521.9099, 0.5074, -1.7954),
    "sensor13": (2388.0557, 0.0548, 0.1484),
    "sensor14": (8137.3729, 7.8701, 24.6539),
    "sensor15": (8.4183, 0.0266, 0.0881),
    "sensor16": (0.03, 0.0, 0.0),
    "sensor17": (392.2605, 1.1469, 3.4335),
    "sensor18": (2388.0, 0.0, 0.0),
    "sensor19": (100.0, 0.0, 0.0),
    "sensor20": (38.9328, 0.1299, -0.415),
    "sensor21": (23.3601, 0.0798, -0.2514),
}


def _frame_from_history(history: list[dict]) -> pd.DataFrame:
    """Assemble a history of readings into the frame shape build_features expects."""
    frame = pd.DataFrame(history)
    missing = [c for c in RAW_COLS if c not in frame.columns]
    if missing:
        raise ValueError(f"Telemetry is missing required channels: {missing}")
    if "cycle" not in frame.columns:
        raise ValueError("Telemetry must include a 'cycle' value (flight count).")
    frame["uid"] = "live"
    return frame


def _predict_rul(history: list[dict]) -> float:
    """Predict remaining cycles from the newest reading, informed by prior readings."""
    frame = _frame_from_history(history)
    features = build_features(frame)
    latest = features.iloc[[-1]].reindex(columns=_feature_cols, fill_value=0.0)
    rul = float(_model.predict(latest)[0])
    return float(np.clip(rul, 0.0, RUL_CAP))


def predict_health(sensor_row: dict) -> float:
    """
    Score a single telemetry reading from 0 (failed) to 100 (healthy).

    Args:
        sensor_row: mapping containing 'cycle', 'setting1'-'setting3' and
            'sensor1'-'sensor21'.

    Returns:
        Health score rounded to one decimal place.

    For a live feed prefer HealthMonitor, which retains history and so can see trends.
    """
    return round(rul_to_health(_predict_rul([dict(sensor_row)])), 1)


def predict_rul(sensor_row: dict) -> float:
    """Remaining useful life in cycles for a single reading, saturating at RUL_CAP."""
    return round(_predict_rul([dict(sensor_row)]), 1)


class HealthMonitor:
    """
    Tracks one drone across its flight history and scores each new reading in context.

    Usage:
        monitor = HealthMonitor(drone_id="dr-01")
        for reading in telemetry_stream:
            result = monitor.update(reading)
            print(result["health"], result["status"])
    """

    def __init__(self, drone_id: str = "drone") -> None:
        self.drone_id = drone_id
        self._history: list[dict] = []

    def update(self, sensor_row: dict) -> dict:
        """Record a reading and return the resulting health assessment."""
        self._history.append(dict(sensor_row))
        self._trim()

        rul = _predict_rul(self._history)
        health = rul_to_health(rul)
        return {
            "drone_id": self.drone_id,
            "cycle": sensor_row.get("cycle"),
            "rul_cycles": round(rul, 1),
            "health": round(health, 1),
            "status": health_status(health),
            "history_length": len(self._history),
        }

    def _trim(self) -> None:
        """
        Bound memory without changing any feature value.

        Only two parts of the history are ever read: the first cycle, which anchors drift,
        and the most recent LONG_WINDOW cycles, which fill the rolling windows. Rows
        between those are dropped because nothing reads them.
        """
        keep = LONG_WINDOW + 1
        if len(self._history) > keep + 1:
            self._history = [self._history[0]] + self._history[-keep:]

    def reset(self) -> None:
        self._history.clear()


def simulate_drone_telemetry(
    num_ticks: int = 120,
    failure_at: int | None = None,
    noise_scale: float = 1.0,
    seed: int | None = 7,
) -> list[dict]:
    """
    Produce a plausible decaying sensor trace, one reading per simulated drone tick.

    Real drone hardware is not wired up yet, so this stands in for the telemetry feed. Each
    channel starts at its measured healthy value and moves toward its measured worn-out
    value, following the accelerating curve real wear exhibits rather than a straight line,
    with sensor noise on top.

    Args:
        num_ticks: how many readings to produce.
        failure_at: tick at which the drone is fully worn out. Defaults to num_ticks, i.e.
            the trace ends at end of life.
        noise_scale: multiplier on the measured per-channel noise.
        seed: seed for reproducibility; None for a fresh random trace.

    Returns:
        List of telemetry dicts ready for predict_health or HealthMonitor.
    """
    rng = np.random.default_rng(seed)
    failure_at = failure_at or num_ticks

    trace = []
    for tick in range(1, num_ticks + 1):
        progress = min(tick / failure_at, 1.0)
        # Degradation is slow early and accelerates near failure, which is why sensor
        # readings barely move during the first half of an engine's life.
        severity = progress**2.2

        reading = {"cycle": tick}
        for channel, (healthy, noise, total_drift) in _SENSOR_PROFILE.items():
            value = healthy + total_drift * severity
            if noise > 0:
                value += rng.normal(0.0, noise * noise_scale)
            reading[channel] = float(value)
        trace.append(reading)

    return trace


if __name__ == "__main__":
    print(f"Model: {MODEL_NAME}  |  RUL cap: {RUL_CAP} cycles")
    print("Simulating a drone from new to worn out\n")

    monitor = HealthMonitor(drone_id="demo-01")
    telemetry = simulate_drone_telemetry(num_ticks=120)

    print(f"  {'Tick':>5} {'RUL':>8} {'Health':>8}  Status")
    print("  " + "-" * 42)
    for reading in telemetry:
        result = monitor.update(reading)
        if reading["cycle"] % 15 == 0 or reading["cycle"] == 1:
            print(
                f"  {result['cycle']:>5} {result['rul_cycles']:>8.1f} "
                f"{result['health']:>7.1f}%  {result['status']}"
            )
