# v3airguard deliverables (agent handoff)

Last agent: Cursor Grok 4.6 (USER STOPPED YOLO train ~2026-09-19T01:10+05:30)
Last update: 2026-09-19T01:11:00+05:30
Branch: v3airguard
Time elapsed so far (running total, this session): 8
Resume here: USER STOPPED Task F. YOLO mix train killed (PID 14736 / worker 28180). Do NOT restart YOLO unless the user asks. Do NOT apply the ACCEPT retry. Task E remains USER DROPPED.

## Task board
| ID | Task | Status | Artifacts | Notes |
|----|------|--------|-----------|-------|
| A | AU-AIR frames + missions JSON | done | `ml/export_auair_frames.py`, `ml/auair_frames/` (gitignored, 240 jpg + index.json), `ml/export_auair_missions.py`, `ml/auair_missions.json` | 8 sessions × 30 strided frames. Sidecars: gps/velocity/time/imu(angular). Missions: relative ENU, alt 40–150 m, re-anchored at Dubai ports. Raw GPS is Denmark (lat ~56.2) and is camera telemetry only. |
| B | VisDrone stills + ground.py split | done | `ml/vision_frames/` 24 `visdrone-*.jpg` + `truth.json`; `backend/ground.py` | Live `/state`: GM-1..4 dataset=AU-AIR, GM-5..6 dataset=VisDrone. Both visible. |
| C | OpenSky replay + live-stale fix | done | `ml/build_air_traffic.py`, `ml/air_traffic.json` (18 flights: 10 arrival + 8 departure), `backend/aircraft.py` | MAX 12+8; only 10 arrivals qualified. HTTP 429 explicit; OAuth refresh 60 s before expiry. `live (stale)` startswith live and does **not** call `_run_replay` until STALE_S. |
| D | AU-AIR GPS missions in sim.py | done | `backend/sim.py` `AUAIR_SEED_SLOTS=(1,3,6)` | After POST /reset: D02 parcel, D04 survey, D07 security fly AU-AIR tracks; others A*. Hard-NFZ waypoints skipped; clipped legs A*-stitched. |
| E | Dubai segmentation on map + soft cost | dropped | `ml/build_ground_cost.py` unused; JSON/PNG may remain on disk | **USER DROPPED** — overlay and soft cost removed from live console because they interfered with map display. Not ingested by `risk_map.py` or Leaflet. Dataset on disk untouched. |
| F | YOLO mix train, beat mAP50 0.2863 | blocked (user-stopped) | `ml/train_yolov8n.py`; weights left as-is | **USER STOPPED** training at 2026-09-19T01:10+05:30. Killed PID 14736 + worker 28180 (+ child 32612). Last log: epoch **5/12** at 267/279 batches (~95%), incomplete. Last completed in-run val mAP50 **0.278** (epoch 4). Shipped `vision_metrics.json` still 0.2863. Not ACCEPT. Do not restart unless the user asks. |
| G | C-MAPSS sanity + smoke tests | done | `ml/sanity_check.py` (4/4 PASS); `backend/test_planner.py` 12/12 ok; `backend/test_server.py` ok | Did not retrain RUL. Spearman 0.907, MAE 8.4 health points. Battery untouched. |
| H | Final numbers in context.md | done | this file § Task H + `context.md` §9–10 | Overlay drop noted. F user-stopped; shipped YOLO numbers unchanged (0.2863). |

## Verification log
- A: `ml/auair_frames/index.json` 179645 B, 8 sets / 240 frames, sidecar keys gps+velocity+time+imu+angular, jpgs non-zero (~18.3 MB). `ml/auair_missions.json` 33611 B, 8 missions, waypoint lat 25.05–25.29 / lon 55.12–55.42 / alt 40–150. OK
- B: 24 `visdrone-*.jpg`, `truth.json` 47765 B with 24 keys, no empty files. Live GM-1..4 AU-AIR / GM-5..6 VisDrone. OK
- C: `air_traffic.json` 258492 B parses, 10 arrival + 8 departure. `aircraft.py` stale branch does not call `_run_replay`. OK
- D: POST /reset → D02/D04/D07 destinations AU-AIR session ids. `test_auair_missions_are_reanchored_in_dubai` OK
- E: **USER DROPPED.** Overlay + `np.maximum` cost removed from live path. Generator left unused. Dataset `Datasets/02_Dubai_aerial_segmentation` not deleted.
- F: **USER STOPPED** 2026-09-19T01:10+05:30. taskkill /T /F PID 14736 (also 28180, 32612). Confirmed no `train_yolov8n` process remains. Last log epoch **5/12** 267/279 (~95%). Last completed in-run val mAP50 **0.278** (epoch 4; e1=0.271 e2=0.245 e3=0.279). `vision_metrics.json` mtime still 2026-09-18 16:32 (0.2863). Weights untouched. NOT done / not ACCEPT.
- G: sanity_check 4/4 PASS this session. test_planner 12/12. test_server WS+REST OK (then reset). OK

## Background job status (Task F)
- PID: was 14736 (trainer child 28180; also child 32612) — **now not running** (user-killed)
- Status: **stopped/killed by user** at 2026-09-19T01:10+05:30. Do not restart.
- Log: ml\logs\yolo_train_stdout.log (225250 B, last line epoch 5/12 267/279)
- Started: 2026-09-19T00:30:57+05:30      Stopped: 2026-09-19T01:10+05:30 (~39 min elapsed)
- Command: `ml\venv\Scripts\python.exe -u train_yolov8n.py` (cwd `ml`)
- device: cpu, threads 14, epochs 12, batch 8, imgsz 512
- train: 1785 VisDrone crops + 446 AU-AIR (20%); val: 175 VisDrone-only
- epoch val mAP50 so far: 1=0.271, 2=0.245, 3=0.279, 4=0.278 (P/R 0.388/0.317, mAP50-95 0.15). Killed mid epoch 5/12 (~95% of 279 batches). Per-class not printed mid-run.
- stderr log empty (0 bytes)
- ACCEPT retry unused (0 of 1) — do **not** apply

## Numbers
- YOLO val mAP50 (VisDrone-only): **shipped 0.2863** (8 epochs, 2026-09-18 16:32) → mix train **user-stopped**, not exported. Last completed in-run val **0.278** (epoch 4; do not treat as shipped / not ACCEPT).
- Shipped per-class mAP50: person 0.3807, car 0.6265, van 0.1937, truck 0.1284, bus 0.1072, motor 0.2809
- AU-AIR holdout mAP50: not scored yet (41 holdout crops prepared; after export)
- Train wall: ~39 min then USER STOPPED mid epoch 5/12. No export.
- Replay flights: 18 (10 arrivals + 8 departures; only 10 arrivals qualified vs target 12)
- Seed drones on AU-AIR GPS: D02 parcel, D04 survey, D07 security (slots 1, 3, 6)
- Cameras: GM-1..4 AU-AIR / GM-5..6 VisDrone (24 stills + truth.json)
- Dubai overlay applied: **no** (USER DROPPED — interfered with map display)

## Task H — v3 numbers report (written 2026-09-19T01:00+05:30)

Honest snapshot. F is **blocked (user-stopped)**. `vision_metrics.json` was **not** rewritten. Weights left as-is.

| Item | Value |
|------|--------|
| Shipped VisDrone val mAP50 | **0.2863** (old 8-epoch fine-tune still loaded by `vision_bridge`) |
| In-run mix-train val mAP50 | epoch1 0.271 → e2 0.245 → e3 0.279 → **e4 0.278**; killed mid **5/12** (267/279). Not ACCEPT. |
| Train time | ~39 min then USER STOPPED 2026-09-19T01:10+05:30. No export of `weights/yolov8n_airspace.pt`. |
| Mix | TRAIN 20% AU-AIR (446/2231 crops); VAL VisDrone-only 175 crops. Start weights: existing `yolov8n_airspace.pt` |
| Replay | 18 DXB 30L flights (10 arrival + 8 departure) |
| AU-AIR seed drones | D02 parcel, D04 survey, D07 security |
| Cameras | GM-1..4 AU-AIR (8×30 + gps/imu); GM-5..6 VisDrone (24 stills) |
| Dubai overlay | **no** — USER DROPPED from live map and planner (interfered with display). Generator unused. |
| C-MAPSS | not retrained; sanity 4/4 PASS. OpenSky/VisDrone do not improve RUL |
| Skipped | 2 of 12 target OpenSky arrivals (only 10 tracks qualified). AU-AIR holdout mAP50 not computed. YOLO mix train USER STOPPED; ACCEPT unused. Dubai overlay removed by user request. |

ACCEPT rule still unused. Do **not** apply the retry unless the user asks to restart YOLO.

## How training / data reach the console
weights/yolov8n_airspace.pt → vision_bridge.py → ground.py (one camera / 2 s) → WS state.ground → GroundCamera / risk-map discs.
auair_missions.json → sim.py seed slots 1/3/6 as Motion/Route (A* only to skip hard NFZ).
air_traffic.json → aircraft.py replay after live failure or AIR_TRAFFIC=replay; live-stale dead-reckons only.
dubai_ground_cost.json is **not** loaded. Live map is Esri + OSM restricted / drones / zones only.

## Next command
```
# Do NOT restart YOLO unless the user asks. Do NOT apply the ACCEPT retry.
# Task F is user-stopped. Shipped weights remain mAP50 0.2863.
cd drone-airspace-guardian
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'train_yolov8n' }
# Must return nothing. Leave ml\weights\yolov8n_airspace.pt and vision_metrics.json as-is.
```
