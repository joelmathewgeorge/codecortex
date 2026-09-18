"""
Fine-tune YOLOv8n on VisDrone2019-DET so the live camera panel runs a real trained
detector instead of falling back to stock COCO weights.

WHY THE FIRST ATTEMPT SCORED mAP50 = 0
    The earlier run fed 48 whole VisDrone frames into a 320 px network. VisDrone frames
    are ~1360x765 to 2000x1500 and a car occupies roughly 30x20 px, so downscaling to
    320 px shrinks a car to about 7x5 px. YOLOv8n's smallest stride-8 head cannot
    resolve that, the head never saw a positive match, and every metric stayed at zero.

WHAT THIS SCRIPT DOES INSTEAD
    1. Crops NATIVE-RESOLUTION windows (default 512x512) out of the big frames, centred
       on clusters of annotated vehicles. No downscaling happens, so a car stays ~30x20
       px inside a 512 px training image — a size the nano model can actually learn.
    2. Merges the 10 VisDrone categories down to 6 demo-legible ones. Ten classes split a
       small CPU budget too thinly, and the HUD only needs to read "car / van / truck /
       bus / person / motor".
    3. Trains from COCO-pretrained yolov8n.pt (never from scratch) at imgsz == crop size.
    4. Writes weights/yolov8n_airspace.pt plus weights/vision_metrics.json, which
       backend/vision_bridge.py serves to the dashboard as `vision.metrics`.
    5. Exports a demo frame rotation into vision_frames/ with a truth.json sidecar that
       carries the VisDrone ground-truth boxes for those frames.

WHAT THIS DOES NOT CLAIM
    VisDrone is street-level aerial traffic imagery, not Dubai and not drone-vs-drone
    detection. It is used here to estimate ground activity (vehicle/pedestrian density)
    beneath a flight path, which is exactly what the dataset supports.

RUN
    cd ml
    venv\\Scripts\\python.exe train_yolov8n.py              # prepare + train + export
    venv\\Scripts\\python.exe train_yolov8n.py --frames-only # re-export demo frames only
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
VISDRONE = Path(
    os.environ.get(
        "VISDRONE_DIR",
        r"C:\Users\rohit\Downloads\Datasets\05_VisDrone_detection_tracking",
    )
)
DUBAI_TILES = Path(
    os.environ.get(
        "DUBAI_TILES_DIR",
        r"C:\Users\rohit\Downloads\Datasets\02_Dubai_aerial_segmentation\images",
    )
)
TRAIN_SRC = VISDRONE / "VisDrone2019-DET-train"
VAL_SRC = VISDRONE / "VisDrone2019-DET-val"
DEMO_SRC = VISDRONE / "VisDrone2019-DET-test-dev"

DATA = ROOT / "yolo_data"
RUNS = ROOT / "runs"
RUN_NAME = "yolov8n_airspace"
WEIGHTS = ROOT / "weights" / "yolov8n_airspace.pt"
METRICS = ROOT / "weights" / "vision_metrics.json"
FRAMES = ROOT / "vision_frames"
TRUTH = FRAMES / "truth.json"

# --- training budget -------------------------------------------------------
# Tuned for a CPU-only 8-core Ryzen: ~20-30 minutes wall clock. Override with env
# vars when moving to a faster box.
CROP = int(os.environ.get("YOLO_CROP", 512))
IMGSZ = int(os.environ.get("YOLO_IMGSZ", CROP))
EPOCHS = int(os.environ.get("YOLO_EPOCHS", 8))
BATCH = int(os.environ.get("YOLO_BATCH", 8))
N_SRC_TRAIN = int(os.environ.get("YOLO_SRC_TRAIN", 520))
N_SRC_VAL = int(os.environ.get("YOLO_SRC_VAL", 110))
CROPS_PER_TRAIN_IMAGE = 2
MIN_BOXES_PER_CROP = 4
SEED = 7

# --- label space -----------------------------------------------------------
# VisDrone category ids: 0 ignored-region, 1 pedestrian, 2 people, 3 bicycle,
# 4 car, 5 van, 6 truck, 7 tricycle, 8 awning-tricycle, 9 bus, 10 motor, 11 others.
# 0 and 11 must be dropped per the official toolkit. bicycle/tricycle/awning-tricycle
# are dropped too: they are rare, visually ambiguous from altitude, and spending a
# short CPU budget on them costs accuracy on the classes the demo actually shows.
NAMES = ["person", "car", "van", "truck", "bus", "motor"]
VISDRONE_TO_CLASS = {1: 0, 2: 0, 4: 1, 5: 2, 6: 3, 9: 4, 10: 5}
VEHICLE_CLASSES = {1, 2, 3, 4}  # car, van, truck, bus — preferred crop anchors


# ---------------------------------------------------------------------------
# VisDrone annotation parsing
# ---------------------------------------------------------------------------

def read_boxes(ann_path: Path, iw: int, ih: int) -> list[tuple[int, float, float, float, float]]:
    """
    Parse one VisDrone annotation file into (class_id, x1, y1, x2, y2) pixel boxes.

    VisDrone line format: left,top,width,height,score,category,truncation,occlusion
    `score == 0` marks a region the benchmark tells you to ignore, so those go too.
    """
    if not ann_path.exists():
        return []
    boxes: list[tuple[int, float, float, float, float]] = []
    for raw in ann_path.read_text(encoding="utf-8", errors="ignore").splitlines():
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
        x1 = max(0.0, left)
        y1 = max(0.0, top)
        x2 = min(float(iw), left + bw)
        y2 = min(float(ih), top + bh)
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        boxes.append((VISDRONE_TO_CLASS[cat], x1, y1, x2, y2))
    return boxes


def pick_windows(
    boxes: list[tuple[int, float, float, float, float]],
    iw: int,
    ih: int,
    size: int,
    max_windows: int,
    rng: random.Random,
) -> list[tuple[int, int, list[tuple[int, float, float, float, float]]]]:
    """
    Choose up to `max_windows` size x size crop windows that are dense with objects.

    Anchors are sampled from vehicle boxes when available so the demo frames are full of
    cars rather than full of distant pedestrians. Windows that overlap an already chosen
    window by more than half their area are skipped so the crops stay distinct.
    """
    if iw < size or ih < size or not boxes:
        return []

    anchors = [b for b in boxes if b[0] in VEHICLE_CLASSES] or boxes
    candidates = []
    for _ in range(14):
        _, ax1, ay1, ax2, ay2 = rng.choice(anchors)
        cx = (ax1 + ax2) / 2.0
        cy = (ay1 + ay2) / 2.0
        x0 = int(min(max(cx - size / 2.0, 0.0), iw - size))
        y0 = int(min(max(cy - size / 2.0, 0.0), ih - size))
        inside = [
            b
            for b in boxes
            if b[1] >= x0 and b[2] >= y0 and b[3] <= x0 + size and b[4] <= y0 + size
        ]
        candidates.append((len(inside), x0, y0, inside))

    candidates.sort(key=lambda c: -c[0])
    chosen: list[tuple[int, int, list]] = []
    for count, x0, y0, inside in candidates:
        if count < MIN_BOXES_PER_CROP:
            continue
        clash = False
        for px, py, _ in chosen:
            ox = max(0, min(x0 + size, px + size) - max(x0, px))
            oy = max(0, min(y0 + size, py + size) - max(y0, py))
            if ox * oy > 0.5 * size * size:
                clash = True
                break
        if clash:
            continue
        chosen.append((x0, y0, inside))
        if len(chosen) >= max_windows:
            break
    return chosen


def to_yolo_lines(
    inside: list[tuple[int, float, float, float, float]], x0: int, y0: int, size: int
) -> list[str]:
    """Rebase pixel boxes onto the crop origin and normalise to YOLO cx,cy,w,h."""
    lines = []
    for cls, x1, y1, x2, y2 in inside:
        cx = ((x1 + x2) / 2.0 - x0) / size
        cy = ((y1 + y2) / 2.0 - y0) / size
        w = (x2 - x1) / size
        h = (y2 - y1) / size
        if not (0 < cx < 1 and 0 < cy < 1 and 0 < w <= 1 and 0 < h <= 1):
            continue
        lines.append(f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return lines


# ---------------------------------------------------------------------------
# Dataset preparation
# ---------------------------------------------------------------------------

def build_split(
    src: Path, split: str, n_images: int, crops_per_image: int, rng: random.Random
) -> tuple[int, int]:
    """Crop one VisDrone split into DATA/images/<split> + DATA/labels/<split>."""
    img_dir = src / "images"
    ann_dir = src / "annotations"
    images = sorted(img_dir.glob("*.jpg"))
    if not images:
        raise SystemExit(f"No VisDrone images under {img_dir}")
    rng.shuffle(images)

    out_img = DATA / "images" / split
    out_lbl = DATA / "labels" / split
    out_img.mkdir(parents=True, exist_ok=True)
    out_lbl.mkdir(parents=True, exist_ok=True)

    crops = 0
    objects = 0
    scanned = 0
    for src_img in images:
        if scanned >= n_images:
            break
        scanned += 1
        try:
            with Image.open(src_img) as im:
                iw, ih = im.size
                boxes = read_boxes(ann_dir / f"{src_img.stem}.txt", iw, ih)
                windows = pick_windows(boxes, iw, ih, CROP, crops_per_image, rng)
                if not windows:
                    continue
                rgb = im.convert("RGB")
                for k, (x0, y0, inside) in enumerate(windows):
                    lines = to_yolo_lines(inside, x0, y0, CROP)
                    if len(lines) < MIN_BOXES_PER_CROP:
                        continue
                    name = f"{src_img.stem}_c{k}"
                    rgb.crop((x0, y0, x0 + CROP, y0 + CROP)).save(
                        out_img / f"{name}.jpg", quality=88
                    )
                    (out_lbl / f"{name}.txt").write_text(
                        "\n".join(lines) + "\n", encoding="utf-8"
                    )
                    crops += 1
                    objects += len(lines)
        except (OSError, ValueError) as exc:
            print(f"  skip {src_img.name}: {exc}")
    print(f"  {split}: {crops} crops from {scanned} source frames, {objects} boxes")
    return crops, objects


def prepare() -> tuple[Path, dict]:
    """Rebuild yolo_data/ from scratch and write data.yaml."""
    print("=" * 72)
    print(f"PREPARE VISDRONE CROPS  ({CROP}x{CROP}, native resolution)")
    print("=" * 72)
    if DATA.exists():
        shutil.rmtree(DATA)
    rng = random.Random(SEED)
    tr_crops, tr_objs = build_split(TRAIN_SRC, "train", N_SRC_TRAIN, CROPS_PER_TRAIN_IMAGE, rng)
    va_crops, va_objs = build_split(VAL_SRC, "val", N_SRC_VAL, 1, rng)
    if tr_crops < 50 or va_crops < 10:
        raise SystemExit(f"Too few crops produced (train={tr_crops}, val={va_crops})")

    yaml_path = DATA / "data.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                f"path: {DATA.as_posix()}",
                "train: images/train",
                "val: images/val",
                "names:",
                *[f"  {i}: {n}" for i, n in enumerate(NAMES)],
                "",
            ]
        ),
        encoding="utf-8",
    )
    stats = {
        "train_images": tr_crops,
        "val_images": va_crops,
        "train_boxes": tr_objs,
        "val_boxes": va_objs,
    }
    print(f"  data.yaml -> {yaml_path}")
    return yaml_path, stats


# ---------------------------------------------------------------------------
# Demo frame rotation for the camera panel
# ---------------------------------------------------------------------------

def export_frames(n_visdrone: int = 9, n_dubai: int = 3) -> dict:
    """
    Fill vision_frames/ with crops that are dense with vehicles, plus a couple of Dubai
    aerial tiles so the rotation still looks like the city the demo claims to be over.

    Demo crops come from VisDrone test-dev, which the model never trains on, so the boxes
    in the panel are honest predictions on unseen imagery. truth.json carries the matching
    ground-truth boxes for the overlay comparison.
    """
    print("=" * 72)
    print("EXPORT DEMO FRAMES")
    print("=" * 72)
    FRAMES.mkdir(parents=True, exist_ok=True)
    for old in FRAMES.iterdir():
        if old.is_file():
            old.unlink()

    rng = random.Random(SEED + 1)
    ann_dir = DEMO_SRC / "annotations"
    images = sorted((DEMO_SRC / "images").glob("*.jpg"))
    rng.shuffle(images)

    truth: dict[str, list[dict]] = {}
    exported = 0
    for src_img in images:
        if exported >= n_visdrone:
            break
        try:
            with Image.open(src_img) as im:
                iw, ih = im.size
                boxes = read_boxes(ann_dir / f"{src_img.stem}.txt", iw, ih)
                vehicles = sum(1 for b in boxes if b[0] in VEHICLE_CLASSES)
                if vehicles < 10:
                    continue
                windows = pick_windows(boxes, iw, ih, CROP, 1, rng)
                if not windows:
                    continue
                x0, y0, inside = windows[0]
                if sum(1 for b in inside if b[0] in VEHICLE_CLASSES) < 6:
                    continue
                name = f"visdrone-{src_img.stem[:14]}-{x0}-{y0}.jpg"
                im.convert("RGB").crop((x0, y0, x0 + CROP, y0 + CROP)).save(
                    FRAMES / name, quality=86
                )
                truth[name] = [
                    {
                        "label": NAMES[cls],
                        "xyxy": [
                            round(x1 - x0, 1),
                            round(y1 - y0, 1),
                            round(x2 - x0, 1),
                            round(y2 - y0, 1),
                        ],
                    }
                    for cls, x1, y1, x2, y2 in inside
                ]
                exported += 1
                print(f"  {name}: {len(inside)} truth boxes ({vehicles} vehicles in frame)")
        except (OSError, ValueError) as exc:
            print(f"  skip {src_img.name}: {exc}")

    dubai = 0
    if DUBAI_TILES.exists():
        for tile in sorted(DUBAI_TILES.glob("tile_0*.png"))[10:]:
            if dubai >= n_dubai:
                break
            try:
                with Image.open(tile) as im:
                    side = min(im.size)
                    left = (im.width - side) // 2
                    top = (im.height - side) // 2
                    out = f"dubai-{tile.stem.split('_')[-1]}.jpg"
                    im.convert("RGB").crop((left, top, left + side, top + side)).resize(
                        (CROP, CROP), Image.LANCZOS
                    ).save(FRAMES / out, quality=84)
                    dubai += 1
                    print(f"  {out}: Dubai aerial tile (no ground truth)")
            except (OSError, ValueError) as exc:
                print(f"  skip {tile.name}: {exc}")

    TRUTH.write_text(json.dumps(truth, indent=1), encoding="utf-8")
    total_kb = sum(p.stat().st_size for p in FRAMES.iterdir() if p.is_file()) / 1024
    print(f"  {exported} VisDrone crops + {dubai} Dubai tiles, {total_kb:.0f} KB total")
    return {"visdrone_frames": exported, "dubai_frames": dubai, "kb": round(total_kb)}


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(yaml_path: Path, stats: dict) -> dict:
    import torch
    from ultralytics import YOLO

    # Ultralytics leaves torch at its default thread count, which on this box comes up
    # as 1 and makes CPU training roughly 6x slower than it needs to be.
    torch.set_num_threads(max(1, (os.cpu_count() or 4) - 2))
    print(f"  torch threads: {torch.get_num_threads()}")

    WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    base = ROOT / "yolov8n.pt"
    model = YOLO(str(base) if base.exists() else "yolov8n.pt")

    started = time.time()
    model.train(
        data=str(yaml_path),
        epochs=EPOCHS,
        imgsz=IMGSZ,
        batch=BATCH,
        device="cpu",
        workers=4,
        project=str(RUNS),
        name=RUN_NAME,
        exist_ok=True,
        patience=0,          # short budget: never early-stop, use every epoch
        cos_lr=True,
        close_mosaic=2,      # last 2 epochs see un-mosaicked frames like inference does
        val=True,
        plots=True,
        verbose=True,
        seed=SEED,
    )
    elapsed = time.time() - started

    run_dir = RUNS / RUN_NAME
    best = run_dir / "weights" / "best.pt"
    src = best if best.exists() else run_dir / "weights" / "last.pt"
    shutil.copy2(src, WEIGHTS)
    print(f"  saved {WEIGHTS}")

    # Re-validate the exported weights so the reported numbers describe the file the
    # backend actually loads, not whatever epoch happened to be in memory.
    final = YOLO(str(WEIGHTS)).val(
        data=str(yaml_path), imgsz=IMGSZ, batch=BATCH, device="cpu", workers=2, verbose=False
    )
    box = final.box
    metrics = {
        "model": "yolov8n-airspace",
        "epochs": EPOCHS,
        "images": stats["train_images"],
        "mAP50": round(float(box.map50), 4),
        "mAP50_95": round(float(box.map), 4),
        "precision": round(float(box.mp), 4),
        "recall": round(float(box.mr), 4),
        "imgsz": IMGSZ,
        "crop": CROP,
        "classes": NAMES,
        "per_class_mAP50": {
            NAMES[int(c)]: round(float(box.ap50[i]), 4)
            for i, c in enumerate(final.box.ap_class_index)
            if int(c) < len(NAMES)
        },
        "val_images": stats["val_images"],
        "train_boxes": stats["train_boxes"],
        "train_seconds": round(elapsed, 1),
        "dataset": "VisDrone2019-DET-train (native-resolution crops)",
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    METRICS.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print("=" * 72)
    print(f"  mAP50      {metrics['mAP50']:.4f}")
    print(f"  mAP50-95   {metrics['mAP50_95']:.4f}")
    print(f"  precision  {metrics['precision']:.4f}   recall {metrics['recall']:.4f}")
    print(f"  per class  {metrics['per_class_mAP50']}")
    print(f"  wall clock {elapsed / 60:.1f} min over {EPOCHS} epochs")
    print(f"  metrics -> {METRICS}")
    print("=" * 72)
    return metrics


def main() -> None:
    if "--frames-only" in sys.argv:
        export_frames()
        return
    yaml_path, stats = prepare()
    if "--prepare-only" in sys.argv:
        return
    metrics = train(yaml_path, stats)
    frames = export_frames()
    metrics["demo_frames"] = frames
    METRICS.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
