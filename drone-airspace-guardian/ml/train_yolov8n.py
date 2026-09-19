"""
Fine-tune YOLOv8n on native-resolution VisDrone2019-DET crops, mixed with AU-AIR boxes
on TRAIN only, so the ground-camera HUD detector sees both street-level and low-altitude
UAV viewpoints.

Dataset: VisDrone2019-DET (train/val) + AU-AIR (train mix + separate holdout).
Task: 6-class object detection (person, car, van, truck, bus, motor).
Why this model: YOLOv8n is the live detector already loaded by vision_bridge.py; we
continue from COCO or the existing airspace fine-tune, never from scratch.
What is NOT claimed: VisDrone is not Dubai and not drone-vs-drone. AU-AIR is Denmark
UAV footage. Val mAP50 stays VisDrone-only so it is comparable to the 0.2863 baseline.
AU-AIR holdout mAP50 is recorded separately and is never mixed into that number.

Who reads the artifact: backend/vision_bridge.py loads weights/yolov8n_airspace.pt;
the operator sees detections on GroundCamera. Metrics land in vision_metrics.json.

The demo loads shipped `weights/yolov8n_airspace.pt`. Do not run this script to start the console.

RUN (optional retrain only)
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
AUAIR_ROOT = Path(
    os.environ.get(
        "AUAIR_DIR",
        r"C:\Users\rohit\Downloads\Datasets\04_AUAIR_multimodal_uav",
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
AUAIR_HOLDOUT_YAML = DATA / "auair_holdout.yaml"

# --- training budget -------------------------------------------------------
CROP = int(os.environ.get("YOLO_CROP", 512))
IMGSZ = int(os.environ.get("YOLO_IMGSZ", CROP))
BATCH = int(os.environ.get("YOLO_BATCH", 8))
N_SRC_TRAIN = int(os.environ.get("YOLO_SRC_TRAIN", 1000))
N_SRC_VAL = int(os.environ.get("YOLO_SRC_VAL", 180))
CROPS_PER_TRAIN_IMAGE = 2
MIN_BOXES_PER_CROP = 4
SEED = 7
AUAIR_MIX_FRAC = float(os.environ.get("YOLO_AUAIR_FRAC", 0.20))  # of TRAIN crops
BASELINE_MAP50 = 0.2863


def _default_epochs() -> int:
    try:
        import torch

        return 20 if torch.cuda.is_available() else 12
    except Exception:
        return 12


EPOCHS = int(os.environ.get("YOLO_EPOCHS", _default_epochs()))

# --- label space -----------------------------------------------------------
# VisDrone category ids: 0 ignored-region, 1 pedestrian, 2 people, 3 bicycle,
# 4 car, 5 van, 6 truck, 7 tricycle, 8 awning-tricycle, 9 bus, 10 motor, 11 others.
NAMES = ["person", "car", "van", "truck", "bus", "motor"]
VISDRONE_TO_CLASS = {1: 0, 2: 0, 4: 1, 5: 2, 6: 3, 9: 4, 10: 5}
VEHICLE_CLASSES = {1, 2, 3, 4}  # car, van, truck, bus — preferred crop anchors

# AU-AIR categories: Human, Car, Truck, Van, Motorbike, Bicycle, Bus, Trailer
# Map: Human→person, Car→car, Van→van, Truck→truck, Bus→bus, Motorbike→motor.
# Drop Bicycle. Trailer optional → truck.
AUAIR_TO_CLASS = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 6: 4, 7: 3}


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


def _write_yaml(path: Path, train_rel: str, val_rel: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"path: {DATA.as_posix()}",
                f"train: {train_rel}",
                f"val: {val_rel}",
                "names:",
                *[f"  {i}: {n}" for i, n in enumerate(NAMES)],
                "",
            ]
        ),
        encoding="utf-8",
    )


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


def _auair_boxes(frame: dict, iw: int, ih: int) -> list[tuple[int, float, float, float, float]]:
    boxes: list[tuple[int, float, float, float, float]] = []
    for b in frame.get("bbox") or []:
        try:
            cat = int(b["class"])
        except (KeyError, TypeError, ValueError):
            continue
        if cat not in AUAIR_TO_CLASS:
            continue
        x1 = max(0.0, float(b["left"]))
        y1 = max(0.0, float(b["top"]))
        x2 = min(float(iw), x1 + float(b["width"]))
        y2 = min(float(ih), y1 + float(b["height"]))
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        boxes.append((AUAIR_TO_CLASS[cat], x1, y1, x2, y2))
    return boxes


def _crop_auair_frame(
    frame: dict,
    img_root: Path,
    out_img: Path,
    out_lbl: Path,
    prefix: str,
    rng: random.Random,
    min_boxes: int = 2,
) -> int:
    src = img_root / "images" / frame["image_name"]
    if not src.exists():
        return 0
    try:
        with Image.open(src) as im:
            iw, ih = im.size
            boxes = _auair_boxes(frame, iw, ih)
            if len(boxes) < min_boxes:
                return 0
            windows = pick_windows(boxes, iw, ih, CROP, 1, rng)
            if not windows:
                # AU-AIR frames can be sparse; accept a centred crop if native size allows.
                if iw < CROP or ih < CROP:
                    return 0
                x0 = max(0, (iw - CROP) // 2)
                y0 = max(0, (ih - CROP) // 2)
                inside = [
                    b
                    for b in boxes
                    if b[1] >= x0 and b[2] >= y0 and b[3] <= x0 + CROP and b[4] <= y0 + CROP
                ]
                windows = [(x0, y0, inside)] if len(inside) >= min_boxes else []
            if not windows:
                return 0
            rgb = im.convert("RGB")
            written = 0
            for k, (x0, y0, inside) in enumerate(windows):
                lines = to_yolo_lines(inside, x0, y0, CROP)
                if len(lines) < min_boxes:
                    continue
                name = f"{prefix}_{Path(frame['image_name']).stem}_c{k}"
                rgb.crop((x0, y0, x0 + CROP, y0 + CROP)).save(out_img / f"{name}.jpg", quality=88)
                (out_lbl / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
                written += 1
            return written
    except (OSError, ValueError) as exc:
        print(f"  skip AU-AIR {frame.get('image_name')}: {exc}")
        return 0


def mix_auair(visdrone_train_crops: int, rng: random.Random) -> dict:
    """
    Add AU-AIR native 512 crops into TRAIN only (~15-25% of train crops) and write a
    disjoint AU-AIR holdout split used later for a separate mAP50. Val stays VisDrone.
    """
    ann_path = AUAIR_ROOT / "annotations.json"
    if not ann_path.exists():
        raise SystemExit(f"AU-AIR annotations not found at {ann_path} (set AUAIR_DIR)")
    print("=" * 72)
    print("MIX AU-AIR INTO TRAIN (val remains VisDrone-only)")
    print("=" * 72)
    payload = json.loads(ann_path.read_text(encoding="utf-8"))
    frames = [f for f in payload.get("annotations") or [] if f.get("bbox")]
    if not frames:
        raise SystemExit(f"AU-AIR annotations at {ann_path} contain no boxes")
    rng.shuffle(frames)

    target_total_frac = min(0.25, max(0.15, AUAIR_MIX_FRAC))
    # A / (V + A) = f  =>  A = f/(1-f) * V
    want_train = max(80, int(round(visdrone_train_crops * target_total_frac / (1.0 - target_total_frac))))
    want_hold = max(40, min(120, want_train // 4))

    train_img = DATA / "images" / "train"
    train_lbl = DATA / "labels" / "train"
    hold_img = DATA / "images" / "auair_holdout"
    hold_lbl = DATA / "labels" / "auair_holdout"
    hold_img.mkdir(parents=True, exist_ok=True)
    hold_lbl.mkdir(parents=True, exist_ok=True)

    train_crops = 0
    hold_crops = 0
    train_used: set[str] = set()
    # Stride through the shuffled list so neighbouring video frames are not all taken.
    for i, frame in enumerate(frames):
        if i % 12 != 0:
            continue
        name = frame.get("image_name") or ""
        if train_crops < want_train:
            n = _crop_auair_frame(frame, AUAIR_ROOT, train_img, train_lbl, "auair", rng)
            if n:
                train_crops += n
                train_used.add(name)
        elif hold_crops < want_hold and name not in train_used:
            n = _crop_auair_frame(frame, AUAIR_ROOT, hold_img, hold_lbl, "hold", rng)
            if n:
                hold_crops += n
        if train_crops >= want_train and hold_crops >= want_hold:
            break

    mix_frac = train_crops / max(1, visdrone_train_crops + train_crops)
    print(
        f"  AU-AIR train mix: {train_crops} crops "
        f"({mix_frac:.1%} of train), holdout {hold_crops} crops"
    )
    if train_crops < 20:
        raise SystemExit(f"AU-AIR mix produced too few train crops ({train_crops})")
    if hold_crops >= 10:
        _write_yaml(AUAIR_HOLDOUT_YAML, "images/train", "images/auair_holdout")
    return {
        "auair_train_crops": train_crops,
        "auair_holdout_crops": hold_crops,
        "auair_mix_frac": round(mix_frac, 4),
    }


def prepare() -> tuple[Path, dict]:
    """Rebuild yolo_data/ from scratch and write data.yaml."""
    print("=" * 72)
    print(f"PREPARE VISDRONE CROPS  ({CROP}x{CROP}, native resolution)")
    print("=" * 72)
    if not TRAIN_SRC.exists():
        raise SystemExit(f"VisDrone train split not found at {TRAIN_SRC} (set VISDRONE_DIR)")
    if DATA.exists():
        shutil.rmtree(DATA)
    rng = random.Random(SEED)
    tr_crops, tr_objs = build_split(TRAIN_SRC, "train", N_SRC_TRAIN, CROPS_PER_TRAIN_IMAGE, rng)
    va_crops, va_objs = build_split(VAL_SRC, "val", N_SRC_VAL, 1, rng)
    if tr_crops < 50 or va_crops < 10:
        raise SystemExit(f"Too few crops produced (train={tr_crops}, val={va_crops})")

    au = mix_auair(tr_crops, rng)
    yaml_path = DATA / "data.yaml"
    _write_yaml(yaml_path, "images/train", "images/val")
    stats = {
        "train_images": tr_crops + au["auair_train_crops"],
        "visdrone_train_images": tr_crops,
        "val_images": va_crops,
        "train_boxes": tr_objs,
        "val_boxes": va_objs,
        **au,
    }
    print(f"  data.yaml -> {yaml_path}")
    return yaml_path, stats


# ---------------------------------------------------------------------------
# Demo frame rotation for the camera panel
# ---------------------------------------------------------------------------

def export_frames(n_visdrone: int = 24, n_dubai: int = 0) -> dict:
    """
    Fill vision_frames/ with dense VisDrone crops from val and/or test-dev (unseen
    test-dev preferred). truth.json carries ground-truth boxes for the overlay.

    These stills feed GM-5 and GM-6 on the live console (see backend/ground.py).
    """
    print("=" * 72)
    print("EXPORT DEMO FRAMES")
    print("=" * 72)
    FRAMES.mkdir(parents=True, exist_ok=True)
    for old in FRAMES.iterdir():
        if old.is_file():
            old.unlink()

    rng = random.Random(SEED + 1)
    sources: list[Path] = []
    if DEMO_SRC.exists():
        sources.append(DEMO_SRC)
    if VAL_SRC.exists():
        sources.append(VAL_SRC)

    truth: dict[str, list[dict]] = {}
    exported = 0
    for src in sources:
        if exported >= n_visdrone:
            break
        ann_dir = src / "annotations"
        images = sorted((src / "images").glob("*.jpg"))
        rng.shuffle(images)
        for src_img in images:
            if exported >= n_visdrone:
                break
            try:
                with Image.open(src_img) as im:
                    iw, ih = im.size
                    boxes = read_boxes(ann_dir / f"{src_img.stem}.txt", iw, ih)
                    vehicles = sum(1 for b in boxes if b[0] in VEHICLE_CLASSES)
                    if vehicles < 8:
                        continue
                    windows = pick_windows(boxes, iw, ih, CROP, 1, rng)
                    if not windows:
                        continue
                    x0, y0, inside = windows[0]
                    if sum(1 for b in inside if b[0] in VEHICLE_CLASSES) < 5:
                        continue
                    name = f"visdrone-{src_img.stem[:14]}-{x0}-{y0}.jpg"
                    if (FRAMES / name).exists():
                        continue
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
    if n_dubai > 0 and DUBAI_TILES.exists():
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

def _box_metrics(final) -> dict:
    box = final.box
    return {
        "mAP50": round(float(box.map50), 4),
        "mAP50_95": round(float(box.map), 4),
        "precision": round(float(box.mp), 4),
        "recall": round(float(box.mr), 4),
        "per_class_mAP50": {
            NAMES[int(c)]: round(float(box.ap50[i]), 4)
            for i, c in enumerate(final.box.ap_class_index)
            if int(c) < len(NAMES)
        },
    }


def train(yaml_path: Path, stats: dict) -> dict:
    import torch
    from ultralytics import YOLO

    cuda = torch.cuda.is_available()
    device = "0" if cuda else "cpu"
    if not cuda:
        torch.set_num_threads(max(1, (os.cpu_count() or 4) - 2))
    print(f"  device: {device}   torch threads: {torch.get_num_threads()}   epochs: {EPOCHS}")

    WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    existing = WEIGHTS if WEIGHTS.exists() else None
    coco = ROOT / "yolov8n.pt"
    if existing is not None:
        base = existing
        print(f"  starting from existing fine-tune {base.name}")
    elif coco.exists():
        base = coco
        print(f"  starting from {base.name}")
    else:
        base = "yolov8n.pt"
        print("  starting from ultralytics yolov8n.pt (download if needed)")
    model = YOLO(str(base))

    started = time.time()
    model.train(
        data=str(yaml_path),
        epochs=EPOCHS,
        imgsz=IMGSZ,
        batch=BATCH,
        device=device,
        workers=2 if device == "cpu" else 4,
        project=str(RUNS),
        name=RUN_NAME,
        exist_ok=True,
        patience=4,
        cos_lr=True,
        close_mosaic=2,
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
    exported = YOLO(str(WEIGHTS))
    final = exported.val(
        data=str(yaml_path), imgsz=IMGSZ, batch=BATCH, device=device, workers=2, verbose=False
    )
    visdrone = _box_metrics(final)

    auair_hold = None
    if AUAIR_HOLDOUT_YAML.exists() and (DATA / "images" / "auair_holdout").exists():
        n_hold = len(list((DATA / "images" / "auair_holdout").glob("*.jpg")))
        if n_hold >= 10:
            hold = exported.val(
                data=str(AUAIR_HOLDOUT_YAML),
                imgsz=IMGSZ,
                batch=BATCH,
                device=device,
                workers=2,
                verbose=False,
            )
            auair_hold = _box_metrics(hold)
            print(f"  AU-AIR holdout mAP50 {auair_hold['mAP50']:.4f} on {n_hold} crops")

    metrics = {
        "model": "yolov8n-airspace",
        "epochs": EPOCHS,
        "images": stats["train_images"],
        "mAP50": visdrone["mAP50"],
        "mAP50_95": visdrone["mAP50_95"],
        "precision": visdrone["precision"],
        "recall": visdrone["recall"],
        "imgsz": IMGSZ,
        "crop": CROP,
        "classes": NAMES,
        "per_class_mAP50": visdrone["per_class_mAP50"],
        "val_images": stats["val_images"],
        "train_boxes": stats["train_boxes"],
        "train_seconds": round(elapsed, 1),
        "dataset": "VisDrone2019-DET-train native 512 crops + AU-AIR train mix; val is VisDrone-only",
        "visdrone_train_images": stats.get("visdrone_train_images"),
        "auair_train_crops": stats.get("auair_train_crops"),
        "auair_mix_frac": stats.get("auair_mix_frac"),
        "auair_holdout_crops": stats.get("auair_holdout_crops"),
        "auair_holdout_mAP50": None if auair_hold is None else auair_hold["mAP50"],
        "auair_holdout": auair_hold,
        "baseline_mAP50": BASELINE_MAP50,
        "beat_baseline": visdrone["mAP50"] > BASELINE_MAP50,
        "device": device,
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    METRICS.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print("=" * 72)
    print(f"  VisDrone val mAP50  {metrics['mAP50']:.4f}  (baseline {BASELINE_MAP50})")
    print(f"  mAP50-95            {metrics['mAP50_95']:.4f}")
    print(f"  precision           {metrics['precision']:.4f}   recall {metrics['recall']:.4f}")
    print(f"  per class           {metrics['per_class_mAP50']}")
    if auair_hold is not None:
        print(f"  AU-AIR holdout      {auair_hold['mAP50']:.4f}")
    print(f"  wall clock          {elapsed / 60:.1f} min over {EPOCHS} epochs")
    print(f"  metrics -> {METRICS}")
    print("=" * 72)
    if metrics["mAP50"] <= BASELINE_MAP50:
        print(
            f"ACCEPT FAIL: VisDrone val mAP50 {metrics['mAP50']} did not beat {BASELINE_MAP50}. "
            "Exactly one retry is allowed (more VisDrone source or +4 epochs)."
        )
    return metrics


def main() -> None:
    if "--frames-only" in sys.argv:
        export_frames()
        return
    yaml_path, stats = prepare()
    if "--prepare-only" in sys.argv:
        return
    metrics = train(yaml_path, stats)
    if "--skip-frames" in sys.argv:
        return
    frames = export_frames()
    metrics["demo_frames"] = frames
    METRICS.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
