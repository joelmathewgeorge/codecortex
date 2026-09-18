"""Quick test script — connects to WebSocket, prints 3 ticks, then tests POST /zones."""
import asyncio
import json
import urllib.request

import websockets


async def test_websocket():
    print("=== WebSocket Test (3 ticks) ===\n")
    async with websockets.connect("ws://localhost:8000/ws") as ws:
        for i in range(3):
            msg = json.loads(await ws.recv())
            print(f"--- Tick {i + 1} ---")
            print(f"Type: {msg['type']}")
            print(f"Timestamp: {msg['timestamp']}")
            for d in msg["drones"]:
                print(f"  {d['id']}: ({d['lat']}, {d['lon']}) "
                      f"status={d['status']} health={d['health']}")
            print()


def test_zones():
    print("=== POST /zones Test ===\n")
    data = json.dumps({"lat": 12.97, "lon": 77.59, "radius": 500}).encode()
    req = urllib.request.Request(
        "http://localhost:8000/zones",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = json.loads(urllib.request.urlopen(req).read())
    print(f"Response: {json.dumps(resp, indent=2)}\n")

    print("=== GET /zones Test ===\n")
    resp = json.loads(urllib.request.urlopen("http://localhost:8000/zones").read())
    print(f"Response: {json.dumps(resp, indent=2)}\n")


def test_emergency():
    print("=== POST /emergency Test ===\n")
    # Place emergency zone right on drone-1's path
    data = json.dumps({"lat": 12.978, "lon": 77.590, "radius": 300}).encode()
    req = urllib.request.Request(
        "http://localhost:8000/emergency",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = json.loads(urllib.request.urlopen(req).read())
    print(f"Response: {json.dumps(resp, indent=2)}\n")


if __name__ == "__main__":
    asyncio.run(test_websocket())
    test_zones()
    test_emergency()
    print("All tests passed!")
