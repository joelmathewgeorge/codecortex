"""
Bridge Pranav's drone loop to Rohit's trained RUL model.

The model lives under ../ml. We never retrain here — we only score live-ish
stand-in telemetry so the dashboard health bars are the real estimator, not
random.randint.
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent / "ml"
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

_monitors: dict[str, object] = {}
_traces: dict[str, list] = {}
_cycles: dict[str, int] = {}
_ready = False
_error: str | None = None


def reset_monitors() -> None:
    """Drop per-drone traces so Reset demo starts health from a clean clock."""
    _monitors.clear()
    _traces.clear()
    _cycles.clear()


def warmup() -> None:
    """Load the joblib bundle once. Safe to call from FastAPI startup."""
    global _ready, _error
    if _ready or _error:
        return
    try:
        from predict import HealthMonitor, simulate_drone_telemetry  # noqa: F401

        _ready = True
    except Exception as exc:  # model missing or sklearn mismatch
        _error = str(exc)
        print(f"[health_bridge] ML unavailable, using last known health: {exc}")


def score_drone(drone_id: str, wear: float = 0.15) -> float | None:
    """
    Advance this drone one telemetry tick and return 0-100 health.

    wear 0 = brand new, 1 = end of life. Used only to pick the starting
    cycle on the synthetic degrading trace so the five drones are not clones.
    """
    warmup()
    if not _ready:
        return None

    from predict import HealthMonitor, simulate_drone_telemetry

    if drone_id not in _monitors:
        start = max(1, int(wear * 110))
        _monitors[drone_id] = HealthMonitor(drone_id=drone_id)
        _traces[drone_id] = simulate_drone_telemetry(
            num_ticks=200, failure_at=180, seed=abs(hash(drone_id)) % 10_000
        )
        _cycles[drone_id] = start

    idx = min(_cycles[drone_id], len(_traces[drone_id]) - 1)
    reading = dict(_traces[drone_id][idx])
    reading["cycle"] = max(1, idx)
    # One model cycle every 6 sim ticks so health does not collapse during a 10-minute demo.
    _sub = _cycles.setdefault(f"{drone_id}_sub", 0) + 1
    _cycles[f"{drone_id}_sub"] = _sub
    if _sub % 6 == 0:
        _cycles[drone_id] = min(idx + 1, len(_traces[drone_id]) - 1)
    result = _monitors[drone_id].update(reading)  # type: ignore[union-attr]
    return float(result["health"])
