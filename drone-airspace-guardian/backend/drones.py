"""
Drone simulation — movement along paths, conflict checking, and rerouting.

HOW THE SIMULATION WORKS:
    Each drone has a list of waypoints (lat/lon pairs) forming its mission
    path.  Every tick (~1 second), the drone walks `speed` metres along the
    polyline (consuming as many dense samples as that distance covers).

    Dense OpenSky tracks are ~360 evenly spaced points, so the flown path
    stays curved instead of pivoting at a handful of corners.

    Open (A→B) tracks ping-pong rather than drawing a straight closing chord.
    Already-closed fallback loops wrap.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from geo_utils import bearing, haversine, offset_point
from health_bridge import score_drone
from missions import MISSIONS, load_mission_tracks
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
    track_source: str = "sim"
    _original_waypoints: list[tuple[float, float]] = field(default_factory=list)
    _reroute_waypoints: list[tuple[float, float]] = field(default_factory=list)
    _speed_profile: list[float] = field(default_factory=list)
    _alt_profile: list[float] = field(default_factory=list)
    _cruise_speed: float = 0.0
    _direction: int = 1
    _closed: bool = False

    def __post_init__(self):
        """Set initial position to the first waypoint."""
        if self.waypoints:
            self.lat, self.lon = self.waypoints[0]
            self._original_waypoints = list(self.waypoints)
            a, b = self.waypoints[0], self.waypoints[-1]
            self._closed = abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6
        if self._cruise_speed <= 0:
            self._cruise_speed = self.speed
        self._apply_profile()

    def to_dict(self) -> dict:
        """
        Convert to the JSON shape Joel's frontend expects.
        This IS the API contract — don't change field names without
        telling Joel.
        """
        target = self.waypoints[self.current_idx] if self.waypoints else (self.lat, self.lon)
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
            "behavior": self._behavior(),
            "trackSource": self.track_source,
            "path": [{"lat": round(lat, 6), "lon": round(lon, 6)} for lat, lon in self._original_waypoints],
            "reroutePath": [{"lat": round(lat, 6), "lon": round(lon, 6)} for lat, lon in self._reroute_waypoints],
        }

    def _profile_index(self) -> int:
        n = max(len(self._original_waypoints), 1)
        return min(max(self.current_idx, 0), n - 1)

    def _apply_profile(self) -> None:
        i = self._profile_index()
        if self._speed_profile:
            i_s = min(i, len(self._speed_profile) - 1)
            self.speed = max(4.0, self._cruise_speed * self._speed_profile[i_s])
        if self._alt_profile:
            i_a = min(i, len(self._alt_profile) - 1)
            self.alt = self._alt_profile[i_a]

    def _behavior(self) -> str:
        if self.status == "rerouting":
            return "orbit"
        alts = self._alt_profile
        if len(alts) >= 2:
            i = min(self._profile_index(), len(alts) - 1)
            ahead = alts[min(len(alts) - 1, i + 10)]
            behind = alts[max(0, i - 10)]
            delta = ahead - behind
            if delta > 12:
                return "climb"
            if delta < -12:
                return "descend"
        if self.speed < 6:
            return "hold"
        wps = self.waypoints
        if len(wps) > 12:
            i = min(max(self.current_idx, 1), len(wps) - 2)
            turn = abs(
                bearing(wps[i - 1][0], wps[i - 1][1], wps[i][0], wps[i][1])
                - bearing(wps[i][0], wps[i][1], wps[i + 1][0], wps[i + 1][1])
            )
            turn = min(turn, 360 - turn)
            if turn > 35:
                return "orbit"
        return "cruise"

    def _turn_around(self) -> None:
        if self.status == "rerouting":
            self.waypoints = list(self._original_waypoints)
            self.status = "en-route"
            self._reroute_waypoints = []
            self.affected = False
            self._direction = 1
            self.current_idx = 1 if len(self.waypoints) > 1 else 0
            return
        if self._closed:
            self.current_idx = 0 if self._direction > 0 else max(len(self.waypoints) - 1, 0)
            return
        if self._direction > 0:
            self._direction = -1
            self.current_idx = max(len(self.waypoints) - 2, 0)
        else:
            self._direction = 1
            self.current_idx = 1 if len(self.waypoints) > 1 else 0

    def tick(self) -> None:
        """
        Advance the drone by one simulation step (~1 second of real time).

        Walks `speed` metres along the waypoint polyline so a 360-point curve
        is traced at the labelled cruise speed instead of snapping one vertex
        per tick.
        """
        if not self.waypoints:
            return
        if self.current_idx < 0 or self.current_idx >= len(self.waypoints):
            self._turn_around()

        budget = max(self.speed, 0.1)
        hops = 0
        while budget > 0.4 and hops < 64:
            hops += 1
            if self.current_idx < 0 or self.current_idx >= len(self.waypoints):
                self._turn_around()
                break
            target_lat, target_lon = self.waypoints[self.current_idx]
            dist = haversine(self.lat, self.lon, target_lat, target_lon)
            if dist <= budget or dist < 1.0:
                self.lat, self.lon = target_lat, target_lon
                budget -= dist
                self.current_idx += self._direction
                if self.current_idx < 0 or self.current_idx >= len(self.waypoints):
                    self._turn_around()
                    break
            else:
                t = budget / dist
                self.lat = self.lat + t * (target_lat - self.lat)
                self.lon = self.lon + t * (target_lon - self.lon)
                budget = 0

        self._apply_profile()

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
        if not self.waypoints:
            return
        if self.current_idx < 0 or self.current_idx >= len(self.waypoints):
            self.current_idx = min(max(self.current_idx, 0), len(self.waypoints) - 1)
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
        if not self.waypoints:
            return []
        if self.current_idx < 0 or self.current_idx >= len(self.waypoints):
            self.current_idx = min(max(self.current_idx, 0), len(self.waypoints) - 1)
        next_wp = self.waypoints[self.current_idx]
        conflicts = check_conflicts(self.lat, self.lon) or check_conflicts(next_wp[0], next_wp[1])
        if conflicts:
            self._check_and_reroute()
        return conflicts


# ---------------------------------------------------------------------------
# Create the 5 hardcoded drones
# ---------------------------------------------------------------------------

FALLBACK_PATHS = [
    [(25.1972, 55.2744), (25.2040, 55.2700), (25.2100, 55.2650), (25.1972, 55.2744)],
    [(25.1890, 55.2820), (25.1930, 55.2760), (25.1980, 55.2690), (25.1890, 55.2820)],
    [(25.2050, 55.2640), (25.1990, 55.2700), (25.1920, 55.2780), (25.2050, 55.2640)],
    [(25.1860, 55.2680), (25.1920, 55.2740), (25.1990, 55.2800), (25.1860, 55.2680)],
    [(25.2110, 55.2810), (25.2040, 55.2760), (25.1960, 55.2700), (25.2110, 55.2810)],
]


def reset_fleet(fleet: list[Drone]) -> None:
    """Rebuild the five Downtown Dubai missions in place."""
    fleet.clear()
    fleet.extend(create_default_drones())


def mark_proximity(drones: list[Drone]) -> None:
    """Pairwise drone-to-drone conflict: <100 m and <30 m altitude."""
    for i, a in enumerate(drones):
        for b in drones[i + 1 :]:
            if haversine(a.lat, a.lon, b.lat, b.lon) < PROXIMITY_M and abs(a.alt - b.alt) < ALT_SEP_M:
                a.affected = True
                b.affected = True


def create_default_drones() -> list[Drone]:
    """
    Five drones over Downtown Dubai. Paths prefer reshaped OpenSky tracks from
    ml/trajectories.json so the missions have real ADS-B curvature; if that
    file is missing we keep the local Dubai fallback legs.
    """
    ml_tracks = load_mission_tracks()
    fleet = []
    for i, (drone_id, mission, speed, alt, wear) in enumerate(MISSIONS):
        track = ml_tracks[i] if ml_tracks else None
        waypoints = list(track["waypoints"]) if track else list(FALLBACK_PATHS[i])
        alt_profile = list(track["alt_profile"]) if track else []
        start_alt = alt_profile[0] if alt_profile else alt
        fleet.append(
            Drone(
                id=drone_id,
                waypoints=waypoints,
                speed=speed,
                mission=mission,
                alt=start_alt,
                wear=wear,
                track_source=track["source"] if track else "sim",
                _speed_profile=list(track["speed_profile"]) if track else [],
                _alt_profile=alt_profile,
            )
        )
    return fleet
