"""
Emergency Escape Planner, and no-fly avoidance for zones that appear mid-flight.

A drone caught inside an emergency zone has two objectives that pull apart: get out by the
shortest safe way, and stay as close as it can to the route it was flying. Candidate exits
are spread every 10 degrees just outside the zone edge and scored on

    3.0 x escape distance      exposure inside the zone is what matters most
  + 1.0 x deviation            distance from the exit to the original route still ahead
  + 0.5 x rejoin distance      exit to the point where the original route resumes
  + collision risk             other drones' predicted positions along the escape leg
  + ground / airspace risk     what the drone would be hovering over at the exit

Exits whose straight leg crosses other restricted airspace are dropped. The winner is flown
straight out at escape speed; weighted A* then routes around the zone (now a hard block) to
a rejoin point on the original trajectory past the zone, and the rest of the original route
is kept. If the destination itself is inside the zone the mission diverts to the nearest
drone port instead.

Drones outside the zone whose remaining route runs into it (or into any other new hard
block) are rerouted before they reach it: A* from where they are to the first clear point
on their original route beyond the blockage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from config import DRONE_H_SEP_M, DRONE_V_SEP_M, ESCAPE_SPEED_FACTOR, MAX_SPEED
from risk_map import densify
from trajectory import LANDED_ALT_M, Motion, Route
from world import Place

EXIT_MARGIN_M = 230.0  # clear of every rasterised hard cell: they reach 108 m past the edge, plus half a diagonal
REJOIN_MARGIN_M = 200.0


@dataclass
class EscapePlan:
    motion: Motion
    exit_xy: tuple[float, float]
    bearing: float
    escape_m: float
    rejoin_s: float | None
    divert: Place | None
    candidates: int
    cost: float


def rejoin_arc(route: Route, blocked, s_from: float, margin: float = REJOIN_MARGIN_M) -> float | None:
    """First arc length past the last blocked stretch of `route` after s_from, or None if the end is blocked."""
    if route.length - s_from < 1.0:
        return None
    s = np.arange(s_from, route.length, 40.0)
    s = np.append(s, route.length)
    x, y = route.pos(s)
    hit = blocked(x, y)
    if not hit.any():
        return s_from
    last = int(np.nonzero(hit)[0].max())
    s_r = float(s[last]) + margin
    return None if s_r >= route.length - 30.0 else s_r


def plan_escape(sim, drone, zone) -> EscapePlan | None:
    rm = sim.riskmap
    world = sim.world
    px, py = drone.x, drone.y
    orig = drone.original or drone.motion.route
    s_orig, _ = orig.closest_s(px, py)
    speed = min(MAX_SPEED, drone.cruise_speed * ESCAPE_SPEED_FACTOR)

    def blocked(x, y):
        r, c = rm.cells_of(np.asarray(x), np.asarray(y))
        return rm.hard[r, c]

    divert: Place | None = None
    s_r = None
    if zone.contains(drone.destination.x, drone.destination.y, margin=zone.buffer):
        divert = nearest_open_port(sim, px, py, zone)
    else:
        s_r = rejoin_arc(orig, blocked, s_orig)
        if s_r is None:
            divert = nearest_open_port(sim, px, py, zone)
    target = (divert.x, divert.y) if divert else orig.point(s_r)

    static_hard = rm.hard_static | rm.aircraft_hard
    others = [(d.id, sim.conflicts.pred[d.id]) for d in sim.airborne() if d.id != drone.id and d.id in sim.conflicts.pred]

    best = None
    evaluated = 0
    for bearing in range(0, 360, 10):
        b = math.radians(bearing)
        ex = zone.x + math.sin(b) * (zone.radius + EXIT_MARGIN_M)
        ey = zone.y + math.cos(b) * (zone.radius + EXIT_MARGIN_M)
        if not world.in_bounds(ex, ey, 150.0):
            continue
        leg = densify(np.array([[px, py], [ex, ey]]), rm.cell / 3)
        r, c = rm.cells_of(leg[:, 0], leg[:, 1])
        if static_hard[r, c].any():
            continue
        evaluated += 1
        escape = math.hypot(ex - px, ey - py)
        if divert:
            deviation = 0.0
        else:
            _, deviation = orig.closest_s(ex, ey, s_min=s_orig)
        rejoin = math.hypot(target[0] - ex, target[1] - ey)
        risk = _collision_risk(drone, others, (px, py), (ex, ey), speed)
        ground = rm.ground_at(ex, ey)
        cost = 3.0 * escape + 1.0 * deviation + 0.5 * rejoin + risk + 40.0 * ground
        if best is None or cost < best[0]:
            best = (cost, bearing, (ex, ey), escape)

    if best is None:
        # Nothing scored (boxed in by other airspace): leave radially, the shortest way out.
        bearing = math.degrees(math.atan2(px - zone.x, py - zone.y)) % 360
        b = math.radians(bearing)
        exit_xy = (zone.x + math.sin(b) * (zone.radius + EXIT_MARGIN_M), zone.y + math.cos(b) * (zone.radius + EXIT_MARGIN_M))
        best = (math.inf, bearing, exit_xy, math.hypot(exit_xy[0] - px, exit_xy[1] - py))
    cost, bearing, exit_xy, escape = best

    original_tail = None if divert else orig.remaining(s_r)
    plan = sim.plan_for(drone, exit_xy, target, deviation=0.0 if divert else 1.0, original=original_tail)
    middle = plan.xy if plan is not None else np.array([exit_xy, target])
    parts = [np.array([[px, py]]), middle]
    rejoin_s = None
    if not divert:
        head = np.vstack(parts)
        rejoin_s = float(np.hypot(*np.diff(head, axis=0).T).sum())
        parts.append(orig.between(s_r, orig.length)[1:])
    xy = np.vstack(parts)
    route = sim.build_route(drone, xy, start_alt=drone.alt)
    motion = Motion(route, 0.0, speed, drone.alt)
    return EscapePlan(motion, exit_xy, float(bearing), float(escape), rejoin_s, divert, evaluated, float(cost))


def _collision_risk(drone, others, p, e, speed) -> float:
    """Penalty for flying the straight escape leg through other drones' predicted positions."""
    length = math.hypot(e[0] - p[0], e[1] - p[1])
    n = max(2, int(length / max(speed, 1.0)) + 2)
    t = np.arange(n)
    frac = np.clip(t * speed / max(length, 1.0), 0.0, 1.0)
    lx = p[0] + (e[0] - p[0]) * frac
    ly = p[1] + (e[1] - p[1]) * frac
    penalty = 0.0
    for _, pred in others:
        k = min(n, len(pred))
        dh = np.hypot(pred[:k, 0] - lx[:k], pred[:k, 1] - ly[:k])
        dz = np.abs(pred[:k, 2] - drone.alt)
        up = pred[:k, 2] > LANDED_ALT_M
        if np.any((dh < DRONE_H_SEP_M) & (dz < DRONE_V_SEP_M) & up):
            penalty += 5000.0
        else:
            near = np.where(up, np.maximum(0.0, 2 * DRONE_H_SEP_M - dh), 0.0)
            penalty += float(near.max()) * 5.0
    return penalty


def nearest_open_port(sim, x: float, y: float, zone=None) -> Place:
    ports = sim.world.ports
    if zone is not None:
        ports = [p for p in ports if not zone.contains(p.x, p.y, margin=zone.buffer)] or ports
    return min(ports, key=lambda p: math.hypot(p.x - x, p.y - y))


def plan_avoidance(sim, drone) -> tuple[Motion, float | None, Place | None, float] | None:
    """
    Reroute a drone whose route ahead enters a hard block. Returns (motion, rejoin arc,
    divert port or None, extra metres) or None when no route exists.
    """
    rm = sim.riskmap
    m = drone.motion
    orig = drone.original or m.route
    s_orig, _ = orig.closest_s(drone.x, drone.y)
    hard = rm.hard_static | rm.hard_zones

    def blocked(x, y):
        r, c = rm.cells_of(np.asarray(x), np.asarray(y))
        return hard[r, c]

    s_r = rejoin_arc(orig, blocked, s_orig)
    divert = None
    if s_r is None:
        divert = sim.world.nearest_port(drone.x, drone.y)
        plan = sim.plan_for(drone, (drone.x, drone.y), (divert.x, divert.y))
        if plan is None:
            return None
        xy = plan.xy
        rejoin_s = None
    else:
        s_r = max(s_r, s_orig + 150.0)
        target = orig.point(min(s_r, orig.length))
        plan = sim.plan_for(drone, (drone.x, drone.y), target, deviation=0.8, original=orig.remaining(s_r))
        if plan is None:
            return None
        rejoin_s = plan.length
        xy = np.vstack([plan.xy, orig.between(s_r, orig.length)[1:]])
    route = sim.build_route(drone, xy, start_alt=drone.alt)
    extra = route.length - (m.route.length - m.s)
    return Motion(route, 0.0, m.speed, drone.alt, m.hold_until), rejoin_s, divert, extra
