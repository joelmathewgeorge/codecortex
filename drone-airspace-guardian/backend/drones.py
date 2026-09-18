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

from dataclasses import dataclass, field

from geo_utils import bearing, haversine, offset_point
from health_bridge import score_drone
from missions import MISSIONS, load_mission_waypoints
from zones import Zone, check_conflicts

PROXIMITY_M = 100.0
ALT_SEP_M = 30.0


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
    wear: float = 0.15
    affected: bool = False
    _original_waypoints: list[tuple[float, float]] = field(default_factory=list)
    _reroute_waypoints: list[tuple[float, float]] = field(default_factory=list)

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
            "health": int(round(self.health)),
            "mission": self.mission,
            "affected": self.affected,
            "path": [{"lat": lat, "lon": lon} for lat, lon in self._original_waypoints],
            "reroutePath": [{"lat": lat, "lon": lon} for lat, lon in self._reroute_waypoints],
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
                    self._reroute_waypoints = []
                    self.affected = False
        else:
            # Move toward target by `speed` metres
            # t = fraction of the remaining distance to cover in this tick
            t = self.speed / dist_to_target
            self.lat = self.lat + t * (target_lat - self.lat)
            self.lon = self.lon + t * (target_lon - self.lon)

        scored = score_drone(self.id, wear=self.wear)
        if scored is not None:
            self.health = round(0.82 * self.health + 0.18 * scored, 1)

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
        conflicts = check_conflicts(self.lat, self.lon) or check_conflicts(next_wp[0], next_wp[1])

        self.affected = bool(conflicts) or self.status == "rerouting"

        for zone in conflicts:
            if self.status == "rerouting":
                continue

            brng = bearing(zone.lat, zone.lon, self.lat, self.lon)
            perp_bearing = (brng + 90) % 360
            detour_lat, detour_lon = offset_point(
                zone.lat, zone.lon, perp_bearing, zone.radius + 100
            )
            self.waypoints.insert(self.current_idx, (detour_lat, detour_lon))
            self._reroute_waypoints = [(self.lat, self.lon), (detour_lat, detour_lon), next_wp]
            self.status = "rerouting"
            self.affected = True

    def force_reroute_check(self) -> list[Zone]:
        """Immediate conflict check for POST /emergency (current position + next waypoint)."""
        next_wp = self.waypoints[self.current_idx]
        conflicts = check_conflicts(self.lat, self.lon) or check_conflicts(next_wp[0], next_wp[1])
        if conflicts:
            self._check_and_reroute()
        return conflicts


# ---------------------------------------------------------------------------
# Create the 5 hardcoded drones
# ---------------------------------------------------------------------------

FALLBACK_PATHS = [
    [(12.9716, 77.5946), (12.9780, 77.5900), (12.9850, 77.5850), (12.9716, 77.5946)],
    [(12.9352, 77.6245), (12.9400, 77.6150), (12.9450, 77.6050), (12.9352, 77.6245)],
    [(12.9698, 77.7500), (12.9650, 77.7400), (12.9600, 77.7300), (12.9698, 77.7500)],
    [(12.9250, 77.5470), (12.9300, 77.5550), (12.9370, 77.5620), (12.9250, 77.5470)],
    [(13.0358, 77.5970), (13.0300, 77.5900), (13.0250, 77.5830), (13.0358, 77.5970)],
]


def mark_proximity(drones: list[Drone]) -> None:
    """Pairwise drone-to-drone conflict: <100 m and <30 m altitude."""
    for i, a in enumerate(drones):
        for b in drones[i + 1 :]:
            if haversine(a.lat, a.lon, b.lat, b.lon) < PROXIMITY_M and abs(a.alt - b.alt) < ALT_SEP_M:
                a.affected = True
                b.affected = True


def create_default_drones() -> list[Drone]:
    """
    Five drones around Bangalore. Paths prefer reshaped OpenSky tracks from
    ml/trajectories.json so the missions have real ADS-B curvature; if that
    file is missing we keep Pranav's original hardcoded legs.
    """
    ml_paths = load_mission_waypoints()
    paths = ml_paths if ml_paths else FALLBACK_PATHS
    fleet = []
    for i, (drone_id, mission, speed, alt, wear) in enumerate(MISSIONS):
        fleet.append(
            Drone(
                id=drone_id,
                waypoints=list(paths[i]),
                speed=speed,
                mission=mission,
                alt=alt,
                wear=wear,
            )
        )
    return fleet
