# Prompt: extend the already-working ml/ layer

Paste this whole file to your coding agent, scoped to this `ml/` folder.

## Context — read this before touching anything

`ml/` already contains a complete, validated deliverable, committed today:
- `rul_model.joblib` — HistGradientBoosting, trained on 709 real C-MAPSS engines
  (FD001–FD004), RMSE 14.78 cycles on 707 held-out engines (engine-level split, not
  row-level — see `train_model.py` / `README.md` for why that matters).
- `cmapss.py` — feature engineering shared by training and inference. `RAW_COLS`,
  `LONG_WINDOW = 20`, `rul_to_health()`, `health_status()` (thresholds: `healthy`
  ≥75, `monitor` ≥50, `service_soon` ≥25, `ground_now` <25).
- `predict.py` — public surface: `predict_health(sensor_row) -> float`,
  `HealthMonitor` (stateful, per-drone, the recommended path),
  `simulate_drone_telemetry(num_ticks, failure_at, noise_scale, seed) -> list[dict]`
  (stand-in telemetry, one dict per tick, healthy → worn-out on an accelerating
  curve, calibrated from real FD001 sensor ranges).
- `trajectories.json` — 8 real OpenSky flight paths (`traj_01`..`traj_08`), each
  ~350s / 20 waypoints / ~85km, straightness 1.0, built by `build_trajectories.py`
  from 157 qualifying candidates (`TARGET_COUNT = 8` in that file).
- `sanity_check.py` — 4 checks, all passing. Do not weaken or remove any of them.

**Do not retrain the model, do not change `cmapss.py`'s feature engineering, and do
not touch `backend/` or `frontend/`** — those are Pranav's and Joel's folders per
the team's ownership rule; only work inside `ml/`.

The gap is not modeling quality — it's that `backend/` is still empty (`.gitkeep`
only) and Pranav hasn't picked Python or Node yet. The roadmap explicitly names the
fallback for that: *"import it directly if both are Python; otherwise a tiny
internal FastAPI endpoint Pranav's server calls."* Build that fallback now, before
the ~3:30 PM merge checkpoint, so integration isn't blocked on his language choice.
Also close the one real usability gap in the demo telemetry generator: every
simulated drone currently starts at tick 1 / 100% health, so a live fleet would look
uniformly healthy for the first several minutes with nothing to demo.

Four tasks, in priority order. Do them in order; stop after Task 1 and check in if
you're short on time — it's the one that unblocks Pranav regardless of what he
picks. **Task 4 is a stretch goal, gated separately below — do not start it until
Tasks 1–3 are committed and, per the roadmap's own review timeline, not before
Review 1 has actually happened.** The roadmap explicitly says not to train a
detector for review 1/2 and to treat it as final-round-only if there's spare time;
Task 4 exists because you asked for a CNN specifically, but it must never come at
the cost of the three tasks that unblock Pranav.

---

## Task 1 (do first): `serve.py` — HTTP fallback for any backend language

New file `ml/serve.py`. It's a thin FastAPI wrapper around the *existing*
`predict.py` functions — it must not reimplement any prediction logic, only call
into `predict_health`, `HealthMonitor`, `simulate_drone_telemetry`. If backend ends
up Python, this file simply won't be used (Pranav imports `predict.py` directly);
if backend is Node, this is the only integration point he needs.

Endpoints, exact contract:

- `GET /healthz` → `{"status": "ok", "model": MODEL_NAME, "rul_cap": RUL_CAP}`
  (pull `MODEL_NAME`/`RUL_CAP` from `predict.py`, don't hardcode).

- `POST /health/{drone_id}` — body is one telemetry reading (the same dict shape
  documented in `README.md`: `cycle`, `setting1..3`, `sensor1..21`). Server keeps an
  in-memory `dict[str, HealthMonitor]` keyed by `drone_id`, creating one on first
  use (mirror the exact pattern already in `README.md`'s "Live telemetry" section —
  just move it server-side). Calls `.update(reading)` and returns that result dict
  unchanged: `{drone_id, cycle, rul_cycles, health, status, history_length}`.

- `GET /health/{drone_id}` — returns the **last** result for that drone without
  adding a new reading (for UI polling/reconnects). 404 with a clear JSON error body
  if that drone has no history yet. You'll need to cache the last result alongside
  each `HealthMonitor` (a small wrapper dict is fine, e.g. `{"monitor": ..., "last":
  ...}` — don't modify `HealthMonitor` itself for this).

- `POST /health/{drone_id}/reset` → clears that drone's history, returns
  `{"drone_id": ..., "reset": true}`.

- `GET /trajectories` → returns the parsed contents of `trajectories.json` as JSON
  (read once at startup, cache in memory — the file doesn't change at runtime).

- `POST /simulate/{drone_id}` — see Task 2 below; this endpoint is the HTTP face of
  `prime_monitor()`. Body: `{"at_tick": 1, "num_ticks": 150, "failure_at": null,
  "seed": null}` (all optional, those are the defaults). Response:
  `{"drone_id": ..., "primed_to_tick": at_tick, "current": <same shape as the
  /health response>, "remaining_ticks": [...]}`. This call **replaces** any
  existing monitor state for that `drone_id` (it's a (re)seed operation) — say so in
  the endpoint's docstring so it isn't confused with `POST /health/{drone_id}`.

Non-functional requirements:
- Add `fastapi` and `uvicorn` to `requirements.txt`, pinned to exact versions like
  every other line in that file already is (check what actually resolves in the
  venv, don't guess a version number).
- Permissive CORS (`allow_origins=["*"]`) — this is a same-laptop hackathon demo,
  not a service with real users; a one-line comment saying that's why is enough,
  don't build real auth/config for it.
- Default port `8500`, overridable via a `PORT` env var (`8000` is a likely default
  for whatever Pranav ends up running, so avoid colliding with it).
- `if __name__ == "__main__":` block that runs it with `uvicorn.run(...)` so
  `python serve.py` works directly, no separate CLI invocation to remember.
- Every route gets a one-line docstring. Match the existing file's voice — short,
  says *why* when it's non-obvious (e.g. why `/simulate` overwrites state), not
  *what* the code already shows.

## Task 2: `prime_monitor()` — fast-forward a drone's health history

Add to `predict.py` (not a new file — it belongs next to `HealthMonitor` and
`simulate_drone_telemetry`, which it composes):

```python
def prime_monitor(
    drone_id: str,
    at_tick: int = 1,
    num_ticks: int = 150,
    failure_at: int | None = None,
    seed: int | None = None,
) -> tuple[HealthMonitor, list[dict]]:
    """
    Build a HealthMonitor already fast-forwarded to `at_tick`, so a demo fleet can
    start with drones at varied points in their lifecycle instead of every drone
    beginning at 100% health and needing minutes of live ticks before the
    predictive-maintenance feature has anything to show.

    Returns the primed monitor plus the unconsumed tail of the trace, so the caller
    keeps calling monitor.update() on each remaining reading at its own cadence.
    """
```

Implementation: call the existing `simulate_drone_telemetry(num_ticks, failure_at,
seed=seed)`, feed `trace[:at_tick]` through a fresh `HealthMonitor(drone_id)` via
`.update()` in a loop, return `(monitor, trace[at_tick:])`. Don't duplicate the
degradation-curve logic — this function's entire job is composing the two pieces
that already exist. `serve.py`'s `POST /simulate/{drone_id}` (Task 1) calls this
same function; don't write the fast-forward loop twice.

Validate: `at_tick` must be `>= 1` and `<= num_ticks` — raise `ValueError` with a
clear message otherwise, same style as `_frame_from_history`'s existing validation.

## Task 3 (only if Tasks 1–2 are done and committed): more trajectory variety

`build_trajectories.py` currently takes the top 8 of 157 qualifying candidates
(`TARGET_COUNT = 8`). Bump it to `16` and rerun `python build_trajectories.py`.
Before committing, look at the printed table for tracks 9–16: confirm straightness
stays reasonably high and max turn stays gentle (tracks 1–8 are all straightness
1.0 — some falloff by #16 is expected and fine, a cliff isn't). If quality drops
sharply well before 16, stop at whatever count still looks like a real flight path,
don't force it to 16. The new `count` is already self-documented in
`trajectories.json`'s own `selection.candidates_considered` field — just confirm
the numbers in `ml/README.md`'s "Trajectories" section still match (currently says
"8 aircraft selected from 214" — fix that line if the count changes).

---

## Task 4 (stretch, final-round only): CNN object detector on AU-AIR

**Gate before starting:** Tasks 1–3 are committed and pushed, Review 1 is done, and
there is genuinely spare time (the roadmap's own final-round guidance: "a static
demo... is the only realistic way to touch [these datasets] at all" — you're doing
more than that static demo because you asked for real training, but the time
discipline still applies). If you're not past that gate, stop here and don't start
this task.

**What "CNN" means here and why this approach, not a hand-built network:** a
convolutional neural network for object detection is not something to train from
random weights in a hackathon — CSPDarknet-style backbones (the CNN inside
YOLOv8/YOLO11) already exist pretrained on COCO. The correct, defensible technique
is transfer learning: fine-tune that pretrained CNN backbone on real drone footage.
When judges ask "where's the CNN," the honest answer is "YOLOv8's backbone is a
convolutional network, fine-tuned via transfer learning on real AU-AIR drone
imagery" — same honesty standard the roadmap already sets for the RUL model.

**Dataset:** `C:\Users\rohit\Downloads\Datasets\04_AUAIR_multimodal_uav\` —
`images/` (32,823 frames, 1920×1080 jpg) + `annotations.json`. This is real UAV
camera footage with synced GPS/IMU per frame, which is why it fits this project
better than VisDrone (VisDrone is drone footage from cities in China with no
telemetry link — don't use it here, AU-AIR is the right one).

Confirmed annotation format (checked directly, don't re-derive it):
- 8 classes, **class id = index into this exact list**: `["Human", "Car", "Truck",
  "Van", "Motorbike", "Bicycle", "Bus", "Trailer"]`.
- Per frame: `bbox: [{"top": int, "left": int, "height": int, "width": int,
  "class": int}, ...]` in pixel coordinates against the frame's actual size (read
  `image_width:` — **note the literal trailing colon inside that JSON key string,
  it is not a typo you introduce, it's in the source file** — and `image_height`
  per record; don't assume every frame is exactly 1920×1080).

**Step 1 — environment, in a separate venv/requirements file.** `ultralytics` pulls
in `torch`+`torchvision` (multi-GB, unrelated weight class to the existing
sklearn-based `ml/` setup). Do not add these to the main `requirements.txt` — create
`requirements-cv.txt` instead, so anyone who only needs `predict.py` (Pranav) still
gets the fast, light install the README already promises. Verify install actually
succeeds on this machine's Python 3.14 before writing any training code — `pip
install ultralytics` and confirm `import ultralytics, torch` both work. (Checked
already: torch 2.14 and torchvision 0.29 both publish `cp314` wheels, so this should
install cleanly, but verify rather than assume.)

**Step 2 — convert annotations to YOLO format.** New script `ml/cv/prepare_auair.py`:
- Pick a deterministic random subsample — **2,500 images, seed=7** — from the
  32,823 (CPU training on the full set is not realistic; say so in a comment).
  Before finalizing the sample, count class frequency across the full dataset vs.
  your subsample and print both — AU-AIR is heavily skewed toward `Car`, and
  `Bus`/`Trailer` are rare. If a rare class has fewer than ~30 instances in your
  2,500-image sample, oversample frames that contain it until it does, rather than
  silently training a detector that never learns those classes.
- Split 85/15 train/val by image (not by annotation), same leakage discipline the
  RUL model already follows for engines — don't let augmented/duplicate views of
  the same frame cross the split (AU-AIR frames are already distinct, so this is
  just a plain random split, but do it before any augmentation step).
- Convert each `{top,left,height,width}` box to YOLO's normalized `(class_id,
  x_center, y_center, w, h)` using that frame's real `image_width:`/`image_height`.
  Write one `.txt` per image alongside a copied/symlinked image, into the layout
  `ultralytics` expects: `ml/cv/data/images/{train,val}/`, `ml/cv/data/labels/{train,val}/`.
- Write `ml/cv/au_air.yaml` (`path`, `train`, `val`, `names` — the 8 classes in
  the exact order above, index-matched).

**Step 3 — timebox before committing to a full run.** First do a pilot: 200 images,
2 epochs, `imgsz=640`, `device=cpu`, and time it. Extrapolate to the full 2,500-image
/ 15-epoch run. If the extrapolated wall-clock exceeds **45 minutes**, cut epochs
and/or subsample size until it doesn't, and note the actual numbers you used and why
in `ml/cv/README.md`. Then run the real training:
`yolo detect train data=ml/cv/au_air.yaml model=yolov8n.pt epochs=15 imgsz=640
device=cpu batch=8` (or the equivalent `ultralytics.YOLO(...).train(...)` Python
call — either is fine, pick whichever makes the timing/logging easier to capture in
a script rather than a one-off CLI invocation).

**Step 4 — outputs.** Copy the trained weights to `ml/cv/au_air_yolov8n.pt`. Add
`ml/cv/detect.py` with the same clean-interface philosophy as `predict.py`:
```python
def detect_objects(image) -> list[dict]:   # [{"class": "Car", "bbox": [x,y,w,h], "conf": 0.87}, ...]
def ground_density(image) -> dict[str, int]  # {"Car": 12, "Human": 3, ...}
```
Both load the model once at module import (mirror `predict.py`'s `_bundle =
joblib.load(...)` pattern — load at import time, not per call).

**Step 5 — evaluate honestly, same standard as the RUL model.** Run `ultralytics`'
built-in validation on the held-out 15% val split, save `mAP50`/`mAP50-95` per class
into `ml/cv/model_metadata.json` (same shape/spirit as the existing
`model_metadata.json`). Then run inference on 5 val images the model never trained
on and save the annotated outputs to `ml/cv/demo_detections/` (`model.predict(...,
save=True)` does this) — a from-the-eyeball check that boxes land on real objects,
the same "don't just trust the metric" standard `sanity_check.py` already holds the
RUL model to. If detections look wrong (boxes way off objects, one class dominating
everything), say so in the README rather than shipping it quietly.

**Non-negotiable:** this task must not touch, weaken, or slow down anything from
Tasks 1–3. If it isn't working well by the time you need to stop, leave it out of
the demo entirely — a missing stretch feature costs nothing; a working RUL model
and trajectory feed are what actually get the team through review.

---

## Testing — must be runnable by someone who didn't write the code

Add `ml/test_serve.py` using FastAPI's `TestClient` (in-process, no port binding, no
`uvicorn` process to manage — this matters under time pressure, don't script
`requests` calls against a live server). Cover, at minimum:
1. `GET /healthz` returns 200 and the real model name.
2. `POST /health/d1` with a healthy-looking reading (cycle 1, sensors at the
   `_SENSOR_PROFILE` healthy baseline from `predict.py`) returns `status ==
   "healthy"`.
3. Two sequential `POST /health/d1` calls increment `history_length` — proves state
   persists per `drone_id` across calls.
4. `POST /simulate/d2` with `at_tick=100, num_ticks=120, failure_at=100` returns a
   `current.status` of `"service_soon"` or `"ground_now"` — proves priming actually
   fast-forwards degradation, not just cycle count.
5. `GET /health/unknown-drone` returns 404.
6. `GET /trajectories` returns `count == len(trajectories)` matching the file on
   disk.

Run it (`pytest test_serve.py` or `python -m pytest test_serve.py`) and paste the
pass/fail output into your own working notes before committing — don't commit on
the assumption it passes.

Also re-run `python sanity_check.py` after Task 2's change to `predict.py`, even
though you didn't touch the model — it must still exit 0. If it doesn't, you broke
something in `predict.py` that the check depends on; fix that before continuing.

## Git & handoff

Same rules the team already agreed on: commit only inside `ml/`, small commits with
a one-line message, push straight to `main` (no branch — nobody else touches this
folder). Suggested commits, in order: `serve.py` + `requirements.txt` addition,
`prime_monitor()` + `test_serve.py`, trajectory count bump (only if you get to
Task 3) — three commits, not one giant one, so a broken later step doesn't block the
earlier working ones from being on `main` before the merge checkpoint. Task 4, if
you get to it, is its own commit (or a few), made well after the merge checkpoint —
never let it hold up Tasks 1–3 landing on `main` first. Make sure `ml/.gitignore`
excludes `ml/cv/data/` (the expanded image/label copies) and the raw AU-AIR dataset
path — commit the code, the weights file, and the metadata/README, not a second copy
of the dataset.

After pushing, message Pranav with the new contract — same move the roadmap
already has him doing for you with his WebSocket shape:

> ml/ now also runs as a standalone service if you want it (`python serve.py`,
> port 8500, or set `PORT`). `POST /health/{drone_id}` with a sensor reading, `POST
> /simulate/{drone_id}` to fast-forward a drone's health for the demo, `GET
> /trajectories` for the waypoint lists. If your backend ends up Python, ignore
> this and `import predict` directly instead — same functions, no HTTP hop.

## Definition of done

- [ ] `serve.py` runs with `python serve.py`, all five endpoints match the contract
      above exactly (field names matter — Pranav's code will key off them).
- [ ] `prime_monitor()` added to `predict.py`, reuses `simulate_drone_telemetry` and
      `HealthMonitor` rather than reimplementing degradation logic.
- [ ] `test_serve.py` passes.
- [ ] `sanity_check.py` still exits 0.
- [ ] `requirements.txt` updated with pinned `fastapi`/`uvicorn` versions.
- [ ] `ml/README.md` gets a short new section documenting `serve.py` and
      `prime_monitor()` in the same style as the existing "Using it from the
      backend" section — one code sample each, no restating what the code says.
- [ ] Three small commits pushed to `main`, Pranav messaged with the contract.
- [ ] (Only if time remains) Task 3 done and `README.md`'s trajectory count updated
      to match.
- [ ] (Stretch, gated — see Task 4) `ml/cv/` contains `prepare_auair.py`,
      `au_air.yaml`, `detect.py`, `au_air_yolov8n.pt`, `model_metadata.json`,
      `demo_detections/` with sample annotated images, and a short `README.md`
      stating the actual subsample size, epoch count, timing, and mAP achieved —
      no invented numbers, only what the run actually produced.
