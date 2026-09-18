# 🚁 Drone Airspace Guardian

A working hackathon prototype: a real-time simulated airspace with multiple
drones, restricted zones, automatic conflict detection, A*-based rerouting,
and an "Emergency Priority Mode" corridor demo. No physical drones, maps API
keys, or external services required — everything runs locally.

## 1. Requirements

- Node.js 18+ (check with `node -v`)
- npm (comes with Node)

## 2. Setup

```bash
cd drone-airspace-guardian
npm install
npm start
```

Then open **http://localhost:3000** in your browser. That's the whole setup.

## 3. File organization (why it's laid out this way)

```
drone-airspace-guardian/
├── package.json          # dependencies (express, ws) + "npm start"
├── README.md
├── server/                # everything that runs on Node — the "brain"
│   ├── index.js            # entry point: HTTP + WebSocket server, REST routes, main loop
│   ├── airspace.js          # grid, restricted/emergency zones, A* pathfinding
│   ├── simulation.js        # Drone objects + per-tick movement (Component 2)
│   ├── conflict.js          # conflict detection + resolution + emergency corridor (Components 3 & 4)
│   └── events.js            # shared event log, broadcast to the dashboard
└── public/                # everything served to the browser — the "face"
    ├── index.html           # page shell: canvas + dashboard panel
    ├── style.css            # dark dashboard styling
    └── app.js               # WebSocket client, canvas rendering, button handlers
```

This mirrors the 5-component breakdown from the project plan:

| Plan component            | File(s)                          |
|----------------------------|-----------------------------------|
| 1. Airspace Map            | `public/index.html`, `app.js`, `style.css` |
| 2. Drone Simulation Engine | `server/simulation.js`            |
| 3. Conflict Detection      | `server/conflict.js`              |
| 4. Route Optimization (A*) | `server/airspace.js`              |
| 5. Decision Dashboard      | `public/app.js` (stats + event log), `server/events.js` |

**Why no separate `frontend/` + `backend/` npm projects?** For a 30-hour
build, one Node process serving static files *and* the API/WebSocket is
simpler to run, deploy, and demo than two servers with CORS to worry about.
If your team splits frontend/backend work, each person just owns a
different folder above — the interface between them is the WebSocket
message shape (`{type: 'state', drones, zones, conflicts}` and
`{type: 'event', event}`) plus two POST routes.

## 4. How it works

- **Drones** (`simulation.js`) are plain objects moving along a path of
  waypoints at a fixed speed, losing battery over time.
- **Paths** (`airspace.js`) come from A* over a 100×100 grid, where cells
  inside a restricted or emergency zone are impassable. This is exactly
  "Route Optimization" from the plan — start with A*, later add weighted
  costs for congestion/risk if you have time.
- **Conflict detection** (`conflict.js`) runs every tick: it predicts each
  drone's position ~3 seconds ahead and flags a conflict when two drones
  would be within 25 units *and* within 20m of altitude of each other —
  i.e. it checks position **and** altitude **and** time, not just whether
  two lines cross on the map.
- **Resolution** is priority-based: the lower-priority drone in a conflict
  climbs 30m to separate. This is the "automatic deconfliction," not just
  an alert.
- **Emergency Priority Mode**: `POST /api/emergency` drops a new
  restricted zone, reroutes any drone whose path crosses it, then spawns a
  `critical`-priority drone and forces nearby drones to reroute out of its
  way (`activateEmergencyCorridor`). This is the demo's "wow moment."

## 5. Extending it (Level 2+ from the plan)

- **Battery-aware rerouting**: `simulation.js` already flags
  `status: 'low-battery'`. Add a charging-station list to `airspace.js`
  and call `simulation.rerouteDrone(drone, ...)` toward the nearest one
  when battery drops below a threshold.
- **Weather**: add a `weatherZones` array in `airspace.js` (same shape as
  `restrictedZones`) with a cost penalty instead of a hard block, and use
  it to weight A* cells instead of making them impassable.
- **AI Mission Copilot**: add a `POST /api/mission-from-text` route that
  sends the operator's free-text request to an LLM, asks for strict JSON
  (`{ mission, priority, maxTimeMinutes, constraints }`), and pipes the
  result into `simulation.createDrone(...)`. Keep the LLM out of the
  actual routing/safety decision — it only produces the mission spec.

## 6. Real datasets wired in

Everything above originally ran on synthetic data. `datasets/` now holds
real drone/aviation datasets plus real Dubai geography, each loaded once at
startup by a module in `server/data/` and wired into actual simulation
behaviour (not just stored for reference):

| Dataset | Folder | Drives |
|---|---|---|
| Dubai geography (OpenStreetMap / Nominatim) | `datasets/dubai-map/` | `server/data/dubaiMap.js` -- the airspace grid *is* Dubai: real airports (DXB, DWC), government buildings and stadiums become `airspace.js`'s no-fly zones; real hospitals are marked as hospitals (not restricted) and are the emergency drone's actual destination; Palm Jumeirah's real outline renders as map texture |
| OpenSky Network ADS-B | `datasets/flight-telemetry/` | `server/data/opensky.js` -- real aircraft trajectories, scaled to each aircraft's own local movement, used by the "Spawn Real Flight" button instead of a random A*-routed path |
| NASA C-MAPSS turbofan run-to-failure | `datasets/predictive-maintenance/` | `server/data/maintenance.js` -- every drone is assigned a real recorded engine; its "battery" is that engine's real degradation curve (via sensor 4 / LPT outlet temperature) instead of a linear drain |
| AU-AIR multimodal UAV | `datasets/multimodal-uav/` | `server/data/auair.js` -- real synced GPS/altitude/IMU + object-detection frames, ticking through the "Live Aerial Detection Feed" panel |
| VisDrone2019-DET | `datasets/aerial-detection/` | `server/data/groundZones.js` -- real drone-captured traffic scenes pinned as "Ground Monitoring" zones; drones flying over a dense zone get a real-data-driven advisory event |

Only the annotation/telemetry data needed to drive these features was
vendored in full; VisDrone's and AU-AIR's raw image sets (tens of
thousands of JPEGs) were left out in favour of small representative
samples, since the images themselves aren't used at runtime.

`datasets/aerial-segmentation/` (Dubai land-use segmentation masks) and
`server/data/segmentationZones.js` are still present and working, but are
no longer wired into `airspace.js` -- once the world became real,
geographically-anchored Dubai coordinates, placing that dataset's
un-geotagged building silhouettes at an arbitrary spot would have been
misleading rather than real. The real no-fly zones now come entirely from
`dubaiMap.js`.

`GET /api/datasets` reports what's currently loaded (also shown in the
dashboard's "Data Sources" panel).

## 7. Demo script (from the pitch)

1. Load the page — ~8 drones already moving.
2. Click **Add Drone** a few times to build up traffic and trigger a
   natural conflict (watch a drone climb 30m in the event log).
3. Click **Trigger Emergency** — a new red zone appears, nearby drones
   reroute around it, and a critical medical drone gets a cleared
   corridor straight through. Narrate this as "Priority-Aware Autonomous
   Airspace Guardian" solving deconfliction, not just detecting it.
