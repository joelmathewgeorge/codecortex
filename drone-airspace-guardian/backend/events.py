"""
Centralised event log.

Every decision the simulation makes is recorded here with a wall-clock timestamp, the sim
clock, a type from EVENT_TYPES, a severity, the drones involved, a readable message and
structured metadata. The WebSocket streams new events every tick and the events page
replays the history on connect.
"""

from __future__ import annotations

import itertools
import threading
from collections import Counter, deque
from datetime import datetime, timezone

EVENT_TYPES = {
    "DRONE_ADDED": "info",
    "ROUTE_GENERATED": "info",
    "CONFLICT_PREDICTED": "alert",
    "DECONFLICTION_STARTED": "warning",
    "ALTITUDE_MANEUVER": "warning",
    "HOLD_MANEUVER": "warning",
    "DETOUR_MANEUVER": "warning",
    "CONFLICT_RESOLVED": "success",
    "CONFLICT_UNRESOLVED": "critical",
    "REROUTE_STARTED": "warning",
    "REROUTE_COMPLETED": "success",
    "NO_FLY_AVOIDED": "success",
    "ZONE_CREATED": "warning",
    "ZONE_CLEARED": "info",
    "EMERGENCY_CREATED": "critical",
    "EMERGENCY_ESCAPE_STARTED": "critical",
    "EMERGENCY_ESCAPE_COMPLETED": "success",
    "LOW_BATTERY": "warning",
    "CRITICAL_BATTERY": "critical",
    "RUL_UPDATED": "info",
    "HEALTH_DEGRADED": "warning",
    "CRITICAL_HEALTH": "critical",
    "MISSION_ABORTED": "critical",
    "MISSION_COMPLETED": "success",
    "AIRCRAFT_DETECTED": "info",
    "AIRCRAFT_CONFLICT": "alert",
    "AIRCRAFT_CONFLICT_RESOLVED": "success",
    "GROUND_RISK_DETECTED": "warning",
    "GROUND_RISK_CLEARED": "info",
    "SIM_RESET": "info",
}


class EventBus:
    def __init__(self, maxlen: int = 2000) -> None:
        self._history: deque[dict] = deque(maxlen=maxlen)
        self._pending: list[dict] = []
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.counts: Counter[str] = Counter()
        self.clock = lambda: 0.0

    def emit(
        self,
        type_: str,
        message: str,
        *,
        drone: str | None = None,
        drones: list[str] | None = None,
        severity: str | None = None,
        **metadata,
    ) -> dict:
        involved = list(drones or ([drone] if drone else []))
        event = {
            "id": next(self._ids),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "simTime": round(self.clock(), 1),
            "type": type_,
            "severity": severity or EVENT_TYPES.get(type_, "info"),
            "droneId": involved[0] if involved else None,
            "droneIds": involved,
            "message": message,
            "metadata": {k: _plain(v) for k, v in metadata.items()},
        }
        with self._lock:
            self._history.append(event)
            self._pending.append(event)
            self.counts[type_] += 1
        return event

    def drain(self) -> list[dict]:
        with self._lock:
            out, self._pending = self._pending, []
        return out

    def history(self, limit: int = 500) -> list[dict]:
        with self._lock:
            items = list(self._history)
        return items[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            self._pending.clear()
            self.counts.clear()


def _plain(value):
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if hasattr(value, "item"):  # numpy scalar
        return _plain(value.item())
    return value
