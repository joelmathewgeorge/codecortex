"""
Drones: mission, battery, health / RUL, and the 4-D motion they fly.

Battery and health are separate on purpose. Battery is the energy on board now and
drains with distance, climbing and hovering. Health comes from the C-MAPSS RUL model in
ml/ and reflects mechanical wear: a drone can be full of charge and still be one the
planner should keep away from crowds and close to a port.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from config import (
    BATTERY_HOVER_PER_S,
    BATTERY_IDLE_PER_S,
    BATTERY_PER_CLIMB_M,
    BATTERY_PER_KM,
    CHARGE_PER_S,
    MAX_VERTICAL_RATE,
)
from geo_utils import LocalFrame
from trajectory import LANDED_ALT_M, Motion, Route
from world import Place

MISSION_KINDS = {
    "medical": ("Medical supplies", ("CRITICAL", "HIGH")),
    "organ": ("Organ transport", ("CRITICAL",)),
    "parcel": ("Parcel delivery", ("NORMAL",)),
    "food": ("Food delivery", ("NORMAL", "LOW")),
    "retail": ("Retail restock", ("LOW", "NORMAL")),
    "survey": ("Infrastructure survey", ("LOW",)),
    "security": ("Security patrol", ("HIGH",)),
    "return": ("Return to port", ("LOW",)),
}


@dataclass
class Drone:
    id: str
    mission_type: str
    priority: str
    origin: Place
    destination: Place
    home: Place
    cruise_alt: float
    cruise_speed: float
    battery: float
    wear: float
    x: float
    y: float
    alt: float
    motion: Motion | None = None
    original: Route | None = None
    phase: str = "cruise"  # cruise | holding | escaping | rejoining | returning | landed | charging
    route_kind: str = "planned"  # planned | detour | replan | escape | return
    health: float = 100.0
    rul: float = 125.0
    health_status: str = "healthy"
    heading: float = 0.0
    speed_now: float = 0.0
    vspeed: float = 0.0
    conflict_state: str = "none"
    maneuver: dict | None = None
    escape_zone: str | None = None
    rejoin_s: float | None = None
    landed_at: float = 0.0
    route_version: int = 0
    distance_flown: float = 0.0
    abort_reason: str | None = None
    created_at: float = 0.0
    announced: dict = field(default_factory=dict)
    route_cells: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))

    @property
    def mission(self) -> str:
        label = MISSION_KINDS.get(self.mission_type, (self.mission_type.title(),))[0]
        return f"{label} to {self.destination.name}"

    @property
    def airborne(self) -> bool:
        return self.phase not in ("landed", "charging")

    @property
    def deviating(self) -> bool:
        return self.route_kind in ("detour", "replan", "escape", "avoid") or self.phase in ("escaping", "rejoining")

    def set_motion(self, motion: Motion, kind: str) -> None:
        self.motion = motion
        self.route_kind = kind
        self.route_version += 1

    # --- physics ------------------------------------------------------------------

    def step(self, dt: float, now: float) -> str | None:
        """Advance one physics step. Returns "arrived" on touchdown."""
        if not self.airborne:
            self.speed_now = 0.0
            self.vspeed = 0.0
            if self.phase == "charging":
                self.battery = min(100.0, self.battery + CHARGE_PER_S * dt)
            return None
        m = self.motion
        prev_alt = self.alt
        if now < m.hold_until:
            self.speed_now = 0.0
            self.battery -= BATTERY_HOVER_PER_S * dt
        else:
            travel = min(m.speed * dt, max(0.0, m.route.length - m.s))
            m.s += travel
            self.distance_flown += travel
            self.speed_now = travel / dt if dt > 0 else 0.0
            self.battery -= BATTERY_PER_KM * travel / 1000.0
            if self.speed_now > 0.5:
                self.heading = m.route.heading(m.s)
        self.x, self.y = m.route.point(m.s)
        target = float(m.target_alt(m.s))
        self.alt = float(np.clip(target, prev_alt - MAX_VERTICAL_RATE * dt, prev_alt + MAX_VERTICAL_RATE * dt))
        m.alt = self.alt
        self.vspeed = (self.alt - prev_alt) / dt if dt > 0 else 0.0
        self.battery -= max(0.0, self.alt - prev_alt) * BATTERY_PER_CLIMB_M + BATTERY_IDLE_PER_S * dt
        self.battery = max(0.0, self.battery)
        if m.s >= m.route.length - 0.5 and self.alt <= LANDED_ALT_M:
            return "arrived"
        return None

    def eta_s(self) -> float:
        if not self.airborne or self.motion is None:
            return 0.0
        return max(0.0, self.motion.route.length - self.motion.s) / max(self.motion.speed, 1.0)

    # --- wire format ------------------------------------------------------------------

    def to_dict(self, frame: LocalFrame) -> dict:
        lat, lon = frame.latlon(self.x, self.y)
        route: list[list[float]] = []
        original: list[list[float]] | None = None
        if self.airborne and self.motion is not None:
            route = _latlon_list(frame, self.motion.route.remaining(self.motion.s))
            if self.deviating and self.original is not None:
                s_orig, _ = self.original.closest_s(self.x, self.y)
                original = _latlon_list(frame, self.original.remaining(s_orig))
        return {
            "id": self.id,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "alt": round(self.alt, 1),
            "heading": round(self.heading, 1),
            "speed": round(self.speed_now, 1),
            "vspeed": round(self.vspeed, 1),
            "battery": round(self.battery, 1),
            "health": round(self.health, 1),
            "rul": round(self.rul, 1),
            "healthStatus": self.health_status,
            "priority": self.priority,
            "missionType": self.mission_type,
            "mission": self.mission,
            "origin": self.origin.name,
            "destination": self.destination.name,
            "home": self.home.name,
            "phase": self.phase,
            "conflict": self.conflict_state,
            "maneuver": self.maneuver,
            "routeKind": self.route_kind,
            "route": route,
            "original": original,
            "cruiseAlt": self.cruise_alt,
            "etaS": round(self.eta_s()),
            "distanceLeftM": round(max(0.0, self.motion.route.length - self.motion.s)) if self.motion and self.airborne else 0,
            "abortReason": self.abort_reason,
        }


def _latlon_list(frame: LocalFrame, xy: np.ndarray) -> list[list[float]]:
    if len(xy) == 0:
        return []
    lat, lon = frame.to_latlon(xy[:, 0], xy[:, 1])
    return [[round(float(a), 6), round(float(b), 6)] for a, b in zip(lat, lon)]


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
