"""
No-fly zones and emergency zones — storage and conflict detection.

ARCHITECTURE NOTE:
    Zones are stored in a plain Python list (in-memory).
    This means they vanish when the server restarts. That's intentional
    for a prototype — no database setup, no migration headaches.
    If this ever needs persistence, swap the list for a DB table.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from geo_utils import haversine


# ---------------------------------------------------------------------------
# Zone data model
# ---------------------------------------------------------------------------

@dataclass
class Zone:
    """
    A circular geographic zone (no-fly or emergency).

    WHY A DATACLASS?
        It's a simple struct with named fields.  A dict would work, but
        dataclasses give you type hints, a free __repr__, and IDE
        autocomplete — much less error-prone when you're moving fast.

    Fields:
        lat, lon   — center of the zone (degrees)
        radius     — radius in metres
        emergency  — True for emergency/danger zones
        id         — auto-generated unique identifier
        created_at — Unix timestamp (for TTL / expiry later)
    """
    lat: float
    lon: float
    radius: float
    emergency: bool = False
    id: str = field(default_factory=lambda: f"zone-{uuid.uuid4().hex[:8]}")
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Convert to JSON-friendly dict for API responses."""
        return {
            "id": self.id,
            "lat": self.lat,
            "lon": self.lon,
            "radius": self.radius,
            "emergency": self.emergency,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# In-memory zone storage
# ---------------------------------------------------------------------------

# This is the "database" — a global list.
# All parts of the app import and mutate this list directly.
_zones: list[Zone] = []


def add_zone(lat: float, lon: float, radius: float,
             emergency: bool = False) -> Zone:
    """Create a zone and add it to the store. Returns the new Zone."""
    zone = Zone(lat=lat, lon=lon, radius=radius, emergency=emergency)
    _zones.append(zone)
    return zone


def get_all_zones() -> list[Zone]:
    """Return all active zones."""
    return list(_zones)


def clear_zones() -> None:
    """Remove all zones (useful for testing)."""
    _zones.clear()


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def check_conflicts(lat: float, lon: float) -> list[Zone]:
    """
    Check if a point (lat, lon) is inside any active zone.

    HOW IT WORKS:
        For each zone, compute the Haversine distance from the zone's
        center to the given point.  If distance < zone.radius, the
        point is inside the zone → conflict!

    WHY RETURN A LIST?
        A drone might be inside multiple overlapping zones.  We return
        all of them so the reroute logic can handle each one.

    Returns: list of Zone objects that the point conflicts with
    """
    conflicts = []
    for zone in _zones:
        dist = haversine(zone.lat, zone.lon, lat, lon)
        if dist < zone.radius:
            conflicts.append(zone)
    return conflicts
