"""
Fit Rohit's OpenSky tracks into a Downtown Dubai operating box.

The ADS-B files are real 80 km cruise segments. Delivery drones cannot fly
those legs, so we keep the *shape* (smooth heading, even spacing) and
rescale each track into ~4 km around Burj Khalifa / Downtown.

`build_trajectories.py` emits ~360 `dense_waypoints` per track. Those are
what the simulator flies — the raw ~20 ADS-B fixes are provenance only.
"""

from __future__ import annotations

import json
from pathlib import Path

DUBAI = (25.1972, 55.2744)  # Burj Khalifa / Downtown
SPAN_DEG = 0.024  # ~2.6 km
OFFSETS = [
    (0.0, 0.0),
    (0.008, 0.007),
    (-0.007, 0.009),
    (0.009, -0.007),
    (-0.008, -0.006),
]
TRAJECTORIES = Path(__file__).resolve().parent.parent / "ml" / "trajectories.json"

MISSIONS = [
    ("drone-1", "Marina clinic run", 12.0, 120.0, 0.10),
    ("drone-2", "Palm grocery drop", 14.0, 80.0, 0.22),
    ("drone-3", "Sheikh Zayed survey", 16.0, 150.0, 0.35),
    ("drone-4", "DIFC parts delivery", 10.0, 90.0, 0.18),
    ("drone-5", "Organ to Emirates Hospital", 18.0, 200.0, 0.55),
]


def _pairs(waypoints) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for w in waypoints or []:
        if isinstance(w, dict):
            out.append((float(w["lat"]), float(w["lon"])))
        elif isinstance(w, (list, tuple)) and len(w) >= 2:
            out.append((float(w[0]), float(w[1])))
    return out


def _fit(waypoints: list[tuple[float, float]], center: tuple[float, float]) -> list[tuple[float, float]]:
    if not waypoints:
        return []
    lats = [w[0] for w in waypoints]
    lons = [w[1] for w in waypoints]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)

    def nx(v: float, lo: float, hi: float) -> float:
        return 0.5 if hi - lo < 1e-9 else (v - lo) / (hi - lo)

    return [
        (center[0] + (nx(lat, lat_min, lat_max) - 0.5) * SPAN_DEG,
         center[1] + (nx(lon, lon_min, lon_max) - 0.5) * SPAN_DEG)
        for lat, lon in waypoints
    ]


def _align(profile: list, n: int) -> list:
    if not profile or n <= 0:
        return []
    if len(profile) == n:
        return [float(v) for v in profile]
    if len(profile) < 2:
        return [float(profile[0])] * n
    out = []
    last = len(profile) - 1
    for i in range(n):
        t = i * last / max(1, n - 1)
        lo = int(t)
        hi = min(lo + 1, last)
        frac = t - lo
        out.append(float(profile[lo]) * (1.0 - frac) + float(profile[hi]) * frac)
    return out


def load_mission_tracks() -> list[dict] | None:
    """
    Five Dubai-fitted tracks. Prefers cubic-spline dense waypoints (~360 pts)
    so the live path is a curve, not a four-corner polyline.
    """
    if not TRAJECTORIES.exists():
        return None
    try:
        data = json.loads(TRAJECTORIES.read_text(encoding="utf-8"))
        tracks = data.get("trajectories") or []
        if len(tracks) < 5:
            return None
        fitted: list[dict] = []
        for t, (dy, dx) in zip(tracks[:5], OFFSETS):
            dense = _pairs(t.get("dense_waypoints") or [])
            sparse = _pairs(t.get("waypoints") or [])
            raw = dense if len(dense) >= 40 else sparse
            pts = _fit(raw, (DUBAI[0] + dy, DUBAI[1] + dx))
            if len(pts) < 2:
                return None
            n = len(pts)
            fitted.append(
                {
                    "id": str(t.get("id") or f"traj_{len(fitted)+1:02d}"),
                    "source": "opensky",
                    "waypoints": pts,
                    "speed_profile": _align(t.get("speed_profile") or [], n),
                    "alt_profile": _align(t.get("alt_profile_m") or [], n),
                }
            )
        counts = [len(t["waypoints"]) for t in fitted]
        print(f"[missions] OpenSky dense tracks: {counts} waypoints")
        return fitted
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def load_mission_waypoints() -> list[list[tuple[float, float]]] | None:
    """Back-compat wrapper — prefer load_mission_tracks()."""
    tracks = load_mission_tracks()
    if not tracks:
        return None
    return [t["waypoints"] for t in tracks]
