"""
Zones drawn during the demo: operator no-fly rings and emergency zones.

Both are circles with a hard core and a soft buffer. An emergency is the serious one: its
buffer costs 500 per metre, drones already inside escape by the cheapest way out, and the
event log and HUD escalate. The predetermined real-world restrictions live in world.py.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from config import (
    COST_EMERGENCY_BUFFER,
    COST_NEAR_RESTRICTED,
    EMERGENCY_BUFFER_M,
    MAX_EMERGENCY_ZONES,
    MAX_OPERATOR_ZONES,
    OPERATOR_ZONE_BUFFER_M,
)
from geo_utils import LocalFrame


@dataclass
class Zone:
    id: str
    kind: str  # operator | emergency
    lat: float
    lon: float
    x: float
    y: float
    radius: float
    buffer: float
    buffer_cost: float
    created_at: float
    label: str

    def distance(self, x: float, y: float) -> float:
        """Metres from the edge of the hard core; negative inside."""
        return math.hypot(x - self.x, y - self.y) - self.radius

    def contains(self, x: float, y: float, margin: float = 0.0) -> bool:
        return self.distance(x, y) < margin

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "radius": self.radius,
            "buffer": self.buffer,
            "label": self.label,
            "createdAt": round(self.created_at, 1),
        }


class ZoneStore:
    def __init__(self, frame: LocalFrame) -> None:
        self.frame = frame
        self.zones: list[Zone] = []
        self._ids = itertools.count(1)

    def add(self, kind: str, lat: float, lon: float, radius: float, now: float) -> tuple[Zone, list[Zone]]:
        """Returns the new zone and any zones it pushed out (oldest first when over the cap)."""
        emergency = kind == "emergency"
        cap = MAX_EMERGENCY_ZONES if emergency else MAX_OPERATOR_ZONES
        same = [z for z in self.zones if z.kind == kind]
        dropped = same[: max(0, len(same) - cap + 1)]
        self.zones = [z for z in self.zones if z not in dropped]
        n = next(self._ids)
        x, y = self.frame.point(lat, lon)
        zone = Zone(
            id=f"{'EZ' if emergency else 'NFZ'}-{n}",
            kind=kind,
            lat=lat,
            lon=lon,
            x=x,
            y=y,
            radius=radius,
            buffer=EMERGENCY_BUFFER_M if emergency else OPERATOR_ZONE_BUFFER_M,
            buffer_cost=COST_EMERGENCY_BUFFER if emergency else COST_NEAR_RESTRICTED,
            created_at=now,
            label=f"Emergency {n}" if emergency else f"No-fly {n}",
        )
        self.zones.append(zone)
        return zone, dropped

    def remove(self, zone_id: str) -> Zone | None:
        for z in self.zones:
            if z.id == zone_id:
                self.zones.remove(z)
                return z
        return None

    def clear(self) -> None:
        self.zones.clear()

    def of_kind(self, kind: str) -> list[Zone]:
        return [z for z in self.zones if z.kind == kind]
