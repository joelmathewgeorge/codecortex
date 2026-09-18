"""
Select clean, steady flight paths from real OpenSky ADS-B telemetry and export them as
waypoint lists the backend can replay directly.

Run:  python build_trajectories.py

The capture holds 214 aircraft over 20 snapshots roughly 20 seconds apart. Most are not
usable as mission seeds: some appear in only a handful of snapshots, some are taxiing on the
ground, and some are mid-turn or climbing steeply. This script keeps only aircraft that were
tracked continuously and were flying a steady course, because a mission seeded from a
half-tracked aircraft would teleport between waypoints.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_CSV = Path(
    r"C:\Users\rohit\Downloads\Datasets\03_OpenSky_flight_telemetry\opensky_trajectories.csv"
)
OUTPUT_PATH = Path(__file__).with_name("trajectories.json")

TARGET_COUNT = 8  # inside the requested 5-10 range
REQUIRED_CHANNELS = ["latitude", "longitude", "velocity", "true_track", "baro_altitude"]

# Drones do not cruise at airliner altitude, so a scaled altitude is offered alongside the
# real one for demo missions that need believable drone heights.
DRONE_ALT_MIN, DRONE_ALT_MAX = 60.0, 120.0

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

    Wrapping matters: an aircraft crossing north goes 359 -> 001, which is a 2 degree turn,
    but subtracting naively reports 358 and would reject a perfectly straight flight.
    """
    diff = np.diff(headings)
    return (diff + 180.0) % 360.0 - 180.0


def score_track(track: pd.DataFrame) -> dict | None:
    """
    Measure how steady one aircraft's track is. Lower penalty is steadier.

    Returns None when the track cannot seed a mission at all.
    """
    track = track.sort_values("snapshot_time")
    lat = track["latitude"].to_numpy(float)
    lon = track["longitude"].to_numpy(float)
    speed = track["velocity"].to_numpy(float)
    heading = track["true_track"].to_numpy(float)
    vrate = track["vertical_rate"].fillna(0.0).to_numpy(float)

    steps = haversine_km(lat[:-1], lon[:-1], lat[1:], lon[1:])
    path_km = float(steps.sum())
    if path_km < 5.0:
        return None  # effectively stationary, nothing to fly

    direct_km = float(haversine_km(lat[0], lon[0], lat[-1], lon[-1]))
    straightness = direct_km / path_km if path_km else 0.0

    turns = np.abs(heading_delta(heading))
    step_cv = float(steps.std() / steps.mean()) if steps.mean() else 1.0
    speed_cv = float(speed.std() / speed.mean()) if speed.mean() else 1.0

    penalty = (
        3.0 * step_cv               # uneven spacing means dropped or jittery fixes
        + 2.0 * speed_cv            # steady flight holds its speed
        + 0.05 * float(turns.mean())  # gentle course only
        + 2.0 * (1.0 - straightness)  # penalise looping or circling tracks
        + 0.15 * float(np.abs(vrate).mean())  # prefer level cruise over climb or descent
    )

    return {
        "penalty": penalty,
        "path_km": path_km,
        "straightness": straightness,
        "mean_speed_mps": float(speed.mean()),
        "max_turn_deg": float(turns.max()),
        "step_cv": step_cv,
        "mean_abs_vrate": float(np.abs(vrate).mean()),
        "track": track,
    }


def main() -> None:
    csv_path = Path(os.environ.get("OPENSKY_CSV", DEFAULT_CSV))
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Could not find {csv_path}. Set OPENSKY_CSV to the trajectory capture."
        )

    print("=" * 72)
    print("BUILD FLIGHT TRAJECTORIES FROM REAL ADS-B TELEMETRY")
    print("=" * 72)

    df = pd.read_csv(csv_path)
    snapshots = df["snapshot_time"].nunique()
    print(f"\n  Loaded {len(df):,} records | {df['icao24'].nunique()} aircraft "
          f"| {snapshots} snapshots")

    # Filter to aircraft that can actually seed a mission.
    counts = df.groupby("icao24").size()
    complete = counts[counts == snapshots].index
    stage = df[df["icao24"].isin(complete)]
    print(f"  Tracked in all {snapshots} snapshots: {stage['icao24'].nunique()}")

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

    print(f"  Actually moving (>5 km of travel): {len(scored)}")

    scored.sort(key=lambda r: r["penalty"])
    chosen = scored[:TARGET_COUNT]

    print(f"\n  Selected the {len(chosen)} steadiest tracks:\n")
    header = (
        f"  {'#':>2} {'Callsign':<10} {'Country':<14} {'Path km':>8} "
        f"{'Straight':>9} {'Speed m/s':>10} {'MaxTurn':>8}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    trajectories = []
    for i, result in enumerate(chosen, start=1):
        track = result["track"]
        first = track.iloc[0]
        callsign = str(first["callsign"]).strip() if pd.notna(first["callsign"]) else ""

        print(
            f"  {i:>2} {callsign or '(none)':<10} {str(first['origin_country'])[:14]:<14} "
            f"{result['path_km']:>8.1f} {result['straightness']:>9.3f} "
            f"{result['mean_speed_mps']:>10.1f} {result['max_turn_deg']:>7.1f}d"
        )

        t0 = int(track["snapshot_time"].iloc[0])
        alt = track["baro_altitude"].to_numpy(float)
        alt_span = float(alt.max() - alt.min())

        waypoints = []
        for seq, (_, row) in enumerate(track.iterrows()):
            # Compress real altitude variation into a drone-plausible band, preserving the
            # shape of the climb or descent. A flat cruise maps to the middle of the band.
            if alt_span > 1e-6:
                frac = (float(row["baro_altitude"]) - alt.min()) / alt_span
            else:
                frac = 0.5
            drone_alt = DRONE_ALT_MIN + frac * (DRONE_ALT_MAX - DRONE_ALT_MIN)

            waypoints.append(
                {
                    "seq": seq,
                    "t_offset_s": int(row["snapshot_time"]) - t0,
                    "lat": round(float(row["latitude"]), 6),
                    "lon": round(float(row["longitude"]), 6),
                    "alt_m": round(float(row["baro_altitude"]), 1),
                    "alt_m_drone_scaled": round(float(drone_alt), 1),
                    "speed_mps": round(float(row["velocity"]), 2),
                    "heading_deg": round(float(row["true_track"]), 2),
                    "vertical_rate_mps": round(float(row["vertical_rate"] or 0.0), 2),
                }
            )

        trajectories.append(
            {
                "id": f"traj_{i:02d}",
                "icao24": result["icao24"],
                "callsign": callsign,
                "origin_country": str(first["origin_country"]),
                "num_waypoints": len(waypoints),
                "duration_s": waypoints[-1]["t_offset_s"],
                "path_length_km": round(result["path_km"], 2),
                "mean_speed_mps": round(result["mean_speed_mps"], 2),
                "straightness": round(result["straightness"], 4),
                "max_turn_deg": round(result["max_turn_deg"], 2),
                "waypoints": waypoints,
            }
        )

    payload = {
        "source": "OpenSky Network ADS-B capture over the Indian subcontinent",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "captured_at_unix": int(df["snapshot_time"].min()),
        "coordinate_system": "WGS84 decimal degrees",
        "count": len(trajectories),
        "selection": {
            "criteria": (
                "Tracked in every snapshot, airborne throughout, no missing required "
                "channels, more than 5 km travelled, then ranked by evenness of spacing, "
                "speed consistency, gentleness of turns, path straightness and level flight."
            ),
            "candidates_considered": len(scored),
        },
        "field_notes": {
            "alt_m": "Real barometric altitude in metres from ADS-B.",
            "alt_m_drone_scaled": (
                "Derived, not measured. Real altitude rescaled into "
                f"{DRONE_ALT_MIN:.0f}-{DRONE_ALT_MAX:.0f} m for believable drone missions."
            ),
            "t_offset_s": "Seconds since the first waypoint; use it to pace replay.",
        },
        "trajectories": trajectories,
    }

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))
    total_wp = sum(t["num_waypoints"] for t in trajectories)
    print(f"\n  Wrote {OUTPUT_PATH.name}: {len(trajectories)} trajectories, {total_wp} waypoints")
    print("=" * 72)


if __name__ == "__main__":
    main()
