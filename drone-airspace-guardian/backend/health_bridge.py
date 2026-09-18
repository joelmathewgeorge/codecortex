"""
Bridge to the C-MAPSS remaining-useful-life model in ml/.

There is no real airframe telemetry, so each drone flies a synthetic degrading sensor
trace from ml/predict.py; its wear picks how far along that trace it starts (wear 0 is
fresh, wear 1 is near failure). Every model cycle each airborne drone takes the next
reading and the whole fleet is scored in one batched call, so health bars and RUL are
the trained estimator's output rather than a formula.

If the model cannot load (missing joblib, sklearn mismatch) health falls back to the
same trace position mapped through a fixed curve, and the HUD labels it as such.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from config import ML_DIR

if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

TRACE_TICKS = 200
FAILURE_AT = 180
WARMUP = 20
RUL_CAP = 125.0


@dataclass
class Reading:
    rul: float
    health: float
    status: str
    cycle: int


@dataclass
class _Track:
    monitor: object | None
    trace: list
    cycle: int


def status_for(health: float) -> str:
    if health >= 75:
        return "healthy"
    if health >= 50:
        return "monitor"
    if health >= 25:
        return "service_soon"
    return "ground_now"


class HealthBridge:
    def __init__(self) -> None:
        self._predict = None
        self.error: str | None = None
        self.tracks: dict[str, _Track] = {}
        try:
            import predict

            self._predict = predict
            self.model = predict.MODEL_NAME
        except Exception as exc:  # model missing or incompatible
            self.error = str(exc)
            self.model = "fallback curve"
            print(f"[health_bridge] RUL model unavailable, using fallback curve: {exc}")

    @property
    def live(self) -> bool:
        return self._predict is not None

    def start_cycle(self, wear: float) -> int:
        return int(10 + max(0.0, min(1.0, wear)) * 140)

    def register(self, drone_id: str, wear: float, seed: int) -> Reading:
        start = self.start_cycle(wear)
        if not self.live:
            self.tracks[drone_id] = _Track(None, [], start)
            return self._fallback(start)
        p = self._predict
        trace = p.simulate_drone_telemetry(num_ticks=TRACE_TICKS, failure_at=FAILURE_AT, seed=seed)
        monitor = p.HealthMonitor(drone_id=drone_id)
        for idx in range(max(0, start - WARMUP), start):
            monitor.record(trace[idx])
        self.tracks[drone_id] = _Track(monitor, trace, start)
        rul = p.predict_rul_many([monitor.history])[0]
        return self._reading(rul, start)

    def advance(self, drone_ids: list[str]) -> dict[str, Reading]:
        """Move each drone one cycle along its trace and score them together."""
        ids = [i for i in drone_ids if i in self.tracks]
        if not ids:
            return {}
        out: dict[str, Reading] = {}
        if not self.live:
            for i in ids:
                t = self.tracks[i]
                t.cycle = min(t.cycle + 1, TRACE_TICKS)
                out[i] = self._fallback(t.cycle)
            return out
        monitors, readings = [], []
        for i in ids:
            t = self.tracks[i]
            t.cycle = min(t.cycle + 1, TRACE_TICKS)
            monitors.append(t.monitor)
            readings.append(t.trace[t.cycle - 1])
        for i, result in zip(ids, self._predict.update_many(monitors, readings)):
            out[i] = self._reading(result["rul_cycles"], self.tracks[i].cycle)
        return out

    def forget(self, drone_id: str) -> None:
        self.tracks.pop(drone_id, None)

    def clear(self) -> None:
        self.tracks.clear()

    def _reading(self, rul: float, cycle: int) -> Reading:
        health = max(0.0, min(100.0, rul / RUL_CAP * 100.0))
        return Reading(round(rul, 1), round(health, 1), status_for(health), cycle)

    def _fallback(self, cycle: int) -> Reading:
        progress = min(cycle / FAILURE_AT, 1.0)
        health = max(0.0, 100.0 * (1.0 - progress**2.2))
        return Reading(round(health / 100.0 * RUL_CAP, 1), round(health, 1), status_for(health), cycle)
