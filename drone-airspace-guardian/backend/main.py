"""
Drone Airspace Guardian — Backend Server

This is the main entry point. It creates the FastAPI app with:
    - WebSocket /ws       → pushes drone positions every ~1 second
    - POST     /zones     → create a no-fly zone
    - GET      /zones     → list all zones
    - POST     /emergency → create emergency zone + immediate conflict check

HOW TO RUN:
    cd backend
    .venv/Scripts/activate       (Windows)
    source .venv/bin/activate    (Mac/Linux)
    uvicorn main:app --reload

    The --reload flag watches for file changes and auto-restarts.
    Great during development, remove it in production.

HOW TO TEST (no frontend needed):
    pip install websockets    (already in requirements.txt)
    python -m websockets ws://localhost:8000/ws

    You'll see drone position JSON every second in the terminal.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from drones import Drone, create_default_drones, mark_proximity
from health_bridge import warmup as warmup_ml
from zones import add_zone, get_all_zones

# ---------------------------------------------------------------------------
# FastAPI app setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Drone Airspace Guardian",
    description="Real-time drone tracking, no-fly zone management, and conflict detection.",
    version="0.1.0",
)

# CORS middleware — allows Joel's frontend (running on a different port)
# to call our API.  Without this, the browser blocks cross-origin requests.
#
# WHY allow_origins=["*"]?
#   For development, we allow ALL origins. In production, you'd lock this
#   down to the actual frontend URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

# The 5 simulated drones — created once when the server starts
drones: list[Drone] = create_default_drones()

# All connected WebSocket clients — we broadcast to everyone
connected_clients: set[WebSocket] = set()


# ---------------------------------------------------------------------------
# Pydantic models for request validation
# ---------------------------------------------------------------------------
# WHY PYDANTIC?
#   FastAPI uses Pydantic to automatically validate incoming JSON.
#   If someone sends {"lat": "not-a-number"}, FastAPI returns a
#   422 error with a helpful message — no manual validation needed.

class ZoneCreate(BaseModel):
    """Request body for POST /zones and POST /emergency."""
    lat: float
    lon: float
    radius: float  # in metres


# ---------------------------------------------------------------------------
# Helper: broadcast a message to all connected WebSocket clients
# ---------------------------------------------------------------------------

async def broadcast(message: dict) -> None:
    """
    Send a JSON message to every connected WebSocket client.

    WHY NOT JUST websocket.send()?
        We might have multiple frontends connected at once (Joel testing
        on his machine, you testing on yours, etc.). We need to send to ALL.

    If a client has disconnected, we catch the exception and remove it.
    """
    payload = json.dumps(message)
    disconnected = set()

    for ws in connected_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.add(ws)

    # Clean up stale connections
    connected_clients.difference_update(disconnected)


# ---------------------------------------------------------------------------
# Background task: simulation tick loop
# ---------------------------------------------------------------------------

async def simulation_loop() -> None:
    """
    Main simulation loop — runs every 1 second.

    Each tick:
        1. Move each drone (linear interpolation along its path)
        2. Build the position payload
        3. Broadcast to all WebSocket clients

    WHY asyncio.sleep(1)?
        This is cooperative multitasking. The sleep yields control back
        to the event loop so FastAPI can handle HTTP requests (like
        POST /zones) between ticks.
    """
    while True:
        # 1. Tick all drones
        for drone in drones:
            drone.tick()
        mark_proximity(drones)

        message = {
            "type": "positions",
            "drones": [d.to_dict() for d in drones],
            "zones": [z.to_dict() for z in get_all_zones()],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 3. Broadcast to all connected clients
        await broadcast(message)

        # 4. Wait ~1 second before next tick
        await asyncio.sleep(1)


# ---------------------------------------------------------------------------
# Startup event: launch the simulation loop
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    """
    Called once when the server starts.
    Launches the simulation as a background asyncio task.

    WHY create_task()?
        We want the simulation to run concurrently with the HTTP/WS
        server. create_task() schedules it on the event loop without
        blocking the server from handling requests.
    """
    warmup_ml()
    asyncio.create_task(simulation_loop())


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time drone tracking.

    LIFECYCLE:
        1. Client connects → we accept and add them to the set
        2. The simulation_loop broadcasts positions to them every second
        3. Client disconnects → we remove them from the set

    The receive loop is there to detect disconnections. We don't expect
    the client to send us anything (yet), but WebSocket requires us
    to read in order to detect when the connection closes.
    """
    await websocket.accept()
    connected_clients.add(websocket)
    await websocket.send_text(
        json.dumps(
            {
                "type": "positions",
                "drones": [d.to_dict() for d in drones],
                "zones": [z.to_dict() for z in get_all_zones()],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    )

    try:
        # Keep the connection alive by reading (even though we don't use the data)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.discard(websocket)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.post("/zones")
async def create_zone(body: ZoneCreate):
    """
    Create a no-fly zone.

    Request:  POST /zones  {"lat": 12.97, "lon": 77.59, "radius": 500}
    Response: {"status": "created", "zone": {...}}

    The zone is stored in memory and the conflict check runs automatically
    on the next simulation tick (within ~1 second).
    """
    zone = add_zone(lat=body.lat, lon=body.lon, radius=body.radius)
    return {"status": "created", "zone": zone.to_dict()}


@app.get("/zones")
async def list_zones():
    """
    List all active no-fly and emergency zones.

    Response: {"zones": [{...}, {...}]}
    """
    return {"zones": [z.to_dict() for z in get_all_zones()]}


@app.post("/emergency")
async def create_emergency(body: ZoneCreate):
    """
    Create an emergency danger zone and IMMEDIATELY check for conflicts.

    Unlike POST /zones, this doesn't wait for the next tick — it runs
    the conflict check right now and broadcasts an alert.

    Request:  POST /emergency  {"lat": 12.97, "lon": 77.59, "radius": 300}
    Response: {"status": "emergency_created", "zone": {...}, "affected_drones": [...]}
    """
    zone = add_zone(lat=body.lat, lon=body.lon, radius=body.radius, emergency=True)

    # Immediately check all drones
    affected = []
    for drone in drones:
        conflicts = drone.force_reroute_check()
        if conflicts:
            affected.append(drone.id)

    # Broadcast alert to all connected clients
    alert = {
        "type": "alert",
        "zone": zone.to_dict(),
        "affected_drones": affected,
        "message": (
            f"Airspace conflict — rerouting {len(affected)} drone(s)"
            if affected
            else "Emergency zone created — no drones in radius"
        ),
        "severity": "high",
    }
    await broadcast(alert)

    return {
        "status": "emergency_created",
        "zone": zone.to_dict(),
        "affected_drones": affected,
    }


# ---------------------------------------------------------------------------
# Health check endpoint (bonus — useful for monitoring)
# ---------------------------------------------------------------------------

@app.get("/state")
async def get_state():
    return {
        "drones": [d.to_dict() for d in drones],
        "zones": [z.to_dict() for z in get_all_zones()],
    }


@app.get("/")
async def root():
    """Simple health check — confirms the server is running."""
    return {
        "service": "Drone Airspace Guardian",
        "status": "running",
        "drones": len(drones),
        "zones": len(get_all_zones()),
    }
