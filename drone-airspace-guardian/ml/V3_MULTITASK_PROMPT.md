# v3airguard multitask injection prompt

Paste the block below as the **entire user message** in a new agent / multitask chat. Work stays on `v3airguard`.

---

You are implementing CodeCortex Airspace Guardian v3 ML work on branch v3airguard. You may be a continuation agent: previous agents may have already finished some tasks. Resume from the handoff file, do not redo completed work unless it is broken.

REPO: c:\Users\rohit\Downloads\CodeCortex
LIVE ARCHITECTURE: drone-airspace-guardian/context.md (read it first).
HANDOFF / DELIVERABLES (read second, write after every task): drone-airspace-guardian/ml/V3_DELIVERABLES.md
If V3_DELIVERABLES.md does not exist, create it immediately from the template at the bottom of this prompt, then continue.
IGNORE: ml/PROMPT.md, ml/EXTENSION_PROMPT.md, leftover v1 UI (AirspaceDashboard, DroneMap, fake-simulator.ts, VisionDock), nested untracked codecortex/ tree.
OWNERSHIP: stay in drone-airspace-guardian/ml/ unless backend/frontend must ingest or display a new artifact. Coordinate-minimal backend/frontend edits only. Do not change operator console contract (toolbar, HUD SAFE/CAUTION/CONFLICT/EMERGENCY, /ws snapshot required fields). Prefer filling ground.telemetry / detections / airTraffic. Additive overlay fields are allowed for the Dubai ground-cost layer.
GIT: work on v3airguard. Do not commit or push unless I ask. Do not force-push or skip hooks.
DATA (local, not git): VISDRONE_DIR default C:\Users\rohit\Downloads\Datasets\05_VisDrone_detection_tracking ; AUAIR_DIR C:\Users\rohit\Downloads\Datasets\04_AUAIR_multimodal_uav ; OPENSKY_CSV C:\Users\rohit\Downloads\Datasets\03_OpenSky_flight_telemetry\opensky_trajectories.csv ; DUBAI_TILES C:\Users\rohit\Downloads\Datasets\02_Dubai_aerial_segmentation (images/, masks/, classes.json — 72 tiles, 6 classes). AU-AIR frames stay gitignored. Commit derived JSON + weights/yolov8n_airspace.pt + vision_metrics.json + ground-cost artifacts when I later ask.

GOAL: do ALL of the following to a minimum viable, efficient, low-bug level. Comment the methodology in each script header (dataset, task type, why this model, what is NOT claimed). Auto-detect CUDA else CPU.

================================================================================
AGENT SWITCHING RULE (mandatory, after EVERY task A–H)
================================================================================
After you finish each lettered task, BEFORE starting the next one:

1. Update drone-airspace-guardian/context.md in the matching sections (datasets, known limitations, v3 open work). Put the new numbers in. Do not rewrite the whole file. Mark a completed open-work bullet as done with the artifact path and metric.
2. Update drone-airspace-guardian/ml/V3_DELIVERABLES.md so the next agent can start cold:
   - Status of each task: pending | in_progress | done | blocked
   - Exact files created/changed
   - Commands already run and their exit status
   - Numbers (mAP50, flight counts, camera mix, which seed drones use AU-AIR, whether tiles overlay is live)
   - What the next agent must run next (copy-pasteable)
   - Blockers / skipped items (none allowed for Dubai tiles — see task 6)
3. If you stop, crash, or hit a long train, leave V3_DELIVERABLES.md with in_progress, the PID/command, and how to resume. The next agent reads context.md + V3_DELIVERABLES.md and continues. Never assume the next agent saw this chat.

================================================================================
TASKS
================================================================================

1) YOLO longer + more VisDrone + mix AU-AIR boxes
   - Edit ml/train_yolov8n.py. Keep six HUD classes: person, car, van, truck, bus, motor.
   - Keep native 512 crops (do not train on downscaled full VisDrone frames).
   - Raise YOLO_SRC_TRAIN/VAL defaults (~1000/180) and epochs (12 CPU / 20 GPU) with patience=4, cos_lr, close_mosaic last 2.
   - Mix AU-AIR into TRAIN ONLY (~15-25% crops). Class map: Human→person, Car→car, Van→van, Truck→truck, Bus→bus, Motorbike→motor. Drop Bicycle; Trailer optional→truck. Val MUST remain VisDrone-only so mAP50 is comparable to 0.2863.
   - Also compute and record a separate AU-AIR holdout mAP50 in vision_metrics.json.
   - device="0" if torch.cuda.is_available() else "cpu". CPU: torch.set_num_threads(max(1, cpu_count-2)).
   - Export weights/yolov8n_airspace.pt. Re-val the exported file (not in-memory last epoch).
   - ACCEPT: val mAP50 > 0.2863. If a first run fails, one retry with more VisDrone source or 4 extra epochs — then stop and report. Do not start from scratch (always yolov8n.pt / existing fine-tune).

2) More VisDrone val/test-dev stills in live cameras
   - export_frames: at least 24 dense visdrone-*.jpg from val and/or test-dev (unseen if possible) + truth.json.
   - ground.py: cameras GM-1..GM-4 replay AU-AIR windows; GM-5..GM-6 replay VisDrone stills. Do not hide VisDrone just because AU-AIR exists.

3) Richer AU-AIR export
   - export_auair_frames.py: more than six 30-frame windows; use every real session present in annotations.json (up to 8); keep stride so the scene moves; sidecars per frame: gps (lat, lon, alt_m), velocity, time, plus imu/angular if the JSON has it (angle_phi / angle_theta / angle_psi).
   - Licence: write local auair_frames/ only (gitignored).

4) AU-AIR GPS as drone missions
   - New ml/export_auair_missions.py → ml/auair_missions.json (waypoints only, no images; OK to commit).
   - Convert each session GPS to relative ENU from the first fix, downsample (e.g. every N metres or every K frames), rescale altitude into 40–150 m, re-anchor the path at a Dubai port from dubai_airspace.json. Raw AU-AIR lat/lon is NOT Dubai — never plot Denmark coordinates on the map.
   - sim.py: 2–3 of the 8 SEED_FLEET drones fly these tracks as Motion/Route. If a waypoint cell is hard NFZ, skip/replace that segment with existing A* between remaining safe waypoints. Other drones stay A* port-to-destination. Do not use leftover backend/missions.py or ml/trajectories.json as the live path source.

5) More OpenSky replay + reliable live
   - build_air_traffic.py: raise MAX_ARRIVALS/MAX_DEPARTURES (target 12+8 or all qualifying tracks); regenerate air_traffic.json.
   - aircraft.py: OpenSky already has exponential backoff — keep it; treat HTTP 429 explicitly; refresh OAuth before expiry (already). CRITICAL: if status is live-stale, do NOT call _run_replay (today stale still launches replay airliners). After STALE_S with no healthy poll, then replay. TopBar chip can stay; status strings must remain startswith "live" for live/stale.

6) Dubai aerial segmentation MUST appear on the map (not optional, do not skip)
   Masks exist at Datasets/02_Dubai_aerial_segmentation/masks/ (72 tiles, classes.json: Water, Land/unpaved, Road, Building, Vegetation, Unlabeled). They are NOT surveyed-georeferenced. Incorporate them ANYWAY as a fitted overlay on the live Leaflet map and as a soft cost under the 150 m planner grid.

   Required method (do not invent a new segmenter, do not train a model):
   - New ml/build_ground_cost.py:
     a) Stitch/pack the 72 RGB tiles + matching masks into one mosaic.
     b) Fit that mosaic into dubai_airspace.json geographic bounds (south/west/north/east) with an affine map from mosaic pixel → lat/lon → local ENU. Document in the JSON that this is a **fitted mosaic**, not certified georeference.
     c) Write:
        - ml/dubai_ground_cost.json (bounds, cell size, class→cost table, applied: true)
        - a PNG the frontend can show, e.g. frontend/public/dubai/ground-cost.png or served from GET /media/... (keep it reasonably small).
     d) Class → extra per-metre cost (soft only): Water 0 (do not fight OSM water), Vegetation ~0.1, Land ~0.4, Road ~MEDIUM 5, Building ~HIGH 8–15, Unlabeled 0. NEVER write inf, NEVER modify hard_static, NEVER replace OSM restricted cores / airport funnels.
   - backend/risk_map.py: load the JSON, add the sampled cost into ground_static via np.maximum with existing OSM water/road/crowd layers. Copy hard_static before and assert identical after.
   - frontend AirspaceMap: show the fitted PNG as a Leaflet imageOverlay using the same lat/lon bounds, low opacity (~0.35), under drones/zones, toggleable from the existing map legend if a control already exists; otherwise always-on at low opacity. Do not change toolbar or HUD states.
   - backend/test_planner.py (or a tiny new assert in it): hard_static unchanged when the layer is applied.
   - If a tile/mask file is missing, skip that tile, still ship the mosaic from whatever is present. Only set applied:false if ZERO masks exist. RGB-only public/dubai/tile-*.png is NOT a substitute for the 72-tile dataset.

7) C-MAPSS
   - Do not retrain. Do not claim OpenSky/VisDrone improve RUL. Run ml/sanity_check.py. Health path stays health_bridge → predict.py → HUD fleet health / average RUL. Battery remains the energy model.

QUALITY
- Efficient: no unused folders (ml/perception, serve.py, segmentation trainer).
- Understandable: each changed file gets a short header comment: data → model/algorithm → who reads the artifact → what the operator sees.
- Low bugs: handle missing datasets with clear SystemExit; empty AU-AIR must not crash cameras; YOLO load failure still uses dataset labels (existing).
- Verify: python backend/test_planner.py ; if FastAPI can start, python backend/test_server.py with AIR_TRAFFIC=replay. If no GPU, still run a real YOLO train with the MVP epoch budget — do not fake metrics.
- Do not rewrite context.md wholesale; patch numbers after each task.

ORDER OF WORK
A. Create/refresh V3_DELIVERABLES.md if missing. Export AU-AIR frames + missions JSON (IO, fast). Then update context.md + V3_DELIVERABLES.md.
B. Expand VisDrone stills + ground.py camera split. Then update both docs.
C. OpenSky JSON + aircraft stale/replay fix. Then update both docs.
D. sim.py AU-AIR missions ingest. Then update both docs.
E. Dubai segmentation mosaic + risk_map cost + Leaflet overlay (required). Then update both docs.
F. YOLO prepare+train+export (slow; start this as soon as mix code is ready; do not block A–E on training finishing if you can parallelize internally). When training starts, mark F in_progress in V3_DELIVERABLES.md with the exact command. When it ends, write mAP50 and update both docs.
G. sanity_check.py + smoke tests. Then update both docs.
H. Final report in V3_DELIVERABLES.md: mAP50 old vs new, per-class, train minutes, flight counts, which seed drones use AU-AIR, camera mix, Dubai overlay bounds/opacity, any skipped dataset.

Do all of this. Make it efficient and understandable.

================================================================================
V3_DELIVERABLES.md template (create if missing)
================================================================================

# v3airguard deliverables (agent handoff)

Last agent: <name/model>
Last update: <ISO time>
Branch: v3airguard
Resume here: <one paragraph + next command>

## Task board
| ID | Task | Status | Artifacts | Notes |
| A | AU-AIR frames + missions JSON | pending | | |
| B | VisDrone stills + ground.py split | pending | | |
| C | OpenSky replay + live-stale fix | pending | | |
| D | AU-AIR GPS missions in sim.py | pending | | |
| E | Dubai segmentation on map + soft cost | pending | | MUST land on map |
| F | YOLO mix train, beat mAP50 0.2863 | pending | | |
| G | C-MAPSS sanity + smoke tests | pending | | do not retrain |
| H | Final numbers in context.md | pending | | |

## Numbers
- YOLO val mAP50 (VisDrone-only): old 0.2863 → new ?
- AU-AIR holdout mAP50: ?
- Replay flights: ?
- Seed drones on AU-AIR GPS: ?
- Cameras: GM-1..4 AU-AIR / GM-5..6 VisDrone ?
- Dubai overlay applied: yes/no, bounds, opacity

## How training / data reach the console
(short: weights → vision_bridge → ground.py → WS → GroundCamera / risk map; missions JSON → sim; air_traffic.json → aircraft; mosaic → risk_map + Leaflet)

## Next command
```
<exact powershell>
```
