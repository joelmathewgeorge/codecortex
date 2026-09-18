"""
Drone simulation — movement along paths, conflict checking, and rerouting.

HOW THE SIMULATION WORKS:
    Each drone has a list of waypoints (lat/lon pairs) forming its mission
    path.  Every tick (~1 second), the drone moves a step along the line
    segment from its current waypoint towards the next.

    Movement uses LINEAR INTERPOLATION (lerp):
        new_position = current + t * (next - current)
    where t is the fraction of the segment to travel in one tick.

    When the drone reaches a waypoint, it advances to the next segment.
    When it finishes all waypoints, it loops back to the start.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from geo_utils import bearing, haversine, offset_point
from zones import Zone, check_conflicts


# ---------------------------------------------------------------------------
# Drone data model
# ---------------------------------------------------------------------------

@dataclass
class Drone:
    """
    Represents a single simulated drone.

    Fields:
        id          — unique identifier like "drone-1"
        waypoints   — list of (lat, lon) tuples defining the mission path
        current_idx — index of the waypoint the drone is currently heading toward
        lat, lon    — current position
        alt         — altitude in metres (simulated)
        speed       — speed in m/s (used to compute how far to move per tick)
        status      — "en-route", "rerouting", or "idle"
        mission     — human-readable mission name
        health      — 0-100 placeholder for Rohit's ML model
        _original_waypoints — backup of original path for resuming after reroute
    """
    id: str
    waypoints: list[tuple[float, float]]
    current_idx: int = 1  # heading toward waypoint[1] (start is waypoint[0])
    lat: float = 0.0
    lon: float = 0.0
    alt: float = 100.0
    speed: float = 15.0  # m/s — roughly 54 km/h, realistic for a delivery drone
    status: str = "en-route"
    mission: str = "Patrol"
    health: int = 100
    _original_waypoints: list[tuple[float, float]] = field(default_factory=list)

    def __post_init__(self):
        """Set initial position to the first waypoint."""
        if self.waypoints:
            self.lat, self.lon = self.waypoints[0]
            # Keep a backup of the original path
            self._original_waypoints = list(self.waypoints)

    def to_dict(self) -> dict:
        """
        Convert to the JSON shape Joel's frontend expects.
        This IS the API contract — don't change field names without
        telling Joel.
        """
        # Compute heading toward next waypoint
        target = self.waypoints[self.current_idx]
        hdg = bearing(self.lat, self.lon, target[0], target[1])

        return {
            "id": self.id,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "alt": round(self.alt, 1),
            "heading": round(hdg, 1),
            "speed": round(self.speed, 1),
            "status": self.status,
            "health": self.health,
            "mission": self.mission,
        }

    def tick(self) -> None:
        """
        Advance the drone by one simulation step (~1 second of real time).

        WHAT HAPPENS EACH TICK:
        1. Compute how far the drone should move (speed * 1 second)
        2. Compute direction toward the next waypoint
        3. Move the drone along that direction
        4. If we've reached the waypoint, advance to the next one
        5. Randomize the health field (placeholder for ML model)
        6. Run conflict check against all active zones
        """
        target_lat, target_lon = self.waypoints[self.current_idx]
        dist_to_target = haversine(self.lat, self.lon, target_lat, target_lon)

        if dist_to_target < self.speed:
            # Close enough — snap to waypoint and advance
            self.lat, self.lon = target_lat, target_lon
            self.current_idx += 1

            # If we've completed all waypoints, loop back
            if self.current_idx >= len(self.waypoints):
                self.current_idx = 0
                # If we were rerouting, restore original path
                if self.status == "rerouting":
                    self.waypoints = list(self._original_waypoints)
                    self.status = "en-route"
        else:
            # Move toward target by `speed` metres
            # t = fraction of the remaining distance to cover in this tick
            t = self.speed / dist_to_target
            self.lat = self.lat + t * (target_lat - self.lat)
            self.lon = self.lon + t * (target_lon - self.lon)

        # --- Placeholder health (Step 7) ---
        # Random jitter around current health — simulates sensor noise
        # Rohit's model will replace this with real predictions
        self.health = max(0, min(100, self.health + random.randint(-5, 5)))

        # --- Conflict check (Steps 5 & 6) ---
        self._check_and_reroute()

    def _check_and_reroute(self) -> None:
        """
        Check if our NEXT waypoint is inside any no-fly zone.
        If it is, compute a detour around the zone.

        REROUTE STRATEGY:
            1. Find the bearing from zone center → our next waypoint
            2. Rotate that bearing by 90° (perpendicular)
            3. Place a detour point at (zone.radius + buffer) along
               that perpendicular bearing from the zone center
            4. Insert the detour point before our next waypoint
            5. Set status to "rerouting"

        This creates a simple "dodge to the side" behavior.
        """
        next_wp = self.waypoints[self.current_idx]
        conflicts = check_conflicts(next_wp[0], next_wp[1])

        if not conflicts and self.status == "rerouting":
            # No more conflicts — check if we should resume
            # (status gets reset when we loop back in tick())
            pass

        for zone in conflicts:
            if self.status == "rerouting":
                # Already rerouting — don't stack reroutes
                continue

            # Compute bearing from zone center to the conflicting waypoint
            brng = bearing(zone.lat, zone.lon, next_wp[0], next_wp[1])

            # Rotate 90° to get the perpendicular direction
            perp_bearing = (brng + 90) % 360

            # Place detour point just outside the zone (radius + 100m buffer)
            detour_lat, detour_lon = offset_point(
                zone.lat, zone.lon, perp_bearing, zone.radius + 100
            )

            # Insert the detour waypoint BEFORE the conflicting waypoint
            self.waypoints.insert(self.current_idx, (detour_lat, detour_lon))
            self.status = "rerouting"

    def force_reroute_check(self) -> list[Zone]:
        """
        Force an immediate conflict check (used by POST /emergency).
        Returns list of zones this drone conflicts with.
        """
        next_wp = self.waypoints[self.current_idx]
        conflicts = check_conflicts(next_wp[0], next_wp[1])
        if conflicts:
            self._check_and_reroute()
        return conflicts


# ---------------------------------------------------------------------------
# Create the 5 hardcoded drones
# ---------------------------------------------------------------------------

def create_default_drones() -> list[Drone]:
    """
    Create 5 drones with realistic paths around Bangalore, India.

    WHY BANGALORE?
        It's a real city with real coordinates — makes it easy to
        visualize on a map.  The paths are ~2-5 km long, which is
        realistic for urban delivery drones.

    Each drone has 3-4 waypoints forming a straight-ish line path.
    """
    return [
        Drone(
            id="drone-1",
            waypoints=[
                (12.9716, 77.5946),   # MG Road
                (12.9780, 77.5900),   # North toward Cubbon Park
                (12.9850, 77.5850),   # Further north
                (12.9716, 77.5946),   # Loop back to start
            ],
            speed=12.0,
            mission="Delivery A — Medical Supplies",
            alt=120.0,
        ),
        Drone(
            id="drone-2",
            waypoints=[
                (12.9352, 77.6245),   # Koramangala
                (12.9400, 77.6150),   # West toward BTM
                (12.9450, 77.6050),   # Further west
                (12.9352, 77.6245),   # Loop back
            ],
            speed=14.0,
            mission="Delivery B — Food Package",
            alt=80.0,
        ),
        Drone(
            id="drone-3",
            waypoints=[
                (12.9698, 77.7500),   # Whitefield
                (12.9650, 77.7400),   # Southwest
                (12.9600, 77.7300),   # Further southwest
                (12.9698, 77.7500),   # Loop back
            ],
            speed=16.0,
            mission="Survey — Traffic Monitoring",
            alt=150.0,
        ),
        Drone(
            id="drone-4",
            waypoints=[
                (12.9250, 77.5470),   # Basavanagudi
                (12.9300, 77.5550),   # Northeast
                (12.9370, 77.5620),   # Further northeast
                (12.9250, 77.5470),   # Loop back
            ],
            speed=10.0,
            mission="Delivery C — Electronics",
            alt=90.0,
        ),
        Drone(
            id="drone-5",
            waypoints=[
                (13.0358, 77.5970),   # Yelahanka (north Bangalore)
                (13.0300, 77.5900),   # South
                (13.0250, 77.5830),   # Further south
                (13.0358, 77.5970),   # Loop back
            ],
            speed=18.0,
            mission="Emergency — Organ Transport",
            alt=200.0,
        ),
    ]
