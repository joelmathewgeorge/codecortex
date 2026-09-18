"""
Export AU-AIR frames for the ground-risk monitor and the aerial detection feed.

AU-AIR is low-altitude traffic surveillance from a Parrot Bebop 2: 1920x1080 frames, each
with its object boxes (Human, Car, Truck, Van, Motorbike, Bicycle, Bus, Trailer) and the
drone's own GPS / altitude / velocity at that instant.

Six windows of 30 frames are cut at different traffic densities (every 8th frame, so the
scene moves between samples) and written downscaled to ml/auair_frames/ with an
index.json holding the real boxes and synced flight telemetry. The backend replays one
window per ground-monitor camera.

The dataset licence asks for links rather than rebundling, so the output is gitignored.

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
# Mean boxes per frame the six windows should sit near, busiest first.
TARGET_DENSITY = [26.0, 17.0, 11.0, 7.0, 4.0, 1.5]


def main() -> None:
    root = Path(os.environ.get("AUAIR_DIR", DEFAULT_DIR))
    annotations = json.loads((root / "annotations.json").read_text(encoding="utf-8"))["annotations"]
    sequences: dict[str, list[dict]] = defaultdict(list)
    for frame in annotations:
        sequences[frame["image_name"][:20]].append(frame)
    for frames in sequences.values():
        frames.sort(key=lambda f: f["image_name"])

    windows = []
    for seq_id, frames in sequences.items():
        counts = [len(f.get("bbox") or []) for f in frames]
        for start in range(0, max(1, len(frames) - WINDOW), WINDOW // 2):
            chunk = counts[start : start + WINDOW : STRIDE]
            if len(chunk) >= WINDOW // STRIDE:
                windows.append((sum(chunk) / len(chunk), seq_id, start))

    chosen = []
    for target in TARGET_DENSITY:
        pool = [w for w in windows if all(abs(w[2] - c[2]) > WINDOW or w[1] != c[1] for c in chosen)]
        chosen.append(min(pool, key=lambda w: abs(w[0] - target)))

    OUT_DIR.mkdir(exist_ok=True)
    for old in OUT_DIR.glob("*.jpg"):
        old.unlink()

    sets = []
    for n, (density, seq_id, start) in enumerate(chosen, start=1):
        frames = sequences[seq_id][start : start + WINDOW : STRIDE]
        entries = []
        for i, frame in enumerate(frames):
            name = f"auair-{n}-{i:02d}.jpg"
            src = root / "images" / frame["image_name"]
            with Image.open(src) as im:
                sx, sy = OUT_W / im.width, OUT_H / im.height
                im.convert("RGB").resize((OUT_W, OUT_H), Image.Resampling.LANCZOS).save(OUT_DIR / name, quality=80)
            boxes = []
            for b in frame.get("bbox") or []:
                label = CATEGORIES[b["class"]] if 0 <= b["class"] < len(CATEGORIES) else "Object"
                x1, y1 = b["left"] * sx, b["top"] * sy
                boxes.append(
                    {"label": label, "xyxy": [round(x1, 1), round(y1, 1), round(x1 + b["width"] * sx, 1), round(y1 + b["height"] * sy, 1)]}
                )
            t = frame["time"]
            entries.append(
                {
                    "file": name,
                    "source": frame["image_name"],
                    "time": f"{t['year']:04d}-{t['month']:02d}-{t['day']:02d}T{t['hour']:02d}:{t['min']:02d}:{t['sec']:02d}",
                    "gps": {"lat": frame["latitude"], "lon": frame["longtitude"], "alt_m": round(frame["altitude"] / 1000.0, 1)},
                    "velocity": {k: round(frame[f"linear_{k}"], 3) for k in ("x", "y", "z")},
                    "boxes": boxes,
                }
            )
        sets.append({"id": n, "sequence": seq_id, "start": start, "mean_boxes": round(density, 1), "frames": entries})
        print(f"  set {n}: {seq_id} from frame {start}, {len(entries)} frames, {density:.1f} boxes/frame")

    index = {
        "source": "AU-AIR multimodal UAV dataset (Bozcan & Kayacan, 2020)",
        "categories": CATEGORIES,
        "width": OUT_W,
        "height": OUT_H,
        "sets": sets,
    }
    (OUT_DIR / "index.json").write_text(json.dumps(index), encoding="utf-8")
    print(f"wrote {sum(len(s['frames']) for s in sets)} frames to {OUT_DIR}")


if __name__ == "__main__":
    main()
