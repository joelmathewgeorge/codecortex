"""
Turn AU-AIR session GPS into Dubai-anchored drone mission waypoints.

Dataset: AU-AIR annotations.json GPS/altitude (Denmark).
Task: relative ENU from each session's first fix, downsample, rescale altitude
into the 40-150 m band, re-anchor at a Dubai drone port from dubai_airspace.json.
Why this method: raw AU-AIR lat/lon is Denmark and must never be plotted on the
Dubai Leaflet map. Waypoints only — no images — so this JSON is safe to commit.
What is NOT claimed: these are not real Dubai BVLOS flights; they are AU-AIR
tracks transplanted onto Dubai ports for the sim.

Who reads the artifact: backend/sim.py (2-3 SEED_FLEET drones fly these as
Motion/Route). The operator sees those drones following the re-anchored path.

Run: python export_auair_missions.py
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
AIRSPACE = HERE / "dubai_airspace.json"
OUT = HERE / "auair_missions.json"
DEFAULT_DIR = Path(r"C:\Users\rohit\Downloads\Datasets\04_AUAIR_multimodal_uav")
MAX_SESSIONS = 8
STEP_M = 80.0
MIN_SPAN_M = 3500.0
MAX_SPAN_M = 9000.0
ALT_LO, ALT_HI = 40.0, 150.0


def _session_id(image_name: str) -> str:
    return image_name[:20]


class Enu:
    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0, self.lon0 = lat0, lon0
        self.m_lat = 110_574.0
        self.m_lon = 111_320.0 * math.cos(math.radians(lat0))

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.m_lon, (lat - self.lat0) * self.m_lat

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        return self.lat0 + y / self.m_lat, self.lon0 + x / self.m_lon


def _downsample(xs: list[float], ys: list[float], alts: list[float], step_m: float):
    out = [(xs[0], ys[0], alts[0])]
    acc = 0.0
    for i in range(1, len(xs)):
        acc += math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1])
        if acc >= step_m:
            out.append((xs[i], ys[i], alts[i]))
            acc = 0.0
    if out[-1][:2] != (xs[-1], ys[-1]):
        out.append((xs[-1], ys[-1], alts[-1]))
    return out


def _rescale_alt(alts: list[float]) -> list[float]:
    lo, hi = min(alts), max(alts)
    if hi - lo < 1.0:
        return [80.0 for _ in alts]
    return [ALT_LO + (a - lo) / (hi - lo) * (ALT_HI - ALT_LO) for a in alts]


def main() -> None:
    root = Path(os.environ.get("AUAIR_DIR", DEFAULT_DIR))
    ann_path = root / "annotations.json"
    if not ann_path.exists():
        raise SystemExit(f"AU-AIR annotations not found at {ann_path} (set AUAIR_DIR)")
    if not AIRSPACE.exists():
        raise SystemExit(f"dubai_airspace.json missing at {AIRSPACE}")

    airspace = json.loads(AIRSPACE.read_text(encoding="utf-8"))
    ports = airspace["drone_ports"]
    bounds = airspace["bounds"]
    annotations = json.loads(ann_path.read_text(encoding="utf-8"))["annotations"]
    sequences: dict[str, list[dict]] = defaultdict(list)
    for frame in annotations:
        sequences[_session_id(frame["image_name"])].append(frame)
    for frames in sequences.values():
        frames.sort(key=lambda f: f["image_name"])

    sessions = sorted(sequences.items(), key=lambda kv: -len(kv[1]))[:MAX_SESSIONS]
    missions = []
    for i, (seq_id, frames) in enumerate(sessions):
        # AU-AIR GPS barely moves (hover boxes of 6-80 m). Sample by frame first,
        # convert to ENU, THEN scale into a Dubai-legible span, THEN downsample.
        stride = max(1, len(frames) // 80)
        sampled = frames[::stride]
        lats = [float(f["latitude"]) for f in sampled]
        lons = [float(f["longtitude"]) for f in sampled]
        alts = [float(f["altitude"]) / 1000.0 for f in sampled]
        if len(lats) < 8:
            print(f"  skip {seq_id}: too few GPS fixes ({len(lats)})")
            continue
        origin = Enu(lats[0], lons[0])
        xs, ys = zip(*(origin.to_xy(la, lo) for la, lo in zip(lats, lons)))
        xs, ys = list(xs), list(ys)
        span = max(math.hypot(x, y) for x, y in zip(xs, ys)) or 1.0
        scale = 1.0
        if span < MIN_SPAN_M:
            scale = MIN_SPAN_M / span
        elif span > MAX_SPAN_M:
            scale = MAX_SPAN_M / span
        xs = [x * scale for x in xs]
        ys = [y * scale for y in ys]
        pts = _downsample(xs, ys, alts, STEP_M)
        if len(pts) < 4:
            step = max(1, len(xs) // 24)
            pts = list(zip(xs[::step], ys[::step], alts[::step]))
        alts_scaled = _rescale_alt([p[2] for p in pts])
        port = ports[i % len(ports)]
        dubai = Enu(port["lat"], port["lon"])
        waypoints = []
        for (x, y, _), alt in zip(pts, alts_scaled):
            lat, lon = dubai.to_latlon(x, y)
            lat = min(max(lat, bounds["south"] + 0.01), bounds["north"] - 0.01)
            lon = min(max(lon, bounds["west"] + 0.01), bounds["east"] - 0.01)
            waypoints.append(
                {"lat": round(lat, 6), "lon": round(lon, 6), "alt_m": round(alt, 1)}
            )
        if len(waypoints) < 4:
            print(f"  skip {seq_id}: only {len(waypoints)} waypoints after re-anchor")
            continue
        missions.append(
            {
                "id": f"auair-{i + 1}",
                "session": seq_id,
                "n_source_frames": len(frames),
                "port_id": port.get("id") or f"port-{i + 1}",
                "port_name": port["name"],
                "anchor_lat": port["lat"],
                "anchor_lon": port["lon"],
                "scale": round(scale, 4),
                "source_span_m": round(span, 1),
                "waypoints": waypoints,
            }
        )
        print(
            f"  {missions[-1]['id']}: {seq_id} -> {port['name']} "
            f"{len(waypoints)} wpts, scale {scale:.2f}, span {span:.0f} m"
        )

    doc = {
        "source": "AU-AIR multimodal UAV GPS (Bozcan & Kayacan, 2020), waypoints only",
        "georeference": (
            "Relative ENU from each session's first GPS fix, rescaled, then re-anchored "
            "at a Dubai drone port from dubai_airspace.json. Fitted demo tracks, NOT a "
            "certified survey. Raw AU-AIR lat/lon is Denmark and is not plotted."
        ),
        "altitude_band_m": [ALT_LO, ALT_HI],
        "step_m": STEP_M,
        "missions": missions,
    }
    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"wrote {OUT.name}: {len(missions)} missions, {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
