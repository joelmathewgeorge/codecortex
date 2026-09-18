# Drone Airspace Guardian — restore context (v2)

Handoff for a new agent. Snapshot of the running stack as of 18 Sep 2026, after the hybrid planner console. Prefer the code if this file and the chat disagree. Do not treat `ml/PROMPT.md` or `ml/EXTENSION_PROMPT.md` as the live architecture; they predate this build.

Public pitch: repo-root [`README.md`](../README.md). Runbook: [`README.md`](README.md). Ownership: [`.github/CODEOWNERS`](../.github/CODEOWNERS).

---

## 1. Pitch

A same-laptop **BVLOS operator console** for Downtown Dubai delivery airspace. Eight simulated drones fly port-to-destination missions over **real OpenStreetMap restricted polygons** (airports, runway-approach funnels, military sites, Zabeel Palace, stadia, Meydan, power plants). An operator adds traffic, draws no-fly rings, and places emergency zones. Weighted A* detours, 4-D deconfliction yields, and an emergency escape planner flies the cheapest safe exit then rejoins the original route.

There is no database, no auth, no radio link, and no physical UAV. Next.js on **:3000**, FastAPI on **:8000**. FastAPI describes itself as *hybrid adaptive airspace planning* (`main.py` version `0.2.0`).

The HUD answers: who is where, what is blocked, what will collide, and what the planner just did.

---

## 2. Architecture

```
Next.js Console `/` + Event log `/events`   (:3000)
        |  REST  POST /drones /zones /emergency /sim /reset, DELETE /zones/{id}
        |  WS    /ws  hello (history) -> state ~1 Hz -> events bursts
        v
FastAPI Simulation (in-memory, process-global)               (:8000)
        |-- sim.py            tick, fleet, replan queue, HUD
        |-- planner.py        epsilon-weighted A* + string-pull
        |-- emergency.py      escape + rejoin original (or divert to port)
        |-- risk_map.py       150 m Dynamic Risk Map
        |-- conflicts.py      4-D prediction + tactical manoeuvres
        |-- zones.py          operator NFZ + emergency rings
        |-- world.py          OSM dubai_airspace.json
        |-- aircraft.py       OpenSky live | replay | scheduled helis
        |-- ground.py         six road cameras
        |-- vision_bridge.py  YOLOv8n (VisDrone fine-tune)
        |-- health_bridge.py  C-MAPSS RUL via ml/predict.py
        +-- drones.py         battery energy model (separate from health)
```

**Frontend.** Next.js 16.3 / React 19 App Router. `app/layout.tsx` wraps everything in `AirspaceProvider` + `TopBar` (Console | Event log tabs, sim clock, **1x / 2x / 4x**, OpenSky live/replay chip, Live/Offline). `app/page.tsx` mounts `Console`. Leaflet map: Esri World Imagery + CARTO labels (`AirspaceMap`). Types in `frontend/types/airspace.ts`. Defaults in `frontend/lib/config.ts`: REST `http://127.0.0.1:8000`, WS `ws://127.0.0.1:8000/ws`. Emergency radii **500 / 700 / 1000 / 1400 m**.

**Backend.** uvicorn `main:app` on 127.0.0.1:**8000**. CORS `allow_origins=["*"]` for two ports on one laptop. `tick_loop` broadcasts every `TICK_S = 1.0` wall second; physics sub-steps at `SUBSTEP_S = 0.25` sim seconds. A* only re-runs when the risk map or a route is dirty (`REPLANS_PER_TICK = 6`). `vision_loop` scores one ground-camera frame every 2 s.

**Planner.** Multi-objective weighted A* over `RiskMap.cost_field` (`planner.py`). Heuristic inflated by `ASTAR_EPSILON = 1.25` (result bounded 25% above optimal). Hard cells are infinity and never expanded. 8-connected path is string-pulled into a few clear legs. Per-drone weights in `sim.weights_for`: low battery raises energy/altitude; low health raises `risk_scale` and a landing-near-port term.

**Risk map.** 150 m grid (`CELL_M`). Static: OSM restricted cores (hard), category buffers, airport ceiling 60 m in airport buffers, water vs urban land, roads, crowd hotspots, distance to nearest port. Dynamic: operator/emergency zones, YOLO ground-risk discs, route congestion, predicted aircraft volumes. Costs per metre (from `config.py`): normal 1, low buffer 5, congestion 10, ground HIGH 15, near-restricted 25, aircraft 100, emergency buffer 500.

**Deconfliction.** `conflicts.py`: project each airborne motion 75 s (`CANDIDATE_HORIZON_S`) as (x, y, alt). A drone-drone conflict is same-second proximity closer than **150 m horiz and 30 m vert**. Detection window used for the first-hit search is 45 s (`PREDICT_HORIZON_S`). Predicted conflicts stay red `DECISION_DELAY_S = 2` (skipped if TTC < 8 s), then the **lower-priority** drone yields (CRITICAL > HIGH > NORMAL > LOW). Candidates: climb, descend, hold, lateral detour, weighted-A* replan. Cheapest safe option is flown. **Manned aircraft always win.**

**Emergency.** `emergency.py`: drones inside a new emergency fly a scored exit (every 10 degrees just outside the ring) at `ESCAPE_SPEED_FACTOR = 1.35`, then A* around the now-hard zone to a rejoin point on the **original** route. If the destination is inside, divert to the nearest drone port. Drones whose remaining route would enter the zone reroute before entry. Original track is kept as a dashed ghost on the map until phase `rejoining`.

**ML.** Health: `health_bridge.py` walks each drone along a synthetic C-MAPSS sensor trace; one model cycle every 15 airborne sim seconds (`HEALTH_MODEL_EVERY_S`), batched. Vision: `vision_bridge.py` loads `ml/weights/yolov8n_airspace.pt` as `yolov8n-airspace`, else `ml/yolov8n.pt`. Ground sites without a detector count dataset labels; without frames they stay MEDIUM with an empty camera.

State is in-memory. Restart wipes fleet, zones, and the event log.

---

## 3. Feature inventory (true now)

| Feature | What the code does |
| --- | --- |
| Opening fleet | Eight simulated drones in `SEED_FLEET` (`sim.py`): medical, parcel, food, survey, organ, parcel (low battery), security, retail (worn airframe). Missions are A*-planned port/hospital/mall/district legs, not hardcoded Downtown loops. |
| Add drone | Toolbar `POST /drones` `{ "mode": "auto" }`. Button reads **Planning route** while A* runs. Notice: *Dxx launched on a clear route* or *Dxx launched. Conflict predicted with …*. Modes `random` / `encounter` exist on the API. Cap via 409 if no plan. |
| Draw no-fly | Arm **Draw no-fly**, click map. Default **450 m** (`OPERATOR_ZONE_RADIUS_M`), cap **4** (oldest dropped). Hint: *Click the map to place a 450 m no-fly zone. Press Escape to cancel.* Popup **Lift no-fly zone** -> `DELETE /zones/{id}`. Inside drones escape; approaching drones reroute. |
| Trigger emergency | Select 500/700/1000/1400 m, **Trigger emergency**, click map. Cap **3**. Banner: *Dxx escaping the emergency zone by the shortest safe exit*. Then **Rejoining route**. Backend default radius 700 m if omitted. |
| Reset | **Reset** -> opening eight, zones cleared, event log restarted. Notice: *Airspace reset to the opening fleet.* WS sends `hello` with `reset: true`. |
| Sim speed | Top bar **1x 2x 4x** -> `POST /sim` `{ "speed": 1 \| 2 \| 4 }`. |
| HUD | `StatusPanel` annunciator **SAFE / CAUTION / CONFLICT / EMERGENCY** from `sim._hud`. EMERGENCY if any emergency zone or drone in phase `escaping`; CONFLICT if unresolved predicted conflict or HIGH-risk aircraft; CAUTION if resolving conflicts, MEDIUM aircraft, HIGH/VERY HIGH ground, or weak battery/health; else SAFE. Separate gauges: airspace risk 0-100, fleet health, average RUL (cycles), **average battery**. Battery is not health. |
| Conflict flash + deconflict | Map + banner from `MapOverlays.AlertBanner`. Types in `airspace.ts`: drone phases `cruise \| holding \| escaping \| rejoining \| returning \| landed \| charging`; conflict marks `none \| predicted \| resolving \| resolved`. Event log expands a **candidate manoeuvre table**. |
| Event log page | `/events` (`EventLog.tsx`). Same WS. Filter by severity and kind, search drone/text, **Pause live updates**, **Export … as JSON**. Types include `CONFLICT_PREDICTED`, `EMERGENCY_ESCAPE_*`, `RUL_UPDATED`, `GROUND_RISK_*`, etc. (`events.py`). |
| Predetermined OSM restricted | 39 polygons from `ml/dubai_airspace.json`: 2 airport, 2 airfield, 6 approach funnels, 5 military, 1 palace, 3 government, 9 power, 10 stadium, 1 racecourse. Category buffers in `RESTRICTED_POLICY`. Eight drone ports. Not operator-drawn. |
| Ground risk monitor | Six sites (`ground.py`): Sheikh Zayed / Al Khail / Al Ittihad / Al Sufouh. YOLO (or labels) -> LOW / MEDIUM / HIGH / VERY HIGH. HIGH+ adds cost and can queue a replan. Right rail `GroundCamera`. |
| OpenSky live vs replay | Default `AIR_TRAFFIC=live` polls OpenSky for the Dubai box (anonymous ~20 s, OAuth client ~10 s). `AIR_TRAFFIC=replay` (or live failure) replays eight DXB **30L** tracks in `ml/air_traffic.json`. Four scheduled helicopters (MEDEVAC / POLICE / TOUR) always share the drone band. Top bar: **OpenSky live** / **OpenSky stale** / **OpenSky replay**. |
| Console chrome | Left: HUD + `FleetList` (per-drone battery bar vs health bar). Centre: map, toolbar, legend. Right: `TrafficFeed`, ground camera, `EventTicker`. |

Leftover, **not** on the live route: `AirspaceDashboard`, `DroneMap`, `MapControls`, `VisionDock`, `ConflictBanner` (old), `useDroneFeed`, `lib/fake-simulator.ts`. `app/page.tsx` mounts `Console` only. `backend/missions.py` (if present) is unused; missions come from `sim.py` + A*. `ml/trajectories.json` is not the live drone path source.

---

## 4. Datasets

Raw dumps stay off git. Training/export scripts default to `C:\Users\rohit\Downloads\Datasets\...`.

| Dataset | Role | Git | Live path |
| --- | --- | --- | --- |
| OSM / Overpass | `ml/build_airspace.py` -> `ml/dubai_airspace.json` (39 restricted, 8 ports, 78 hospitals, roads, water mask). Cache `ml/.cache/osm/` | JSON **committed**. Cache **gitignored** | Yes. ODbL 1.0 |
| OpenSky Network | Live ADS-B box. `ml/build_air_traffic.py` -> `ml/air_traffic.json` (8 arrivals/departures re-anchored to DXB 30L). Older `trajectories.json` is leftover capture extract | Derived JSON **committed**. Raw CSV **not** in git | Yes as **manned** traffic, not drone missions |
| NASA C-MAPSS FD001-FD004 | `ml/train_model.py` -> `rul_model.joblib` (HistGradientBoosting: held-out RMSE **14.78** cycles, MAE 10.50, R2 0.877; 709 train / 707 test engines) | Model **committed**. Raw C-MAPSS **not** in git | Yes — synthetic traces scored by the trained estimator |
| VisDrone2019-DET | `ml/train_yolov8n.py` -> `weights/yolov8n_airspace.pt` + `vision_metrics.json`. Native 512 crops, 6 classes (person/car/van/truck/bus/motor). Val **mAP50 0.2863** (8 epochs, 924 train / 107 val images) | Weights + metrics **committed**. Frames/runs **gitignored** (`vision_frames/`, `yolo_data/`, `runs/`, `*.pt` except `ml/weights/*.pt`) | Yes as the detector; `ml/vision_frames/` optional fallback stills |
| AU-AIR | `ml/export_auair_frames.py` -> `ml/auair_frames/` (six 30-frame windows). Licence asks for links, not rebundling | **Gitignored** | Yes when exported. Else VisDrone stills, or MEDIUM + empty camera |
| Dubai aerial plates `frontend/public/dubai/tile-*.png` | Old overlay | May exist | **Not used.** Live map is Esri |

`.gitignore` also drops `venv/`, `.next/`, `node_modules/`, `.env*`, `debug-*.log`.

---

## 5. How to run

Two PowerShell terminals. Team Python env is `drone-airspace-guardian/ml/venv`. Install **both** requirement files into it.

### Backend (FastAPI, 8000)

```powershell
cd drone-airspace-guardian\ml
python -m venv venv          # skip if ml\venv already exists
.\venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pip install -r ..\backend\requirements.txt
cd ..\backend
$env:AIR_TRAFFIC = "replay"  # omit to poll live OpenSky
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

`GET http://127.0.0.1:8000/` should include `"city": "dubai"`. Optional smoke: `python test_server.py` (Downtown 25.1972, 55.2744). Drop `--reload` for a stable demo. Without `ultralytics`, map + planner still run.

Optional OpenSky OAuth: `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET`. Poll interval `OPENSKY_POLL_S` (default 20 anonymous / 10 with client).

Ground cameras: `python export_auair_frames.py` from `ml/` against a local AU-AIR copy (`AUAIR_DIR` overrides).

### Frontend (Next.js, 3000)

```powershell
cd drone-airspace-guardian\frontend
npm install
npm run dev
```

Open http://localhost:3000. Top bar should read **Live**. **Offline** / **Disconnected** means FastAPI is not on 8000.

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://127.0.0.1:8000` | REST |
| `NEXT_PUBLIC_WS_URL` | `ws://127.0.0.1:8000/ws` | Stream |
| `AIR_TRAFFIC` | `live` | `replay` uses `ml/air_traffic.json` |

Retrain (not needed to demo): `python train_model.py`, `python sanity_check.py`, `python train_yolov8n.py`, `python build_airspace.py`, `python build_air_traffic.py`.

---

## 6. API (`backend/main.py`)

Zone body: `{ "lat", "lon", "radius"? }` metres. Operator default 450 m, emergency default 700 m.

| Method | Path | What it does |
| --- | --- | --- |
| WS | `/ws` | `hello` with up to 800 events (`reset: true` after reset); then `state` ~1 Hz; `events` when the bus drained something |
| GET | `/` | Health: `city: "dubai"`, drone count, restricted-area count, `airTraffic`, detector name |
| GET | `/world` | Static OSM map + `groundSites` + `planner` constants (cell, separation, costs, speeds) |
| GET | `/state` | Latest snapshot: drones, zones, aircraft, conflicts, crossings, ground, feed, hud, airTraffic, healthModel |
| GET | `/events` | `{ "events": [...] }` (`?limit=`, 1-2000, default 500) |
| POST | `/drones` | `{ "mode": "auto" \| "random" \| "encounter" }`. 409 if no plan |
| POST | `/zones` | Operator no-fly. Returns zone + `inside` + `approaching` |
| POST | `/emergency` | Emergency zone. Same shape; drones inside start escape |
| DELETE | `/zones/{id}` | Lift a drawn zone. 404 if missing |
| POST | `/sim` | `{ "speed": 1 \| 2 \| 4 }` |
| POST | `/reset` | Opening fleet, zones cleared, log restarted |
| GET | `/media/auair/...` | AU-AIR frames if `ml/auair_frames/` exists |
| GET | `/media/visdrone/...` | VisDrone stills if `ml/vision_frames/` exists |

`POST /drones` -> `{ "drone": {...}, "predictedConflicts": ["D03", ...] }`.  
`POST /reset` -> `{ "status": "reset", "drones": <opening size> }`.

---

## 7. File map

### Backend (Pranav)

| File | Role |
| --- | --- |
| `main.py` | FastAPI, WS, REST, tick + vision loops |
| `sim.py` | Simulation owner: seed fleet, step, HUD, add_drone / add_zone |
| `config.py` | All policy numbers |
| `planner.py` | Weighted A* + string-pull |
| `emergency.py` | Escape planner + mid-flight avoidance |
| `risk_map.py` | 150 m cost grid |
| `conflicts.py` | 4-D prediction + yield manoeuvres |
| `world.py` | Load OSM JSON, local ENU frame |
| `zones.py` | Operator + emergency circles |
| `drones.py` | Drone state, battery vs health |
| `trajectory.py` | Route / Motion / predict |
| `aircraft.py` | OpenSky + replay + helis |
| `ground.py` | Six cameras, risk levels |
| `vision_bridge.py` | YOLO load/detect |
| `health_bridge.py` | C-MAPSS bridge |
| `events.py` | Event bus |
| `geo_utils.py` | Lat/lon <-> metres |
| `test_server.py` | Live REST/WS smoke |
| `test_planner.py` | Planner unit checks |

### Frontend (Joel)

| File | Role |
| --- | --- |
| `app/page.tsx` | Console |
| `app/events/page.tsx` | Event log |
| `app/layout.tsx` | Provider + TopBar |
| `components/Console.tsx` | Three-pane shell |
| `components/AirspaceProvider.tsx` | World fetch, WS, toolbar actions |
| `components/MapToolbar.tsx` | Add / Draw / Emergency / Reset |
| `components/StatusPanel.tsx` | HUD annunciator |
| `components/EventLog.tsx` | `/events` page |
| `components/AirspaceMap.tsx` | Leaflet |
| `components/MapOverlays.tsx` | Banner, placing hint, notices, legend |
| `components/FleetList.tsx` | Battery vs health rows |
| `types/airspace.ts` | HUD, phases, conflicts, world |
| `lib/api.ts` | REST client |
| `lib/config.ts` | Ports, radii |

### ML (Rohit)

| File | Role |
| --- | --- |
| `predict.py` | `predict_health`, `HealthMonitor`, telemetry simulator |
| `cmapss.py` | Shared features |
| `train_model.py` / `sanity_check.py` | RUL train + four checks |
| `rul_model.joblib` / `model_metadata.json` | Shipped estimator |
| `build_airspace.py` / `dubai_airspace.json` | OSM world |
| `build_air_traffic.py` / `air_traffic.json` | DXB replay |
| `train_yolov8n.py` | VisDrone fine-tune |
| `weights/yolov8n_airspace.pt` + `vision_metrics.json` | Detector + mAP50 0.2863 |
| `export_auair_frames.py` | Local camera export |

---

## 8. Team

Stay in your folder unless a change is coordinated. This file is the exception: it describes the whole stack.

| Person | Role | Directory | GitHub |
| --- | --- | --- | --- |
| Joel | Frontend | `drone-airspace-guardian/frontend/` | [@joelmathewgeorge](https://github.com/joelmathewgeorge) |
| Pranav | Backend | `drone-airspace-guardian/backend/` | [@pranav3086](https://github.com/pranav3086) |
| Rohit | ML | `drone-airspace-guardian/ml/` | [@vrrroro](https://github.com/vrrroro) |

---

## 9. Known limitations

- The fleet is **software**. Nothing commands or tracks a physical UAV.
- Planner numbers (150 m cells, 150/30 m drone separation, cost table, 40-150 m altitude band) are demo policy, not certified UTM.
- OpenSky live is real ADS-B and often rate-limits anonymously. Replay tracks are **airliner** state vectors re-anchored to DXB 30L, not Dubai drone flights. Use `AIR_TRAFFIC=replay` for a judge demo.
- Scheduled helicopters are scripted on OSM hospitals and E11, not live rotorcraft.
- Health is a **turbofan** RUL model on stand-in traces. Battery is a separate energy drain (`BATTERY_PER_KM`, climb, hover). Real airframe telemetry would need a new training set.
- Ground cameras replay AU-AIR (or VisDrone) stills. VisDrone is street-level aerial traffic, not Dubai and not drone-vs-drone. **mAP50 = 0.2863** (8 epochs) — modest, not production detection.
- AU-AIR frames are local-only (gitignored). Without the export, cameras degrade.
- Zones, fleet, and the event log vanish on process restart.
- Leftover v1 dashboard files (`AirspaceDashboard`, mock simulator, `missions.py` / `trajectories.json` as drone paths) are unused.

---

## 10. Open work for branch `v3airguard` (do not implement here)

Intended ML / dataset expansion only. Hybrid planner console is v2. Branch exists so this work can land later.

- Train YOLOv8n longer and on more VisDrone source frames (today: 8 epochs, 520/110 source images cropped to 924/107). Target a higher val mAP50 than **0.2863**; keep the six HUD classes.
- Put more VisDrone val/test-dev stills into the live camera rotation instead of a handful of fallback frames.
- Export richer AU-AIR into the loop: more than six 30-frame windows, more of the eight real sessions, keep GPS/IMU sidecars on every frame the ground monitor already knows how to show.
- Use AU-AIR session traces as **drone missions** (downsample GPS to waypoints, rescale altitude into the 40-150 m band) rather than only as camera footage under A*-invented legs.
- Drive OpenSky harder: more than eight DXB-30L replay flights from the capture, and a more reliable live path (client credentials, backoff, clearer stale/replay fallback).
- Mix AU-AIR boxes into YOLO training (or a second head) so the detector sees low-altitude UAV viewpoints, not only VisDrone street crops.
- Optionally add the unused Dubai aerial segmentation tiles as a static ground-cost layer under the 150 m risk map (Road/Land/Water/Building) without replacing OSM hard NFZs.
- Keep C-MAPSS as the health model unless a drone-specific RUL set appears; do not pretend more OpenSky/VisDrone rows improve turbofan RUL.
- Do not change the operator console contract (toolbar, HUD states, `/ws` snapshot shape) unless a dataset feature needs a new field; prefer filling existing `ground.telemetry` / `detections` / `airTraffic`.
- Leave leftover v1 UI files alone unless a cleanup PR is explicitly requested.

When starting v3: read this file, then `ml/train_yolov8n.py`, `ml/export_auair_frames.py`, `ml/build_air_traffic.py`, and `backend/ground.py` / `aircraft.py`. Stay in `ml/` unless backend must ingest a new JSON.
