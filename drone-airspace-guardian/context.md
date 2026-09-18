# Drone Airspace Guardian — working context

Snapshot of the repo as of 18 Sep 2026. This file is a handoff, not a spec. Prefer the code when they disagree.

---

## 1. Pitch

A live **Beyond Visual Line of Sight (BVLOS)** airspace console for a Downtown Dubai delivery corridor.

Five simulated drones fly named missions over Burj Khalifa / Downtown (25.1972 N, 55.2744 E). An operator draws no-fly rings, declares an inbound helicopter, and watches the fleet detect the conflict, detour, and raise a banner — without touching a joystick.

Health scores come from a trained remaining-useful-life (RUL) model, not random jitter. A camera dock cycles aerial frames through a VisDrone-fine-tuned YOLOv8n (`yolov8n-airspace`) so the same HUD can show ground activity under the corridor.

This is a same-laptop hackathon demo (CodeCortex). There is no auth, no database, no real radio link. The project README is a Dubai runbook. A few FastAPI docstring examples and `backend/test_server.py` still post Bangalore coordinates (12.97, 77.59).

---

## 2. Architecture

Four cooperating pieces, all in-process or on localhost:

```
Next.js dashboard (Leaflet map + HUD)
        |  REST: POST /zones, /emergency, /reset
        |  WS:   /ws  (positions + zones + vision + alerts)
        v
FastAPI simulation (in-memory drones + zones)
        |-- health_bridge  ->  ml/predict.py  (C-MAPSS HistGradientBoosting)
        |-- vision_bridge  ->  YOLOv8n on ml/vision_frames/
        |-- missions.py    ->  ml/trajectories.json  (dense_waypoints, Dubai-fitted)
        +-- drones.py      ->  tick, proximity, geometric reroute
```

**Frontend.** Next.js 16 / React 19 App Router. Leaflet (not Mapbox) with Esri World Imagery, a faint CARTO dark label layer, and four local Dubai aerial plates. The map is encased in dashboard chrome — not full-bleed — via `globals.css` (`dag-body`, `dag-stage`, `dag-map-frame`) around the three-pane shell (fleet | map | camera). Default data mode is **live** WebSocket; `NEXT_PUBLIC_DATA_MODE=mock` falls back to `lib/fake-simulator.ts`. Marker motion is interpolated on the map (~1 s) so a 1 Hz backend tick does not teleport. The old `posDbg` debug ingest is gone from `useDroneFeed`. Dev URL is **http://localhost:3000**.

**Backend.** FastAPI + uvicorn on **http://127.0.0.1:8000** with `--reload` (see `main.py`'s run comment). A 1-second asyncio loop advances each drone along its waypoint list, scores health, checks zones and pairwise proximity, then broadcasts JSON to every `/ws` client. State is a process-global list. CORS is `allow_origins=["*"]` on purpose for a two-port laptop demo. Agent `#region` debug file logging is stripped from `main.py`, `zones.py`, and `vision_bridge.py`. `GET /` reports `city: "dubai"` and the live drone count (five on a default fleet).

**Simulation.** Five drones. `missions.py` loads `dense_waypoints` (~360 points per track) from `ml/trajectories.json` and fits them into a Downtown Dubai box (`SPAN_DEG = 0.024`, ~2.6 km, plus per-drone offsets). Raw `waypoints` (~20 ADS-B fixes) are provenance; they are used only if a track has fewer than 40 dense points. If the JSON is missing, four-corner Dubai fallback legs in `drones.py` are used. Missions loop (open tracks ping-pong). `drones.py` emits `behavior` (cruise / orbit / hold / climb / descend) and `trackSource` (`opensky` when a fitted track loaded, else `sim`). Reroute is a perpendicular offset past the zone radius plus 100 m — no terrain cost grid.

**Health (C-MAPSS RUL).** `backend/health_bridge.py` imports `ml/predict.py` directly. Each drone walks a synthetic degrading sensor trace through `HealthMonitor`. Wear seeds them at different life points so the fleet is not five clones at 100%. One model cycle is applied every six sim ticks so health does not collapse in a 10-minute demo.

**Vision (YOLOv8n).** `backend/vision_bridge.py` loads `ml/weights/yolov8n_airspace.pt` when `vision_metrics.json` is present (else `runs/.../best.pt` if that file exists), falling back to stock `ml/yolov8n.pt`. Live model id is **`yolov8n-airspace`** once the trained weights load. Every third tick it scores the next file in `ml/vision_frames/` and attaches a `vision` blob with `frame`, `truth`, `metrics` (plus detections, counts, image, model, ready, width/height). Frames are served as static files at `/media`.

Prompts under `ml/PROMPT.md` and `ml/EXTENSION_PROMPT.md` describe a later layout (AU-AIR missions, Mapbox, `serve.py` on port 8500, a segmentation cost grid). Several of those files do not exist. The running system is FastAPI importing Python ML, Leaflet, and OpenSky-shaped drone paths — not the prompt's target architecture.

---

## 3. CODEOWNERS

Repo-root `.github/CODEOWNERS`:

| Path | Owner | GitHub |
| --- | --- | --- |
| `drone-airspace-guardian/backend/` | Pranav | [@pranav3086](https://github.com/pranav3086) |
| `drone-airspace-guardian/frontend/` | Joel | [@joelmathewgeorge](https://github.com/joelmathewgeorge) |
| `drone-airspace-guardian/ml/` | Rohit | [@vrrroro](https://github.com/vrrroro) |

The project README repeats the same split. Stay in your folder unless a change is coordinated. This `context.md` is the exception: it describes the whole stack so the next person does not have to reconstruct it from chat.

---

## 4. Feature inventory

What is actually wired, versus what the prompts asked for.

| Feature | Status |
| --- | --- |
| Live Leaflet map, Dubai center, five drones | Working (live WS or mock) |
| Mission names + looped dense waypoint paths | Working; `dense_waypoints` (~360) fitted to Downtown |
| Draw no-fly (click after arming Draw) | Working; `POST /zones`, default 450 m |
| Operator zone cap (max 4) | Working |
| Emergency helicopter inbound | Working; 900 m ring on Downtown, `POST /emergency` |
| Emergency zones replace the previous emergency (no stacked red fills) | Working (backend + frontend collapse) |
| Geometric reroute + conflict banner | Working |
| Pairwise proximity (&lt;100 m horiz, &lt;30 m alt) | Working; flags `affected`, does not reroute |
| Demo reset (`POST /reset`) | Working; clears zones, rebuilds fleet, resets health monitors |
| C-MAPSS health bars | Working when `rul_model.joblib` loads |
| Vision dock (camera panel, boxes, class tally, mAP chip) | Working if YOLO imports; payload includes `frame` / `truth` / `metrics` |
| Dark HUD chrome (fonts, gold/cyan/red palette) | Working; map sits inside `dag-stage` / `dag-map-frame` |
| Marker interpolation (~1 s ease) | Working inside `DroneMap` |
| Mock simulator | Working via env flag; also emits `behavior` + `trackSource` |
| AU-AIR as the drone missions | **Not built** (`au_air_missions.py` / `.json` are not in the tree) |
| OpenSky as *background traffic* (separate from drone missions) | **Not built**; OpenSky *is* the drone paths |
| Dubai segmentation cost-grid reroute | **Not built** |
| `ml/serve.py` health HTTP service on 8500 | **Not built**; backend imports `predict` |
| Auth / persistence / deploy | Out of scope |

Demo beat: open the map, click **Helicopter inbound**, watch affected drones detour and the banner fire within about a second.

---

## 5. Datasets

Raw dumps live under `C:\Users\rohit\Downloads\Datasets\` and are not committed. Only derived artifacts sit in this repo.

**NASA C-MAPSS (FD001–FD004).** Real turbofan run-to-failure. 160,359 cycles from 709 engines for training; 707 held-out test engines. Shipped model is HistGradientBoosting: RMSE 14.78 cycles, MAE 10.50, R² 0.877, PHM08 3095, ~2.1 MB (`ml/rul_model.joblib`). Engines are split, never rows. RUL target is capped at 125 cycles. Health is that RUL mapped to 0–100 (`healthy` ≥75, `monitor` ≥50, `service_soon` ≥25, `ground_now` &lt;25 on the ML side). The dashboard collapses those four bands to three colors (healthy / watch / critical).

**OpenSky ADS-B.** Capture over the Indian subcontinent. `ml/build_trajectories.py` ranks tracks by *curvature* (total heading change), cubic-splines them against wall-clock time, and emits 360 dense `[lat, lon]` points per track. `ml/trajectories.json` generated 18 Sep 2026 16:07: 8 tracks, 117 candidates considered, `dense_waypoints` plus the original ~20 raw fixes, speed/altitude profiles scaled into 60–220 m. First five tracks are what the backend flies: `load_mission_tracks()` prefers `dense_waypoints` when a track has at least 40 of them.

**AU-AIR.** Multimodal UAV logs (Aarhus GPS/IMU + frames). Prompted as the real drone missions. `au_air_missions.py` / `au_air_missions.json` are not in the tree. GPS bbox is tiny; do not apply OpenSky's kilometre travel filter.

**VisDrone 2019 DET.** Street-level aerial traffic, not Dubai and not drone-vs-drone. Used to train ground-activity detection (person / car / van / truck / bus / motor). First attempt scored **mAP50 = 0** because whole frames were fed at 320 px and cars shrank below the nano head. `train_yolov8n.py` cut native 512×512 crops (924 train / 107 val, 8 epochs, CPU, imgsz 512). Training **finished 8/8**. Shipped metrics in `ml/weights/vision_metrics.json`: **mAP50 0.2863**, mAP50-95 0.1531, precision 0.351, recall 0.3404, model id `yolov8n-airspace`, trained_at 2026-09-18 16:32:45. Weights copied to `ml/weights/yolov8n_airspace.pt`. Per-class mAP50: person 0.3807, car 0.6265, van 0.1937, truck 0.1284, bus 0.1072, motor 0.2809. That is modest, not 0.00.

**Dubai aerial tiles.** Four plates in `frontend/public/dubai/tile-a.png` … `tile-d.png`, georeferenced around Downtown and overlaid at 0.22 opacity. Extra tiles from the segmentation dataset are in the camera rotation as `dubai-010.jpg` … `dubai-012.jpg`. The U-Net/DeepLab terrain model was never trained.

**Vision frames on disk now.** Nine VisDrone crops (`visdrone-….jpg`) plus three Dubai jpgs, and `ml/vision_frames/truth.json` (labels for the VisDrone stills; Dubai tiles have no ground truth). The directory is gitignored at the repo root.

---

## 6. Chronology

Order of what actually happened, compressed:

1. **Bengaluru MVP.** Five drones, Leaflet, FastAPI WS, OpenSky-shaped paths, C-MAPSS health. `test_server.py` and a few `main.py` request examples still use 12.97, 77.59.
2. **Relocate to Dubai.** Map center, mission names (Marina clinic, Palm grocery, Sheikh Zayed survey, DIFC parts, organ to Emirates Hospital), fallback paths, WS `city: "dubai"`, aerial plates. `BENGALURU` in `config.ts` is an alias of `DUBAI`. Project `README.md` is now the Dubai runbook.
3. **Zone stacking fix.** Repeated Helicopter inbound drew opaque stacked circles. Emergencies now replace previous emergencies; operator zones cap at four; the client also collapses identical rings. `POST /reset` plus a Reset demo button clears zones, restores the five missions, resets health monitors, broadcasts `reset: true`.
4. **Interpolation.** Backend still ticks at 1 Hz. `DroneMap` eases marker lat/lon over `INTERPOLATION_MS` (1000). `useInterpolatedPosition.ts` exists but is unused.
5. **Vision dock.** `VisionDock` + `vision_bridge` + `/media`. Cycles frames, draws boxes, lists counts, shows truth overlays and mAP/epoch chips from the WS payload.
6. **Dark HUD.** Three-pane shell (fleet | map | camera) with Outfit / IBM Plex Mono and a gold-on-navy palette. `globals.css` defines `dag-body`, `dag-stage`, `dag-map-frame` so the Leaflet map sits inside dashboard chrome rather than a full-viewport overlay.
7. **Dense missions.** `missions.py` flies `dense_waypoints` (~360), fitted to Downtown. `drones.py` adds `behavior` and `trackSource`.
8. **YOLO crop run finished.** 8/8 epochs, val mAP50 0.2863 (not 0.00). Metrics JSON + `truth.json` + demo frames exported; `vision_bridge` loads the fine-tune with a `yolov8n.pt` fallback.
9. **Cleanup.** Agent debug ingest (`posDbg`) removed from the feed hook; file logging stripped from `main.py`, `zones.py`, `vision_bridge.py`. Repo-root `.gitignore` covers env, node, Python, `debug-*.log`, vision frames, and YOLO runs.

---

## 7. How to run (ports from the code)

There is no extra proxy. Two processes, two ports, from the files that actually set them.

**API / WebSocket — FastAPI on `http://127.0.0.1:8000`**

From `drone-airspace-guardian/README.md` and `main.py` (`uvicorn main:app --reload`):

```bash
cd drone-airspace-guardian/backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Do not point this at 8500; that port exists only in an unbuilt `serve.py` prompt.

Frontend contract (defaults if env is unset):

- `NEXT_PUBLIC_API_BASE_URL` = `http://127.0.0.1:8000`
- `NEXT_PUBLIC_WS_URL` = `ws://127.0.0.1:8000/ws`
- `NEXT_PUBLIC_DATA_MODE` = `live` (set `mock` to skip the backend)

HTTP surface:

| Method | Path | Role |
| --- | --- | --- |
| WS | `/ws` | Position stream (~1 Hz) plus `alert` messages |
| GET | `/` | Process health: `city: "dubai"`, drone count (5), zone count |
| GET | `/state` | Full snapshot |
| GET | `/zones` | Zone list |
| POST | `/zones` | `{lat, lon, radius}` operator ring (max 4 kept) |
| POST | `/emergency` | Same body, emergency=true, replaces prior emergency, immediate reroute + alert |
| POST | `/reset` | Clear zones, rebuild Dubai fleet |
| GET | `/media/...` | Vision frames from `ml/vision_frames/` |

**Dashboard — Next.js on `http://localhost:3000`**

```bash
cd drone-airspace-guardian/frontend
npm install
npm run dev
```

`package.json` script is `next dev` with no port flag, so **3000**. Open that URL. Click **Helicopter inbound**.

**ML (optional, not required to open the map)**

```bash
cd drone-airspace-guardian/ml
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python sanity_check.py          # C-MAPSS checks
python train_yolov8n.py         # VisDrone fine-tune; already completed 8/8 on this machine
```

C-MAPSS retrain needs `CMAPSS_DIR`. Trajectory rebuild needs `OPENSKY_CSV`. YOLO needs `VISDRONE_DIR` (default `C:\Users\rohit\Downloads\Datasets\05_VisDrone_detection_tracking`).

Smoke without the UI: `python backend/test_server.py` (still posts Bangalore coordinates; the WS printout is still useful).

---

## 8. File map

```
.gitignore                      # repo root: env, node, Python, debug-*.log, ml frames/runs
.github/CODEOWNERS
drone-airspace-guardian/
  README.md                 # Dubai runbook + team table + ports
  context.md                # this file
  backend/
    main.py                 # FastAPI app, WS loop, /zones /emergency /reset /state /media
    drones.py               # tick, lerp, reroute, proximity, fleet factory, behavior + trackSource
    missions.py             # Dubai box + load trajectories.json dense_waypoints
    zones.py                # in-memory rings, replace/cap, haversine conflict
    health_bridge.py        # HealthMonitor + synthetic traces
    vision_bridge.py        # YOLO snapshot every 3 ticks; trained weights + yolov8n.pt fallback
    geo_utils.py            # haversine, bearing, offset
    test_server.py          # WS + REST smoke; Bangalore coords leftover
    requirements.txt
  frontend/
    app/layout.tsx          # fonts, title "Dubai airspace"
    app/page.tsx            # AirspaceDashboard
    app/globals.css         # dag-body / dag-stage / dag-map-frame chrome
    components/AirspaceDashboard.tsx
    components/DroneMap.tsx
    components/DronePanel.tsx
    components/VisionDock.tsx
    components/MapControls.tsx
    components/ConflictBanner.tsx
    components/ErrorNotice.tsx
    hooks/useDroneFeed.ts   # no posDbg ingest
    hooks/useInterpolatedPosition.ts   # unused
    lib/config.ts           # Dubai, ports, tiles, timings
    lib/api.ts
    lib/drone-adapter.ts    # drones, zones, vision.frame / truth / metrics
    lib/fake-simulator.ts
    lib/health.ts
    types/airspace.ts
    public/dubai/tile-*.png
    .env.example / .env.local
  ml/
    predict.py / cmapss.py / train_model.py / sanity_check.py
    rul_model.joblib / model_metadata.json
    build_trajectories.py / trajectories.json
    train_yolov8n.py / train_yolo.log
    yolov8n.pt              # COCO pretrained fallback
    weights/yolov8n_airspace.pt
    weights/vision_metrics.json   # mAP50 0.2863, model yolov8n-airspace
    vision_frames/          # 9 VisDrone + 3 Dubai + truth.json (gitignored)
    runs/yolov8n_airspace/  # training dumps (gitignored)
    PROMPT.md / EXTENSION_PROMPT.md / README.md
```

Not in the tree (prompted, never landed): `ml/serve.py`, `ml/au_air_missions.py`, `ml/segmentation/`, `ml/perception/`, `ml/requirements-cv.txt`, `backend/simulation.py`, `conflict.py`, `reroute.py` as separate modules.

---

## 9. Known limitations

- **Not a real UTM.** Simulated BVLOS. No command-and-control, no ADS-B in, no SORA case.
- **Health is turbofan physics on drone-shaped traces.** Retrain when real airframe sensors exist. `predict_health` on a single row is optimistic; the bridge uses `HealthMonitor`.
- **OpenSky is airliners.** Geometry is real; altitude and speed are rescaled. Capture is a short subcontinent window. Paths are fitted into Downtown, not flown there.
- **Reroute is a single perpendicular poke.** No occupancy grid, no Dubai segmentation, no 3D separation manoeuvre. Proximity only sets `affected`.
- **Vision domain gap.** VisDrone is not Dubai. Dubai tiles in the rotation have no boxes. Fine-tune mAP50 is 0.2863 — better than the failed 0.00 run, still modest. Cars dominate; bus/truck stay weak.
- **Docs drift.** `ml/README.md` still describes the old 8×~20-waypoint straightness-1.0 extract. `main.py` examples and `test_server.py` still use 12.97, 77.59. `BENGALURU` remains an alias in `config.ts`.
- **In-memory only.** Restart wipes zones and fleet progress.
- **CORS `*`.** Fine on a laptop; not a product posture.
- **`useInterpolatedPosition` is dead code.** Interpolation lives in `DroneMap`.
- **Frontend health bands ≠ ML status labels.** UI: &gt;70 / ≥30 / else. Model: 75 / 50 / 25.
- **Ultralytics lives in `ml/requirements.txt`.** The prompt wanted a separate `requirements-cv.txt` so the health install stayed small. That split never happened.
- **CPU-only training.** No NVIDIA GPU on this machine. YOLO was slow; the backend loads whatever weights are on disk at startup (or after `--reload`).

---

## 10. Open work

Nothing from the previous in-flight list is still running. Remaining honest leftovers:

1. **Simulated fleet.** Five software drones. No radio, no physical UAV, no real BVLOS operation.
2. **YOLO mAP is still modest.** 0.2863 mAP50 after 8 epochs on VisDrone crops. Not production detection; the first run really was 0.00, this one is not.
3. **AU-AIR was never extracted.** No `au_air_missions.py` / `au_air_missions.json`. Missions are OpenSky shapes, not Aarhus UAV logs.
4. **Prompt backlog, not started:** OpenSky as *other traffic*, Dubai segmentation cost grid, `serve.py` + `prime_monitor` HTTP fallback (unneeded while the backend is Python).
5. **Leftover Bangalore in smoke tests / docstrings.** `test_server.py` and `main.py` request examples still post 12.97, 77.59. `ml/README.md` trajectory section is stale versus `trajectories.json`.
6. **Dead hook.** Drop unused `useInterpolatedPosition` or actually use it.
7. **Not committed.** This working tree is a local demo snapshot. Do not commit this file (or the rest) unless someone asks.

Do not treat `PROMPT.md` as the live architecture; it is the backlog that produced this tree.
