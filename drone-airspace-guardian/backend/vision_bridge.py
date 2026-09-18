"""Run YOLOv8n on cycling aerial frames for the live HUD."""

from __future__ import annotations

import json
import os
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent / "ml"
FRAMES = ML_DIR / "vision_frames"
TRUTH_FILE = FRAMES / "truth.json"
METRICS_FILE = ML_DIR / "weights" / "vision_metrics.json"
FINAL_WEIGHTS = ML_DIR / "weights" / "yolov8n_airspace.pt"
RUN_BEST = ML_DIR / "runs" / "yolov8n_airspace" / "weights" / "best.pt"
PRETRAINED = ML_DIR / "yolov8n.pt"
RESULTS_CSV = ML_DIR / "runs" / "yolov8n_airspace" / "results.csv"

VISDRONE_DIR = Path(
    os.environ.get(
        "VISDRONE_DIR",
        r"C:\Users\rohit\Downloads\Datasets\05_VisDrone_detection_tracking",
    )
)
TRUTH_NAMES = ["person", "car", "van", "truck", "bus", "motor"]
VISDRONE_TO_CLASS = {1: 0, 2: 0, 4: 1, 5: 2, 6: 3, 9: 4, 10: 5}

_model = None
_fallback = None
_loaded_path: Path | None = None
_idx = 0
_truth: dict[str, list] = {}
_truth_mtime: float = 0.0
_last: dict = {
    "image": "",
    "frame": "",
    "model": "yolov8n",
    "ready": False,
    "detections": [],
    "truth": [],
    "metrics": None,
    "counts": {},
    "width": 0,
    "height": 0,
}


def current_vision() -> dict:
    return _last


def warmup_vision() -> None:
    global _fallback, _model, _last
    frames = _frames()
    if frames:
        _last["image"] = f"/media/{frames[0].name}"
        _last["frame"] = frames[0].name
    _load_truth()
    _last["metrics"] = _snapshot_metrics()
    try:
        from ultralytics import YOLO

        base = str(PRETRAINED) if PRETRAINED.exists() else "yolov8n.pt"
        _fallback = YOLO(base)
        _model = _fallback
        _last["model"] = "yolov8n"
        _last["ready"] = True
        print("[vision_bridge] loaded yolov8n (pretrained fallback)")
    except Exception as exc:
        _last["ready"] = False
        print(f"[vision_bridge] YOLO unavailable: {exc}")
        return
    _maybe_load_trained()


def _frames() -> list[Path]:
    if not FRAMES.exists():
        return []
    imgs = sorted([p for p in FRAMES.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}])
    if _truth:
        keyed = [p for p in imgs if p.name in _truth or p.stem.startswith("dubai-")]
        if keyed:
            return keyed
    return imgs


def _trained_candidate() -> Path | None:
    """
    Prefer the exported demo weights once training has written vision_metrics.json.
    While the run is in progress (or stripped to ~6.2 MB), use runs/.../best.pt.
    File size is NOT a signal: pretrained yolov8n.pt and a stripped fine-tune are
    both ~6.2 MB.
    """
    if METRICS_FILE.exists() and FINAL_WEIGHTS.exists():
        return FINAL_WEIGHTS
    if RUN_BEST.exists():
        return RUN_BEST
    if RESULTS_CSV.exists() and FINAL_WEIGHTS.exists():
        return FINAL_WEIGHTS
    return None


def _maybe_load_trained() -> None:
    """Use fine-tuned weights when they exist; never unload the pretrained fallback."""
    global _model, _loaded_path, _last
    cand = _trained_candidate()
    if cand is None or _fallback is None:
        return
    if _loaded_path == cand:
        return
    # Already on a trained checkpoint — only hot-swap onto the final export.
    if _loaded_path is not None and cand != FINAL_WEIGHTS:
        return
    try:
        from ultralytics import YOLO

        _model = YOLO(str(cand))
        _loaded_path = cand
        _last["model"] = "yolov8n-airspace"
        print(f"[vision_bridge] loaded trained weights: {cand}")
    except Exception as exc:
        print(f"[vision_bridge] trained weights not ready ({cand.name}): {exc}")


def _read_visdrone_boxes(ann: Path) -> list[dict]:
    boxes: list[dict] = []
    if not ann.exists():
        return boxes
    for raw in ann.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = raw.strip().rstrip(",").split(",")
        if len(parts) < 6:
            continue
        try:
            left, top, bw, bh = (float(p) for p in parts[:4])
            score = float(parts[4])
            cat = int(float(parts[5]))
        except ValueError:
            continue
        if score == 0 or cat not in VISDRONE_TO_CLASS:
            continue
        x1, y1, x2, y2 = left, top, left + bw, top + bh
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        boxes.append(
            {
                "label": TRUTH_NAMES[VISDRONE_TO_CLASS[cat]],
                "xyxy": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
            }
        )
    return boxes[:40]


def _truth_from_visdrone() -> dict[str, list]:
    names = {p.name: p.stem for p in _frames()}
    if not names or not VISDRONE_DIR.exists():
        return {}
    out: dict[str, list] = {}
    splits = (
        "VisDrone2019-DET-test-dev",
        "VisDrone2019-DET-val",
        "VisDrone2019-DET-train",
    )
    pending = dict(names)
    for split in splits:
        ann_dir = VISDRONE_DIR / split / "annotations"
        if not ann_dir.exists():
            continue
        for filename, stem in list(pending.items()):
            boxes = _read_visdrone_boxes(ann_dir / f"{stem}.txt")
            if boxes:
                out[filename] = boxes
                pending.pop(filename, None)
        if not pending:
            break
    return out


def _load_truth() -> None:
    global _truth, _truth_mtime
    if TRUTH_FILE.exists():
        try:
            _truth = json.loads(TRUTH_FILE.read_text(encoding="utf-8"))
            _truth_mtime = TRUTH_FILE.stat().st_mtime
            if isinstance(_truth, dict):
                print(f"[vision_bridge] truth.json: {len(_truth)} frames")
                return
        except (OSError, json.JSONDecodeError):
            pass
    _truth = _truth_from_visdrone()
    _truth_mtime = TRUTH_FILE.stat().st_mtime if TRUTH_FILE.exists() else 0.0
    if _truth:
        print(f"[vision_bridge] VisDrone truth for {len(_truth)} frames")


def _refresh_truth_if_needed() -> None:
    if TRUTH_FILE.exists() and TRUTH_FILE.stat().st_mtime != _truth_mtime:
        _load_truth()


def _metrics_from_csv() -> dict | None:
    if not RESULTS_CSV.exists():
        return None
    try:
        lines = RESULTS_CSV.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
        if len(lines) < 2:
            return None
        headers = [h.strip() for h in lines[0].split(",")]
        row = [c.strip() for c in lines[-1].split(",")]
        data = dict(zip(headers, row))

        def num(*keys: str) -> float | None:
            for key in keys:
                raw = data.get(key, "")
                if raw == "":
                    continue
                try:
                    return float(raw)
                except ValueError:
                    continue
            return None

        epoch = num("epoch")
        map50 = num("metrics/mAP50(B)", "metrics/mAP50")
        out: dict = {"model": "yolov8n-airspace"}
        if epoch is not None:
            out["epochs"] = int(epoch)
        if map50 is not None:
            out["mAP50"] = round(map50, 4)
        train_dir = ML_DIR / "yolo_data" / "images" / "train"
        if train_dir.exists():
            out["images"] = sum(1 for p in train_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        return out if len(out) > 1 else None
    except OSError:
        return None


def _snapshot_metrics() -> dict | None:
    if METRICS_FILE.exists():
        try:
            data = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "model": data.get("model", "yolov8n-airspace"),
                    "epochs": data.get("epochs"),
                    "images": data.get("images"),
                    "mAP50": data.get("mAP50"),
                }
        except (OSError, json.JSONDecodeError):
            pass
    return _metrics_from_csv()


def _run(model, path: Path, conf: float) -> tuple[list[dict], dict[str, int]]:
    dets: list[dict] = []
    counts: dict[str, int] = {}
    if model is None:
        return dets, counts
    result = model.predict(str(path), imgsz=320, verbose=False, conf=conf)[0]
    names = result.names
    boxes = result.boxes
    if boxes is None:
        return dets, counts
    for i in range(len(boxes)):
        cls = int(boxes.cls[i])
        label = str(names.get(cls, cls))
        score = float(boxes.conf[i])
        xyxy = [round(float(v), 1) for v in boxes.xyxy[i].tolist()]
        dets.append({"label": label, "conf": round(score, 3), "xyxy": xyxy})
        counts[label] = counts.get(label, 0) + 1
    return dets, counts


def snapshot_vision() -> dict:
    global _idx, _last
    frames = _frames()
    if not frames:
        _last["metrics"] = _snapshot_metrics()
        return _last
    _refresh_truth_if_needed()
    _maybe_load_trained()
    path = frames[_idx % len(frames)]
    _idx += 1
    dets: list[dict] = []
    counts: dict[str, int] = {}
    used = "yolov8n-airspace" if _loaded_path is not None else "yolov8n"
    try:
        dets, counts = _run(_model, path, 0.12)
        if not dets and _fallback is not None and _fallback is not _model:
            dets, counts = _run(_fallback, path, 0.15)
            used = "yolov8n"
    except Exception as exc:
        print(f"[vision_bridge] predict failed: {exc}")
        if _fallback is not None and _fallback is not _model:
            try:
                dets, counts = _run(_fallback, path, 0.15)
                used = "yolov8n"
            except Exception:
                pass
    _last = {
        "image": f"/media/{path.name}",
        "frame": path.name,
        "model": used,
        "ready": _model is not None,
        "detections": dets[:12],
        "truth": list(_truth.get(path.name, []))[:40],
        "metrics": _snapshot_metrics(),
        "counts": counts,
        "width": 0,
        "height": 0,
    }
    try:
        from PIL import Image

        with Image.open(path) as im:
            _last["width"], _last["height"] = im.size
    except Exception:
        pass
    return _last
