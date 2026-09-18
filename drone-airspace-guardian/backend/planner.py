"""
Multi-objective weighted A* over the Dynamic Risk Map.

The search minimises the per-metre cost field from RiskMap.cost_field, which already folds
distance, energy, altitude penalties, ground risk, traffic and original-route deviation
into one number per cell with the drone's own weights. Hard cells are never expanded.

"Weighted" is used twice over: the objectives are weighted, and the heuristic is inflated
by ASTAR_EPSILON (1.25), which bounds the result at 25% above the optimal cost while
expanding far fewer cells, so a replan fits inside a simulation tick.

The raw 8-connected cell path is then string-pulled: a waypoint is skipped when the
straight line past it is clear of hard cells and no more expensive than the path it
replaces. Routes come out as a few smooth legs that bend around zones.
"""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field

import numpy as np

from config import ASTAR_EPSILON, ASTAR_MAX_EXPANSIONS
from risk_map import RiskMap, Weights

SQRT2 = math.sqrt(2.0)
_NEIGHBORS = ((-1, -1, SQRT2), (-1, 0, 1.0), (-1, 1, SQRT2), (0, -1, 1.0), (0, 1, 1.0), (1, -1, SQRT2), (1, 0, 1.0), (1, 1, SQRT2))


@dataclass
class Plan:
    xy: np.ndarray
    length: float
    cost: float
    expansions: int
    ms: float
    weights: Weights
    notes: list[str] = field(default_factory=list)


def _free_cell_near(blocked: np.ndarray, r: int, c: int, max_ring: int = 40) -> tuple[int, int] | None:
    if not blocked[r, c]:
        return r, c
    rows, cols = blocked.shape
    for ring in range(1, max_ring + 1):
        best = None
        for dr in range(-ring, ring + 1):
            for dc in (-ring, ring) if abs(dr) != ring else range(-ring, ring + 1):
                rr, cc = r + dr, c + dc
                if 0 <= rr < rows and 0 <= cc < cols and not blocked[rr, cc]:
                    d = dr * dr + dc * dc
                    if best is None or d < best[0]:
                        best = (d, rr, cc)
        if best:
            return best[1], best[2]
    return None


def astar(field2d: np.ndarray, start: tuple[int, int], goal: tuple[int, int], cell: float, eps: float = ASTAR_EPSILON):
    """Returns (cell path, g-cost per path cell, expansions) or (None, None, expansions)."""
    rows, cols = field2d.shape
    cost = field2d.ravel().tolist()
    finite = np.isfinite(field2d)
    min_cost = float(field2d[finite].min()) if finite.any() else 1.0
    s_idx = start[0] * cols + start[1]
    g_idx = goal[0] * cols + goal[1]
    gr, gc = goal
    hscale = cell * min_cost * eps
    diag_extra = SQRT2 - 2.0

    inf = math.inf
    g = [inf] * (rows * cols)
    came = [-1] * (rows * cols)
    closed = bytearray(rows * cols)
    g[s_idx] = 0.0
    heap = [(0.0, s_idx)]
    expansions = 0
    while heap:
        _, cur = heapq.heappop(heap)
        if closed[cur]:
            continue
        if cur == g_idx:
            path = [cur]
            while came[path[-1]] >= 0:
                path.append(came[path[-1]])
            path.reverse()
            return [divmod(i, cols) for i in path], [g[i] for i in path], expansions
        closed[cur] = 1
        expansions += 1
        if expansions > ASTAR_MAX_EXPANSIONS:
            break
        r, c = divmod(cur, cols)
        gcur = g[cur]
        ccur = cost[cur]
        for dr, dc, step in _NEIGHBORS:
            nr = r + dr
            nc = c + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            n = nr * cols + nc
            cn = cost[n]
            if cn == inf or closed[n]:
                continue
            # No squeezing diagonally between two blocked cells.
            if dr and dc and (cost[r * cols + nc] == inf or cost[nr * cols + c] == inf):
                continue
            ng = gcur + step * cell * (ccur + cn) * 0.5
            if ng < g[n]:
                g[n] = ng
                came[n] = cur
                ar = abs(nr - gr)
                ac = abs(nc - gc)
                h = (ar + ac + diag_extra * (ar if ar < ac else ac)) * hscale
                heapq.heappush(heap, (ng + h, n))
    return None, None, expansions


def string_pull(riskmap: RiskMap, pts: list[tuple[float, float]], g: list[float], field2d: np.ndarray) -> list[tuple[float, float]]:
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    i = 0
    n = len(pts)
    while i < n - 1:
        j = i + 1
        k = j + 1
        while k < n:
            clear, seg_cost = riskmap.segment(pts[i], pts[k], field2d)
            if not clear or seg_cost > (g[k] - g[i]) * 1.001 + 1.0:
                break
            j = k
            k += 1
        out.append(pts[j])
        i = j
    return out


def plan_route(
    riskmap: RiskMap,
    start: tuple[float, float],
    goal: tuple[float, float],
    weights: Weights,
    *,
    own_cells: np.ndarray | None = None,
    original: np.ndarray | None = None,
    avoid: np.ndarray | None = None,
    field2d: np.ndarray | None = None,
) -> Plan | None:
    t0 = time.perf_counter()
    if field2d is None:
        field2d = riskmap.cost_field(weights, own_cells=own_cells, original=original, avoid=avoid)
    notes: list[str] = []
    blocked = ~np.isfinite(field2d)

    sr, sc = riskmap.cell_of(*start)
    if blocked[sr, sc]:
        # The drone is on a hard cell (a zone's rasterised edge, or an aircraft volume that
        # just swept over it). Open only the shortest chain of cells out, at a steep price.
        field2d = field2d.copy()
        for r, c in _way_out(blocked, sr, sc):
            field2d[r, c] = 60.0
        blocked = ~np.isfinite(field2d)
        notes.append("start inside a hard cell")
    gcell = _free_cell_near(blocked, *riskmap.cell_of(*goal))
    if gcell is None:
        return None
    if gcell != riskmap.cell_of(*goal):
        notes.append("goal moved to the nearest open cell")
        goal = riskmap.center(*gcell)

    cells, gs, expansions = astar(field2d, (sr, sc), gcell, riskmap.cell)
    if cells is None:
        return None
    pts = [riskmap.center(r, c) for r, c in cells]
    pts[0] = (float(start[0]), float(start[1]))
    pts[-1] = (float(goal[0]), float(goal[1]))
    smooth = string_pull(riskmap, pts, gs, field2d)
    xy = np.array(smooth, dtype=float)
    length = float(np.hypot(*np.diff(xy, axis=0).T).sum()) if len(xy) > 1 else 0.0
    return Plan(xy, length, float(gs[-1]), expansions, (time.perf_counter() - t0) * 1000, weights, notes)


def _way_out(blocked: np.ndarray, r: int, c: int) -> list[tuple[int, int]]:
    """Hard cells on the shortest 8-connected path from (r, c) to the nearest open cell."""
    rows, cols = blocked.shape
    parent: dict[tuple[int, int], tuple[int, int] | None] = {(r, c): None}
    frontier = [(r, c)]
    while frontier:
        nxt = []
        for cell in frontier:
            for dr, dc, _ in _NEIGHBORS:
                q = (cell[0] + dr, cell[1] + dc)
                if not (0 <= q[0] < rows and 0 <= q[1] < cols) or q in parent:
                    continue
                parent[q] = cell
                if not blocked[q]:
                    path = []
                    node: tuple[int, int] | None = cell
                    while node is not None:
                        path.append(node)
                        node = parent[node]
                    return path
                nxt.append(q)
        frontier = nxt
    return [(r, c)]
