"""
Regression tests for the planner's safety guarantees.

Run from this folder with the ml venv:  python test_planner.py   (pytest works too)
Uses AIR_TRAFFIC=replay and no scheduled helicopters so results do not depend on the network.
"""

from __future__ import annotations

import json
import math
import os
import random

os.environ.setdefault("AIR_TRAFFIC", "replay")

import numpy as np  # noqa: E402

from aircraft import Aircraft  # noqa: E402
from config import ALT_MAX_M, DRONE_H_SEP_M, DRONE_V_SEP_M, ML_DIR  # noqa: E402
from drones import Drone  # noqa: E402
from sim import Simulation  # noqa: E402
from trajectory import Motion, make_route  # noqa: E402
from world import Place  # noqa: E402

_SIM: Simulation | None = None

# Open airspace west of Al Quoz in the local frame (metres): no hard cells, no airport ceiling.
A_START, A_END = (-6400.0, -2000.0), (-2000.0, -2000.0)
CROSS = (-6000.0, -2000.0)


def fresh() -> Simulation:
    global _SIM
    if _SIM is None:
        _SIM = Simulation(seed=11)
        _SIM.aircraft._helis = []
        _SIM.aircraft._replay = []
    s = _SIM
    s.drones.clear()
    s.zones.clear()
    s.riskmap.set_zones([])
    s.riskmap.set_routes({})
    s.conflicts.reset()
    s.aircraft.aircraft.clear()
    s._replans.clear()
    s.events.clear()
    return s


def straight(s: Simulation, did: str, start, end, alt: float, speed: float, priority: str = "NORMAL") -> Drone:
    lat, lon = s.world.frame.latlon(*end)
    place = Place(f"test-{did}", f"Test point {did}", "district", lat, lon, end[0], end[1])
    d = Drone(
        id=did,
        mission_type="parcel",
        priority=priority,
        origin=place,
        destination=place,
        home=place,
        cruise_alt=alt,
        cruise_speed=speed,
        battery=90.0,
        wear=0.1,
        x=start[0],
        y=start[1],
        alt=alt,
    )
    route = make_route(np.array([start, end]), alt, alt, alt, speed, s.riskmap.ceiling_at)
    d.motion = Motion(route, 0.0, speed, alt)
    d.original = route
    d.announced = {"battery": "ok", "health": d.health_status, "rul": d.rul}
    s.drones[did] = d
    s.on_route_changed(d)
    return d


def open_airspace(s: Simulation) -> None:
    for p in (A_START, A_END, CROSS, (-6000.0, -4000.0), (-6000.0, 1000.0)):
        r, c = s.riskmap.cell_of(*p)
        assert not s.riskmap.hard[r, c], f"test area {p} is inside restricted airspace"
        assert s.riskmap.ceiling[r, c] >= ALT_MAX_M, f"test area {p} is under an airport ceiling"


def pair_key(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))  # type: ignore[return-value]


def test_astar_never_enters_restricted_airspace():
    s = fresh()
    rng = random.Random(3)
    probe = straight(s, "P1", A_START, A_END, 90.0, 18.0)
    for _ in range(6):
        a, b = rng.sample(s.world.destinations, 2)
        plan = s.plan_for(probe, (a.x, a.y), (b.x, b.y))
        assert plan is not None, f"no route {a.name} -> {b.name}"
        assert s.riskmap.first_hard_along(plan.xy) is None, f"route {a.name} -> {b.name} crosses a hard cell"


def test_crossing_at_different_times_is_not_a_conflict():
    s = fresh()
    open_airspace(s)
    straight(s, "A", A_START, A_END, 90.0, 20.0)  # at the crossing after 20 s
    straight(s, "B", (-6000.0, -2760.0), (-6000.0, 1000.0), 90.0, 20.0)  # at the crossing after 38 s
    s.conflicts.update()
    assert pair_key("A", "B") not in s.conflicts.active
    crossing = [x for x in s.conflicts.crossings if {x["a"], x["b"]} == {"A", "B"}]
    assert crossing and crossing[0]["status"] == "time", crossing


def test_same_time_same_height_is_a_conflict():
    s = fresh()
    open_airspace(s)
    straight(s, "A", A_START, A_END, 90.0, 20.0)
    straight(s, "B", (-6000.0, -2400.0), (-6000.0, 1000.0), 90.0, 20.0)  # both at the crossing after 20 s
    s.conflicts.update()
    c = s.conflicts.active.get(pair_key("A", "B"))
    assert c is not None and c.state == "predicted"
    ttc = c.t_first - s.now
    assert 10.0 <= ttc <= 18.0, ttc
    assert any(e["type"] == "CONFLICT_PREDICTED" for e in s.events.history())


def test_crossing_separated_by_height_is_not_a_conflict():
    s = fresh()
    open_airspace(s)
    straight(s, "A", A_START, A_END, 90.0, 20.0)
    straight(s, "B", (-6000.0, -2400.0), (-6000.0, 1000.0), 90.0 + DRONE_V_SEP_M + 15.0, 20.0)
    s.conflicts.update()
    assert pair_key("A", "B") not in s.conflicts.active
    crossing = [x for x in s.conflicts.crossings if {x["a"], x["b"]} == {"A", "B"}]
    assert crossing and crossing[0]["status"] == "altitude", crossing


def test_lower_priority_yields_and_separation_holds():
    s = fresh()
    open_airspace(s)
    critical = straight(s, "MED", A_START, A_END, 90.0, 20.0, priority="CRITICAL")
    straight(s, "PKG", (-6000.0, -2400.0), (-6000.0, 1000.0), 90.0, 20.0, priority="NORMAL")
    critical_version = critical.route_version
    closest = math.inf
    for _ in range(40):
        s.step(1.0)
        a, b = s.drones.get("MED"), s.drones.get("PKG")
        if a and b and a.airborne and b.airborne and abs(a.alt - b.alt) < DRONE_V_SEP_M:
            closest = min(closest, math.hypot(a.x - b.x, a.y - b.y))
    types = [e["type"] for e in s.events.history()]
    assert "DECONFLICTION_STARTED" in types
    started = next(e for e in s.events.history() if e["type"] == "DECONFLICTION_STARTED")
    assert started["metadata"]["yielding"] == "PKG"
    assert critical.route_version == critical_version and critical.motion.override is None
    assert closest >= DRONE_H_SEP_M * 0.9, f"separation lost: {closest:.0f} m"
    assert "CONFLICT_RESOLVED" in types


def test_drone_yields_to_manned_aircraft():
    s = fresh()
    open_airspace(s)
    drone = straight(s, "D1", A_START, A_END, 110.0, 18.0, priority="CRITICAL")
    # Northbound at 45 m/s, reaching the drone's track where the drone will be ~20 s from now, 40 m above it.
    heli = Aircraft("TEST-HELI", "TEST 1", "helicopter", "scheduled", x=-6040.0, y=-2900.0, alt=150.0, speed=45.0, heading=0.0)
    s.aircraft.aircraft[heli.id] = heli
    s.aircraft.refresh(s.airborne(), s.now)
    assert heli.relevant
    s.conflicts.update()
    c = s.conflicts.active.get(("D1", "TEST-HELI"))
    assert c is not None and c.kind == "aircraft"
    s.now += 3.0
    s.aircraft.refresh(s.airborne(), s.now)
    s.conflicts.update()
    assert c.state == "resolving" and c.yielding == "D1", (c.state, c.yielding)
    assert drone.maneuver is not None


def test_emergency_escape_leaves_zone_and_rejoins():
    s = fresh()
    open_airspace(s)
    d = straight(s, "E1", A_START, A_END, 90.0, 18.0)
    for _ in range(5):
        s.step(1.0)
    lat, lon = s.world.frame.latlon(d.x, d.y)
    result = s.add_zone("emergency", lat, lon, 700.0)
    zone = s.zones.zones[-1]
    assert result["inside"] == ["E1"]
    assert d.phase == "escaping"
    start = next(e for e in s.events.history() if e["type"] == "EMERGENCY_ESCAPE_STARTED")
    assert start["metadata"]["escape_m"] <= zone.radius + 260.0  # it was at the centre: shortest way out
    left = False
    for _ in range(240):
        s.step(1.0)
        if d.phase != "escaping":
            left = True
        if left:
            assert not zone.contains(d.x, d.y), "re-entered the emergency zone"
        if any(e["type"] == "REROUTE_COMPLETED" for e in s.events.history()):
            break
    assert left, "never left the emergency zone"
    assert any(e["type"] == "EMERGENCY_ESCAPE_COMPLETED" for e in s.events.history())
    assert any(e["type"] == "REROUTE_COMPLETED" for e in s.events.history()), "never rejoined the original route"


def test_no_fly_zone_ahead_is_flown_around_not_through():
    s = fresh()
    open_airspace(s)
    d = straight(s, "N1", A_START, A_END, 90.0, 18.0)
    ahead = (A_START[0] + 1800.0, A_START[1])
    lat, lon = s.world.frame.latlon(*ahead)
    result = s.add_zone("operator", lat, lon, 450.0)
    zone = s.zones.zones[-1]
    assert result["approaching"] == ["N1"]
    assert any(e["type"] == "REROUTE_STARTED" for e in s.events.history())
    for _ in range(300):
        s.step(1.0)
        if not d.airborne:
            break
        assert not zone.contains(d.x, d.y), "flew into the no-fly zone"
        if any(e["type"] == "NO_FLY_AVOIDED" for e in s.events.history()):
            break
    assert any(e["type"] == "NO_FLY_AVOIDED" for e in s.events.history())


def test_battery_and_health_change_the_weights():
    s = fresh()
    d = straight(s, "W1", A_START, A_END, 90.0, 18.0)
    base = s.weights_for(d)
    d.battery = 35.0
    low = s.weights_for(d)
    d.battery = 15.0
    critical = s.weights_for(d)
    assert base.energy < low.energy < critical.energy
    d.battery = 90.0
    d.health = 40.0
    worn = s.weights_for(d)
    assert worn.risk_scale > base.risk_scale and worn.landing > 0


def test_auair_missions_are_reanchored_in_dubai():
    path = ML_DIR / "auair_missions.json"
    assert path.exists() and path.stat().st_size > 0
    data = json.loads(path.read_text(encoding="utf-8"))
    missions = data.get("missions") or []
    assert len(missions) >= 3
    for m in missions:
        assert len(m.get("waypoints") or []) >= 4
        for wp in m["waypoints"]:
            assert 25.02 <= wp["lat"] <= 25.30
            assert 55.10 <= wp["lon"] <= 55.43
            assert 40.0 <= wp["alt_m"] <= 150.0
    from sim import AUAIR_SEED_SLOTS, SEED_FLEET
    assert AUAIR_SEED_SLOTS == (1, 3, 6)
    assert [SEED_FLEET[i][0] for i in AUAIR_SEED_SLOTS] == ["parcel", "survey", "security"]


def test_opensky_replay_has_raised_flight_count():
    path = ML_DIR / "air_traffic.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    flights = data.get("flights") or []
    assert len(flights) >= 12
    kinds = {f["kind"] for f in flights}
    assert "arrival" in kinds and "departure" in kinds


def test_hard_static_untouched_without_dubai_layer():
    """Dubai mosaic is not ingested. OSM hard cores stay identical; ground cost is finite."""
    s = fresh()
    hard = s.riskmap.hard_static.copy()
    assert getattr(s.riskmap, "dubai_ground", None) is None
    assert not hasattr(s.riskmap, "_apply_dubai_ground_cost")
    assert np.array_equal(hard, s.riskmap.hard_static)
    assert np.isfinite(s.riskmap.ground_static).all()
    assert not np.isinf(s.riskmap.ground_static).any()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
