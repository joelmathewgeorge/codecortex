"""
Export AU-AIR frames for the ground-risk monitor camera rotation.

Dataset: AU-AIR multimodal UAV (Parrot Bebop 2, 1920x1080, Denmark).
Task: copy strided windows from every real flight session (up to 8) into a local
gitignored folder the backend serves at GET /media/auair/...
Why this method: the licence asks for links rather than rebundling, so only a
small replay slice is written locally. Stride keeps the scene moving.
What is NOT claimed: these are not Dubai streets; GPS is Denmark and is shown as
camera telemetry only — drone missions are re-anchored separately
(export_auair_missions.py).

Who reads the artifact: backend/ground.py (GM-1..GM-4). Operator sees the
GroundCamera feed plus gps/velocity/time/imu sidecars.

Run: python export_auair_frames.py        (AUAIR_DIR overrides the dataset path)
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "auair_frames"
DEFAULT_DIR = Path(r"C:\Users\rohit\Downloads\Datasets\04_AUAIR_multimodal_uav")
CATEGORIES = ["Human", "Car", "Truck", "Van", "Motorbike", "Bicycle", "Bus", "Trailer"]

WINDOW = 240
STRIDE = 8
OUT_W, OUT_H = 960, 540
MAX_SESSIONS = 8


def _session_id(image_name: str) -> str:
    return image_name[:20]


def _iso_time(t: dict) -> str:
    return (
        f"{int(t['year']):04d}-{int(t['month']):02d}-{int(t['day']):02d}"
        f"T{int(t['hour']):02d}:{int(t['min']):02d}:{int(t['sec']):02d}"
    )


def _imu(frame: dict) -> dict | None:
    keys = ("angle_phi", "angle_theta", "angle_psi")
    if not all(k in frame for k in keys):
        return None
    return {k.replace("angle_", ""): round(float(frame[k]), 5) for k in keys}


def _pick_window(frames: list[dict]) -> int:
    """Start index of the densest strided 30-frame window that still moves."""
    counts = [len(f.get("bbox") or []) for f in frames]
    best = (0.0, 0)
    step = max(1, WINDOW // 2)
    for start in range(0, max(1, len(frames) - WINDOW + 1), step):
        chunk = counts[start : start + WINDOW : STRIDE]
        if len(chunk) < WINDOW // STRIDE:
            continue
        density = sum(chunk) / len(chunk)
        if density > best[0]:
            best = (density, start)
    if best[0] == 0.0 and len(frames) >= WINDOW // STRIDE:
        return 0
    return best[1]


def main() -> None:
    root = Path(os.environ.get("AUAIR_DIR", DEFAULT_DIR))
    ann_path = root / "annotations.json"
    if not ann_path.exists():
        raise SystemExit(f"AU-AIR annotations not found at {ann_path} (set AUAIR_DIR)")
    annotations = json.loads(ann_path.read_text(encoding="utf-8"))["annotations"]
    sequences: dict[str, list[dict]] = defaultdict(list)
    for frame in annotations:
        sequences[_session_id(frame["image_name"])].append(frame)
    for frames in sequences.values():
        frames.sort(key=lambda f: f["image_name"])

    sessions = sorted(sequences.items(), key=lambda kv: -len(kv[1]))[:MAX_SESSIONS]
    if not sessions:
        raise SystemExit(f"No AU-AIR sessions in {ann_path}")

    OUT_DIR.mkdir(exist_ok=True)
    for old in OUT_DIR.glob("*.jpg"):
        old.unlink()

    sets = []
    for n, (seq_id, frames) in enumerate(sessions, start=1):
        start = _pick_window(frames)
        window = frames[start : start + WINDOW : STRIDE]
        entries = []
        for i, frame in enumerate(window):
            name = f"auair-{n}-{i:02d}.jpg"
            src = root / "images" / frame["image_name"]
            if not src.exists():
                print(f"  skip missing {src.name}")
                continue
            with Image.open(src) as im:
                sx, sy = OUT_W / im.width, OUT_H / im.height
                im.convert("RGB").resize((OUT_W, OUT_H), Image.Resampling.LANCZOS).save(
                    OUT_DIR / name, quality=80
                )
            boxes = []
            for b in frame.get("bbox") or []:
                label = CATEGORIES[b["class"]] if 0 <= b["class"] < len(CATEGORIES) else "Object"
                x1, y1 = b["left"] * sx, b["top"] * sy
                boxes.append(
                    {
                        "label": label,
                        "xyxy": [
                            round(x1, 1),
                            round(y1, 1),
                            round(x1 + b["width"] * sx, 1),
                            round(y1 + b["height"] * sy, 1),
                        ],
                    }
                )
            t = frame["time"]
            entry = {
                "file": name,
                "source": frame["image_name"],
                "time": _iso_time(t),
                "gps": {
                    "lat": frame["latitude"],
                    "lon": frame["longtitude"],
                    "alt_m": round(frame["altitude"] / 1000.0, 1),
                },
                "velocity": {k: round(float(frame[f"linear_{k}"]), 3) for k in ("x", "y", "z")},
                "boxes": boxes,
            }
            imu = _imu(frame)
            if imu is not None:
                entry["imu"] = imu
                entry["angular"] = imu
            entries.append(entry)
        mean_boxes = sum(len(e["boxes"]) for e in entries) / max(1, len(entries))
        sets.append(
            {
                "id": n,
                "sequence": seq_id,
                "start": start,
                "mean_boxes": round(mean_boxes, 1),
                "frames": entries,
            }
        )
        print(
            f"  set {n}: {seq_id} from frame {start}, {len(entries)} frames, {mean_boxes:.1f} boxes/frame"
        )

    index = {
        "source": "AU-AIR multimodal UAV dataset (Bozcan & Kayacan, 2020)",
        "categories": CATEGORIES,
        "width": OUT_W,
        "height": OUT_H,
        "sets": sets,
    }
    (OUT_DIR / "index.json").write_text(json.dumps(index), encoding="utf-8")
    print(f"wrote {sum(len(s['frames']) for s in sets)} frames / {len(sets)} sessions to {OUT_DIR}")


if __name__ == "__main__":
    main()
