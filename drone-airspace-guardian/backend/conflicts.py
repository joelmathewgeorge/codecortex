"""
Trajectory conflict prediction and priority-based tactical deconfliction.

Every tick each airborne drone's motion is projected 75 s ahead as (x, y, alt) samples.
A pair is in conflict only if, at the same future second, they are closer than 150 m
horizontally AND 30 m vertically. Two route lines crossing on the map are not enough: the
crossings list reports those separately with the time and height gap at the crossing.

A predicted conflict stays red for DECISION_DELAY_S (or not at all when time-to-conflict is
under IMMEDIATE_TTC_S), then the lower-priority drone yields. It gets candidate manoeuvres
(climb, descend, hold, lateral detour, weighted-A* replan). Each is re-predicted against
every other drone, every relevant aircraft and the hard cells of the risk map, and the
cheapest safe one is flown. The conflict is resolved once the pair has passed its closest
point of approach with separation intact.

Manned aircraft always win: a drone predicted to enter an aircraft's safety volume
yields regardless of its own mission priority.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from config import (
    AIRCRAFT_HORIZON_S,
    AIRCRAFT_SEPARATION,
    ALT_MAX_M,
    ALT_MIN_M,
    CANDIDATE_HORIZON_S,
    DECISION_DELAY_S,
    DRONE_H_SEP_M,
    DRONE_V_SEP_M,
    IMMEDIATE_TTC_S,
    PREDICT_HORIZON_S,
    PREDICT_STEP_S,
    PRIORITY_RANK,
    RESOLVED_DISPLAY_S,
)
from trajectory import LANDED_ALT_M, Motion, altitude_window, predict

LONG_DTS = np.arange(0.0, CANDIDATE_HORIZON_S + 1e-9, PREDICT_STEP_S)
N_DETECT = int(PREDICT_HORIZON_S / PREDICT_STEP_S) + 1
N_AIRCRAFT = int(AIRCRAFT_HORIZON_S / PREDICT_STEP_S) + 1
ALT_COST_PER_M = 12.0  # climbing a metre costs about as much energy as flying twelve
HOVER_COST_PER_S = 22.0  # hover drain expressed in metres of cruise


@dataclass
class Candidate:
    kind: str
    label: str
    motion: Motion | None
    cost: float
    safe: bool = False
    reason: str = ""
    route_kind: str = "planned"
    rejoin_s: float | None = None

    def summary(self) -> dict:
        return {"kind": self.kind, "label": self.label, "safe": self.safe, "cost": round(self.cost) if math.isfinite(self.cost) else None, "reason": self.reason}


@dataclass
class Conflict:
    id: str
    kind: str  # drone | aircraft
    a: str
    b: str
    state: str
    first_seen: float
    t_first: float  # absolute sim time of the first predicted violation
    t_cpa: float
    point: tuple[float, float]
    min_h: float
    dz: float
    b_label: str = ""
    sep_h: float = DRONE_H_SEP_M
    yielding: str | None = None
    maneuver: str | None = None
    attempts: int = 0
    applied_at: float = -1.0
    resolved_at: float | None = None
    observed_min_h: float = math.inf
    observed_dz: float = math.inf
    last_distance: float = math.inf
    note: str = ""
    candidates: list[dict] = field(default_factory=list)


class ConflictManager:
    def __init__(self, sim) -> None:
        self.sim = sim
        self.active: dict[tuple[str, str], Conflict] = {}
        self.pred: dict[str, np.ndarray] = {}
        self.crossings: list[dict] = []
        self.resolved_total = 0
        self._ids = itertools.count(1)
        self._stack_ids: list[str] = []
        self._stack = np.zeros((0, len(LONG_DTS), 4))

    def reset(self) -> None:
        self.active.clear()
        self.pred.clear()
        self.crossings = []
        self.resolved_total = 0

    # --- per tick -------------------------------------------------------------------

    def update(self) -> None:
        sim = self.sim
        self.pred = {d.id: predict(d.motion, sim.now, LONG_DTS) for d in sim.airborne()}
        self._stack_ids = list(self.pred)
        self._stack = np.stack([self.pred[i] for i in self._stack_ids]) if self.pred else np.zeros((0, len(LONG_DTS), 4))
        found = self._detect_drone_pairs()
        found.update(self._detect_aircraft())
        self._reconcile(found)
        self._crossings()
        self._flag_drones()

    def _detect_drone_pairs(self) -> dict:
        ids = self._stack_ids
        if len(ids) < 2:
            return {}
        P = self._stack[:, :N_DETECT, :]
        valid = P[:, :, 2] > LANDED_ALT_M
        dh = np.hypot(P[:, None, :, 0] - P[None, :, :, 0], P[:, None, :, 1] - P[None, :, :, 1])
        dz = np.abs(P[:, None, :, 2] - P[None, :, :, 2])
        both = valid[:, None, :] & valid[None, :, :]
        viol = (dh < DRONE_H_SEP_M) & (dz < DRONE_V_SEP_M) & both
        out = {}
        for i, j in zip(*np.triu_indices(len(ids), 1)):
            v = viol[i, j]
            if not v.any():
                continue
            k_first = int(np.argmax(v))
            close = np.where(both[i, j] & (dz[i, j] < DRONE_V_SEP_M), dh[i, j], np.inf)
            k_cpa = int(np.argmin(close))
            a, b = sorted((ids[i], ids[j]))
            out[(a, b)] = {
                "kind": "drone",
                "t_first": float(LONG_DTS[k_first]),
                "k_cpa": k_cpa,
                "t_cpa": float(LONG_DTS[k_cpa]),
                "min_h": float(dh[i, j, k_cpa]),
                "dz": float(dz[i, j, k_cpa]),
                "point": ((P[i, k_cpa, 0] + P[j, k_cpa, 0]) / 2, (P[i, k_cpa, 1] + P[j, k_cpa, 1]) / 2),
            }
        return out

    def _detect_aircraft(self) -> dict:
        out = {}
        for ac in self.sim.aircraft.relevant():
            h_sep, v_sep = AIRCRAFT_SEPARATION[ac.kind]
            Q = ac.pred[:N_AIRCRAFT]
            for drone_id, P in self.pred.items():
                P = P[:N_AIRCRAFT]
                dh = np.hypot(P[:, 0] - Q[:, 0], P[:, 1] - Q[:, 1])
                dz = np.abs(P[:, 2] - Q[:, 2])
                v = (dh < h_sep) & (dz < v_sep) & (P[:, 2] > LANDED_ALT_M)
                if not v.any():
                    continue
                k_first = int(np.argmax(v))
                k_cpa = int(np.argmin(np.where(dz < v_sep, dh, np.inf)))
                out[(drone_id, ac.id)] = {
                    "kind": "aircraft",
                    "t_first": float(LONG_DTS[k_first]),
                    "k_cpa": k_cpa,
                    "t_cpa": float(LONG_DTS[k_cpa]),
                    "min_h": float(dh[k_cpa]),
                    "dz": float(dz[k_cpa]),
                    "point": (float(Q[k_cpa, 0]), float(Q[k_cpa, 1])),
                    "label": ac.callsign,
                    "sep_h": h_sep,
                }
        return out

    # --- lifecycle --------------------------------------------------------------------

    def _reconcile(self, found: dict) -> None:
        sim = self.sim
        now = sim.now
        for key, info in found.items():
            c = self.active.get(key)
            if c is None or c.state == "resolved":
                c = Conflict(
                    id=f"C-{next(self._ids):04d}",
                    kind=info["kind"],
                    a=key[0],
                    b=key[1],
                    state="predicted",
                    first_seen=now,
                    t_first=now + info["t_first"],
                    t_cpa=now + info["t_cpa"],
                    point=info["point"],
                    min_h=info["min_h"],
                    dz=info["dz"],
                    b_label=info.get("label", key[1]),
                    sep_h=info.get("sep_h", DRONE_H_SEP_M),
                )
                self.active[key] = c
                self._announce(c, info)
            else:
                c.t_first = now + info["t_first"]
                c.t_cpa = now + info["t_cpa"]
                c.point = info["point"]
                c.min_h = info["min_h"]
                c.dz = info["dz"]
            ttc = info["t_first"]
            if c.state == "predicted" and (now - c.first_seen >= DECISION_DELAY_S or ttc <= IMMEDIATE_TTC_S):
                self._resolve(c, info)
            elif c.state in ("resolving", "unresolved") and c.applied_at < now:
                if c.attempts < 3:
                    self._resolve(c, info)
                elif c.state != "unresolved":
                    self._give_up(c)

        for key, c in list(self.active.items()):
            self._observe(c)
            if key in found:
                continue
            if c.state == "resolved":
                if now - (c.resolved_at or now) > RESOLVED_DISPLAY_S:
                    del self.active[key]
                continue
            gone = c.a not in self.pred or (c.kind == "drone" and c.b not in self.pred)
            passed = (now >= c.t_cpa + 1.0 and c.last_distance > c.sep_h) or now > c.t_cpa + 45.0
            if c.state == "predicted" or gone or passed:
                self._close(c, "cleared" if c.state == "predicted" else ("landed" if gone else "passed"))

    def _announce(self, c: Conflict, info: dict) -> None:
        ev = self.sim.events
        point = self.sim.world.frame.latlon(*c.point)
        if c.kind == "drone":
            ev.emit(
                "CONFLICT_PREDICTED",
                f"{c.a} and {c.b} predicted conflict. Time to conflict: {info['t_first']:.1f} s "
                f"(closest {info['min_h']:.0f} m horizontal / {info['dz']:.0f} m vertical).",
                drones=[c.a, c.b],
                conflict=c.id,
                ttc_s=info["t_first"],
                min_horizontal_m=info["min_h"],
                vertical_m=info["dz"],
                point=point,
            )
        else:
            ev.emit(
                "AIRCRAFT_CONFLICT",
                f"{c.a} predicted to enter the safety volume of {c.b_label} in {info['t_first']:.1f} s "
                f"({info['min_h']:.0f} m / {info['dz']:.0f} m). Drone must yield.",
                drone=c.a,
                conflict=c.id,
                aircraft=c.b_label,
                ttc_s=info["t_first"],
                point=point,
            )

    def _observe(self, c: Conflict) -> None:
        sim = self.sim
        a = sim.drones.get(c.a)
        if a is None or not a.airborne:
            return
        if c.kind == "drone":
            b = sim.drones.get(c.b)
            if b is None or not b.airborne:
                return
            d = math.hypot(a.x - b.x, a.y - b.y)
            dz = abs(a.alt - b.alt)
        else:
            ac = sim.aircraft.get(c.b)
            if ac is None:
                return
            d = math.hypot(a.x - ac.x, a.y - ac.y)
            dz = abs(a.alt - ac.alt)
        if d < c.observed_min_h:
            c.observed_min_h, c.observed_dz = d, dz
        c.last_distance = d

    def _close(self, c: Conflict, why: str) -> None:
        sim = self.sim
        c.state = "resolved"
        c.resolved_at = sim.now
        c.note = why
        self.resolved_total += 1
        for drone_id in (c.a, c.b):
            d = sim.drones.get(drone_id)
            if d and d.maneuver and d.maneuver.get("conflict") == c.id and d.maneuver["kind"] in ("hold",):
                d.maneuver = None
        seen = ""
        if math.isfinite(c.observed_min_h):
            seen = f" Closest approach {c.observed_min_h:.0f} m horizontal / {c.observed_dz:.0f} m vertical."
        if c.kind == "drone":
            how = f" via {c.maneuver}" if c.maneuver else ""
            sim.events.emit(
                "CONFLICT_RESOLVED",
                f"{c.a}/{c.b} conflict successfully resolved{how}.{seen}" if why != "cleared" else f"{c.a}/{c.b} conflict cleared before intervention.",
                drones=[c.a, c.b],
                conflict=c.id,
                outcome=why,
                min_horizontal_m=c.observed_min_h if math.isfinite(c.observed_min_h) else None,
                vertical_m=c.observed_dz if math.isfinite(c.observed_dz) else None,
            )
        else:
            sim.events.emit(
                "AIRCRAFT_CONFLICT_RESOLVED",
                f"{c.a} clear of {c.b_label}'s predicted corridor.{seen}",
                drone=c.a,
                conflict=c.id,
                aircraft=c.b_label,
                outcome=why,
            )

    def _give_up(self, c: Conflict) -> None:
        """Three manoeuvres did not clear it: stop the yielding drone where it is."""
        sim = self.sim
        c.state = "unresolved"
        drone = sim.drones.get(c.yielding or c.a)
        if drone and drone.airborne:
            drone.motion.hold_until = sim.now + 20.0
            drone.maneuver = {"kind": "hold", "label": "Emergency hold 20 s", "conflict": c.id}
        sim.events.emit(
            "CONFLICT_UNRESOLVED",
            f"{c.a}/{c.b_label} still predicted after 3 manoeuvres. {c.yielding or c.a} holding in place.",
            drones=[c.a] + ([c.b] if c.kind == "drone" else []),
            conflict=c.id,
        )

    # --- resolution -----------------------------------------------------------------

    def _rank(self, d) -> float:
        r = PRIORITY_RANK.get(d.priority, 2)
        if d.battery < 30 or d.health < 40:
            r += 0.5  # degraded drones should not be the ones manoeuvring
        if d.phase in ("escaping",):
            r += 3.0
        return r

    def _resolve(self, c: Conflict, info: dict) -> None:
        sim = self.sim
        if c.kind == "aircraft":
            drone = sim.drones.get(c.a)
            ac = sim.aircraft.get(c.b)
            if drone is None or ac is None or not drone.airborne:
                return
            options = [(drone, None)]
        else:
            a, b = sim.drones.get(c.a), sim.drones.get(c.b)
            if a is None or b is None:
                return
            ra, rb = self._rank(a), self._rank(b)
            options = [(a, b), (b, a)] if ra <= rb else [(b, a), (a, b)]
            tie = ra == rb

        best = None
        for idx, (y, k) in enumerate(options):
            if c.kind == "aircraft":
                cands = self._aircraft_candidates(y, sim.aircraft.get(c.b), info)
            else:
                cands = self._drone_candidates(y, k, info)
            safe = [cd for cd in cands if cd.safe]
            pick = min(safe, key=lambda cd: cd.cost) if safe else None
            if pick and (best is None or pick.cost < best[2].cost):
                best = (y, k, pick, cands)
            # The lower-priority drone yields when it can; only a tie compares both.
            if c.kind == "aircraft" or (best is not None and not (c.kind == "drone" and tie and idx == 0)):
                break

        if best is None:
            c.attempts += 1
            c.applied_at = sim.now
            if c.attempts >= 3:
                self._give_up(c)
            return

        y, k, pick, cands = best
        first = c.attempts == 0
        c.attempts += 1
        c.state = "resolving"
        c.yielding = y.id
        c.maneuver = pick.label
        c.applied_at = sim.now
        c.candidates = [cd.summary() for cd in cands]
        y.set_motion(pick.motion, pick.route_kind)
        y.rejoin_s = pick.rejoin_s if pick.rejoin_s is not None else y.rejoin_s
        y.maneuver = {"kind": pick.kind, "label": pick.label, "conflict": c.id}
        sim.on_route_changed(y)

        other = c.b_label if c.kind == "aircraft" else k.id
        why = self._why(y, k) if c.kind == "drone" else "manned aircraft have priority"
        if first:
            sim.events.emit(
                "DECONFLICTION_STARTED",
                f"{y.id} selected as yielding drone ({why}).",
                drones=[y.id] + ([k.id] if k else []),
                conflict=c.id,
                yielding=y.id,
                candidates=c.candidates,
            )
        detail = {"conflict": c.id, "cost": pick.cost, "candidates": c.candidates}
        if pick.kind in ("climb", "descend"):
            sim.events.emit(
                "ALTITUDE_MANEUVER",
                f"{y.id} altitude changed from {y.alt:.0f} m to {pick.motion.override.alt:.0f} m to clear {other}.",
                drone=y.id,
                **detail,
            )
        elif pick.kind == "hold":
            sim.events.emit("HOLD_MANEUVER", f"{y.id} {pick.label.lower()} to let {other} pass.", drone=y.id, **detail)
        elif pick.kind == "detour":
            sim.events.emit("DETOUR_MANEUVER", f"{y.id} {pick.label.lower()} around {other}.", drone=y.id, **detail)
        else:
            sim.events.emit(
                "REROUTE_STARTED",
                f"{y.id} trajectory replanning initiated with weighted A* ({pick.label}) to avoid {other}.",
                drone=y.id,
                **detail,
            )

    def _why(self, y, k) -> str:
        if PRIORITY_RANK.get(y.priority, 2) < PRIORITY_RANK.get(k.priority, 2):
            return f"{y.priority} vs {k.priority} {k.mission_type}"
        if self._rank(y) < self._rank(k):
            return f"{k.id} is degraded (battery {k.battery:.0f}%, health {k.health:.0f}%)"
        return "cheaper manoeuvre at equal priority"

    # --- candidates -----------------------------------------------------------------

    def _factors(self, d) -> tuple[float, float]:
        energy = 1.8 if d.battery < 50 else 1.0
        aggressive = 2.0 if d.health < 50 else 1.0
        return energy, aggressive

    def _drone_candidates(self, y, k, info: dict) -> list[Candidate]:
        sim = self.sim
        m = y.motion
        Py, Pk = self.pred[y.id], self.pred[k.id]
        kc = info["k_cpa"]
        s_c = float(Py[kc, 3])
        alt_k = float(Pk[kc, 2])
        energy, aggressive = self._factors(y)
        out: list[Candidate] = []

        ceiling = self._min_ceiling(m, s_c + DRONE_H_SEP_M * 2)
        for kind, target in (("climb", alt_k + DRONE_V_SEP_M + 15.0), ("descend", alt_k - DRONE_V_SEP_M - 15.0)):
            label = f"{'Climb' if kind == 'climb' else 'Descend'} to {target:.0f} m"
            if target > min(ALT_MAX_M, ceiling) or target < ALT_MIN_M:
                out.append(Candidate(kind, label, None, math.inf, reason="outside allowed altitude band here"))
                continue
            motion = m.copy(override=altitude_window(m, s_c, target, DRONE_H_SEP_M * 1.3))
            cost = 2 * abs(target - y.alt) * ALT_COST_PER_M * energy * aggressive
            out.append(self._check(y, Candidate(kind, label, motion, cost, route_kind=y.route_kind)))

        out.append(self._hold(y, (5, 10, 15, 20, 30, 45), energy))

        side = self._side_away(Py[kc], Pk[kc], m.route.heading(s_c))
        for offset in (300.0, 500.0):
            cand = self._detour(y, s_c, offset * side, energy)
            if cand:
                out.append(cand)

        avoid = sim.riskmap.blob(Pk[max(0, kc - 20) : kc + 20, :2], DRONE_H_SEP_M * 1.6, 150.0)
        out.append(self._replan(y, avoid, energy))
        return out

    def _aircraft_candidates(self, y, ac, info: dict) -> list[Candidate]:
        m = y.motion
        Py = self.pred[y.id]
        kc = info["k_cpa"]
        s_c = float(Py[kc, 3])
        h_sep, v_sep = AIRCRAFT_SEPARATION[ac.kind]
        alt_ac = float(ac.pred[kc, 2])
        energy, aggressive = self._factors(y)
        out: list[Candidate] = []

        below = alt_ac - v_sep - 10.0
        if below >= ALT_MIN_M:
            motion = m.copy(override=altitude_window(m, s_c, below, h_sep))
            out.append(self._check(y, Candidate("descend", f"Descend to {below:.0f} m", motion, 2 * abs(below - y.alt) * ALT_COST_PER_M * energy * aggressive, route_kind=y.route_kind)))
        else:
            out.append(Candidate("descend", "Descend", None, math.inf, reason="aircraft too low to pass under"))
        out.append(self._hold(y, (10, 20, 30, 45, 60), energy))
        side = self._side_away(Py[kc], ac.pred[kc], m.route.heading(s_c))
        cand = self._detour(y, s_c, (h_sep + 250.0) * side, energy)
        if cand:
            out.append(cand)
        avoid = self.sim.riskmap.blob(ac.pred[: N_AIRCRAFT : 2, :2], h_sep * 1.3, 300.0)
        out.append(self._replan(y, avoid, energy))
        return out

    def _hold(self, y, durations, energy: float) -> Candidate:
        m = y.motion
        last = None
        for d in durations:
            motion = m.copy(hold_until=max(self.sim.now, m.hold_until) + d)
            cost = d * (y.cruise_speed + HOVER_COST_PER_S * energy)
            last = self._check(y, Candidate("hold", f"Hold {d} s", motion, cost, route_kind=y.route_kind))
            if last.safe:
                return last
        return last

    def _detour(self, y, s_c: float, offset: float, energy: float) -> Candidate | None:
        sim = self.sim
        m = y.motion
        r = m.route
        s_a = max(m.s + 120.0, s_c - 450.0)
        s_b = min(r.length - 250.0, s_c + 450.0)
        s_join = min(r.length, s_b + 450.0)
        if s_b <= s_a + 150.0:
            return None
        h = math.radians(r.heading(s_c))
        nx, ny = math.cos(h), -math.sin(h)  # right of track
        ax, ay = r.point(s_a)
        bx, by = r.point(s_b)
        xy = np.vstack(
            [
                [[y.x, y.y], [ax + nx * offset, ay + ny * offset], [bx + nx * offset, by + ny * offset]],
                r.between(s_join, r.length),
            ]
        )
        route = sim.build_route(y, xy, start_alt=y.alt)
        rejoin = float(np.hypot(*np.diff(xy[:4], axis=0).T).sum())
        motion = Motion(route, 0.0, m.speed, y.alt, m.hold_until)
        extra = route.length - (r.length - m.s)
        label = f"Lateral detour {abs(offset):.0f} m {'right' if offset > 0 else 'left'} of track"
        return self._check(y, Candidate("detour", label, motion, max(0.0, extra) * energy + 0.3 * abs(offset), route_kind="detour", rejoin_s=rejoin))

    def _replan(self, y, avoid: np.ndarray, energy: float) -> Candidate:
        sim = self.sim
        m = y.motion
        remaining = m.route.length - m.s
        plan = sim.plan_for(y, (y.x, y.y), (y.destination.x, y.destination.y), avoid=avoid, deviation=0.6)
        if plan is None:
            return Candidate("replan", "Weighted A* replan", None, math.inf, reason="no route found")
        route = sim.build_route(y, plan.xy, start_alt=y.alt)
        motion = Motion(route, 0.0, m.speed, y.alt, m.hold_until)
        extra = route.length - remaining
        label = f"Replan {'+' if extra >= 0 else ''}{extra:.0f} m"
        return self._check(y, Candidate("replan", label, motion, max(0.0, extra) * energy + 150.0, route_kind="replan"))

    def _check(self, y, cand: Candidate) -> Candidate:
        safe, reason = self.is_safe(y, cand.motion)
        cand.safe = safe
        cand.reason = reason
        if not safe:
            cand.cost = math.inf
        return cand

    def is_safe(self, y, motion: Motion) -> tuple[bool, str]:
        sim = self.sim
        P = predict(motion, sim.now, LONG_DTS)
        up = P[:, 2] > LANDED_ALT_M
        if len(self._stack_ids) > 1:
            mask = np.array([i != y.id for i in self._stack_ids])
            Q = self._stack[mask]
            dh = np.hypot(Q[:, :, 0] - P[None, :, 0], Q[:, :, 1] - P[None, :, 1])
            dz = np.abs(Q[:, :, 2] - P[None, :, 2])
            viol = (dh < DRONE_H_SEP_M) & (dz < DRONE_V_SEP_M) & up[None, :] & (Q[:, :, 2] > LANDED_ALT_M)
            if viol.any():
                row, col = np.argwhere(viol)[0]
                other = [i for i in self._stack_ids if i != y.id][row]
                return False, f"conflicts with {other} in {LONG_DTS[col]:.0f} s"
        for ac in sim.aircraft.relevant():
            h_sep, v_sep = AIRCRAFT_SEPARATION[ac.kind]
            Q = ac.pred
            n = min(len(Q), len(P))
            dh = np.hypot(P[:n, 0] - Q[:n, 0], P[:n, 1] - Q[:n, 1])
            dz = np.abs(P[:n, 2] - Q[:n, 2])
            hits = (dh < h_sep) & (dz < v_sep) & up[:n]
            if hits.any():
                return False, f"inside {ac.callsign} safety volume in {LONG_DTS[int(np.argmax(hits))]:.0f} s"
        ahead = motion.route.between(motion.s, min(motion.route.length, float(P[-1, 3]) + 400.0))
        if len(ahead) >= 2 and sim.riskmap.first_entry_along(ahead) is not None:
            return False, "enters restricted airspace"
        return True, ""

    def _min_ceiling(self, m: Motion, s_to: float) -> float:
        s = np.linspace(m.s, min(m.route.length, s_to), 12)
        x, y = m.route.pos(s)
        return float(self.sim.riskmap.ceiling_at(x, y).min())

    @staticmethod
    def _side_away(p_self: np.ndarray, p_other: np.ndarray, heading_deg: float) -> float:
        h = math.radians(heading_deg)
        right = (math.cos(h), -math.sin(h))
        rel = (p_other[0] - p_self[0], p_other[1] - p_self[1])
        return -1.0 if rel[0] * right[0] + rel[1] * right[1] > 0 else 1.0

    # --- display ------------------------------------------------------------------------

    def _flag_drones(self) -> None:
        order = {"none": 0, "resolved": 1, "resolving": 2, "unresolved": 3, "predicted": 4}
        flags: dict[str, str] = {}
        for c in self.active.values():
            state = "resolving" if c.state == "unresolved" else c.state
            ids = [c.a] if c.kind == "aircraft" else [c.a, c.b]
            for i in ids:
                if order[state] > order[flags.get(i, "none")]:
                    flags[i] = state
        for d in self.sim.drones.values():
            d.conflict_state = flags.get(d.id, "none")

    def _crossings(self) -> None:
        """Where remaining routes cross in 2-D, with the time and height gap at the crossing."""
        sim = self.sim
        now = sim.now
        drones = [d for d in sim.airborne()]
        segs = {}
        for d in drones:
            m = d.motion
            xy = m.route.between(m.s, min(m.route.length, m.s + 8000.0))
            if len(xy) < 2:
                continue
            seg_len = np.hypot(*np.diff(xy, axis=0).T)
            segs[d.id] = (xy[:-1], xy[1:], np.concatenate([[0.0], np.cumsum(seg_len)[:-1]]), seg_len)
        active_pairs = {tuple(sorted((c.a, c.b))) for c in self.active.values() if c.kind == "drone" and c.state != "resolved"}
        out = []
        for a, b in itertools.combinations(drones, 2):
            if a.id not in segs or b.id not in segs:
                continue
            A1, A2, As, Al = segs[a.id]
            B1, B2, Bs, Bl = segs[b.id]
            d1 = A2 - A1
            d2 = B2 - B1
            denom = d1[:, None, 0] * d2[None, :, 1] - d1[:, None, 1] * d2[None, :, 0]
            diff = B1[None, :, :] - A1[:, None, :]
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (diff[..., 0] * d2[None, :, 1] - diff[..., 1] * d2[None, :, 0]) / denom
                u = (diff[..., 0] * d1[:, None, 1] - diff[..., 1] * d1[:, None, 0]) / denom
            hit = (np.abs(denom) > 1e-9) & (t >= 0) & (t <= 1) & (u >= 0) & (u <= 1)
            for i, j in np.argwhere(hit)[:3]:
                sa = As[i] + t[i, j] * Al[i]
                sb = Bs[j] + u[i, j] * Bl[j]
                ta = max(0.0, a.motion.hold_until - now) + sa / max(a.motion.speed, 1.0)
                tb = max(0.0, b.motion.hold_until - now) + sb / max(b.motion.speed, 1.0)
                if min(ta, tb) > 240:
                    continue
                za = float(a.motion.target_alt(a.motion.s + sa))
                zb = float(b.motion.target_alt(b.motion.s + sb))
                px, py = A1[i] + t[i, j] * d1[i]
                pair = tuple(sorted((a.id, b.id)))
                dt = abs(ta - tb)
                if pair in active_pairs:
                    status = "conflict"
                elif abs(za - zb) >= DRONE_V_SEP_M:
                    status = "altitude"
                elif dt * min(a.motion.speed, b.motion.speed) >= DRONE_H_SEP_M:
                    status = "time"
                else:
                    status = "watch"  # same time and height, beyond the prediction horizon for now
                lat, lon = sim.world.frame.latlon(float(px), float(py))
                out.append(
                    {
                        "a": a.id,
                        "b": b.id,
                        "lat": round(lat, 6),
                        "lon": round(lon, 6),
                        "dt": round(dt, 1),
                        "dalt": round(abs(za - zb), 1),
                        "inS": round(min(ta, tb), 1),
                        "status": status,
                    }
                )
        out.sort(key=lambda c: c["inS"])
        self.crossings = out[:40]

    def to_list(self) -> list[dict]:
        frame = self.sim.world.frame
        now = self.sim.now
        out = []
        for c in self.active.values():
            lat, lon = frame.latlon(*c.point)
            out.append(
                {
                    "id": c.id,
                    "kind": c.kind,
                    "a": c.a,
                    "b": c.b,
                    "bLabel": c.b_label,
                    "state": c.state,
                    "ttc": round(max(0.0, c.t_first - now), 1),
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "minH": round(c.min_h),
                    "dz": round(c.dz),
                    "yielding": c.yielding,
                    "maneuver": c.maneuver,
                    "observedMinH": round(c.observed_min_h) if math.isfinite(c.observed_min_h) else None,
                }
            )
        return out
