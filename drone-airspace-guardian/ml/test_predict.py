"""
Checks the numpy live-inference path against the pandas training path.

Run: python test_predict.py   (or pytest, if installed)
"""

from __future__ import annotations

import time

import numpy as np

import predict
from predict import HealthMonitor, latest_features, reference_features, simulate_drone_telemetry, update_many


def test_fast_features_match_training_features():
    trace = simulate_drone_telemetry(num_ticks=60, failure_at=50, seed=3)
    monitor = HealthMonitor("t")
    for reading in trace:
        monitor.record(reading)
        fast = latest_features(monitor.history)
        slow = reference_features(monitor.history).to_numpy(dtype=float)
        assert np.allclose(fast, slow, rtol=1e-9, atol=1e-9), f"feature drift at cycle {reading['cycle']}"


def test_batched_scores_match_single_scores():
    monitors = [HealthMonitor(f"d{i}") for i in range(4)]
    traces = [simulate_drone_telemetry(num_ticks=40, failure_at=45, seed=10 + i) for i in range(4)]
    for tick in range(40):
        batched = update_many(monitors, [t[tick] for t in traces])
        singles = [predict._predict_rul(m.history) for m in monitors]
        for got, want in zip(batched, singles):
            assert abs(got["rul_cycles"] - round(want, 1)) < 1e-6


def test_worn_trace_scores_lower_than_new_trace():
    new = HealthMonitor("new")
    worn = HealthMonitor("worn")
    trace = simulate_drone_telemetry(num_ticks=200, failure_at=180, seed=5)
    for reading in trace[:25]:
        new.update(reading)
    for reading in trace[150:175]:
        worn.update(reading)
    assert worn.update(trace[175])["health"] < new.update(trace[25])["health"]


def test_fast_path_is_fast():
    monitor = HealthMonitor("speed")
    trace = simulate_drone_telemetry(num_ticks=30, seed=1)
    for reading in trace:
        monitor.record(reading)
    start = time.perf_counter()
    for _ in range(20):
        predict._predict_rul(monitor.history)
    per_call_ms = (time.perf_counter() - start) / 20 * 1000
    assert per_call_ms < 25, f"{per_call_ms:.1f} ms per score"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
