"""
Pack the 72 Dubai aerial segmentation tiles + masks into a fitted ground-cost overlay.

Dataset: Humans-in-the-Loop / MBRSC Dubai aerial semantic segmentation (72 RGB tiles
and matching masks: Water, Land, Road, Building, Vegetation, Unlabeled).
Task: stitch the tiles, fit them affinely into dubai_airspace.json bounds, write a
soft per-metre cost grid for the 150 m planner and a PNG the Leaflet map can show.
Why this method: the masks are labeled but NOT surveyed-georeferenced. We do not
train a segmenter; we use the existing labels and document the fit as a demo overlay.
What is NOT claimed: this is not a certified cadastral georeference. Soft cost only —
never inf, never hard_static, never a replacement for OSM restricted cores.

Who reads the artifact: backend/risk_map.py (np.maximum into ground_static) and
frontend AirspaceMap (Leaflet imageOverlay at ~0.35 opacity).

Run: python build_ground_cost.py
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
AIRSPACE = HERE / "dubai_airspace.json"
OUT_JSON = HERE / "dubai_ground_cost.json"
OUT_MOSAIC = HERE / "dubai_mosaic.png"
OVERLAY_PNG = HERE.parent / "frontend" / "public" / "dubai" / "ground-cost.png"
DEFAULT_TILES = Path(r"C:\Users\rohit\Downloads\Datasets\02_Dubai_aerial_segmentation")
CELL_M = 150.0

# Pixel colours actually present in masks/ (Humans-in-the-Loop Dubai set).
# classes.json hex values are Supervisely UI colours and do not match the PNGs.
MASK_TO_CLASS = {
    (60, 16, 152): "Building",  # #3C1098
    (132, 41, 246): "Land",  # #8429F6  (unpaved)
    (110, 193, 228): "Road",  # #6EC1E4
    (254, 221, 58): "Vegetation",  # #FEDD3A
    (226, 169, 41): "Water",  # #E2A929
    (155, 155, 155): "Unlabeled",  # #9B9B9B
    (0, 0, 0): "Unlabeled",
}

# Extra per-metre cost. NEVER inf. Water is 0 so we do not fight the OSM water layer.
CLASS_COST = {
    "Water": 0.0,
    "Vegetation": 0.1,
    "Land": 0.4,
    "Road": 5.0,
    "Building": 10.0,
    "Unlabeled": 0.0,
}

# Overlay colours (classes.json), easier to read on Esri imagery than the mask palette.
CLASS_DISPLAY = {
    "Water": (80, 227, 194),
    "Land": (245, 166, 35),
    "Road": (222, 89, 127),
    "Building": (208, 2, 27),
    "Vegetation": (65, 117, 5),
    "Unlabeled": (155, 155, 155),
}


def _nearest_class(rgb: np.ndarray) -> np.ndarray:
    """Map an (H,W,3) mask to class-id 0..5 by nearest of the known palette."""
    names = ["Water", "Land", "Road", "Building", "Vegetation", "Unlabeled"]
    palette = np.array(list(MASK_TO_CLASS.keys()), dtype=np.int16)
    labels = [MASK_TO_CLASS[tuple(c)] for c in MASK_TO_CLASS]
    palette_ids = np.array([names.index(lab) for lab in labels], dtype=np.uint8)
    pix = rgb.reshape(-1, 3).astype(np.int16)
    d = np.abs(pix[:, None, :] - palette[None, :, :]).sum(axis=2)
    idx = d.argmin(axis=1)
    return palette_ids[idx].reshape(rgb.shape[:2])


def _pack(images: list[Path], masks: list[Path]) -> tuple[Image.Image, np.ndarray, list[str], list[str]]:
    used, skipped = [], []
    cells: list[tuple[Image.Image, np.ndarray]] = []
    for img_path, mask_path in zip(images, masks):
        if not img_path.exists() or not mask_path.exists():
            skipped.append(img_path.name)
            continue
        try:
            rgb = Image.open(img_path).convert("RGB")
            m = np.array(Image.open(mask_path).convert("RGB"))
            if m.shape[0] != rgb.size[1] or m.shape[1] != rgb.size[0]:
                m = np.array(Image.open(mask_path).convert("RGB").resize(rgb.size, Image.NEAREST))
            cells.append((rgb, _nearest_class(m)))
            used.append(img_path.name)
        except (OSError, ValueError) as exc:
            print(f"  skip {img_path.name}: {exc}")
            skipped.append(img_path.name)

    if not cells:
        return Image.new("RGB", (1, 1), (0, 0, 0)), np.zeros((1, 1), dtype=np.uint8), used, skipped

    cell_w = max(im.size[0] for im, _ in cells)
    cell_h = max(im.size[1] for im, _ in cells)
    cols = 8
    rows = int(math.ceil(len(cells) / cols))
    mosaic = Image.new("RGB", (cols * cell_w, rows * cell_h), (20, 24, 32))
    class_map = np.full((rows * cell_h, cols * cell_w), 5, dtype=np.uint8)  # Unlabeled
    for i, (im, cls) in enumerate(cells):
        r, c = divmod(i, cols)
        x, y = c * cell_w, r * cell_h
        mosaic.paste(im, (x, y))
        class_map[y : y + cls.shape[0], x : x + cls.shape[1]] = cls
    return mosaic, class_map, used, skipped


def _overlay_from_classes(class_map: np.ndarray, max_w: int = 1280) -> Image.Image:
    names = ["Water", "Land", "Road", "Building", "Vegetation", "Unlabeled"]
    lut = np.array([CLASS_DISPLAY[n] for n in names], dtype=np.uint8)
    rgb = lut[np.clip(class_map, 0, 5)]
    im = Image.fromarray(rgb, mode="RGB")
    if im.width > max_w:
        h = int(round(im.height * max_w / im.width))
        im = im.resize((max_w, h), Image.NEAREST)
    return im


def main() -> None:
    root = Path(os.environ.get("DUBAI_TILES", DEFAULT_TILES))
    img_dir, mask_dir = root / "images", root / "masks"
    if not AIRSPACE.exists():
        raise SystemExit(f"dubai_airspace.json missing at {AIRSPACE}")
    images = sorted(img_dir.glob("tile_*.png"))
    masks = [mask_dir / p.name for p in images]
    print(f"packing {len(images)} tiles from {root}")
    mosaic, class_map, used, skipped = _pack(images, masks)

    airspace = json.loads(AIRSPACE.read_text(encoding="utf-8"))
    bounds = airspace["bounds"]
    south, west, north, east = bounds["south"], bounds["west"], bounds["north"], bounds["east"]
    applied = len(used) > 0

    # Affine: mosaic pixel (0,0) top-left -> (north, west); (W,H) -> (south, east).
    # Fitted into the operating box. NOT a certified survey georeference.
    mh, mw = class_map.shape
    lat0 = (south + north) / 2.0
    lon0 = (west + east) / 2.0
    m_lat = 110_574.0
    m_lon = 111_320.0 * math.cos(math.radians(lat0))
    x_min = (west - lon0) * m_lon
    y_min = (south - lat0) * m_lat
    x_max = (east - lon0) * m_lon
    y_max = (north - lat0) * m_lat
    cols = int(math.ceil((x_max - x_min) / CELL_M))
    rows = int(math.ceil((y_max - y_min) / CELL_M))
    xc = x_min + (np.arange(cols) + 0.5) * CELL_M
    yc = y_min + (np.arange(rows) + 0.5) * CELL_M
    X, Y = np.meshgrid(xc, yc)
    lon = lon0 + X / m_lon
    lat = lat0 + Y / m_lat
    px = np.clip(((lon - west) / max(east - west, 1e-9) * mw).astype(int), 0, mw - 1)
    py = np.clip(((north - lat) / max(north - south, 1e-9) * mh).astype(int), 0, mh - 1)
    names = ["Water", "Land", "Road", "Building", "Vegetation", "Unlabeled"]
    cost_lut = np.array([CLASS_COST[n] for n in names], dtype=np.float32)
    if applied:
        extra = cost_lut[class_map[py, px]]
    else:
        extra = np.zeros((rows, cols), dtype=np.float32)

    if np.isinf(extra).any():
        raise SystemExit("ground-cost grid contained inf; refusing to write")

    OVERLAY_PNG.parent.mkdir(parents=True, exist_ok=True)
    if applied:
        mosaic.save(OUT_MOSAIC, optimize=True)
        overlay = _overlay_from_classes(class_map)
        overlay.save(OVERLAY_PNG, optimize=True)
        print(f"  mosaic {mosaic.size} -> {OUT_MOSAIC.name}")
        print(f"  overlay {overlay.size} -> {OVERLAY_PNG}")

    doc = {
        "applied": applied,
        "georeference": (
            "Fitted affine of the 72-tile mosaic into dubai_airspace.json bounds "
            "(pixel (0,0)=north-west). NOT a certified survey georeference."
        ),
        "bounds": bounds,
        "mosaic_px": [int(mw), int(mh)],
        "cell_m": CELL_M,
        "grid": {"rows": rows, "cols": cols, "x0": x_min, "y0": y_min},
        "class_cost": CLASS_COST,
        "class_names": names,
        "overlay_png": "/dubai/ground-cost.png",
        "opacity": 0.35,
        "tiles_used": len(used),
        "tiles_skipped": skipped,
        "never_inf": True,
        "hard_static_untouched": True,
        "cost_grid": extra.round(2).tolist(),
    }
    OUT_JSON.write_text(json.dumps(doc), encoding="utf-8")
    print(
        f"wrote {OUT_JSON.name}: applied={applied}, tiles={len(used)}/{len(used)+len(skipped)}, "
        f"grid {rows}x{cols}, {OUT_JSON.stat().st_size / 1024:.0f} KB"
    )


if __name__ == "__main__":
    main()
