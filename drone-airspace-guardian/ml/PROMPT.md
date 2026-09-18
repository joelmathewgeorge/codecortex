# PROMPT.md — Master build prompt: Drone Airspace Guardian MVP

Paste this whole file to your coding agent. This supersedes `EXTENSION_PROMPT.md`
in this folder — that file was about the health/RUL model, which is parked (see
below). This prompt is the current source of truth.

## 1. The only thing that matters right now

**MVP, in one sentence:** a live map with a handful of simulated drones flying
their missions, one no-fly zone, and a button that triggers an emergency
("helicopter entering airspace") that automatically detects which drones are
affected and reroutes them in real time, with a visible alert.

**The killer demo moment:** 10 drones flying calmly, then someone clicks
"Emergency: helicopter inbound." The system detects which drones are in the danger
radius, redraws their paths live on the map, and fires a red alert banner — all
within a couple of seconds, with no manual intervention.

Everything else in this document exists to serve that one sentence and that one
moment. Build the skeleton that makes them real *first*, with the fastest available
real data. Only after that skeleton is demoable do you spend time training the two
models that make it richer.

**Six functionalities. This is the actual checklist — nothing else counts as done
until these do:**

1. Live map renders with several simulated drones moving on it.
2. Someone can draw a restricted "no-fly" zone (airport, hospital, danger area).
3. The system detects when a drone is about to enter a restricted zone, or gets too
   close to another drone.
4. The system automatically calculates a new, safe route around the problem and
   reroutes the drone.
5. Each drone has a mission — a start point, an end point, and a path between them.
6. A human operator gets alerted when something dangerous happens.

## 2. Explicitly out of scope right now

- **Drone health / predictive maintenance / C-MAPSS / RUL is parked.** It is not
  part of this build. `ml/predict.py`, `ml/cmapss.py`, `ml/rul_model.joblib`,
  `ml/sanity_check.py` already exist and already work — **do not touch them, do not
  retrain, do not wire health into the reroute trigger.** Health becomes a feature
  to bolt on later, once the six functionalities above are solid. If you find
  yourself importing `predict_health` anywhere in this build, stop — that's scope
  creep back into the parked feature.
- No database — in-memory state in the backend process only.
- No auth, no deployment, no styling polish. Ugly and working beats pretty and
  broken. A skeleton that satisfies the six functionalities above, even with rough
  edges, is the deliverable.

## 3. Datasets → capabilities, and the order to build them in

Four datasets, each mapped to one part of the system. **Two require no training at
all and must be done first — they directly enable functionalities 1 and 5. Two
require training a model and are enhancements layered on afterward — never let
them block the skeleton.**

| Dataset | Gives you | Required for | Needs training? |
|---|---|---|---|
| AU-AIR | Real drone GPS/IMU/velocity flight logs | Functionality 5 (each drone's mission) | No — extraction only |
| OpenSky | Real aircraft ADS-B trajectories | Background/"other" traffic for functionality 3 | No — already built |
| Dubai segmentation | Pixel-labeled terrain (water/land/road/building/vegetation) | Better-than-straight-line reroutes (enhancement on functionality 4) | Yes — CNN, do after skeleton works |
| VisDrone | Bounding-box object detection (cars, people, buses, ...) | Ground-activity awareness (enhancement, not required for the 6) | Yes — CNN, do after skeleton works |

### 3.1 AU-AIR → each drone's own mission (build first, no training)

Path: `C:\Users\rohit\Downloads\Datasets\04_AUAIR_multimodal_uav\` —
`images/` (32,823 frames) + `annotations.json`.

Verified directly (don't re-derive):
- `image_name` format is `frame_{session}_x_{frame_index}.jpg`. Splitting on `_`
  gives the session id as the second token. There are **exactly 8 distinct
  sessions** (real separate flights), sizes 771 to 6,986 frames:
  `20190829091111, 20190905091750, 20190905103112, 20190905111947,
  20190905112522, 20190905142119, 20190905143505, 20190906150731`. Group by this,
  sort by `frame_index` within a group, and you have one continuous real flight
  per session — this is your per-drone mission source.
- Per-frame fields to pull: `longtitude` (note: misspelled in the source data, not
  a typo you introduce), `latitude`, `altitude`, `linear_x/y/z` (velocity),
  `angle_phi/theta/psi` (IMU orientation), and the `time` dict.
- GPS bounding box is tiny (lat 56.206–56.207, lon 10.188–10.191 — Aarhus,
  Denmark), confirming these are short local survey flights, not long-range
  legs — don't apply OpenSky's 5km-minimum-travel filter here, it will reject
  everything. Use a much smaller minimum (on the order of tens of meters) just to
  drop sessions where the drone was essentially hovering, and print the actual
  per-session path length so you're deciding from real numbers, not a guess.
- **Altitude unit is ambiguous** (raw values range ~2,806 to ~30,625 across the
  dataset) — could be mm or cm, the AU-AIR docs aren't bundled here. Don't guess
  the unit and hardcode a conversion. Instead do exactly what `build_trajectories.py`
  already does for OpenSky's `alt_m_drone_scaled`: min-max rescale each session's
  raw altitude into a plausible drone band (e.g. 20–120m), preserving the shape of
  climbs/descents. That sidesteps the unit ambiguity entirely.

Build `ml/au_air_missions.py` → writes `ml/au_air_missions.json`. Mirror the
existing `trajectories.json` schema as closely as sensible (same field names where
they mean the same thing: `lat`, `lon`, `alt_m_drone_scaled`, `t_offset_s`) so the
backend can treat both files uniformly. Downsample each session to roughly 20–40
evenly-spaced waypoints — thousands of near-duplicate consecutive frames make a
useless waypoint list; a handful of well-spaced points is what a mission path
actually needs.

### 3.2 OpenSky → background/other-aircraft traffic (already built, reuse)

`ml/trajectories.json` already exists — 8 real flight paths extracted from
`opensky_trajectories.csv` by `build_trajectories.py`, already committed. **Do not
rebuild this from scratch.** These are airliner-speed, airliner-altitude tracks;
use them as *other aircraft in the airspace* the drones must be aware of, not as
drone missions themselves (that's what AU-AIR is for — real drones move at drone
speed and altitude, not 220 m/s at 10,000m). This is exactly the distinction the
data already earned: AU-AIR = the drones you're flying, OpenSky = the traffic
around them.

### 3.3 Dubai segmentation → terrain-aware reroute cost (enhancement, train after skeleton works)

Path: `C:\Users\rohit\Downloads\Datasets\02_Dubai_aerial_segmentation\` —
`images/tile_000..071.png`, `masks/` (matching), `classes.json` (6 classes: Water,
Land, Road, Building, Vegetation, Unlabeled), `data/train-00000-of-00001.parquet`
(source).

Technique: 72 images is too few to train from scratch. Fine-tune a U-Net or
DeepLabV3+ with an ImageNet-pretrained encoder (`segmentation-models-pytorch` is
the right library) on tiled 256×256 crops with heavy augmentation (flip, rotate,
color jitter). Split by tile, not by crop, to avoid leakage.

Output: `ml/segmentation/dubai_segmenter.pt` + `ml/segmentation/infer.py` exposing
`mask_to_cost_grid(mask) -> 2D cost array` using a mapping like `Road=1, Land=3,
Vegetation=5, Water=8, Building=100` (put this mapping in a small JSON config, not
hardcoded, so it's tunable during the demo). This plugs into the reroute algorithm
in §5.4 as an *optional* bias, never a requirement — the baseline geometric reroute
must work with or without this model being trained yet.

### 3.4 VisDrone → ground-activity perception CNN (enhancement, train after skeleton works)

Path: `C:\Users\rohit\Downloads\Datasets\05_VisDrone_detection_tracking\` — three
splits (`train` 6,471 / `val` 548 / `test-dev` 1,610), `images/` + `annotations/`
(one txt per image, lines `x,y,width,height,score,category,truncation,occlusion`).
Per VisDrone's own spec, `category=0` is "ignored region" and `category=11` is
"others" — drop both. The 10 real classes: pedestrian, people, bicycle, car, van,
truck, tricycle, awning-tricycle, bus, motor.

Technique: this is a real CNN, fine-tuned via transfer learning — fine-tune
YOLOv8n (COCO-pretrained; its backbone is a convolutional network, that's the
honest "where's the CNN" answer for judges) on a subsample of ~1,500–2,000 train
images, reduced resolution, few epochs, CPU. Time a small pilot run (a couple
hundred images, 2 epochs) first and extrapolate before committing to the full run —
don't let this eat the time budget for §5.

Output: `ml/perception/visdrone_yolov8n.pt` + `ml/perception/detect.py` exposing
`ground_density(image) -> dict[class_name, count]`. This is a nice-to-have overlay
(richer risk signal, a second visible AI touchpoint) — it is not required for any
of the six functionalities in §1.

### Environment note

No NVIDIA GPU on this machine — everything above is CPU-only by design (small
models, pretrained backbones, small subsamples, few epochs). Confirmed `torch`
2.14 and `torchvision` 0.29 both publish Python 3.14 (`cp314`) wheels, so
installation should work on this machine's Python — verify with
`pip install torch torchvision segmentation-models-pytorch ultralytics` before
writing training code, don't assume. Put these in `ml/requirements-cv.txt`, kept
separate from the existing lightweight `ml/requirements.txt` (sklearn/pandas) so
the already-working health model's setup stays fast for anyone who doesn't need
computer vision.

## 4. System architecture

Four pieces, matching the team's own roadmap:

```
Simulation engine (backend) -- positions every tick --> WebSocket
WebSocket -- live updates --> Map UI (frontend)
Map UI -- draw zone / emergency --> REST API --> Simulation engine
Simulation engine -- checks --> Conflict detector -- affected drones --> Reroute calculator -- new path --> Simulation engine
```

State lives in memory in the backend process (a dict of drone objects, a list of
zones) — no database.

## 5. Functionality-by-functionality build spec

### 5.1 Live map with moving drones

Backend: a tick loop (every 1–2s) that advances each drone along its current
mission waypoint list (from `au_air_missions.json`) and pushes state over
WebSocket. Drone state shape (send exactly this — frontend and any later feature
key off these field names):

```json
{
  "id": "drone-01",
  "lat": 56.2065, "lon": 10.1890, "alt_m": 80,
  "heading_deg": 137, "speed_mps": 8.2,
  "mission_id": "au_air_02", "status": "in_flight"
}
```

Frontend: Next.js + Mapbox GL JS (Leaflet as fallback) rendering a marker per
drone, connected to the WebSocket, updating marker positions as messages arrive —
no polling/refresh.

### 5.2 Draw a no-fly zone

`POST /zones` — body `{"lat": ..., "lon": ..., "radius_m": ...}`, stored in the
in-memory zone list, returns the created zone with an id. Frontend: a draw tool
(click center, drag for radius, or a simple form) that calls this endpoint and
renders the zone as a circle overlay.

### 5.3 Conflict detection

Runs every tick, two checks:
- **Zone conflict:** for each drone, haversine distance from its current/next
  position to each zone's center; affected if `distance < radius_m`.
- **Drone-to-drone conflict:** pairwise distance between all active drones;
  flagged if horizontal separation `< 100m` **and** altitude difference `< 30m`
  (defaults — make both configurable constants, not magic numbers buried in logic).

`POST /emergency` drops a temporary zone (e.g. a large-radius danger circle at a
given point) and immediately runs this check against it — this is what the
"helicopter inbound" button calls.

### 5.4 Automatic reroute

Baseline (must work standalone, no trained model required): for an affected drone,
compute the perpendicular offset direction from the line between the drone and the
zone center, push the next waypoint outward past the zone's radius plus a margin,
then resume the original mission from there. This is genuinely enough for the demo
— don't gate the MVP on anything fancier.

Optional enhancement, once §3.3's segmentation cost grid exists: when choosing
which side to offset toward (left vs. right of the zone), check `mask_to_cost_grid`
under both candidate paths and prefer the cheaper one (e.g. avoid pushing a drone's
detour directly over a building). Implement this as a strategy the baseline can run
without — if the segmentation model isn't ready, fall back to a fixed/arbitrary
offset direction (e.g. always offset clockwise) and say so in a comment.

### 5.5 Missions

At backend startup, load `au_air_missions.json` and assign one flight's waypoint
list to each simulated drone as its mission (start = first waypoint, end = last).
Load `trajectories.json` (OpenSky) separately and simulate those as background
"other aircraft" that drones must avoid via §5.3's drone-to-drone check — they
don't get missions from the operator, they just move along their real recorded
paths on a loop.

### 5.6 Alerts

WebSocket message type distinct from routine position updates, e.g.
`{"type": "alert", "drone_id": ..., "reason": "zone_conflict" | "proximity" |
"emergency", "severity": "high", "message": "..."}`, sent the moment §5.3 flags a
conflict. Frontend renders a red banner / list entry when one arrives, cleared when
the affected drone's status returns to normal.

## 6. Repo layout

```
backend/
  main.py            # FastAPI app + WebSocket endpoint
  simulation.py       # tick loop, drone state
  zones.py             # POST /zones, POST /emergency, zone store
  conflict.py          # §5.3 checks
  reroute.py            # §5.4 baseline + optional cost-grid strategy
  requirements.txt
frontend/
  (Next.js app — map, zone draw tool, emergency button, alert banner)
ml/
  au_air_missions.py / au_air_missions.json     # §3.1
  trajectories.json                              # §3.2, already exists, reuse
  segmentation/  (dubai_segmenter.pt, infer.py, train.py)   # §3.3
  perception/    (visdrone_yolov8n.pt, detect.py, train.py) # §3.4
  requirements-cv.txt
  # health/RUL files (predict.py, cmapss.py, rul_model.joblib, sanity_check.py,
  # trajectories.json) already exist — leave them exactly as they are
```

Same ownership convention as before — stay inside your own top-level folder unless
a change is coordinated, commit small and often, push straight to `main`.

## 7. Build order (time-boxed — protect the skeleton over the models)

1. **Backend skeleton with dummy drones** — WebSocket pushing a few hardcoded
   drones moving in straight lines. Test standalone before touching frontend.
2. **Frontend map + WebSocket connection** — dots moving on a real map. This is
   functionality 1, even with fake data.
3. **Zone drawing + emergency button** — functionality 2, wired to `POST /zones`
   and `POST /emergency`.
4. **Conflict detection + reroute + alert** — functionalities 3, 4, 6. At this
   point the killer demo moment should already work end to end, on dummy drones.
   **Rehearse it. This is the MVP. Everything below is enhancement.**
5. **Swap in real missions** — replace straight-line dummy drones with
   `au_air_missions.json` waypoints (functionality 5, now genuinely real) and
   `trajectories.json` as background traffic. No model training required for this
   step, just wiring already-extracted data in.
6. **Only now, if time remains:** train the Dubai segmentation model (§3.3), wire
   `mask_to_cost_grid` into `reroute.py` as the optional strategy.
7. **Only if more time remains:** train the VisDrone detector (§3.4), surface
   `ground_density` somewhere visible (e.g. a per-zone overlay number).

If 6 or 7 aren't done in time, the system described by §1 is still fully intact
without them — that's the point of building in this order.

## 8. Definition of done

- [ ] All six functionalities in §1 work end to end, driven by real AU-AIR mission
      data and real OpenSky background traffic (not hardcoded straight lines).
- [ ] The killer demo moment — emergency click → affected drones detected →
      rerouted live → red alert — runs in a couple of seconds with zero manual
      intervention, and has been rehearsed at least twice.
- [ ] Nothing under `ml/` related to health/RUL was modified.
- [ ] `ml/au_air_missions.json` exists, built from real AU-AIR telemetry, 8 flight
      sessions or fewer if some don't pass the movement-sanity check, with the
      altitude-rescaling approach documented in a comment.
- [ ] (Enhancement, only if reached) segmentation model trained, `mask_to_cost_grid`
      wired into `reroute.py` behind a flag/fallback.
- [ ] (Enhancement, only if reached) VisDrone detector trained, `ground_density`
      surfaced somewhere in the demo.
