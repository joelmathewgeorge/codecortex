"""
4-D trajectories: where a drone will be, and how high, at each moment ahead.

A Route is a 2-D polyline with arc length and an altitude profile along it. The profile
holds cruise altitude, drops under airport ceilings, and ramps at the climb rate, so the
altitude the planner promises is one the drone can fly.

Motion is the live state on a route (distance flown, speed, altitude, any hold or
altitude manoeuvre). `predict` turns it into (x, y, alt) samples at future times, which is
what the conflict predictor compares: two lines crossing on the map are only a conflict
if both drones reach the crossing at the same time and at a similar height.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from config import ALT_MIN_M, CLIMB_RATE, MAX_VERTICAL_RATE
from geo_utils import heading_of

LANDED_ALT_M = 12.0


class Route:
    def __init__(self, xy: np.ndarray, alt_s: np.ndarray, alt_v: np.ndarray) -> None:
        self.xy = np.asarray(xy, dtype=float)
        seg = np.hypot(*np.diff(self.xy, axis=0).T) if len(self.xy) > 1 else np.zeros(0)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.length = float(self.cum[-1])
        self.alt_s = alt_s
        self.alt_v = alt_v

    def pos(self, s):
        s = np.clip(s, 0.0, self.length)
        return np.interp(s, self.cum, self.xy[:, 0]), np.interp(s, self.cum, self.xy[:, 1])

    def point(self, s: float) -> tuple[float, float]:
        x, y = self.pos(s)
        return float(x), float(y)

    def heading(self, s: float) -> float:
        if len(self.xy) < 2:
            return 0.0
        i = int(np.clip(np.searchsorted(self.cum, s, side="right") - 1, 0, len(self.xy) - 2))
        dx, dy = self.xy[i + 1] - self.xy[i]
        return heading_of(float(dx), float(dy))

    def alt(self, s):
        return np.interp(s, self.alt_s, self.alt_v)

    def between(self, s0: float, s1: float) -> np.ndarray:
        s0 = float(np.clip(s0, 0.0, self.length))
        s1 = float(np.clip(s1, s0, self.length))
        inner = self.xy[(self.cum > s0) & (self.cum < s1)]
        return np.vstack([np.array([self.point(s0)]), inner, np.array([self.point(s1)])])

    def remaining(self, s: float) -> np.ndarray:
        return self.between(s, self.length)

    def closest_s(self, x: float, y: float, s_min: float = 0.0) -> tuple[float, float]:
        """(arc length, distance) of the route point nearest (x, y), at or after s_min."""
        best = (s_min, float("inf"))
        for i in range(len(self.xy) - 1):
            if self.cum[i + 1] < s_min:
                continue
            a, b = self.xy[i], self.xy[i + 1]
            d = b - a
            L2 = float(d @ d)
            t = 0.0 if L2 == 0 else float(np.clip(((x - a[0]) * d[0] + (y - a[1]) * d[1]) / L2, 0.0, 1.0))
            s = self.cum[i] + t * (self.cum[i + 1] - self.cum[i])
            if s < s_min:
                s, t = s_min, (s_min - self.cum[i]) / max(self.cum[i + 1] - self.cum[i], 1e-9)
            px, py = a + t * d
            dist = float(np.hypot(px - x, py - y))
            if dist < best[1]:
                best = (float(s), dist)
        return best


def altitude_profile(
    xy: np.ndarray,
    start_alt: float,
    cruise_alt: float,
    end_alt: float,
    speed: float,
    ceiling: Callable[[np.ndarray, np.ndarray], np.ndarray],
    spacing: float = 40.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Cruise altitude under every ceiling on the way, climbing and descending at CLIMB_RATE."""
    tmp = Route(xy, np.array([0.0, 1.0]), np.array([0.0, 0.0]))
    L = tmp.length
    s = np.unique(np.concatenate([np.arange(0.0, L, spacing), [L]]))
    if len(s) < 2:
        s = np.array([0.0, max(L, 1.0)])
    x, y = tmp.pos(s)
    target = np.maximum(np.minimum(cruise_alt, ceiling(x, y)), ALT_MIN_M)
    target[-1] = end_alt
    slope = CLIMB_RATE / max(speed, 5.0)
    ds = np.diff(s)
    a = np.empty_like(target)
    a[0] = start_alt
    for k in range(1, len(s)):
        step = slope * ds[k - 1]
        a[k] = min(max(target[k], a[k - 1] - step), a[k - 1] + step)
    a[-1] = end_alt
    for k in range(len(s) - 2, 0, -1):
        a[k] = min(a[k], a[k + 1] + slope * ds[k])
    return s, a


def make_route(xy, start_alt, cruise_alt, end_alt, speed, ceiling) -> Route:
    s, a = altitude_profile(np.asarray(xy, dtype=float), start_alt, cruise_alt, end_alt, speed, ceiling)
    return Route(xy, s, a)


@dataclass
class AltOverride:
    """Temporary climb or descent over a stretch of route, blended into the base profile."""

    kind: str  # "climb" | "descend"
    alt: float
    s_start: float
    s_full: float
    s_release: float
    s_end: float

    def apply(self, s, base):
        s = np.asarray(s, dtype=float)
        f = np.zeros_like(s)
        up = (s >= self.s_start) & (s < self.s_full)
        f = np.where(up, (s - self.s_start) / max(self.s_full - self.s_start, 1e-6), f)
        f = np.where((s >= self.s_full) & (s <= self.s_release), 1.0, f)
        down = (s > self.s_release) & (s < self.s_end)
        f = np.where(down, 1.0 - (s - self.s_release) / max(self.s_end - self.s_release, 1e-6), f)
        return base + f * (self.alt - base)


@dataclass
class Motion:
    route: Route
    s: float
    speed: float
    alt: float
    hold_until: float = 0.0
    override: AltOverride | None = None

    def target_alt(self, s):
        base = self.route.alt(s)
        if self.override is not None:
            base = self.override.apply(s, base)
        return base

    def copy(self, **changes) -> "Motion":
        fields = dict(
            route=self.route, s=self.s, speed=self.speed, alt=self.alt, hold_until=self.hold_until, override=self.override
        )
        fields.update(changes)
        return Motion(**fields)


def predict(motion: Motion, now: float, dts: np.ndarray) -> np.ndarray:
    """(len(dts), 4) array of x, y, alt, s at now + dts."""
    hold_left = max(0.0, motion.hold_until - now)
    travel = np.maximum(0.0, dts - hold_left) * motion.speed
    s = np.minimum(motion.s + travel, motion.route.length)
    x, y = motion.route.pos(s)
    target = motion.target_alt(s)
    z = np.clip(target, motion.alt - MAX_VERTICAL_RATE * dts, motion.alt + MAX_VERTICAL_RATE * dts)
    return np.stack([x, y, z, s], axis=1)


def altitude_window(motion: Motion, s_conflict: float, alt: float, margin_m: float) -> AltOverride:
    """Build a climb/descent that is fully established margin_m before s_conflict and held past it."""
    base = float(motion.target_alt(motion.s))
    ramp = abs(alt - base) / (CLIMB_RATE / max(motion.speed, 5.0))
    s_full = max(motion.s + 1.0, s_conflict - margin_m)
    s_start = max(motion.s, s_full - ramp)
    s_release = min(motion.route.length, s_conflict + margin_m)
    s_end = min(motion.route.length, s_release + ramp)
    return AltOverride("climb" if alt > base else "descend", alt, s_start, s_full, s_release, s_end)
