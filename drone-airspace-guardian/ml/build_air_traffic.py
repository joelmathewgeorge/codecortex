"""
Build ml/air_traffic.json: real OpenSky arrivals and departures re-flown at DXB.

The OpenSky capture covers the Indian subcontinent, so its aircraft never pass Dubai. What
it does have is real low-level flying: final approaches descending through 100-600 m and
departures climbing out, each a 20-fix state-vector track (~18 s apart) with its own
speed, heading and vertical-rate history.

Each chosen track keeps that history and is anchored to a real DXB runway end from
dubai_airspace.json:

  arrivals    the last recorded fix is placed on the extended centreline at the distance
              a 3 degree glide path puts its altitude; the recorded headings are rotated
              so the final one matches the landing heading, and positions are integrated
              backwards from there. A modelled final segment finishes at the threshold.
  departures  the mirror image: a modelled take-off roll and initial climb, then the
              recorded climb-out from the point its first altitude implies.

Output samples every 2 s: [t, lat, lon, alt_m, speed_ms, heading_deg, vrate_ms].
Writes up to 12 arrivals + 8 departures (or every qualifying track if fewer).

Run: python build_air_traffic.py        (OPENSKY_CSV overrides the capture path)
"""

from __future__ import annotations

import csv
import json
import math
import os
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
AIRSPACE = HERE / "dubai_airspace.json"
OUT = HERE / "air_traffic.json"
DEFAULT_CSV = Path(r"C:\Users\rohit\Downloads\Datasets\03_OpenSky_flight_telemetry\opensky_trajectories.csv")

GLIDE = math.tan(math.radians(3.0))
CLIMB = 0.09  # ~5 degree initial climb gradient
THRESHOLD_ALT = 15.0
SAMPLE_S = 2.0
MAX_ARRIVALS = 12
MAX_DEPARTURES = 8


def load_tracks(path: Path) -> list[dict]:
    rows_by_id: dict[str, list[dict]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                rec = {
                    "t": int(row["snapshot_time"]),
                    "alt": float(row["baro_altitude"]),
                    "speed": float(row["velocity"]),
                    "track": float(row["true_track"]),
                    "vrate": float(row["vertical_rate"] or 0.0),
                }
            except (ValueError, KeyError):
                continue
            if row.get("on_ground") == "True":
                continue
            rec["callsign"] = (row.get("callsign") or "").strip() or row["icao24"]
            rec["icao24"] = row["icao24"]
            rec["country"] = row.get("origin_country", "")
            rows_by_id[row["icao24"]].append(rec)

    tracks = []
    for icao, rows in rows_by_id.items():
        rows.sort(key=lambda r: r["t"])
        deduped = [rows[0]] + [r for prev, r in zip(rows, rows[1:]) if r["t"] > prev["t"]]
        if len(deduped) < 10:
            continue
        tracks.append(
            {
                "icao24": icao,
                "callsign": deduped[0]["callsign"],
                "country": deduped[0]["country"],
                "t": np.array([r["t"] - deduped[0]["t"] for r in deduped], dtype=float),
                "alt": np.array([r["alt"] for r in deduped]),
                "speed": np.array([r["speed"] for r in deduped]),
                "track": np.unwrap(np.radians([r["track"] for r in deduped])),
                "vrate": np.array([r["vrate"] for r in deduped]),
            }
        )
    return tracks


def pick(tracks: list[dict]) -> tuple[list[dict], list[dict]]:
    arrivals = [
        t for t in tracks
        if t["alt"][-1] < t["alt"][0] - 120 and t["alt"].min() < 2000 and t["speed"].mean() < 160
    ]
    departures = [
        t for t in tracks
        if t["alt"][-1] > t["alt"][0] + 300 and t["vrate"].max() > 2
    ]
    arrivals.sort(key=lambda t: t["alt"].min())
    departures.sort(key=lambda t: t["alt"][0])
    return arrivals[:MAX_ARRIVALS], departures[:MAX_DEPARTURES]


class LocalFrame:
    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0, self.lon0 = lat0, lon0
        self.m_lat = 110_574.0
        self.m_lon = 111_320.0 * math.cos(math.radians(lat0))

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.m_lon, (lat - self.lat0) * self.m_lat

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        return self.lat0 + y / self.m_lat, self.lon0 + x / self.m_lon


def resample(t: np.ndarray, *series: np.ndarray) -> tuple[np.ndarray, ...]:
    grid = np.arange(0.0, t[-1] + 1e-9, SAMPLE_S)
    return (grid,) + tuple(np.interp(grid, t, s) for s in series)


def integrate(x0: float, y0: float, headings: np.ndarray, speeds: np.ndarray, dt: float, sign: float = 1.0):
    """Dead-reckon a path from (x0, y0); sign=-1 walks it backwards in time."""
    xs, ys = [x0], [y0]
    for hdg, spd in zip(headings, speeds):
        xs.append(xs[-1] + sign * math.sin(hdg) * spd * dt)
        ys.append(ys[-1] + sign * math.cos(hdg) * spd * dt)
    return np.array(xs), np.array(ys)


def build_arrival(track: dict, end: dict, frame: LocalFrame) -> dict:
    t, alt, speed, hdg, vrate = resample(track["t"], track["alt"], track["speed"], track["track"], track["vrate"])
    land = math.radians(end["landing_heading"])
    hdg = hdg - hdg[-1] + land  # rotate so the final recorded heading lines up with the runway

    tx, ty = frame.to_xy(end["lat"], end["lon"])
    gap = max(0.0, (alt[-1] - THRESHOLD_ALT) / GLIDE)  # centreline distance for the last fix's altitude
    ex, ey = tx - math.sin(land) * gap, ty - math.cos(land) * gap

    back_x, back_y = integrate(ex, ey, hdg[::-1][:-1], speed[::-1][:-1], SAMPLE_S, sign=-1.0)
    xs, ys = back_x[::-1], back_y[::-1]

    final_speed = float(speed[-1])
    n_final = max(1, int(gap / max(final_speed, 40.0) / SAMPLE_S))
    fx = np.linspace(ex, tx, n_final + 1)[1:]
    fy = np.linspace(ey, ty, n_final + 1)[1:]
    falt = np.linspace(alt[-1], THRESHOLD_ALT, n_final + 1)[1:]
    fv = -(alt[-1] - THRESHOLD_ALT) / (n_final * SAMPLE_S)

    xs = np.concatenate([xs, fx])
    ys = np.concatenate([ys, fy])
    alts = np.concatenate([alt, falt])
    speeds = np.concatenate([speed, np.full(n_final, final_speed)])
    headings = np.concatenate([hdg, np.full(n_final, land)])
    vrates = np.concatenate([vrate, np.full(n_final, fv)])
    return package(track, "arrival", end, frame, xs, ys, alts, speeds, headings, vrates)


def build_departure(track: dict, end: dict, frame: LocalFrame) -> dict:
    t, alt, speed, hdg, vrate = resample(track["t"], track["alt"], track["speed"], track["track"], track["vrate"])
    out = math.radians(end["landing_heading"])  # take off in the same direction aircraft land
    hdg = hdg - hdg[0] + out

    tx, ty = frame.to_xy(end["lat"], end["lon"])
    gap = max(0.0, alt[0] / CLIMB)
    sx, sy = tx + math.sin(out) * gap, ty + math.cos(out) * gap

    climb_speed = float(speed[0])
    n_climb = max(1, int(gap / max(climb_speed, 60.0) / SAMPLE_S))
    cx = np.linspace(tx, sx, n_climb + 1)[:-1]
    cy = np.linspace(ty, sy, n_climb + 1)[:-1]
    calt = np.linspace(0.0, alt[0], n_climb + 1)[:-1]
    cv = alt[0] / (n_climb * SAMPLE_S)

    fwd_x, fwd_y = integrate(sx, sy, hdg[:-1], speed[:-1], SAMPLE_S)
    xs = np.concatenate([cx, fwd_x])
    ys = np.concatenate([cy, fwd_y])
    alts = np.concatenate([calt, alt])
    speeds = np.concatenate([np.full(n_climb, climb_speed), speed])
    headings = np.concatenate([np.full(n_climb, out), hdg])
    vrates = np.concatenate([np.full(n_climb, cv), vrate])
    return package(track, "departure", end, frame, xs, ys, alts, speeds, headings, vrates)


def package(track, kind, end, frame, xs, ys, alts, speeds, headings, vrates) -> dict:
    samples = []
    for i, (x, y) in enumerate(zip(xs, ys)):
        lat, lon = frame.to_latlon(float(x), float(y))
        samples.append(
            [
                round(i * SAMPLE_S, 1),
                round(lat, 6),
                round(lon, 6),
                round(float(alts[i]), 1),
                round(float(speeds[i]), 1),
                round(math.degrees(float(headings[i])) % 360.0, 1),
                round(float(vrates[i]), 2),
            ]
        )
    return {
        "callsign": track["callsign"],
        "icao24": track["icao24"],
        "country": track["country"],
        "kind": kind,
        "runway": end["label"],
        "recorded_fixes": int(len(track["t"])),
        "samples": samples,
    }


def main() -> None:
    csv_path = Path(os.environ.get("OPENSKY_CSV", DEFAULT_CSV))
    airspace = json.loads(AIRSPACE.read_text(encoding="utf-8"))
    dxb = next(r for r in airspace["runways"] if r["airport"].startswith("Dubai International") and "30L" in r["ref"])
    ends = {e["label"]: e for e in dxb["ends"]}
    # Dubai lands and departs on runway 30 for most of the year (prevailing north-westerly).
    arrive_on, depart_on = ends["30L"], ends["30L"]

    b = airspace["bounds"]
    frame = LocalFrame((b["south"] + b["north"]) / 2, (b["west"] + b["east"]) / 2)
    arrivals, departures = pick(load_tracks(csv_path))
    flights = [build_arrival(t, arrive_on, frame) for t in arrivals] + [
        build_departure(t, depart_on, frame) for t in departures
    ]
    doc = {
        "source": f"OpenSky Network state vectors ({csv_path.name})",
        "license": "OpenSky Network, non-commercial research use; trimmed derived slice",
        "method": "recorded speed, altitude, vertical-rate and turn history re-anchored to DXB runway 30L",
        "sample_s": SAMPLE_S,
        "fields": ["t", "lat", "lon", "alt_m", "speed_ms", "heading_deg", "vrate_ms"],
        "flights": flights,
    }
    OUT.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.name}: {OUT.stat().st_size / 1024:.0f} KB")
    for f in flights:
        s = f["samples"]
        print(f"  {f['kind']:<9} {f['callsign']:<8} {f['country']:<22} {len(s) * SAMPLE_S:5.0f} s  alt {s[0][3]:6.0f} -> {s[-1][3]:6.0f} m")


if __name__ == "__main__":
    main()
