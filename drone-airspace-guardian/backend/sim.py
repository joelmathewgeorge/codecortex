"""
The simulation: one object that owns the world, the fleet and every planner.

Each tick (event-driven: A* only re-runs when something changed):
  1. physics sub-steps: drones fly their motions, aircraft move
  2. manoeuvre bookkeeping: holds and altitude windows expire, escapes leave their zone,
     detours rejoin the original route
  3. health model cycle (batched RUL) and battery thresholds -> reweighting or abort
  4. missions: turnarounds at destinations, charging and maintenance at ports
  5. aircraft predictions -> safety volumes on the risk map
  6. route validation: remaining routes re-checked against hard blocks, before entry
  7. queued replans in safety-priority order (hard airspace, battery, health, ground risk)
  8. conflict prediction and deconfliction
"""

from __future__ import annotations

import itertools
import math
import random
import threading

import numpy as np

from aircraft import AircraftService
from config import (
    CRITICAL_BATTERY,
    CRUISE_ALTS,
    EMERGENCY_RADIUS_M,
    HEALTH_MODEL_EVERY_S,
    LOW_BATTERY,
    OPERATOR_ZONE_RADIUS_M,
    REPLANS_PER_TICK,
    SIM_SPEEDS,
    SPEED_RANGE,
    SUBSTEP_S,
    TURNAROUND_S,
)
from conflicts import LONG_DTS, ConflictManager
from drones import MISSION_KINDS, Drone
from emergency import plan_avoidance, plan_escape
from events import EventBus
from ground import GroundMonitor
from health_bridge import HealthBridge
from planner import Plan, plan_route
from risk_map import RiskMap, Weights
from trajectory import LANDED_ALT_M, Motion, Route, make_route, predict
from world import Place, World
from zones import ZoneStore

HEALTH_ORDER = {"healthy": 0, "monitor": 1, "service_soon": 2, "ground_now": 3}
HEALTH_LABEL = {"healthy": "healthy", "monitor": "monitor", "service_soon": "service soon", "ground_now": "ground now"}

# Opening fleet: (mission, priority, cruise alt, speed, battery, wear, progress along route)
SEED_FLEET = [
    ("medical", "CRITICAL", 100.0, 19.0, 92.0, 0.10, 0.35),
    ("parcel", "NORMAL", 80.0, 17.0, 76.0, 0.30, 0.15),
    ("food", "NORMAL", 90.0, 16.0, 64.0, 0.25, 0.50),
    ("survey", "LOW", 70.0, 15.0, 88.0, 0.55, 0.25),
    ("organ", "CRITICAL", 110.0, 20.0, 95.0, 0.15, 0.10),
    ("parcel", "NORMAL", 90.0, 18.0, 44.0, 0.35, 0.40),  # under 50%: energy-weighted routing
    ("security", "HIGH", 120.0, 18.0, 83.0, 0.20, 0.30),
    ("retail", "LOW", 70.0, 15.0, 70.0, 0.90, 0.20),  # worn airframe: reaches critical health a few minutes in
]
DEST_KINDS = {
    "medical": ("hospital",),
    "organ": ("hospital",),
    "parcel": ("mall", "district"),
    "retail": ("mall",),
    "food": ("district",),
    "survey": ("district",),
    "security": ("district", "mall"),
}


class Simulation:
    def __init__(self, seed: int = 7) -> None:
        self.lock = threading.RLock()
        self.seed = seed
        self.world = World()
        self.riskmap = RiskMap(self.world)
        self.events = EventBus()
        self.events.clock = lambda: self.now
        self.zones = ZoneStore(self.world.frame)
        self.health = HealthBridge()
        self.aircraft = AircraftService(self.world, self.events)
        self.ground = GroundMonitor(self.world, self.events)
        self.conflicts = ConflictManager(self)
        self.drones: dict[str, Drone] = {}
        self.now = 0.0
        self.speed = 1
        self.ticks = 0
        self.rng = random.Random(seed)
        self._ids = itertools.count(1)
        self._tmp = itertools.count(1)
        self._replans: dict[str, tuple[int, str, dict]] = {}
        self._health_acc = 0.0
        self._routes_dirty = True
        self.riskmap.set_ground(self.ground.sites)
        self.seed_fleet()

    # --- planning helpers ------------------------------------------------------------

    def airborne(self) -> list[Drone]:
        return [d for d in self.drones.values() if d.airborne and d.motion is not None]

    def weights_for(self, d: Drone, deviation: float = 0.0) -> Weights:
        w = Weights(cruise_alt=d.cruise_alt, deviation=deviation)
        if d.battery < CRITICAL_BATTERY:
            w.energy, w.altitude, w.ground, w.traffic = 2.5, 1.5, 0.4, 0.6
        elif d.battery < LOW_BATTERY:
            w.energy, w.altitude, w.ground, w.traffic = 1.2, 1.0, 0.6, 0.8
        if d.health < 50:
            w.risk_scale, w.landing = 1.8, 0.6
        elif d.health < 75:
            w.risk_scale, w.landing = 1.3, 0.2
        return w

    def plan_for(self, d: Drone, start, goal, *, avoid=None, deviation: float = 0.0, original=None) -> Plan | None:
        orig = original
        if deviation > 0 and orig is None and d.original is not None:
            s0, _ = d.original.closest_s(d.x, d.y)
            orig = d.original.remaining(s0)
        return plan_route(self.riskmap, start, goal, self.weights_for(d, deviation), own_cells=d.route_cells, original=orig, avoid=avoid)

    def build_route(self, d: Drone, xy, start_alt: float, end_alt: float = 0.0, speed: float | None = None) -> Route:
        spd = speed or (d.motion.speed if d.motion else d.cruise_speed)
        return make_route(np.asarray(xy, dtype=float), start_alt, d.cruise_alt, end_alt, spd, self.riskmap.ceiling_at)

    def on_route_changed(self, d: Drone) -> None:
        if d.airborne and d.motion is not None:
            d.route_cells = self.riskmap.route_cells(d.motion.route.remaining(d.motion.s))
        else:
            d.route_cells = np.zeros(0, dtype=int)
        self._routes_dirty = True

    def hazard_name(self, x: float, y: float) -> str:
        for z in self.zones.zones:
            if z.contains(x, y, margin=200.0):
                return f"{z.label} ({z.id})"
        r, c = self.riskmap.cell_of(x, y)
        idx = int(self.riskmap.zone_label[r, c])
        if idx >= 0:
            return self.world.restricted[idx].name
        if self.riskmap.aircraft_hard[r, c]:
            return "a manned-aircraft corridor"
        return "restricted airspace"

    def _queue(self, d: Drone, priority: int, reason: str, info: dict | None = None) -> None:
        current = self._replans.get(d.id)
        if current is None or priority < current[0]:
            self._replans[d.id] = (priority, reason, info or {})

    # --- fleet creation ----------------------------------------------------------------

    def _new_drone(
        self,
        mission_type: str,
        priority: str,
        origin: Place,
        dest: Place,
        home: Place,
        start_xy: tuple[float, float],
        start_alt: float,
        cruise_alt: float,
        speed: float,
        battery: float,
        wear: float,
        progress: float = 0.0,
        commit: bool = True,
    ) -> tuple[Drone, Plan] | None:
        did = f"D{next(self._ids):02d}" if commit else f"TMP-{next(self._tmp)}"
        d = Drone(
            id=did,
            mission_type=mission_type,
            priority=priority,
            origin=origin,
            destination=dest,
            home=home,
            cruise_alt=cruise_alt,
            cruise_speed=speed,
            battery=battery,
            wear=wear,
            x=start_xy[0],
            y=start_xy[1],
            alt=start_alt,
            created_at=self.now,
        )
        self._apply_health(d, self.health.register(did, wear, seed=self.rng.randrange(10_000)), announce=False)
        plan = self.plan_for(d, start_xy, (dest.x, dest.y))
        if plan is None:
            self.health.forget(did)
            return None
        route = self.build_route(d, plan.xy, start_alt=start_alt, speed=speed)
        s0 = progress * route.length
        alt0 = start_alt if progress == 0 else float(route.alt(s0))
        d.motion = Motion(route, s0, speed, alt0)
        d.original = route
        if progress > 0:
            d.x, d.y = route.point(s0)
            d.alt = alt0
        d.heading = route.heading(s0)
        d.announced = {"battery": self._battery_band(battery), "health": d.health_status, "rul": d.rul}
        if commit:
            self._commit(d)
        return d, plan

    def _commit(self, d: Drone) -> None:
        if d.id.startswith("TMP-"):
            new_id = f"D{next(self._ids):02d}"
            track = self.health.tracks.pop(d.id, None)
            if track is not None:
                self.health.tracks[new_id] = track
            d.id = new_id
        self.drones[d.id] = d
        self.on_route_changed(d)

    def seed_fleet(self) -> None:
        ports = self.world.ports
        for i, (kind, prio, alt, speed, battery, wear, progress) in enumerate(SEED_FLEET):
            port = ports[i % len(ports)]
            for _ in range(8):
                dest = self.world.random_destination(self.rng, (port.x, port.y), 4000.0, 10000.0, DEST_KINDS[kind])
                made = self._new_drone(kind, prio, port, dest, port, (port.x, port.y), 0.0, alt, speed, battery, wear, progress)
                if made:
                    break
        self.events.emit(
            "SIM_RESET",
            f"Airspace initialised over {len(self.world.restricted)} real restricted areas with {len(self.drones)} drones "
            f"from {len(ports)} drone ports.",
            drones=list(self.drones),
        )

    def _pick_destination(self, origin: tuple[float, float]) -> tuple[Place, str, str]:
        kind = self.rng.choices(
            ["medical", "organ", "parcel", "food", "retail", "survey", "security"], weights=[3, 1, 4, 3, 2, 1, 1]
        )[0]
        dest = self.world.random_destination(self.rng, origin, 3500.0, 11000.0, DEST_KINDS[kind])
        return dest, kind, self.rng.choice(MISSION_KINDS[kind][1])

    def add_drone(self, mode: str = "auto") -> dict:
        rng = self.rng
        speed = rng.uniform(*SPEED_RANGE)
        battery = rng.uniform(55, 100) if rng.random() > 0.2 else rng.uniform(28, 50)
        wear = rng.uniform(0.05, 0.6) if rng.random() > 0.15 else rng.uniform(0.72, 0.88)

        attempts = []
        if mode in ("auto", "encounter") and self.airborne() and (mode == "encounter" or rng.random() < 0.7):
            for _ in range(4):
                setup = self._encounter_setup(speed)
                if setup:
                    attempts.append(setup)
        chosen = None
        for start_xy, dest, alt, target in attempts:
            made = self._try_add(start_xy, dest, alt, speed, battery, wear)
            if made is None:
                continue
            hit = self._predicts_conflict(made[0], target)
            if chosen is None or (hit and not chosen[2]):
                if chosen is not None:
                    self.health.forget(chosen[0].id)
                chosen = (made[0], made[1], hit)
            else:
                self.health.forget(made[0].id)
            if hit:
                break
        if chosen is None:
            for _ in range(10):
                origin = rng.choice(self.world.destinations + self.world.ports)
                dest, _, _ = self._pick_destination((origin.x, origin.y))
                made = self._try_add((origin.x, origin.y), dest, rng.choice(CRUISE_ALTS), speed, battery, wear, origin=origin)
                if made:
                    chosen = (made[0], made[1], False)
                    break
        if chosen is None:
            raise ValueError("could not find a safe mission for a new drone")
        d, plan, _ = chosen
        self._commit(d)
        self.events.emit(
            "DRONE_ADDED",
            f"{d.id} added to airspace: {d.mission} ({d.priority}), battery {d.battery:.0f}%, "
            f"health {d.health:.0f}% (RUL {d.rul:.0f} cycles), cruising {d.cruise_alt:.0f} m at {d.cruise_speed:.0f} m/s.",
            drone=d.id,
            mission=d.mission_type,
            priority=d.priority,
            battery=d.battery,
            health=d.health,
            rul=d.rul,
            start=list(self.world.frame.latlon(d.x, d.y)),
        )
        self._announce_route(d, plan, "initial")
        self.conflicts.update()
        predicted = [c.b if c.a == d.id else c.a for c in self.conflicts.active.values() if d.id in (c.a, c.b) and c.state != "resolved"]
        return {"drone": d.to_dict(self.world.frame), "predictedConflicts": predicted}

    def _try_add(self, start_xy, dest: Place, alt: float, speed: float, battery: float, wear: float, origin: Place | None = None):
        home = self.world.nearest_port(*start_xy)
        dest_kind = dest.kind if dest.kind in ("hospital", "mall", "district") else "district"
        kind = {"hospital": self.rng.choice(["medical", "medical", "organ"]), "mall": self.rng.choice(["parcel", "retail"]), "district": self.rng.choice(["food", "parcel", "security", "survey"])}[dest_kind]
        prio = self.rng.choice(MISSION_KINDS[kind][1])
        if origin is None:
            lat, lon = self.world.frame.latlon(*start_xy)
            origin = Place("entry", f"Airspace entry {lat:.3f}N {lon:.3f}E", "entry", lat, lon, start_xy[0], start_xy[1])
        return self._new_drone(kind, prio, origin, dest, home, start_xy, alt, alt, speed, battery, wear, commit=False)

    def _encounter_setup(self, speed: float):
        """A start point and destination whose straight line crosses an existing drone's path when it is there."""
        rng = self.rng
        cands = [d for d in self.airborne() if d.phase == "cruise" and d.motion.route.length - d.motion.s > 3000 and d.motion.hold_until <= self.now]
        if not cands:
            return None
        for _ in range(40):
            tgt = rng.choice(cands)
            t_enc = rng.uniform(25.0, 42.0)
            p = predict(tgt.motion, self.now, np.array([t_enc]))[0]
            if p[2] < 40.0:
                continue
            h = math.radians(tgt.motion.route.heading(p[3]) + rng.choice([-1, 1]) * rng.uniform(60.0, 120.0))
            ux, uy = math.sin(h), math.cos(h)
            sx, sy = p[0] - ux * speed * t_enc, p[1] - uy * speed * t_enc
            if not self.world.is_clear(sx, sy, 150.0) or self.riskmap.hard[self.riskmap.cell_of(sx, sy)]:
                continue
            reach = rng.uniform(2500.0, 5500.0)
            fx, fy = p[0] + ux * reach, p[1] + uy * reach
            dest = self.world.nearest(self.world.destinations, fx, fy)
            if math.hypot(dest.x - fx, dest.y - fy) > 2000.0 or math.hypot(dest.x - p[0], dest.y - p[1]) < 1500.0:
                continue
            return (sx, sy), dest, float(round(p[2] / 10.0) * 10.0), tgt.id
        return None

    def _predicts_conflict(self, d: Drone, target: str | None) -> bool:
        if target is None or target not in self.drones:
            return False
        other = self.drones[target]
        if not other.airborne:
            return False
        P = predict(d.motion, self.now, LONG_DTS)
        Q = predict(other.motion, self.now, LONG_DTS)
        dh = np.hypot(P[:, 0] - Q[:, 0], P[:, 1] - Q[:, 1])
        dz = np.abs(P[:, 2] - Q[:, 2])
        return bool(np.any((dh < 150.0) & (dz < 30.0) & (P[:, 2] > LANDED_ALT_M) & (Q[:, 2] > LANDED_ALT_M)))

    def _announce_route(self, d: Drone, plan: Plan, why: str) -> None:
        w = plan.weights
        self.events.emit(
            "ROUTE_GENERATED",
            f"{d.id} route generated using weighted A*: {plan.length / 1000:.1f} km to {d.destination.name}, "
            f"{len(plan.xy) - 1} legs, {plan.expansions} cells searched in {plan.ms:.0f} ms.",
            drone=d.id,
            reason=why,
            length_m=plan.length,
            cost=plan.cost,
            weights=w.to_dict(),
            notes=plan.notes,
        )

    # --- commands -----------------------------------------------------------------------

    def add_zone(self, kind: str, lat: float, lon: float, radius: float | None) -> dict:
        x, y = self.world.frame.point(lat, lon)
        if not self.world.in_bounds(x, y):
            raise ValueError("That point is outside the operating area.")
        radius = radius or (EMERGENCY_RADIUS_M if kind == "emergency" else OPERATOR_ZONE_RADIUS_M)
        zone, dropped = self.zones.add(kind, lat, lon, radius, self.now)
        for z in dropped:
            self.events.emit("ZONE_CLEARED", f"{z.label} ({z.id}) lifted to make room for {zone.id}.", zone=z.id)
        self.riskmap.set_zones(self.zones.zones)

        air = self.airborne()
        inside = [d for d in air if zone.contains(d.x, d.y)]
        hard = self.riskmap.hard_static | self.riskmap.hard_zones
        approaching = [
            d for d in air if d not in inside and self.riskmap.first_entry_along(d.motion.route.remaining(d.motion.s), hard) is not None
        ]
        near = self.world.nearest(self.world.destinations, zone.x, zone.y).name
        if kind == "emergency":
            self.events.emit(
                "EMERGENCY_CREATED",
                f"Emergency zone {zone.id} declared near {near} (radius {radius:.0f} m, {zone.buffer:.0f} m buffer). "
                f"{len(inside)} drone(s) inside, {len(approaching)} on course into it.",
                drones=[d.id for d in inside + approaching],
                zone=zone.id,
                lat=lat,
                lon=lon,
                radius=radius,
                inside=[d.id for d in inside],
                approaching=[d.id for d in approaching],
            )
        else:
            self.events.emit(
                "ZONE_CREATED",
                f"No-fly zone {zone.id} drawn near {near} (radius {radius:.0f} m). "
                f"{len(inside)} drone(s) inside, {len(approaching)} will reroute before reaching it.",
                drones=[d.id for d in inside + approaching],
                zone=zone.id,
                radius=radius,
            )
        for d in inside:
            self._start_escape(d, zone)
        for d in approaching:
            self._avoid(d, {})
        self.conflicts.update()
        return {"zone": zone.to_dict(), "inside": [d.id for d in inside], "approaching": [d.id for d in approaching]}

    def remove_zone(self, zone_id: str) -> dict:
        zone = self.zones.remove(zone_id)
        if zone is None:
            raise KeyError(zone_id)
        self.riskmap.set_zones(self.zones.zones)
        self.events.emit("ZONE_CLEARED", f"{zone.label} ({zone.id}) lifted by the operator.", zone=zone.id)
        return {"removed": zone.id}

    def set_speed(self, speed: int) -> None:
        if speed not in SIM_SPEEDS:
            raise ValueError(f"speed must be one of {SIM_SPEEDS}")
        self.speed = speed

    def reset(self) -> None:
        self.drones.clear()
        self.zones.clear()
        self.riskmap.set_zones([])
        self.conflicts.reset()
        self.health.clear()
        self.aircraft.reset()
        self.events.clear()
        self._replans.clear()
        self._ids = itertools.count(1)
        self.rng = random.Random(self.seed)
        self.seed_fleet()
        self._routes_dirty = True

    # --- tick ----------------------------------------------------------------------------

    def step(self, wall_dt: float) -> None:
        sim_dt = wall_dt * self.speed
        self.aircraft.time_scale = float(self.speed)
        n = max(1, int(math.ceil(sim_dt / SUBSTEP_S - 1e-9)))
        dt = sim_dt / n
        for _ in range(n):
            self.now += dt
            for d in list(self.drones.values()):
                if d.step(dt, self.now) == "arrived":
                    self._arrived(d)
            self.aircraft.tick(self.now, dt)
        self._housekeeping()
        self._health_accumulate(sim_dt)
        self._battery_checks()
        self._missions()
        self.aircraft.refresh(self.airborne(), self.now)
        self.riskmap.set_aircraft(self.aircraft.volumes())
        self._validate_routes()
        self._process_replans()
        if self._routes_dirty or self.ticks % 5 == 0:
            for d in self.drones.values():
                if d.airborne:
                    d.route_cells = self.riskmap.route_cells(d.motion.route.remaining(d.motion.s))
            self.riskmap.set_routes({d.id: d.route_cells for d in self.drones.values() if d.airborne})
            self._routes_dirty = False
        self.conflicts.update()
        self.aircraft.mark_conflicts({c.b for c in self.conflicts.active.values() if c.kind == "aircraft" and c.state != "resolved"})
        self.ticks += 1

    def _housekeeping(self) -> None:
        active_yield = {c.yielding for c in self.conflicts.active.values() if c.state != "resolved"}
        for d in self.airborne():
            m = d.motion
            if m.override is not None and m.s > m.override.s_end:
                m.override = None
                if d.maneuver and d.maneuver["kind"] in ("climb", "descend"):
                    d.maneuver = None
            if d.maneuver and d.maneuver["kind"] == "hold" and self.now >= m.hold_until:
                d.maneuver = None
            if d.phase == "escaping":
                zone = next((z for z in self.zones.zones if z.id == d.escape_zone), None)
                exit_s = (d.maneuver or {}).get("exit_s", 0.0)
                if zone is None or (not zone.contains(d.x, d.y) and m.s >= exit_s - 1.0):
                    m.speed = d.cruise_speed
                    took = self.now - (d.maneuver or {}).get("since", self.now)
                    d.phase = "rejoining" if d.rejoin_s is not None else "returning"
                    d.maneuver = {"kind": "rejoin", "label": "Rejoining original route"} if d.rejoin_s is not None else None
                    self.events.emit(
                        "EMERGENCY_ESCAPE_COMPLETED",
                        f"{d.id} cleared {zone.label if zone else 'the emergency zone'} in {took:.0f} s"
                        + (", now rejoining its original route." if d.rejoin_s is not None else f", heading to {d.destination.name}."),
                        drone=d.id,
                        zone=d.escape_zone,
                        seconds=took,
                    )
                    self.on_route_changed(d)
            if d.rejoin_s is not None and d.phase != "escaping" and m.s >= d.rejoin_s:
                kind = d.route_kind
                hazard = (d.maneuver or {}).get("hazard")
                d.rejoin_s = None
                if d.phase == "rejoining":
                    d.phase = "cruise"
                d.route_kind = "planned"
                d.maneuver = None
                if kind == "avoid":
                    self.events.emit("NO_FLY_AVOIDED", f"{d.id} flew around {hazard or 'the restricted area'} without entering it and rejoined its original route.", drone=d.id, hazard=hazard)
                else:
                    self.events.emit("REROUTE_COMPLETED", f"{d.id} rejoined its original route after the {kind}.", drone=d.id, kind=kind)
            if d.route_kind == "replan" and d.id not in active_yield:
                d.original = m.route
                d.route_kind = "planned"
                if d.maneuver and d.maneuver["kind"] == "replan":
                    d.maneuver = None
                self.events.emit("REROUTE_COMPLETED", f"{d.id} conflict cleared; the replanned route is now its nominal route.", drone=d.id, kind="replan")

    def _health_accumulate(self, sim_dt: float) -> None:
        self._health_acc += sim_dt
        while self._health_acc >= HEALTH_MODEL_EVERY_S:
            self._health_acc -= HEALTH_MODEL_EVERY_S
            readings = self.health.advance([d.id for d in self.airborne()])
            for did, r in readings.items():
                self._apply_health(self.drones[did], r, announce=True)

    def _apply_health(self, d: Drone, r, announce: bool) -> None:
        prev_status = d.health_status
        d.health, d.rul, d.health_status = r.health, r.rul, r.status
        if not announce:
            return
        if abs(r.rul - d.announced.get("rul", r.rul)) >= 8.0:
            d.announced["rul"] = r.rul
            self.events.emit(
                "RUL_UPDATED",
                f"{d.id} predicted remaining useful life {r.rul:.0f} cycles (health {r.health:.0f}%, {HEALTH_LABEL[r.status]}).",
                drone=d.id,
                rul=r.rul,
                health=r.health,
                status=r.status,
                model=self.health.model,
            )
        if HEALTH_ORDER[r.status] <= HEALTH_ORDER.get(d.announced.get("health", prev_status), 0):
            return
        d.announced["health"] = r.status
        if r.status == "ground_now":
            self.events.emit(
                "CRITICAL_HEALTH",
                f"{d.id} health {r.health:.0f}% (RUL {r.rul:.0f} cycles): predicted near end of life, grounding.",
                drone=d.id,
                rul=r.rul,
                health=r.health,
            )
            self._abort(d, "critical health", maintenance=True)
        else:
            self.events.emit(
                "HEALTH_DEGRADED",
                f"{d.id} health {r.health:.0f}% ({HEALTH_LABEL[r.status]}): risk weights raised, keeping clear of crowds "
                "and closer to drone ports.",
                drone=d.id,
                rul=r.rul,
                health=r.health,
                status=r.status,
            )
            self._queue(d, 7, "health")

    @staticmethod
    def _battery_band(battery: float) -> str:
        return "ok" if battery >= LOW_BATTERY else ("low" if battery >= CRITICAL_BATTERY else "critical")

    def _battery_checks(self) -> None:
        for d in self.airborne():
            band = self._battery_band(d.battery)
            prev = d.announced.get("battery", "ok")
            if band == prev or (band == "ok" and prev != "ok"):
                continue
            d.announced["battery"] = band
            if band == "low":
                self.events.emit(
                    "LOW_BATTERY",
                    f"{d.id} battery {d.battery:.0f}%: energy weight raised, avoiding unnecessary altitude changes.",
                    drone=d.id,
                    battery=d.battery,
                )
                if d.motion.route.length - d.motion.s > 1500.0:
                    self._queue(d, 8, "battery")
            elif band == "critical":
                self.events.emit(
                    "CRITICAL_BATTERY",
                    f"{d.id} battery {d.battery:.0f}%: holding reserve, diverting to the nearest drone port.",
                    drone=d.id,
                    battery=d.battery,
                )
                self._abort(d, "critical battery")

    def _abort(self, d: Drone, reason: str, maintenance: bool = False) -> None:
        open_ports = [p for p in self.world.ports if not any(z.contains(p.x, p.y, margin=z.buffer) for z in self.zones.zones)]
        port = min(open_ports or self.world.ports, key=lambda p: math.hypot(p.x - d.x, p.y - d.y))
        d.announced["maintenance"] = maintenance or d.announced.get("maintenance", False)
        if d.mission_type == "return" and d.destination.id == port.id:
            return
        if not d.airborne:
            return
        self.events.emit(
            "MISSION_ABORTED",
            f"{d.id} mission aborted ({reason}); diverting to {port.name} for {'maintenance' if maintenance else 'recharge'}.",
            drone=d.id,
            reason=reason,
            port=port.name,
        )
        self._divert(d, port)

    def _divert(self, d: Drone, place: Place) -> bool:
        plan = self.plan_for(d, (d.x, d.y), (place.x, place.y))
        if plan is None:
            return False
        route = self.build_route(d, plan.xy, start_alt=d.alt)
        d.set_motion(Motion(route, 0.0, d.cruise_speed, d.alt), "return")
        d.original = route
        d.destination = place
        d.mission_type = "return"
        d.phase = "returning"
        d.rejoin_s = None
        d.escape_zone = None
        d.maneuver = None
        self.on_route_changed(d)
        self._announce_route(d, plan, "divert")
        return True

    def _arrived(self, d: Drone) -> None:
        at_port = d.destination.kind == "port"
        d.phase = "charging" if at_port else "landed"
        d.landed_at = self.now
        d.maneuver = None
        d.rejoin_s = None
        d.alt = 0.0
        d.origin = d.destination
        self.on_route_changed(d)
        if at_port:
            self.events.emit(
                "MISSION_COMPLETED",
                f"{d.id} landed at {d.destination.name} for {'maintenance' if d.announced.get('maintenance') else 'charging'} "
                f"(battery {d.battery:.0f}%).",
                drone=d.id,
                battery=d.battery,
            )
        else:
            self.events.emit(
                "MISSION_COMPLETED",
                f"{d.id} completed {d.mission} after {d.distance_flown / 1000:.1f} km (battery {d.battery:.0f}%).",
                drone=d.id,
                battery=d.battery,
            )
        d.distance_flown = 0.0

    def _missions(self) -> None:
        for d in list(self.drones.values()):
            if d.airborne:
                continue
            idle = self.now - d.landed_at
            if d.phase == "landed" and idle >= TURNAROUND_S:
                if d.battery < 45.0:
                    port = self.world.nearest_port(d.x, d.y)
                    self._launch(d, port, "return", "LOW")
                else:
                    dest, kind, prio = self._pick_destination((d.x, d.y))
                    self._launch(d, dest, kind, prio)
            elif d.phase == "charging":
                if d.announced.get("maintenance") and idle >= 40.0:
                    d.announced["maintenance"] = False
                    d.wear = 0.05
                    self._apply_health(d, self.health.register(d.id, d.wear, seed=self.rng.randrange(10_000)), announce=False)
                    d.announced.update({"health": d.health_status, "rul": d.rul})
                    self.events.emit(
                        "RUL_UPDATED",
                        f"{d.id} maintenance complete at {d.destination.name}: RUL {d.rul:.0f} cycles, health {d.health:.0f}%.",
                        drone=d.id,
                        rul=d.rul,
                        health=d.health,
                    )
                if not d.announced.get("maintenance") and d.battery >= 95.0 and idle >= TURNAROUND_S:
                    d.announced["battery"] = "ok"
                    dest, kind, prio = self._pick_destination((d.x, d.y))
                    self._launch(d, dest, kind, prio)

    def _launch(self, d: Drone, dest: Place, kind: str, priority: str) -> None:
        d.destination = dest
        d.mission_type = kind
        d.priority = priority
        plan = self.plan_for(d, (d.x, d.y), (dest.x, dest.y))
        if plan is None:
            d.landed_at = self.now  # try again after another turnaround
            return
        route = self.build_route(d, plan.xy, start_alt=0.0, speed=d.cruise_speed)
        d.motion = Motion(route, 0.0, d.cruise_speed, 0.0)
        d.original = route
        d.route_kind = "return" if kind == "return" else "planned"
        d.phase = "returning" if kind == "return" else "cruise"
        d.route_version += 1
        d.maneuver = None
        self.on_route_changed(d)
        self._announce_route(d, plan, "new mission")

    def _validate_routes(self) -> None:
        """Predict no-fly violations on every remaining route before the drone gets there."""
        hard = self.riskmap.hard_static | self.riskmap.hard_zones
        for d in self.airborne():
            if d.phase == "escaping" or d.id in self._replans:
                continue
            m = d.motion
            ahead = m.route.remaining(m.s)
            if len(ahead) < 2:
                continue
            zone = next((z for z in self.zones.zones if z.contains(d.x, d.y)), None)
            if zone is not None:
                self._start_escape(d, zone)
                continue
            s_hit = self.riskmap.first_entry_along(ahead, hard)
            if s_hit is not None:
                self._queue(d, 3, "avoid", {"s_hit": s_hit})

    def _process_replans(self) -> None:
        budget = REPLANS_PER_TICK
        for did, (prio, reason, info) in sorted(self._replans.items(), key=lambda kv: kv[1][0]):
            if budget <= 0:
                break
            del self._replans[did]
            d = self.drones.get(did)
            if d is None or not d.airborne or d.phase == "escaping":
                continue
            budget -= 1
            if reason == "avoid":
                self._avoid(d, info)
            else:
                self._reweight(d, reason)

    def _start_escape(self, d: Drone, zone) -> None:
        plan = plan_escape(self, d, zone)
        if plan is None:
            return
        d.set_motion(plan.motion, "escape")
        d.phase = "escaping"
        d.escape_zone = zone.id
        d.rejoin_s = plan.rejoin_s
        d.maneuver = {"kind": "escape", "label": f"Escaping {zone.label}", "since": self.now, "exit_s": plan.escape_m}
        if plan.divert:
            d.destination = plan.divert
            d.mission_type = "return"
            self.events.emit(
                "MISSION_ABORTED",
                f"{d.id} destination lies inside {zone.label}; diverting to {plan.divert.name} after escaping.",
                drone=d.id,
                reason="destination inside emergency zone",
            )
        speed = plan.motion.speed
        self.events.emit(
            "EMERGENCY_ESCAPE_STARTED",
            f"{d.id} caught inside {zone.label}: shortest safe exit on bearing {plan.bearing:.0f}°, {plan.escape_m:.0f} m "
            f"(~{plan.escape_m / speed:.0f} s at {speed:.0f} m/s), then "
            + (f"diverting to {plan.divert.name}." if plan.divert else "rejoining its original route beyond the zone."),
            drone=d.id,
            zone=zone.id,
            bearing=plan.bearing,
            escape_m=plan.escape_m,
            exits_scored=plan.candidates,
            cost=plan.cost,
            exit=list(self.world.frame.latlon(*plan.exit_xy)),
        )
        self.on_route_changed(d)

    def _avoid(self, d: Drone, info: dict) -> None:
        m = d.motion
        ahead = m.route.remaining(m.s)
        hard = self.riskmap.hard_static | self.riskmap.hard_zones
        s_hit = info.get("s_hit")
        if s_hit is None:
            s_hit = self.riskmap.first_entry_along(ahead, hard)
        if s_hit is None:
            return
        hx, hy = m.route.point(m.s + s_hit)
        hazard = self.hazard_name(hx, hy)
        res = plan_avoidance(self, d)
        if res is None:
            m.hold_until = self.now + 10.0
            d.maneuver = {"kind": "hold", "label": "Holding: no clear route", "conflict": None}
            self.events.emit("REROUTE_STARTED", f"{d.id} route ahead enters {hazard}; no clear route yet, holding 10 s.", drone=d.id, severity="critical")
            return
        motion, rejoin_s, divert, extra = res
        d.set_motion(motion, "return" if divert else "avoid")
        d.rejoin_s = rejoin_s
        d.maneuver = {"kind": "avoid", "label": f"Avoiding {hazard}", "hazard": hazard}
        if divert:
            d.destination = divert
            d.mission_type = "return"
            d.phase = "returning"
            d.original = motion.route
            self.events.emit("MISSION_ABORTED", f"{d.id} destination now lies in {hazard}; diverting to {divert.name}.", drone=d.id, reason="destination restricted")
        else:
            d.phase = "rejoining" if d.phase != "returning" else d.phase
        eta = s_hit / max(m.speed, 1.0)
        self.events.emit(
            "REROUTE_STARTED",
            f"{d.id} route ahead enters {hazard} in {eta:.0f} s; replanned around it with weighted A* ({extra:+.0f} m).",
            drone=d.id,
            hazard=hazard,
            seconds_to_entry=eta,
            extra_m=extra,
        )
        self.on_route_changed(d)

    def _reweight(self, d: Drone, reason: str) -> None:
        m = d.motion
        plan = self.plan_for(d, (d.x, d.y), (d.destination.x, d.destination.y))
        if plan is None:
            return
        route = self.build_route(d, plan.xy, start_alt=d.alt)
        before = m.route.length - m.s
        d.set_motion(Motion(route, 0.0, m.speed, d.alt, m.hold_until), "return" if d.route_kind == "return" else "planned")
        d.original = route
        d.rejoin_s = None
        if d.phase == "rejoining":
            d.phase = "cruise"
        if d.maneuver and d.maneuver["kind"] in ("avoid", "rejoin", "detour"):
            d.maneuver = None
        self.on_route_changed(d)
        self.events.emit(
            "ROUTE_GENERATED",
            f"{d.id} route re-optimised for {reason}: {route.length / 1000:.1f} km ({route.length - before:+.0f} m) "
            f"with weights {self._weights_note(plan.weights)}.",
            drone=d.id,
            reason=reason,
            weights=plan.weights.to_dict(),
        )

    @staticmethod
    def _weights_note(w: Weights) -> str:
        parts = [f"energy x{w.energy:.1f}", f"altitude x{w.altitude:.1f}"]
        if w.risk_scale > 1:
            parts.append(f"risk x{w.risk_scale:.1f}")
        if w.landing > 0:
            parts.append("near-port bias")
        return ", ".join(parts)

    # --- ground monitor hooks ------------------------------------------------------------

    def ground_job(self):
        return self.ground.next_job()

    def ground_result(self, site, frame, detections, model_name: str) -> None:
        change = self.ground.apply(site, frame, detections, model_name, self.now)
        if not change:
            return
        self.riskmap.set_ground(self.ground.sites)
        old, new = change
        if new in ("HIGH", "VERY HIGH") and new != old:
            for d in self.airborne():
                ahead = d.motion.route.remaining(d.motion.s)
                if len(ahead) < 2:
                    continue
                dist = np.hypot(ahead[:, 0] - site.x, ahead[:, 1] - site.y).min()
                if dist < site.radius:
                    self._queue(d, 8, "ground risk")

    # --- output ---------------------------------------------------------------------------

    def snapshot(self) -> dict:
        frame = self.world.frame
        drones = list(self.drones.values())
        return {
            "type": "state",
            "t": round(self.now, 1),
            "speed": self.speed,
            "tick": self.ticks,
            "drones": [d.to_dict(frame) for d in drones],
            "zones": [z.to_dict() for z in self.zones.zones],
            "aircraft": self.aircraft.to_list(),
            "conflicts": self.conflicts.to_list(),
            "crossings": self.conflicts.crossings,
            "ground": self.ground.to_list(),
            "feed": self.ground.feed(),
            "hud": self._hud(drones),
            "airTraffic": {"mode": self.aircraft.mode, "status": self.aircraft.status},
            "healthModel": {"name": self.health.model, "live": self.health.live},
        }

    def _hud(self, drones: list[Drone]) -> dict:
        air = [d for d in drones if d.airborne]
        open_conf = [c for c in self.conflicts.active.values() if c.state != "resolved"]
        unresolved = [c for c in open_conf if c.state in ("predicted", "unresolved")]
        emergencies = self.zones.of_kind("emergency")
        escaping = [d for d in air if d.phase == "escaping"]
        aircraft = [a for a in self.aircraft.aircraft.values() if math.isfinite(a.nearest_m) and a.nearest_m < 25000]
        high_ac = [a for a in aircraft if a.risk == "HIGH"]
        med_ac = [a for a in aircraft if a.risk == "MEDIUM"]
        ground_hot = [s for s in self.ground.sites if s.level in ("HIGH", "VERY HIGH")]
        weak = [d for d in air if d.battery < CRITICAL_BATTERY or d.health < 25]

        def avg(vals):
            return round(sum(vals) / len(vals), 1) if vals else None

        avg_health = avg([d.health for d in drones])
        if emergencies or escaping:
            status = "EMERGENCY"
        elif unresolved or high_ac:
            status = "CONFLICT"
        elif open_conf or med_ac or ground_hot or weak:
            status = "CAUTION"
        else:
            status = "SAFE"
        risk = (
            30 * min(1.0, len(open_conf) / 3)
            + 25 * (1.0 if emergencies else 0.0)
            + 15 * min(1.0, (len(high_ac) + 0.5 * len(med_ac)) / 2)
            + 15 * (1 - (avg_health or 100) / 100)
            + 10 * min(1.0, len(ground_hot) / 3)
            + 5 * min(1.0, len(weak) / 2)
        )
        label = "LOW" if risk < 20 else "MODERATE" if risk < 40 else "ELEVATED" if risk < 60 else "HIGH" if risk < 80 else "SEVERE"
        return {
            "status": status,
            "activeDrones": len(air),
            "totalDrones": len(drones),
            "activeAircraft": len(aircraft),
            "lowAircraft": len([a for a in aircraft if a.relevant]),
            "predictedConflicts": len(open_conf),
            "unresolvedConflicts": len(unresolved),
            "resolvedConflicts": self.conflicts.resolved_total,
            "noFlyZones": len(self.world.restricted),
            "operatorZones": len(self.zones.of_kind("operator")),
            "emergencyZones": len(emergencies),
            "escaping": len(escaping),
            "avgHealth": avg_health,
            "avgRul": avg([d.rul for d in drones]),
            "avgBattery": avg([d.battery for d in drones]),
            "groundAlerts": len(ground_hot),
            "riskLevel": round(risk),
            "riskLabel": label,
        }
