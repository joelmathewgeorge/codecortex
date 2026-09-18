"""
Smoke test against a running backend (python -m uvicorn main:app --port 8000).

Reads the WebSocket hello and two state ticks, then exercises the REST surface: add a
drone, draw a no-fly zone and an emergency zone in Downtown Dubai, lift them, and reset.

Run: python test_server.py
"""

import asyncio
import json
import urllib.request

import websockets

API = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws"
DOWNTOWN = (25.1972, 55.2744)


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


async def watch_ws() -> None:
    async with websockets.connect(WS, max_size=None) as ws:
        hello = json.loads(await ws.recv())
        print(f"hello: {len(hello['events'])} events in history")
        states = 0
        while states < 2:
            msg = json.loads(await ws.recv())
            if msg["type"] != "state":
                continue
            states += 1
            hud = msg["hud"]
            print(
                f"state t={msg['t']}: {hud['status']}, {hud['activeDrones']} drones airborne, "
                f"{hud['activeAircraft']} aircraft ({msg['airTraffic']['status']}), "
                f"{hud['predictedConflicts']} open conflicts, risk {hud['riskLevel']}"
            )


def exercise_rest() -> None:
    world = call("GET", "/world")
    print(f"world: {len(world['restricted'])} restricted areas, {len(world['ports'])} drone ports")
    added = call("POST", "/drones", {"mode": "auto"})
    print(f"added {added['drone']['id']}: {added['drone']['mission']} (predicted conflicts: {added['predictedConflicts']})")
    nfz = call("POST", "/zones", {"lat": DOWNTOWN[0], "lon": DOWNTOWN[1]})
    print(f"no-fly {nfz['zone']['id']}: inside {nfz['inside']}, rerouting {nfz['approaching']}")
    ez = call("POST", "/emergency", {"lat": DOWNTOWN[0] + 0.03, "lon": DOWNTOWN[1] - 0.03, "radius": 700})
    print(f"emergency {ez['zone']['id']}: escaping {ez['inside']}, rerouting {ez['approaching']}")
    for zone in (nfz, ez):
        call("DELETE", f"/zones/{zone['zone']['id']}")
    events = call("GET", "/events?limit=20")["events"]
    print("latest events:")
    for e in events[-8:]:
        print(f"  {e['type']:<26} {e['message'][:110]}")
    print(call("POST", "/reset"))


if __name__ == "__main__":
    asyncio.run(watch_ws())
    exercise_rest()
