"""
Dynamic Risk Map: every hazard the planner weighs, on one 150 m grid.

Static layers are built once from the real Dubai data:
    hard_static     restricted-airspace cores (cost = infinity)
    buffer_static   soft rings around them (5 or 25 per metre, by category)
    ceiling         max altitude; lower inside airport buffers
    ground_static   OSM water / urban land / roads / crowd (soft cost; never inf / hard_static)
    landing_dist    metres to the nearest drone port, for degraded drones

Dynamic layers change during the demo:
    hard_zones, buffer_zones   operator no-fly rings and emergency zones
    ground_dyn                 ground-monitor cameras (AU-AIR detections)
    route_count                how many planned routes use each cell (congestion)
    aircraft_cost/_hard        predicted manned-aircraft volumes

`cost_field` folds the layers into one per-metre cost with a drone's own weights; hard
cells come back as infinity. `version` changes whenever a hard or buffer layer does, which
is how the simulation knows existing routes must be re-checked.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from config import (
    AIRPORT_CEILING_M,
    ALT_MAX_M,
    CELL_M,
    COST_AIRCRAFT,
    COST_CONGESTION,
    CROWD_RADIUS_M,
    GROUND_COST,
    URBAN_GROUND_COST,
)
from world import World


@dataclass
class Weights:
    """Multi-objective weights for one plan. Tuned per drone from battery and health."""

    distance: float = 1.0
    energy: float = 0.4
    altitude: float = 0.3
    ground: float = 1.0
    traffic: float = 1.0
    risk_scale: float = 1.0  # health: degraded drones feel every risk more
    landing: float = 0.0  # health: prefer staying near a port
    deviation: float = 0.0  # stay near the original route when replanning
    cruise_alt: float = 100.0

    def to_dict(self) -> dict:
        return {k: round(v, 2) for k, v in self.__dict__.items()}


class RiskMap:
    def __init__(self, world: World) -> None:
        self.world = world
        self.cell = CELL_M
        self.x0, self.y0 = world.x_min, world.y_min
        self.cols = int(math.ceil((world.x_max - world.x_min) / self.cell))
        self.rows = int(math.ceil((world.y_max - world.y_min) / self.cell))
        self.xc = self.x0 + (np.arange(self.cols) + 0.5) * self.cell
        self.yc = self.y0 + (np.arange(self.rows) + 0.5) * self.cell
        self.X, self.Y = np.meshgrid(self.xc, self.yc)
        shape = (self.rows, self.cols)

        self.hard_static = np.zeros(shape, dtype=bool)
        self.buffer_static = np.zeros(shape, dtype=np.float32)
        self.ceiling = np.full(shape, ALT_MAX_M, dtype=np.float32)
        self.zone_label = np.full(shape, -1, dtype=np.int16)
        self.water = np.zeros(shape, dtype=bool)
        self.ground_static = np.zeros(shape, dtype=np.float32)
        self.landing_dist = np.zeros(shape, dtype=np.float32)

        self.hard_zones = np.zeros(shape, dtype=bool)
        self.buffer_zones = np.zeros(shape, dtype=np.float32)
        self.ground_dyn = np.zeros(shape, dtype=np.float32)
        self.route_count = np.zeros(shape, dtype=np.int16)
        self.aircraft_cost = np.zeros(shape, dtype=np.float32)
        self.aircraft_hard = np.zeros(shape, dtype=bool)
        self.version = 0

        self._build_static()

    # --- grid helpers -----------------------------------------------------------

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        c = int((x - self.x0) // self.cell)
        r = int((y - self.y0) // self.cell)
        return min(max(r, 0), self.rows - 1), min(max(c, 0), self.cols - 1)

    def cells_of(self, xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        c = np.clip(((xs - self.x0) // self.cell).astype(int), 0, self.cols - 1)
        r = np.clip(((ys - self.y0) // self.cell).astype(int), 0, self.rows - 1)
        return r, c

    def center(self, r: int, c: int) -> tuple[float, float]:
        return float(self.xc[c]), float(self.yc[r])

    def _window(self, x0: float, y0: float, x1: float, y1: float) -> tuple[slice, slice]:
        r0, c0 = self.cell_of(x0, y0)
        r1, c1 = self.cell_of(x1, y1)
        return slice(r0, r1 + 1), slice(c0, c1 + 1)

    @property
    def hard(self) -> np.ndarray:
        return self.hard_static | self.hard_zones | self.aircraft_hard

    # --- static layers ------------------------------------------------------------

    def _build_static(self) -> None:
        w = self.world
        # A cell is hard if the zone reaches into it at all, not just its centre.
        reach = self.cell * 0.72
        for idx, zone in enumerate(w.restricted):
            x0, y0, x1, y1 = zone.bbox
            pad = zone.buffer_m + self.cell
            rs, cs = self._window(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
            d = zone.signed_distance(self.X[rs, cs], self.Y[rs, cs])
            core = d <= reach
            self.hard_static[rs, cs] |= core
            self.zone_label[rs, cs] = np.where(core & (self.zone_label[rs, cs] < 0), idx, self.zone_label[rs, cs])
            ring = (~core) & (d <= zone.buffer_m)
            self.buffer_static[rs, cs] = np.where(
                ring, np.maximum(self.buffer_static[rs, cs], zone.buffer_cost), self.buffer_static[rs, cs]
            )
            if zone.category in ("airport", "approach"):
                self.ceiling[rs, cs] = np.where(d <= zone.buffer_m, np.minimum(self.ceiling[rs, cs], AIRPORT_CEILING_M), self.ceiling[rs, cs])

        lat, lon = w.frame.to_latlon(self.X, self.Y)
        self.water = w.water.at(lat, lon)
        self.ground_static = np.where(self.water, 0.0, URBAN_GROUND_COST).astype(np.float32)

        road = np.zeros_like(self.water)
        for line in w.roads:
            seg = np.diff(line, axis=0)
            for (ax, ay), (dx, dy) in zip(line[:-1], seg):
                n = max(2, int(math.hypot(dx, dy) / (self.cell / 4)) + 1)
                t = np.linspace(0.0, 1.0, n)
                r, c = self.cells_of(ax + dx * t, ay + dy * t)
                road[r, c] = True
        self.ground_static = np.where(road & ~self.water, GROUND_COST["MEDIUM"], self.ground_static)

        for crowd in w.crowds:
            rs, cs = self._window(crowd.x - CROWD_RADIUS_M, crowd.y - CROWD_RADIUS_M, crowd.x + CROWD_RADIUS_M, crowd.y + CROWD_RADIUS_M)
            near = np.hypot(self.X[rs, cs] - crowd.x, self.Y[rs, cs] - crowd.y) <= CROWD_RADIUS_M
            self.ground_static[rs, cs] = np.where(near, np.maximum(self.ground_static[rs, cs], GROUND_COST["HIGH"]), self.ground_static[rs, cs])

        dist = np.full(self.X.shape, np.inf, dtype=np.float32)
        for port in w.ports:
            dist = np.minimum(dist, np.hypot(self.X - port.x, self.Y - port.y))
        self.landing_dist = dist

    # --- dynamic layers -------------------------------------------------------------

    def set_zones(self, zones: list) -> None:
        """Operator no-fly rings and emergency zones (circles with a soft buffer)."""
        hard = np.zeros_like(self.hard_zones)
        buf = np.zeros_like(self.buffer_zones)
        reach = self.cell * 0.72
        for z in zones:
            outer = z.radius + z.buffer
            rs, cs = self._window(z.x - outer - self.cell, z.y - outer - self.cell, z.x + outer + self.cell, z.y + outer + self.cell)
            d = np.hypot(self.X[rs, cs] - z.x, self.Y[rs, cs] - z.y) - z.radius
            hard[rs, cs] |= d <= reach
            ring = (d > reach) & (d <= z.buffer)
            buf[rs, cs] = np.where(ring, np.maximum(buf[rs, cs], z.buffer_cost), buf[rs, cs])
        if not (np.array_equal(hard, self.hard_zones) and np.array_equal(buf, self.buffer_zones)):
            self.hard_zones = hard
            self.buffer_zones = buf
            self.version += 1

    def set_ground(self, sites: list) -> None:
        layer = np.zeros_like(self.ground_dyn)
        for s in sites:
            cost = GROUND_COST.get(s.level, 0.0)
            if cost <= 0:
                continue
            rs, cs = self._window(s.x - s.radius, s.y - s.radius, s.x + s.radius, s.y + s.radius)
            d = np.hypot(self.X[rs, cs] - s.x, self.Y[rs, cs] - s.y)
            # Full cost over the watched stretch, tapering to half at its edge.
            val = np.where(d <= s.radius, cost * (1.0 - 0.5 * d / s.radius), 0.0)
            layer[rs, cs] = np.maximum(layer[rs, cs], val)
        self.ground_dyn = layer.astype(np.float32)

    def set_routes(self, route_cells: dict[str, np.ndarray]) -> None:
        count = np.zeros(self.rows * self.cols, dtype=np.int16)
        for cells in route_cells.values():
            np.add.at(count, cells, 1)
        self.route_count = count.reshape(self.rows, self.cols)

    def set_aircraft(self, volumes: list[tuple[np.ndarray, float, float]]) -> None:
        """volumes: (predicted xy points, exclusion radius, proximity radius) per relevant aircraft."""
        cost = np.zeros_like(self.aircraft_cost)
        hard = np.zeros_like(self.aircraft_hard)
        for pts, r_hard, r_soft in volumes:
            if len(pts) == 0:
                continue
            x0, y0 = pts.min(axis=0) - r_soft
            x1, y1 = pts.max(axis=0) + r_soft
            rs, cs = self._window(x0, y0, x1, y1)
            X, Y = self.X[rs, cs], self.Y[rs, cs]
            d = np.full(X.shape, np.inf)
            for px, py in pts[:: max(1, len(pts) // 24)]:
                d = np.minimum(d, np.hypot(X - px, Y - py))
            cost[rs, cs] = np.maximum(cost[rs, cs], np.where(d <= r_soft, COST_AIRCRAFT, 0.0))
            # Only the aircraft's next seconds are a hard block; further out it is a cost.
            hx, hy = pts[0]
            near = np.hypot(X - hx, Y - hy) <= r_hard
            hard[rs, cs] |= near
        changed = not np.array_equal(hard, self.aircraft_hard)
        self.aircraft_cost = cost
        self.aircraft_hard = hard
        if changed:
            self.version += 1

    # --- the combined field -----------------------------------------------------------

    def cost_field(
        self,
        w: Weights,
        own_cells: np.ndarray | None = None,
        original: np.ndarray | None = None,
        avoid: np.ndarray | None = None,
    ) -> np.ndarray:
        """Per-metre cost for one plan; np.inf where the cell is a hard block."""
        others = self.route_count.astype(np.float32)
        if own_cells is not None and len(own_cells):
            flat = others.ravel()
            np.subtract.at(flat, own_cells, 1)
            others = flat.reshape(self.rows, self.cols)
        # One crossing route is normal traffic the 4-D predictor handles; two or more is a corridor.
        congestion = np.where(others >= 2, COST_CONGESTION, 0.0)

        ground = np.maximum(self.ground_static, self.ground_dyn)
        traffic = congestion + self.aircraft_cost
        buffers = np.maximum(self.buffer_static, self.buffer_zones)
        alt_penalty = np.maximum(0.0, w.cruise_alt - self.ceiling) / 40.0

        field = (
            w.distance
            + w.energy
            + w.altitude * alt_penalty
            + w.risk_scale * (w.ground * ground + w.traffic * traffic + buffers)
        )
        if w.landing > 0:
            field = field + w.landing * self.landing_dist / 1000.0
        if w.deviation > 0 and original is not None and len(original) >= 2:
            field = field + w.deviation * np.minimum(self.distance_to_polyline(original), 2000.0) / 250.0
        if avoid is not None:
            field = field + avoid
        field = field.astype(np.float32)
        field[self.hard] = np.inf
        return field

    def distance_to_polyline(self, xy: np.ndarray) -> np.ndarray:
        # Sampled every half cell: the result feeds a soft cost, so sub-cell error is fine.
        pts = densify(xy, self.cell / 2)
        best = np.full(self.X.shape, np.inf, dtype=np.float32)
        for px, py in pts:
            best = np.minimum(best, np.hypot(self.X - px, self.Y - py))
        return best

    def blob(self, pts: np.ndarray, radius: float, cost: float) -> np.ndarray:
        """Temporary extra cost around points, e.g. another drone's predicted positions."""
        layer = np.zeros(self.X.shape, dtype=np.float32)
        if len(pts) == 0:
            return layer
        x0, y0 = pts.min(axis=0) - radius
        x1, y1 = pts.max(axis=0) + radius
        rs, cs = self._window(x0, y0, x1, y1)
        X, Y = self.X[rs, cs], self.Y[rs, cs]
        d = np.full(X.shape, np.inf)
        for px, py in pts:
            d = np.minimum(d, np.hypot(X - px, Y - py))
        layer[rs, cs] = np.where(d <= radius, cost, 0.0)
        return layer

    # --- geometry checks against the grid ---------------------------------------------

    def segment(self, p: tuple[float, float], q: tuple[float, float], field: np.ndarray) -> tuple[bool, float]:
        """(clear of hard cells, integrated cost) for the straight segment p -> q."""
        length = math.hypot(q[0] - p[0], q[1] - p[1])
        n = max(2, int(length / (self.cell / 3)) + 1)
        t = np.linspace(0.0, 1.0, n)
        r, c = self.cells_of(p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
        vals = field[r, c]
        if not np.all(np.isfinite(vals)):
            return False, math.inf
        return True, float(vals.mean() * length)

    def first_hard_along(self, xy: np.ndarray, hard: np.ndarray | None = None) -> float | None:
        """Arc length at which a polyline first touches a hard cell, or None."""
        hard = self.hard if hard is None else hard
        pts, s = densify_with_s(xy, self.cell / 3)
        r, c = self.cells_of(pts[:, 0], pts[:, 1])
        hits = np.nonzero(hard[r, c])[0]
        return float(s[hits[0]]) if len(hits) else None

    def first_entry_along(self, xy: np.ndarray, hard: np.ndarray | None = None) -> float | None:
        """
        Arc length at which a polyline enters a hard cell from open airspace. A run of hard
        cells at the very start is ignored: that is a drone already in a zone's rasterised
        edge on its way out, which the escape logic owns.
        """
        hard = self.hard if hard is None else hard
        pts, s = densify_with_s(xy, self.cell / 3)
        r, c = self.cells_of(pts[:, 0], pts[:, 1])
        flags = hard[r, c]
        start = 0
        if flags[0]:
            open_idx = np.nonzero(~flags)[0]
            if len(open_idx) == 0:
                return None
            start = int(open_idx[0])
        hits = np.nonzero(flags[start:])[0]
        return float(s[start + hits[0]]) if len(hits) else None

    def route_cells(self, xy: np.ndarray) -> np.ndarray:
        pts = densify(xy, self.cell / 2)
        r, c = self.cells_of(pts[:, 0], pts[:, 1])
        return np.unique(r * self.cols + c)

    def ceiling_at(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        r, c = self.cells_of(xs, ys)
        return self.ceiling[r, c]

    def ground_at(self, x: float, y: float) -> float:
        r, c = self.cell_of(x, y)
        return float(max(self.ground_static[r, c], self.ground_dyn[r, c]))


def densify(xy: np.ndarray, step: float) -> np.ndarray:
    return densify_with_s(xy, step)[0]


def densify_with_s(xy: np.ndarray, step: float) -> tuple[np.ndarray, np.ndarray]:
    xy = np.asarray(xy, dtype=float)
    if len(xy) < 2:
        return xy, np.zeros(len(xy))
    seg = np.hypot(*np.diff(xy, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(2, int(cum[-1] / step) + 1)
    s = np.linspace(0.0, cum[-1], n)
    return np.stack([np.interp(s, cum, xy[:, 0]), np.interp(s, cum, xy[:, 1])], axis=1), s
