"""
Fit Rohit's OpenSky tracks into Pranav's Bangalore operating box.

The ADS-B files are real 80 km cruise segments. Delivery drones cannot fly
those legs, so we keep the *shape* (smooth heading, even spacing) and
rescale each track into ~4 km around MG Road. Mission names stay Pranav's.
"""

from __future__ import annotations

import json
from pathlib import Path

BANGALORE = (12.9716, 77.5946)
SPAN_DEG = 0.028  # ~3 km
OFFSETS = [
    (0.0, 0.0),
    (0.012, 0.01),
    (-0.01, 0.014),
    (0.014, -0.01),
    (-0.012, -0.008),
]
TRAJECTORIES = Path(__file__).resolve().parent.parent / "ml" / "trajectories.json"

MISSIONS = [
    ("drone-1", "Delivery A — Medical Supplies", 12.0, 120.0, 0.10),
    ("drone-2", "Delivery B — Food Package", 14.0, 80.0, 0.22),
    ("drone-3", "Survey — Traffic Monitoring", 16.0, 150.0, 0.35),
    ("drone-4", "Delivery C — Electronics", 10.0, 90.0, 0.18),
    ("drone-5", "Emergency — Organ Transport", 18.0, 200.0, 0.55),
]


def _fit(waypoints: list[dict], center: tuple[float, float]) -> list[tuple[float, float]]:
    lats = [float(w["lat"]) for w in waypoints]
    lons = [float(w["lon"]) for w in waypoints]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)

    def nx(v: float, lo: float, hi: float) -> float:
        return 0.5 if hi - lo < 1e-9 else (v - lo) / (hi - lo)

    out = []
    for w in waypoints:
        y = nx(float(w["lat"]), lat_min, lat_max)
        x = nx(float(w["lon"]), lon_min, lon_max)
        out.append((center[0] + (y - 0.5) * SPAN_DEG, center[1] + (x - 0.5) * SPAN_DEG))
    return out


def load_mission_waypoints() -> list[list[tuple[float, float]]] | None:
    if not TRAJECTORIES.exists():
        return None
    try:
        data = json.loads(TRAJECTORIES.read_text(encoding="utf-8"))
        tracks = data.get("trajectories") or []
        if len(tracks) < 5:
            return None
        fitted = []
        for t, (dy, dx) in zip(tracks[:5], OFFSETS):
            pts = _fit(t["waypoints"], (BANGALORE[0] + dy, BANGALORE[1] + dx))
            if pts and pts[0] != pts[-1]:
                pts.append(pts[0])
            fitted.append(pts)
        return fitted
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
