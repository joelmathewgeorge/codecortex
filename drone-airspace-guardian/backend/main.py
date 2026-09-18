"""
Drone Airspace Guardian API.

    WS     /ws           "hello" with the event history on connect, then a "state" snapshot
                         every second and an "events" message whenever something happened
    GET    /world        static map: bounds, real restricted airspace (with buffers), drone
                         ports, hospitals, ground-monitor sites, planner constants
    GET    /state        latest snapshot
    GET    /events       event history (?limit=)
    POST   /drones       add a drone               {"mode": "auto" | "random" | "encounter"}
    POST   /zones        operator no-fly ring      {"lat", "lon", "radius"?}
    POST   /emergency    emergency zone            {"lat", "lon", "radius"?}
    DELETE /zones/{id}   lift a zone
    POST   /reset        fresh fleet, zones cleared, event log restarted
    POST   /sim          simulation speed          {"speed": 1 | 2 | 4}
    GET    /media/...    AU-AIR / VisDrone frames behind the camera feed

Run from this folder:
    python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

AIR_TRAFFIC=replay skips the live OpenSky feed and replays recorded flights instead.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import (
    AIRCRAFT_SEPARATION,
    ALT_MAX_M,
    ALT_MIN_M,
    AUAIR_DIR,
    CELL_M,
    COST_AIRCRAFT,
    COST_CONGESTION,
    COST_EMERGENCY_BUFFER,
    COST_GROUND_AREA,
    COST_LOW_BUFFER,
    COST_NEAR_RESTRICTED,
    DRONE_H_SEP_M,
    DRONE_V_SEP_M,
    EMERGENCY_RADIUS_M,
    ML_DIR,
    OPERATOR_ZONE_RADIUS_M,
    PREDICT_HORIZON_S,
    SIM_SPEEDS,
    TICK_S,
)
from sim import Simulation
from vision_bridge import Detector

GROUND_SCORE_EVERY_S = 2.0
VISDRONE_DIR = ML_DIR / "vision_frames"

sim = Simulation()
detector = Detector()
clients: set[WebSocket] = set()
latest: dict[str, str | None] = {"state": None}


def _locked(fn, *args, **kwargs):
    with sim.lock:
        return fn(*args, **kwargs)


async def run_locked(fn, *args, **kwargs):
    return await asyncio.to_thread(_locked, fn, *args, **kwargs)


async def broadcast(text: str) -> None:
    for ws in list(clients):
        try:
            await ws.send_text(text)
        except Exception:
            clients.discard(ws)


def _snapshot_and_events() -> tuple[str, str | None]:
    state = json.dumps(sim.snapshot(), separators=(",", ":"))
    events = sim.events.drain()
    latest["state"] = state
    return state, (json.dumps({"type": "events", "events": events}, separators=(",", ":")) if events else None)


async def push_now() -> None:
    """Send the result of an operator command without waiting for the next tick."""
    state, events = await run_locked(_snapshot_and_events)
    if events:
        await broadcast(events)
    await broadcast(state)


def _tick() -> tuple[str, str | None]:
    with sim.lock:
        sim.step(TICK_S)
        return _snapshot_and_events()


async def tick_loop() -> None:
    loop = asyncio.get_running_loop()
    while True:
        started = loop.time()
        try:
            state, events = await asyncio.to_thread(_tick)
            if events:
                await broadcast(events)
            await broadcast(state)
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(max(0.05, TICK_S - (loop.time() - started)))


async def vision_loop() -> None:
    await asyncio.to_thread(detector.load)
    with sim.lock:
        sim.ground.model_name = detector.name if detector.ready else "dataset labels"
        sim.ground.metrics = detector.metrics()
    while True:
        try:
            job = await run_locked(sim.ground_job)
            if job:
                site, frame = job
                path = sim.ground.frame_path(frame)
                detections = await asyncio.to_thread(detector.detect, path) if detector.ready and path.exists() else None
                await run_locked(sim.ground_result, site, frame, detections, detector.name)
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(GROUND_SCORE_EVERY_S)


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = [asyncio.create_task(tick_loop()), asyncio.create_task(vision_loop())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(
    title="Drone Airspace Guardian",
    description="Hybrid adaptive airspace planning over real Dubai airspace.",
    version="0.2.0",
    lifespan=lifespan,
)
# Two ports on one laptop (Next.js on 3000, this API on 8000); not a production posture.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ZoneBody(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius: float | None = Field(default=None, ge=100, le=3000)


class DroneBody(BaseModel):
    mode: Literal["auto", "random", "encounter"] = "auto"


class SpeedBody(BaseModel):
    speed: int


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    try:
        history = await run_locked(sim.events.history, 800)
        await ws.send_text(json.dumps({"type": "hello", "events": history}, separators=(",", ":")))
        if latest["state"]:
            await ws.send_text(latest["state"])
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)


@app.get("/")
async def root() -> dict:
    return {
        "service": "Drone Airspace Guardian",
        "status": "running",
        "city": "dubai",
        "drones": len(sim.drones),
        "restrictedAreas": len(sim.world.restricted),
        "zones": len(sim.zones.zones),
        "airTraffic": sim.aircraft.status,
        "detector": detector.name,
    }


@app.get("/world")
async def world() -> dict:
    def build() -> dict:
        out = sim.world.to_dict()
        out["groundSites"] = [
            {"id": s.id, "name": s.name, "road": s.road, "lat": s.lat, "lon": s.lon, "radius": s.radius} for s in sim.ground.sites
        ]
        out["planner"] = {
            "cellM": CELL_M,
            "droneSeparation": {"horizontalM": DRONE_H_SEP_M, "verticalM": DRONE_V_SEP_M},
            "aircraftSeparation": {k: {"horizontalM": h, "verticalM": v} for k, (h, v) in AIRCRAFT_SEPARATION.items()},
            "predictionHorizonS": PREDICT_HORIZON_S,
            "altitudeBandM": [ALT_MIN_M, ALT_MAX_M],
            "costs": {
                "normal": 1,
                "lowRiskBuffer": COST_LOW_BUFFER,
                "droneCongestion": COST_CONGESTION,
                "groundRiskArea": COST_GROUND_AREA,
                "nearRestricted": COST_NEAR_RESTRICTED,
                "aircraftProximity": COST_AIRCRAFT,
                "emergencyBuffer": COST_EMERGENCY_BUFFER,
                "hard": "infinity",
            },
            "emergencyRadiusM": EMERGENCY_RADIUS_M,
            "operatorRadiusM": OPERATOR_ZONE_RADIUS_M,
            "simSpeeds": list(SIM_SPEEDS),
        }
        return out

    return await run_locked(build)


@app.get("/state")
async def state() -> dict:
    return await run_locked(sim.snapshot)


@app.get("/events")
async def events(limit: int = 500) -> dict:
    return {"events": await run_locked(sim.events.history, max(1, min(limit, 2000)))}


@app.post("/drones")
async def add_drone(body: DroneBody | None = None) -> dict:
    try:
        result = await run_locked(sim.add_drone, (body or DroneBody()).mode)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await push_now()
    return result


async def _zone(kind: str, body: ZoneBody) -> dict:
    try:
        result = await run_locked(sim.add_zone, kind, body.lat, body.lon, body.radius)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await push_now()
    return result


@app.post("/zones")
async def create_zone(body: ZoneBody) -> dict:
    return await _zone("operator", body)


@app.post("/emergency")
async def create_emergency(body: ZoneBody) -> dict:
    return await _zone("emergency", body)


@app.delete("/zones/{zone_id}")
async def delete_zone(zone_id: str) -> dict:
    try:
        result = await run_locked(sim.remove_zone, zone_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no zone {zone_id}") from exc
    await push_now()
    return result


@app.post("/sim")
async def set_speed(body: SpeedBody) -> dict:
    try:
        await run_locked(sim.set_speed, body.speed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"speed": body.speed}


@app.post("/reset")
async def reset() -> dict:
    def do_reset() -> list[dict]:
        sim.reset()
        sim.events.drain()  # clients get these through the hello below, not twice
        return sim.events.history(800)

    history = await run_locked(do_reset)
    await broadcast(json.dumps({"type": "hello", "events": history, "reset": True}, separators=(",", ":")))
    await push_now()
    return {"status": "reset", "drones": len(sim.drones)}


if AUAIR_DIR.exists():
    app.mount("/media/auair", StaticFiles(directory=str(AUAIR_DIR)), name="auair")
if VISDRONE_DIR.exists():
    app.mount("/media/visdrone", StaticFiles(directory=str(VISDRONE_DIR)), name="visdrone")
