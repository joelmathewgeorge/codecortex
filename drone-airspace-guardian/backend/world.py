"""
The real Dubai operating area, loaded once from ml/dubai_airspace.json.

That file is built from OpenStreetMap by ml/build_airspace.py: restricted airspace
(airports and runway funnels, military and police sites, stadiums, Meydan, power plants,
Zabeel Palace), drone ports, hospitals, malls, districts, motorway/trunk roads, the
coastline-derived water mask and DXB's runway ends.
"""

from __future__ import annotations

import base64
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from config import AIRSPACE_FILE, RESTRICTED_POLICY
from geo_utils import LocalFrame


def points_in_polygon(px: np.ndarray, py: np.ndarray, poly: np.ndarray) -> np.ndarray:
    inside = np.zeros(np.shape(px), dtype=bool)
    x1, y1 = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    for a, b, c, d in zip(x1, y1, x2, y2):
        crosses = (b > py) != (d > py)
        inside ^= crosses & (px < (c - a) * (py - b) / (d - b + 1e-12) + a)
    return inside


def distance_to_polygon_edges(px: np.ndarray, py: np.ndarray, poly: np.ndarray) -> np.ndarray:
    best = np.full(np.shape(px), np.inf)
    x1, y1 = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    for a, b, c, d in zip(x1, y1, x2, y2):
        dx, dy = c - a, d - b
        L2 = dx * dx + dy * dy
        t = np.clip(((px - a) * dx + (py - b) * dy) / L2, 0.0, 1.0) if L2 > 0 else 0.0
        best = np.minimum(best, np.hypot(px - (a + t * dx), py - (b + t * dy)))
    return best


@dataclass
class Place:
    id: str
    name: str
    kind: str  # port | hospital | mall | district
    lat: float
    lon: float
    x: float
    y: float

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "lat": self.lat, "lon": self.lon}


@dataclass
class Restricted:
    id: str
    name: str
    category: str
    polygon: list[list[float]]
    xy: np.ndarray
    buffer_m: float
    buffer_cost: float
    bbox: tuple[float, float, float, float] = field(init=False)
    buffer_outline: list[list[float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.bbox = (
            float(self.xy[:, 0].min()),
            float(self.xy[:, 1].min()),
            float(self.xy[:, 0].max()),
            float(self.xy[:, 1].max()),
        )

    def signed_distance(self, px: np.ndarray, py: np.ndarray) -> np.ndarray:
        """Metres to the outline; negative inside."""
        d = distance_to_polygon_edges(px, py, self.xy)
        return np.where(points_in_polygon(px, py, self.xy), -d, d)

    def contains(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.bbox
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return False
        return bool(points_in_polygon(np.array([x]), np.array([y]), self.xy)[0])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "polygon": self.polygon,
            "bufferM": self.buffer_m,
            "bufferCost": self.buffer_cost,
            "buffer": self.buffer_outline,
        }


def convex_hull(points: np.ndarray) -> np.ndarray:
    pts = sorted(set(map(tuple, np.round(points, 2))))
    if len(pts) < 3:
        return np.array(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


class WaterMask:
    def __init__(self, meta: dict) -> None:
        bits = np.unpackbits(np.frombuffer(base64.b64decode(meta["bits"]), dtype=np.uint8))
        self.rows, self.cols = meta["rows"], meta["cols"]
        self.grid = bits[: self.rows * self.cols].reshape(self.rows, self.cols).astype(bool)
        self.south, self.west = meta["south"], meta["west"]
        self.dlat, self.dlon = meta["dlat"], meta["dlon"]

    def at(self, lat, lon) -> np.ndarray:
        r = np.clip(((np.asarray(lat) - self.south) / self.dlat).astype(int), 0, self.rows - 1)
        c = np.clip(((np.asarray(lon) - self.west) / self.dlon).astype(int), 0, self.cols - 1)
        return self.grid[r, c]


class World:
    def __init__(self, path: Path = AIRSPACE_FILE) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        b = data["bounds"]
        self.bounds = b
        self.source = data.get("source", "")
        self.license = data.get("license", "")
        self.frame = LocalFrame((b["south"] + b["north"]) / 2, (b["west"] + b["east"]) / 2)
        self.x_min, self.y_min = self.frame.point(b["south"], b["west"])
        self.x_max, self.y_max = self.frame.point(b["north"], b["east"])

        self.restricted: list[Restricted] = []
        for z in data["restricted"]:
            buffer_m, buffer_cost = RESTRICTED_POLICY.get(z["category"], (250.0, 5.0))
            ring = np.array(z["polygon"], dtype=float)
            x, y = self.frame.to_xy(ring[:, 0], ring[:, 1])
            zone = Restricted(z["id"], z["name"], z["category"], z["polygon"], np.stack([x, y], axis=1), buffer_m, buffer_cost)
            # Display outline of the soft buffer: the polygon grown by buffer_m, as a hull.
            angles = np.linspace(0.0, 2 * np.pi, 24, endpoint=False)
            ring = (zone.xy[:, None, :] + buffer_m * np.stack([np.cos(angles), np.sin(angles)], axis=1)[None, :, :]).reshape(-1, 2)
            hull = convex_hull(ring)
            blat, blon = self.frame.to_latlon(hull[:, 0], hull[:, 1])
            zone.buffer_outline = [[round(float(a), 6), round(float(o), 6)] for a, o in zip(blat, blon)]
            self.restricted.append(zone)

        def places(items: list[dict], kind: str, prefix: str) -> list[Place]:
            out = []
            for i, p in enumerate(items):
                x, y = self.frame.point(p["lat"], p["lon"])
                out.append(Place(p.get("id") or f"{prefix}-{i + 1}", p["name"], kind, p["lat"], p["lon"], x, y))
            return out

        self.ports = places(data["drone_ports"], "port", "port")
        self.hospitals = places(data["hospitals"], "hospital", "hosp")
        self.malls = places(data["malls"], "mall", "mall")
        self.crowds = places(data["crowds"], "mall", "crowd")
        self.districts = places(data["districts"], "district", "dist")
        self.runways = data.get("runways", [])
        self.water = WaterMask(data["water"])

        self.roads: list[np.ndarray] = []
        self.road_meta: list[dict] = []
        for r in data["roads"]:
            line = np.array(r["line"], dtype=float)
            x, y = self.frame.to_xy(line[:, 0], line[:, 1])
            self.roads.append(np.stack([x, y], axis=1))
            self.road_meta.append({"ref": r.get("ref", ""), "name": r.get("name", ""), "class": r.get("class", "")})

        # Destinations must be somewhere a drone may actually land.
        self.destinations = [p for p in self.hospitals + self.malls + self.districts if self.is_clear(p.x, p.y, 250.0)]

    # --- queries ---------------------------------------------------------------

    def in_bounds(self, x: float, y: float, margin: float = 0.0) -> bool:
        return self.x_min + margin <= x <= self.x_max - margin and self.y_min + margin <= y <= self.y_max - margin

    def is_water(self, x: float, y: float) -> bool:
        lat, lon = self.frame.to_latlon(x, y)
        return bool(self.water.at(lat, lon))

    def restricted_at(self, x: float, y: float, margin: float = 0.0) -> Restricted | None:
        for z in self.restricted:
            x0, y0, x1, y1 = z.bbox
            if x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin:
                d = z.signed_distance(np.array([x]), np.array([y]))[0]
                if d <= margin:
                    return z
        return None

    def is_clear(self, x: float, y: float, margin: float = 0.0) -> bool:
        return self.in_bounds(x, y, 300.0) and not self.is_water(x, y) and self.restricted_at(x, y, margin) is None

    def nearest(self, places: list[Place], x: float, y: float) -> Place:
        return min(places, key=lambda p: math.hypot(p.x - x, p.y - y))

    def nearest_port(self, x: float, y: float) -> Place:
        return self.nearest(self.ports, x, y)

    def find(self, name: str) -> Place | None:
        want = name.lower()
        for p in self.ports + self.hospitals + self.malls + self.districts:
            if p.name.lower() == want:
                return p
        for p in self.ports + self.hospitals + self.malls + self.districts:
            if want in p.name.lower():
                return p
        return None

    def random_destination(
        self,
        rng: random.Random,
        origin: tuple[float, float],
        min_m: float = 3500.0,
        max_m: float = 11000.0,
        kinds: tuple[str, ...] = ("hospital", "mall", "district"),
    ) -> Place:
        pool = [
            p
            for p in self.destinations
            if p.kind in kinds and min_m <= math.hypot(p.x - origin[0], p.y - origin[1]) <= max_m
        ]
        return rng.choice(pool or self.destinations)

    def to_dict(self) -> dict:
        return {
            "bounds": self.bounds,
            "source": self.source,
            "license": self.license,
            "restricted": [z.to_dict() for z in self.restricted],
            "ports": [p.to_dict() for p in self.ports],
            "hospitals": [p.to_dict() for p in self.hospitals],
            "crowds": [p.to_dict() for p in self.crowds],
            "runways": self.runways,
        }
