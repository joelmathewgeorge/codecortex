"""
Pack prepared YOLO crops + checkpoints for an optional Colab GPU train.

The live demo does not need this. Run only if someone later wants more YOLO epochs.
Do not train here.

    cd ml
    venv\\Scripts\\python.exe pack_colab_bundle.py

Output (gitignored):
    ml/colab_bundle/          unpacked copy with portable yaml paths
    ml/colab_bundle.zip       upload this to Drive as airspace-yolo/colab_bundle.zip

The Colab notebook unzips the zip onto local SSD and writes checkpoints to Drive.
Does not touch weights/yolov8n_airspace.pt or start training.
"""

from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "yolo_data"
RUN_WEIGHTS = ROOT / "runs" / "yolov8n_airspace" / "weights"
SHIPPED = ROOT / "weights" / "yolov8n_airspace.pt"
OUT_DIR = ROOT / "colab_bundle"
OUT_ZIP = ROOT / "colab_bundle.zip"

NAMES = ["person", "car", "van", "truck", "bus", "motor"]


def _write_yaml(path: Path, data_root: str, train_rel: str, val_rel: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"path: {data_root}",
                f"train: {train_rel}",
                f"val: {val_rel}",
                "names:",
                *[f"  {i}: {n}" for i, n in enumerate(NAMES)],
                "",
            ]
        ),
        encoding="utf-8",
    )


def _count(folder: Path, pattern: str) -> int:
    return len(list(folder.glob(pattern))) if folder.exists() else 0


def main() -> None:
    if not DATA.exists():
        raise SystemExit(
            f"Prepared dataset missing at {DATA}. Run train_yolov8n.py --prepare-only first."
        )
    train_n = _count(DATA / "images" / "train", "*.jpg")
    val_n = _count(DATA / "images" / "val", "*.jpg")
    hold_n = _count(DATA / "images" / "auair_holdout", "*.jpg")
    if train_n < 50 or val_n < 10:
        raise SystemExit(f"Too few crops (train={train_n}, val={val_n}) under {DATA}")

    last_pt = RUN_WEIGHTS / "last.pt"
    best_pt = RUN_WEIGHTS / "best.pt"
    if not last_pt.exists() and not SHIPPED.exists():
        raise SystemExit("No last.pt and no shipped yolov8n_airspace.pt — nothing to resume from.")

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    dest_data = OUT_DIR / "yolo_data"
    dest_ckpt = OUT_DIR / "checkpoints"
    dest_data.mkdir(parents=True)
    dest_ckpt.mkdir(parents=True)

    print("=" * 72)
    print("PACK COLAB BUNDLE")
    print("=" * 72)

    def _ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n.endswith(".cache")}

    shutil.copytree(DATA / "images", dest_data / "images", ignore=_ignore)
    shutil.copytree(DATA / "labels", dest_data / "labels", ignore=_ignore)
    # Portable placeholder; the Colab notebook rewrites this to the Drive mount.
    _write_yaml(dest_data / "data.yaml", "yolo_data", "images/train", "images/val")
    if hold_n:
        _write_yaml(
            dest_data / "auair_holdout.yaml",
            "yolo_data",
            "images/train",
            "images/auair_holdout",
        )

    copied = []
    for src, name in (
        (last_pt, "last.pt"),
        (best_pt, "best.pt"),
        (SHIPPED, "yolov8n_airspace.pt"),
    ):
        if src.exists():
            shutil.copy2(src, dest_ckpt / name)
            copied.append(f"{name} ({src.stat().st_size / 1e6:.1f} MB)")
            print(f"  checkpoint {name} <- {src}")
        else:
            print(f"  skip missing {src}")

    manifest = {
        "packed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "classes": NAMES,
        "crop": 512,
        "imgsz": 512,
        "train_images": train_n,
        "val_images": val_n,
        "auair_holdout_images": hold_n,
        "checkpoints": copied,
        "source_run": "runs/yolov8n_airspace",
        "source_run_epochs_completed": 4,
        "source_run_target_epochs": 12,
        "source_run_device": "cpu",
        "ultralytics": "8.4.155",
        "notebook": "colab_continue_train.ipynb",
        "default_mode": "train",
        "default_start_from": "auto",
        "default_epochs": 50,
        "in_run_mAP50": {"1": 0.2711, "2": 0.24523, "3": 0.27937, "4": 0.27786},
        "in_run_mAP50_95": {"1": 0.13729, "2": 0.12999, "3": 0.14938, "4": 0.14973},
        "shipped_mAP50": 0.2863,
        "note": (
            "Full Colab GPU train (50 epochs), not leftover CPU 12-epoch cleanup. "
            "Default START_FROM=auto uses last.pt if present else yolov8n.pt. "
            "MODE=resume is only for an interrupted Colab run on Drive. "
            "Keep the zip on Drive; the notebook unzips to /content/airspace and "
            "skips if that local tree already exists."
        ),
        "drive_layout": [
            "MyDrive/airspace-yolo/colab_bundle.zip",
            "MyDrive/airspace-yolo/checkpoints/   (copied by notebook)",
            "MyDrive/airspace-yolo/runs/          (created by Colab)",
            "MyDrive/airspace-yolo/exports/       (created by Colab)",
        ],
    }
    (OUT_DIR / "BUNDLE.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"  dataset train={train_n}  val={val_n}  auair_holdout={hold_n}")
    print(f"  writing {OUT_ZIP} ...")
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in OUT_DIR.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(OUT_DIR).as_posix())
    print(f"  zip {OUT_ZIP.stat().st_size / 1e6:.1f} MB")
    print()
    print("Upload to Google Drive as:")
    print("  My Drive / airspace-yolo / colab_bundle.zip")
    print("Open ml/colab_continue_train.ipynb in Colab → GPU → Run all.")
    print("Do not unzip the zip in Drive's UI.")
    print("=" * 72)


if __name__ == "__main__":
    main()
