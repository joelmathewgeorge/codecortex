"""
Turn real OpenSky ADS-B state vectors into smooth, densely sampled flight paths the
backend can replay as drone missions.

Run:  python build_trajectories.py   ->  writes trajectories.json

WHY THIS WAS REWRITTEN
    The first version ranked candidate aircraft by *straightness* and picked the eight
    steadiest cruise legs. It worked exactly as designed and that was the problem: every
    selected track scored straightness 1.0 with under 1 degree of total heading change,
    so once the backend fitted them into a Dubai box the drones flew dead-straight legs
    between four corners. Replaying a straight line does not look like a recorded flight.

WHAT IT DOES NOW
    1. Ranks candidates by how much genuine curvature they contain — total heading change
       across the track — while still rejecting tracks whose fixes teleport.
    2. Interpolates each track against WALL-CLOCK TIME, not fix index. The capture's
       snapshots are 10-23 s apart, so index-based interpolation bunches waypoints where
       the feed happened to be fast. Time-based cubic splines give even spatial spacing.
    3. Resamples each spline to uniform arc length and emits a few hundred closely spaced
       waypoints per track, so the curvature survives into the simulator and the drone
       turns gradually instead of pivoting at a corner.

WHAT THIS IS NOT
    OpenSky is real *manned aircraft* ADS-B, not drone traffic. Only the geometry of the
    path is reused here; the altitudes and speeds an airliner flies are replaced with
    drone-plausible values (see alt_m_drone_scaled, and the AU-AIR behaviour profiles in
    build_behavior.py). Twenty fixes per aircraft is far too little to train anything on,
    which is why this stays classical interpolation rather than a learned model.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline

DEFAULT_CSV = Path(
    os.environ.get(
        "OPENSKY_CSV",
        r"C:\Users\rohit\Downloads\Datasets\03_OpenSky_flight_telemetry\opensky_trajectories.csv",
    )
)
OUTPUT_PATH = Path(__file__).with_name("trajectories.json")

TARGET_COUNT = 8            # inside the requested 5-10 range; backend uses the first 5
MIN_SNAPSHOTS = 14          # enough fixes to define a curve
MIN_PATH_KM = 8.0           # must actually have gone somewhere
MAX_STEP_TURN_DEG = 60.0    # above a standard-rate turn over ~20 s means a bad fix
MAX_SPEED_CV = 0.35         # implied ground speed must be self-consistent
DENSE_POINTS = 360          # waypoints emitted per track after resampling
REQUIRED_CHANNELS = ["latitude", "longitude", "velocity", "true_track", "baro_altitude"]

# Airliners cruise at 10 km; delivery drones do not. Real altitude variation is kept as a
# *shape* and compressed into a band the demo can show honestly.
DRONE_ALT_MIN, DRONE_ALT_MAX = 60.0, 220.0

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between arrays of coordinates."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def heading_delta(headings: np.ndarray) -> np.ndarray:
    """
    Consecutive heading changes in degrees, wrapped to [-180, 180].

    Wrapping matters: an aircraft crossing north goes 359 -> 001, which is a 2 degree
    turn, but subtracting naively reports -358 and would mis-rank the track.
    """
    return (np.diff(headings) + 180.0) % 360.0 - 180.0


def path_bearings(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Bearing of each segment of a polyline, in degrees."""
    lat1, lon1 = np.radians(lat[:-1]), np.radians(lon[:-1])
    lat2, lon2 = np.radians(lat[1:]), np.radians(lon[1:])
    dlon = lon2 - lon1
    x = np.sin(dlon) * np.cos(lat2)
    y = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
    return (np.degrees(np.arctan2(x, y)) + 360.0) % 360.0


def score_track(track: pd.DataFrame) -> dict | None:
    """
    Rate one aircraft's track on how much usable curvature it carries.

    Returns None for tracks that cannot seed a mission — too short, too jittery, or
    containing a fix that jumps impossibly far.
    """
    track = track.sort_values("snapshot_time")
    lat = track["latitude"].to_numpy(float)
    lon = track["longitude"].to_numpy(float)
    speed = track["velocity"].to_numpy(float)
    heading = track["true_track"].to_numpy(float)
    t = track["snapshot_time"].to_numpy(float)

    steps_km = haversine_km(lat[:-1], lon[:-1], lat[1:], lon[1:])
    path_km = float(steps_km.sum())
    if path_km < MIN_PATH_KM:
        return None

    dt = np.diff(t)
    if np.any(dt <= 0):
        return None

    # Implied ground speed per segment. A consistent value means the fixes are real and
    # evenly paced in time; a wild one means a dropped or duplicated position.
    implied = steps_km * 1000.0 / dt
    speed_cv = float(implied.std() / implied.mean()) if implied.mean() else 1.0
    if speed_cv > MAX_SPEED_CV:
        return None

    turns = np.abs(heading_delta(heading))
    if turns.size and float(turns.max()) > MAX_STEP_TURN_DEG:
        return None

    total_turn = float(turns.sum())
    direct_km = float(haversine_km(lat[0], lon[0], lat[-1], lon[-1]))
    straightness = direct_km / path_km if path_km else 0.0

    # Higher is better. Curvature is what we came for; the other terms keep the winner
    # from being a noisy track that only looks curved because its fixes are bad.
    score = (
        min(total_turn, 200.0) / 200.0 * 3.0   # genuine course change
        + (1.0 - min(straightness, 1.0)) * 1.5  # a real arc, not a line with wobble
        - speed_cv * 1.0                        # penalise inconsistent pacing
    )

    return {
        "score": score,
        "path_km": path_km,
        "straightness": straightness,
        "total_turn_deg": total_turn,
        "max_turn_deg": float(turns.max()) if turns.size else 0.0,
        "turn_per_km": total_turn / path_km if path_km else 0.0,
        "mean_speed_mps": float(speed.mean()),
        "speed_cv": speed_cv,
        "track": track,
    }


def densify(track: pd.DataFrame, n_points: int) -> dict:
    """
    Spline-interpolate a track against wall-clock time, then resample to uniform arc
    length so consecutive waypoints are equally spaced on the ground.

    Uniform spacing is what makes the replay look like flight rather than a slideshow:
    the simulator steps a fixed number of metres per tick, so evenly spaced waypoints
    mean an even rate of turn through every bend.
    """
    track = track.sort_values("snapshot_time")
    t = track["snapshot_time"].to_numpy(float)
    t = t - t[0]
    lat = track["latitude"].to_numpy(float)
    lon = track["longitude"].to_numpy(float)
    alt = track["baro_altitude"].to_numpy(float)
    spd = track["velocity"].to_numpy(float)

    lat_s = CubicSpline(t, lat)
    lon_s = CubicSpline(t, lon)
    alt_s = CubicSpline(t, alt)
    spd_s = CubicSpline(t, spd)

    # Oversample in time first, then pick equal-arc-length samples off that fine curve.
    fine_t = np.linspace(t[0], t[-1], n_points * 8)
    fine_lat = lat_s(fine_t)
    fine_lon = lon_s(fine_t)

    seg = haversine_km(fine_lat[:-1], fine_lon[:-1], fine_lat[1:], fine_lon[1:])
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    targets = np.linspace(0.0, arc[-1], n_points)
    pick_t = np.interp(targets, arc, fine_t)

    out_lat = lat_s(pick_t)
    out_lon = lon_s(pick_t)
    out_alt = alt_s(pick_t)
    out_spd = spd_s(pick_t)

    alt_span = float(out_alt.max() - out_alt.min())
    if alt_span > 1e-6:
        alt_frac = (out_alt - out_alt.min()) / alt_span
    else:
        alt_frac = np.full_like(out_alt, 0.5)
    drone_alt = DRONE_ALT_MIN + alt_frac * (DRONE_ALT_MAX - DRONE_ALT_MIN)

    spd_mean = float(out_spd.mean()) or 1.0
    bearings = path_bearings(out_lat, out_lon)
    dense_turns = np.abs(heading_delta(bearings)) if bearings.size > 1 else np.array([0.0])

    return {
        "dense_waypoints": [
            [round(float(a), 6), round(float(b), 6)] for a, b in zip(out_lat, out_lon)
        ],
        # Multipliers around 1.0, so the backend can shape a drone's own cruise speed with
        # a real aircraft's acceleration pattern without inheriting airliner speeds.
        "speed_profile": [round(float(v) / spd_mean, 4) for v in out_spd],
        "alt_profile_m": [round(float(v), 1) for v in drone_alt],
        "arc_length_km": round(float(arc[-1]), 2),
        "spacing_m": round(float(arc[-1]) * 1000.0 / max(1, n_points - 1), 1),
        "dense_mean_turn_deg": round(float(dense_turns.mean()), 4),
        "dense_max_turn_deg": round(float(dense_turns.max()), 3),
    }


def main() -> None:
    csv_path = DEFAULT_CSV
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Could not find {csv_path}. Set OPENSKY_CSV to the trajectory capture."
        )

    print("=" * 78)
    print("BUILD CURVED FLIGHT TRAJECTORIES FROM REAL ADS-B TELEMETRY")
    print("=" * 78)

    df = pd.read_csv(csv_path)
    snapshots = df["snapshot_time"].nunique()
    print(f"\n  Loaded {len(df):,} records | {df['icao24'].nunique()} aircraft "
          f"| {snapshots} snapshots")

    counts = df.groupby("icao24").size()
    stage = df[df["icao24"].isin(counts[counts >= MIN_SNAPSHOTS].index)]
    print(f"  Tracked in >= {MIN_SNAPSHOTS} snapshots: {stage['icao24'].nunique()}")

    airborne = stage.groupby("icao24").filter(lambda g: not g["on_ground"].any())
    print(f"  Airborne throughout: {airborne['icao24'].nunique()}")

    usable = airborne.groupby("icao24").filter(
        lambda g: g[REQUIRED_CHANNELS].notna().all().all()
    )
    print(f"  No gaps in required channels: {usable['icao24'].nunique()}")

    scored = []
    for icao, track in usable.groupby("icao24"):
        result = score_track(track)
        if result:
            result["icao24"] = icao
            scored.append(result)
    print(f"  Clean, moving, non-teleporting: {len(scored)}")

    scored.sort(key=lambda r: -r["score"])
    chosen = scored[:TARGET_COUNT]

    print(f"\n  Selected the {len(chosen)} most curved tracks:\n")
    header = (
        f"  {'#':>2} {'ICAO':<8} {'Callsign':<10} {'Path km':>8} {'Straight':>9} "
        f"{'TotTurn':>8} {'Turn/km':>8} {'Spacing':>8} {'DenseTurn':>10}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    trajectories = []
    for i, result in enumerate(chosen, start=1):
        track = result["track"]
        first = track.iloc[0]
        callsign = str(first["callsign"]).strip() if pd.notna(first["callsign"]) else ""
        dense = densify(track, DENSE_POINTS)

        print(
            f"  {i:>2} {result['icao24']:<8} {callsign or '(none)':<10} "
            f"{result['path_km']:>8.1f} {result['straightness']:>9.3f} "
            f"{result['total_turn_deg']:>7.1f}d {result['turn_per_km']:>7.2f}d "
            f"{dense['spacing_m']:>7.0f}m {dense['dense_mean_turn_deg']:>9.3f}d"
        )

        t0 = int(track["snapshot_time"].iloc[0])
        alt = track["baro_altitude"].to_numpy(float)
        alt_span = float(alt.max() - alt.min())

        # The raw fixes are kept alongside the dense curve so the provenance of every
        # waypoint stays inspectable.
        waypoints = []
        vrates = track["vertical_rate"].fillna(0.0).to_numpy(float)
        for seq, (_, row) in enumerate(track.iterrows()):
            if alt_span > 1e-6:
                frac = (float(row["baro_altitude"]) - alt.min()) / alt_span
            else:
                frac = 0.5
            waypoints.append(
                {
                    "seq": seq,
                    "t_offset_s": int(row["snapshot_time"]) - t0,
                    "lat": round(float(row["latitude"]), 6),
                    "lon": round(float(row["longitude"]), 6),
                    "alt_m": round(float(row["baro_altitude"]), 1),
                    "alt_m_drone_scaled": round(
                        DRONE_ALT_MIN + frac * (DRONE_ALT_MAX - DRONE_ALT_MIN), 1
                    ),
                    "speed_mps": round(float(row["velocity"]), 2),
                    "heading_deg": round(float(row["true_track"]), 2),
                    "vertical_rate_mps": round(float(vrates[seq]), 2),
                }
            )

        entry = {
            "id": f"traj_{i:02d}",
            "icao24": result["icao24"],
            "callsign": callsign,
            "origin_country": str(first["origin_country"]),
            "num_waypoints": len(waypoints),
            "num_dense_waypoints": len(dense["dense_waypoints"]),
            "duration_s": waypoints[-1]["t_offset_s"],
            "path_length_km": round(result["path_km"], 2),
            "mean_speed_mps": round(result["mean_speed_mps"], 2),
            "straightness": round(result["straightness"], 4),
            "total_turn_deg": round(result["total_turn_deg"], 2),
            "max_turn_deg": round(result["max_turn_deg"], 2),
            "turn_per_km_deg": round(result["turn_per_km"], 3),
            "waypoints": waypoints,
        }
        entry.update(dense)
        trajectories.append(entry)

    payload = {
        "source": "OpenSky Network ADS-B capture over the Indian subcontinent",
        "disclaimer": (
            "Real manned-aircraft ADS-B state vectors, NOT drone traffic. Only the "
            "geometry of each path is reused as a mission shape; altitudes and speeds "
            "are rescaled to drone-plausible values."
        ),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "captured_at_unix": int(df["snapshot_time"].min()),
        "coordinate_system": "WGS84 decimal degrees",
        "count": len(trajectories),
        "selection": {
            "criteria": (
                f"Tracked in >= {MIN_SNAPSHOTS} snapshots, airborne throughout, no "
                f"missing required channels, more than {MIN_PATH_KM} km travelled, "
                f"implied ground speed consistent to within {MAX_SPEED_CV:.0%}, no fix "
                f"turning more than {MAX_STEP_TURN_DEG:.0f} degrees, then ranked by "
                "TOTAL HEADING CHANGE so the winners are genuinely curved arcs."
            ),
            "candidates_considered": len(scored),
        },
        "field_notes": {
            "waypoints": "The raw ADS-B fixes, unmodified apart from rounding.",
            "dense_waypoints": (
                f"[lat, lon] pairs, {DENSE_POINTS} per track, cubic-spline interpolated "
                "against wall-clock time then resampled to uniform arc length. This is "
                "what the simulator flies."
            ),
            "speed_profile": (
                "Per-dense-waypoint speed multiplier around the track's own mean, so a "
                "drone can borrow a real aircraft's acceleration pattern."
            ),
            "alt_profile_m": (
                "Derived, not measured. Real barometric altitude variation rescaled into "
                f"{DRONE_ALT_MIN:.0f}-{DRONE_ALT_MAX:.0f} m."
            ),
            "t_offset_s": "Seconds since the first waypoint; use it to pace replay.",
        },
        "trajectories": trajectories,
    }

    OUTPUT_PATH.write_text(json.dumps(payload, indent=1))
    total = sum(t["num_dense_waypoints"] for t in trajectories)
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\n  Wrote {OUTPUT_PATH.name}: {len(trajectories)} trajectories, "
          f"{total} dense waypoints, {size_kb:.0f} KB")
    print("=" * 78)


if __name__ == "__main__":
    main()
