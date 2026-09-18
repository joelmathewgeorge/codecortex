"""
Ground Risk Monitor: aerial cameras over busy Dubai roads, scored by YOLOv8n.

Each monitor site sits on a real road (snapped to OSM motorway/trunk geometry) and replays
one window of AU-AIR low-altitude traffic footage (ml/auair_frames, exported by
ml/export_auair_frames.py). Every couple of seconds one site's next frame goes through the
detector; the vehicle and pedestrian count sets that site's ground-risk level:

    LOW  < 6  <=  MEDIUM  < 14  <=  HIGH  < 22  <=  VERY HIGH      (vehicles + 2 x people)

smoothed and with hysteresis so one busy frame does not flap the map. The level becomes a
per-metre cost on the risk map within the site radius, and a rise to HIGH or above sends
drones whose route crosses that stretch back through the planner.

Without YOLO the dataset's own labels are counted instead; without exported frames the
sites keep a fixed MEDIUM level and the camera feed is empty.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from config import AUAIR_DIR, GROUND_COST, ML_DIR

VEHICLES = {"car", "van", "truck", "bus", "motor", "motorcycle", "motorbike", "bicycle", "trailer", "tricycle", "awning-tricycle"}
PEOPLE = {"person", "pedestrian", "people", "human"}
# Set against the fine-tuned detector on the exported windows: busy roads sit around 10-15.
THRESHOLDS = (("VERY HIGH", 22.0), ("HIGH", 14.0), ("MEDIUM", 6.0), ("LOW", 0.0))
ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "VERY HIGH": 3}
SITE_RADIUS_M = 700.0

# (id, name, approximate lat/lon, road ref to snap onto), busiest first.
SITES = [
    ("GM-1", "Sheikh Zayed Rd at Trade Centre", (25.2170, 55.2800), "E11"),
    ("GM-2", "Sheikh Zayed Rd at Al Barsha", (25.1180, 55.2020), "E11"),
    ("GM-3", "Al Khail Rd at Al Quoz", (25.1560, 55.2450), "E44"),
    ("GM-4", "Al Ittihad Rd in Deira", (25.2620, 55.3330), "E11"),
    ("GM-5", "Al Khail Rd at Business Bay", (25.1840, 55.2800), "E44"),
    ("GM-6", "Al Sufouh Rd at Dubai Marina", (25.0900, 55.1450), None),
]


@dataclass
class Site:
    id: str
    name: str
    road: str
    lat: float
    lon: float
    x: float
    y: float
    radius: float
    frames: list[dict]
    media: str
    dataset: str
    idx: int = 0
    score: float | None = None
    level: str = "MEDIUM"
    counts: dict = field(default_factory=dict)
    detections: list = field(default_factory=list)
    frame: dict | None = None
    scored_by: str = ""
    updated_at: float = -1.0

    def to_dict(self) -> dict:
        f = self.frame or {}
        return {
            "id": self.id,
            "name": self.name,
            "road": self.road,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "radius": self.radius,
            "level": self.level,
            "score": round(self.score, 1) if self.score is not None else None,
            "counts": self.counts,
            "cost": GROUND_COST.get(self.level, 0.0),
            "image": f"{self.media}/{f['file']}" if f else None,
            "frame": f.get("source"),
            "width": f.get("width"),
            "height": f.get("height"),
            "truth": f.get("boxes", []),
            "detections": self.detections,
            "telemetry": {"gps": f.get("gps"), "velocity": f.get("velocity"), "time": f.get("time")} if f.get("gps") else None,
            "scoredBy": self.scored_by,
            "dataset": self.dataset,
            "updatedAt": round(self.updated_at, 1),
        }


def _load_frame_sets() -> tuple[list[list[dict]], str, str]:
    index = AUAIR_DIR / "index.json"
    if index.exists():
        data = json.loads(index.read_text(encoding="utf-8"))
        sets = sorted(data["sets"], key=lambda s: -s["mean_boxes"])
        for s in sets:
            for f in s["frames"]:
                f["width"], f["height"] = data["width"], data["height"]
                for b in f["boxes"]:
                    b["label"] = {"Human": "person", "Motorbike": "motor"}.get(b["label"], b["label"].lower())
        return [s["frames"] for s in sets], "/media/auair", "AU-AIR"
    visdrone = ML_DIR / "vision_frames"
    truth_file = visdrone / "truth.json"
    if visdrone.exists():
        truth = json.loads(truth_file.read_text(encoding="utf-8")) if truth_file.exists() else {}
        frames = []
        for p in sorted(visdrone.glob("visdrone-*.jpg")):
            try:
                from PIL import Image

                with Image.open(p) as im:
                    w, h = im.size
            except Exception:
                w, h = 0, 0
            frames.append({"file": p.name, "source": p.name, "boxes": truth.get(p.name, []), "width": w, "height": h})
        if frames:
            return [frames], "/media/visdrone", "VisDrone"
    return [], "", ""


class GroundMonitor:
    def __init__(self, world, events) -> None:
        self.world = world
        self.events = events
        sets, media, dataset = _load_frame_sets()
        self.media_ready = bool(sets)
        self.sites: list[Site] = []
        for i, (sid, name, (lat, lon), ref) in enumerate(SITES):
            x, y = world.frame.point(lat, lon)
            if ref:
                lines = [r for r, m in zip(world.roads, world.road_meta) if m["ref"] == ref]
                if lines:
                    cloud = np.vstack(lines)
                    j = int(np.argmin(np.hypot(cloud[:, 0] - x, cloud[:, 1] - y)))
                    if math.hypot(cloud[j, 0] - x, cloud[j, 1] - y) < 1500:
                        x, y = float(cloud[j, 0]), float(cloud[j, 1])
                        lat, lon = world.frame.latlon(x, y)
            frames = sets[i % len(sets)] if sets else []
            self.sites.append(
                Site(sid, name, ref or "", lat, lon, x, y, SITE_RADIUS_M, frames, media, dataset, idx=(i * 7) % max(1, len(frames)))
            )
        self._cursor = 0
        self.last_site: Site | None = None
        self.metrics: dict | None = None
        self.model_name = "labels"

    def next_job(self) -> tuple[Site, dict] | None:
        live = [s for s in self.sites if s.frames]
        if not live:
            return None
        site = live[self._cursor % len(live)]
        self._cursor += 1
        frame = site.frames[site.idx % len(site.frames)]
        site.idx += 1
        return site, frame

    def frame_path(self, frame: dict) -> Path:
        return (AUAIR_DIR if self.sites and self.sites[0].media.endswith("auair") else ML_DIR / "vision_frames") / frame["file"]

    def apply(self, site: Site, frame: dict, detections: list[dict] | None, model_name: str, now: float) -> tuple[str, str] | None:
        """Score one frame. Returns (old level, new level) when the site's level changed."""
        boxes = detections if detections else frame.get("boxes", [])
        counts: dict[str, int] = {}
        for b in boxes:
            counts[b["label"]] = counts.get(b["label"], 0) + 1
        vehicles = sum(n for k, n in counts.items() if k.lower() in VEHICLES)
        people = sum(n for k, n in counts.items() if k.lower() in PEOPLE)
        raw = vehicles + 2.0 * people
        site.score = raw if site.score is None else 0.5 * site.score + 0.5 * raw
        site.counts = counts
        site.detections = detections or []
        site.frame = frame
        site.scored_by = model_name if detections else f"{site.dataset} labels"
        site.updated_at = now
        self.last_site = site

        old = site.level
        new = next(name for name, floor in THRESHOLDS if site.score >= floor)
        if ORDER[new] < ORDER[old]:
            # Step down only once the smoothed score is clearly below the old level's floor.
            floor = dict(THRESHOLDS)[old]
            if site.score > floor * 0.8:
                new = old
        if new == old:
            return None
        site.level = new
        cost = GROUND_COST.get(new, 0.0)
        if ORDER[new] >= ORDER["HIGH"] and ORDER[new] > ORDER[old]:
            self.events.emit(
                "GROUND_RISK_DETECTED",
                f"{site.name}: ground traffic {new}. {vehicles} vehicles and {people} people in view "
                f"({site.scored_by}); overflight cost raised to {cost:.0f}/m within {site.radius:.0f} m.",
                site=site.id,
                level=new,
                vehicles=vehicles,
                people=people,
                score=site.score,
                frame=frame.get("source"),
            )
        elif ORDER[old] >= ORDER["HIGH"] and ORDER[new] < ORDER["HIGH"]:
            self.events.emit(
                "GROUND_RISK_CLEARED",
                f"{site.name}: ground traffic eased to {new} ({vehicles} vehicles, {people} people).",
                site=site.id,
                level=new,
            )
        return old, new

    def to_list(self) -> list[dict]:
        return [s.to_dict() for s in self.sites]

    def feed(self) -> dict | None:
        if self.last_site is None:
            return None
        out = self.last_site.to_dict()
        out["model"] = self.model_name
        out["metrics"] = self.metrics
        return out
