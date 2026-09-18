"""
Build ml/dubai_airspace.json, the real-world map the airspace planner flies over.

Everything comes from OpenStreetMap through the Overpass API:

  restricted   airports and airfields, DXB / Al Minhad runway approach funnels, military
               and police sites, stadiums and arenas, Meydan racecourse, power plants,
               Zabeel Palace
  hospitals    medical-mission destinations and helicopter endpoints
  districts    named neighbourhoods; random missions and drone ports are drawn from these
  malls        delivery destinations; the largest become crowd hotspots for ground risk
  roads        motorway / trunk centrelines for the ground-risk base layer
  water mask   coastline flood-filled into a 100 m land/water raster

Raw responses are cached in ml/.cache/osm/, so a rebuild is offline and repeatable.
Pass --refresh to fetch again.

Run: python build_airspace.py [--refresh]
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache" / "osm"
OUT = HERE / "dubai_airspace.json"

BOUNDS = {"south": 25.02, "west": 55.10, "north": 25.30, "east": 55.43}
BBOX = f"({BOUNDS['south']},{BOUNDS['west']},{BOUNDS['north']},{BOUNDS['east']})"
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
USER_AGENT = "CodeCortex-airspace-sim/0.1 (hackathon build script)"

LAT0 = (BOUNDS["south"] + BOUNDS["north"]) / 2
LON0 = (BOUNDS["west"] + BOUNDS["east"]) / 2
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))

WATER_RES_M = 100.0

# Named sites the category queries do not tag as restricted.
EXTRA_WAYS = {
    213204581: ("Zabeel Palace", "palace"),
    1121192056: ("Dubai Police General Headquarters", "government"),
}

DRONE_PORT_DISTRICTS = [
    "Dubai Marina",
    "Al Barsha",
    "Al Quoz",
    "Business Bay",
    "Jumeirah",
    "Al Karama",
    "Al Qusais",
    "Mirdif",
    "Dubai Silicon Oasis",
    "Al Warqa",
]


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _ssl_context() -> ssl.SSLContext:
    # Some Windows Python builds ship a CA store that rejects the public endpoints' chains.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def overpass(name: str, body: str, refresh: bool) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))["elements"]
    query = f"[out:json][timeout:120];({body});out geom;"
    data = urllib.parse.urlencode({"data": query}).encode()
    attempts = [url for _ in range(3) for url in OVERPASS_ENDPOINTS]
    for attempt, url in enumerate(attempts):
        request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=180, context=_ssl_context()) as resp:
                raw = resp.read()
            break
        except Exception as exc:  # 429 / 504 from a busy public endpoint
            if attempt == len(attempts) - 1:
                raise
            print(f"  overpass {name} via {urllib.parse.urlparse(url).netloc}: {exc}; retrying")
            time.sleep(5 + 5 * attempt)
    path.write_bytes(raw)
    time.sleep(2)  # the public endpoint asks for spacing between queries
    return json.loads(raw)["elements"]


# ---------------------------------------------------------------------------
# Geometry helpers (local equirectangular metres around the box centre)
# ---------------------------------------------------------------------------


def to_xy(lat: float, lon: float) -> tuple[float, float]:
    return (lon - LON0) * M_PER_DEG_LON, (lat - LAT0) * M_PER_DEG_LAT


def to_latlon(x: float, y: float) -> tuple[float, float]:
    return LAT0 + y / M_PER_DEG_LAT, LON0 + x / M_PER_DEG_LON


def in_bounds(lat: float, lon: float) -> bool:
    return BOUNDS["south"] <= lat <= BOUNDS["north"] and BOUNDS["west"] <= lon <= BOUNDS["east"]


def douglas_peucker(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    ax, ay = points[0]
    bx, by = points[-1]
    dx, dy = bx - ax, by - ay
    seg = math.hypot(dx, dy)
    best, idx = -1.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if seg < 1e-9:
            d = math.hypot(px - ax, py - ay)
        else:
            d = abs(dy * px - dx * py + bx * ay - by * ax) / seg
        if d > best:
            best, idx = d, i
    if best <= tol:
        return [points[0], points[-1]]
    left = douglas_peucker(points[: idx + 1], tol)
    return left[:-1] + douglas_peucker(points[idx:], tol)


def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def polygon_area(xy: list[tuple[float, float]]) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def centroid(xy: list[tuple[float, float]]) -> tuple[float, float]:
    xs = [p[0] for p in xy]
    ys = [p[1] for p in xy]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def element_xy(el: dict) -> list[tuple[float, float]]:
    """Outline of a node, way or relation in local metres. Relations collapse to their outer hull."""
    if el["type"] == "node":
        return [to_xy(el["lat"], el["lon"])]
    if el["type"] == "way":
        pts = [to_xy(g["lat"], g["lon"]) for g in el.get("geometry", []) if g]
        return pts[:-1] if len(pts) > 3 and pts[0] == pts[-1] else pts
    pts: list[tuple[float, float]] = []
    for member in el.get("members", []):
        if member.get("role") in ("outer", "") and member.get("geometry"):
            pts.extend(to_xy(g["lat"], g["lon"]) for g in member["geometry"] if g)
    return convex_hull(pts)


def english_name(tags: dict) -> str:
    name = tags.get("name:en") or tags.get("int_name") or ""
    if not name:
        raw = tags.get("name", "")
        name = raw if raw.isascii() else ""
    return name.strip()


def latlon_ring(xy: list[tuple[float, float]]) -> list[list[float]]:
    out = []
    for x, y in xy:
        lat, lon = to_latlon(x, y)
        out.append([round(lat, 6), round(lon, 6)])
    return out


# ---------------------------------------------------------------------------
# Restricted airspace
# ---------------------------------------------------------------------------


def classify(tags: dict, area_m2: float) -> str | None:
    name = english_name(tags).lower()
    if tags.get("aeroway") == "aerodrome":
        if area_m2 < 10_000:  # the DXB vertiport pad, already inside the airport polygon
            return None
        return "airport" if area_m2 > 2_000_000 else "airfield"
    if tags.get("aeroway") == "heliport":
        return "heliport"
    if tags.get("landuse") == "military" or "military" in tags:
        if "police" in name:
            return "government"
        return "military" if (area_m2 >= 20_000 or name) else None
    if tags.get("leisure") == "stadium" or tags.get("building") == "stadium":
        return "stadium" if (name or area_m2 >= 15_000) else None
    if tags.get("leisure") == "track" and "meydan" in name:
        return "racecourse"
    if tags.get("power") == "plant" or ("power" in name and tags.get("landuse") == "industrial"):
        # District cooling plants are tagged power=plant too; only generating sites count.
        return "power" if area_m2 >= 50_000 else None
    return None


def heading_deg(dx: float, dy: float) -> float:
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def merge_runways(runway_ways: list[dict], airports: list[dict]) -> list[dict]:
    """
    One record per physical runway at a real airport. OSM splits DXB's runways into a main
    way plus displaced-threshold stubs, and draws some of them against the numbering, so
    ways are merged by ref and each end is labelled by the heading an aircraft lands on.
    """
    groups: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for rw in runway_ways:
        xy = element_xy(rw)
        if len(xy) < 2:
            continue
        mid = centroid(xy)
        owner = next((a for a in airports if point_in_polygon(mid, a["_xy"])), None)
        if owner is None:
            continue
        groups.setdefault((owner["name"], rw.get("tags", {}).get("ref", "")), []).extend(xy)

    runways = []
    for (airport, ref), pts in groups.items():
        arr = np.array(pts)
        centre = arr.mean(axis=0)
        _, _, vt = np.linalg.svd(arr - centre)
        axis = vt[0]
        proj = (arr - centre) @ axis
        a = centre + axis * proj.min()
        b = centre + axis * proj.max()
        length = float(np.hypot(*(b - a)))
        if length < 1500:
            continue
        labels = ref.split("/") if "/" in ref else []
        ends = []
        for thr, other in ((a, b), (b, a)):
            hdg = heading_deg(other[0] - thr[0], other[1] - thr[1])
            number = round(hdg / 10) % 36 or 36
            label = next((lab for lab in labels if lab[:2].isdigit() and int(lab[:2]) == number), f"{number:02d}")
            lat, lon = to_latlon(float(thr[0]), float(thr[1]))
            ends.append({"label": label, "lat": round(lat, 6), "lon": round(lon, 6), "landing_heading": round(hdg, 1)})
        runways.append({"airport": airport, "ref": ref, "length_m": round(length), "ends": ends})
    return runways


def runway_funnels(runways: list[dict]) -> list[dict]:
    """
    Approach funnels off both ends of every runway: 4 km out, 250 m either side of the
    centreline at the threshold widening to 700 m. Simulation policy, not published
    procedure surfaces.
    """
    funnels = []
    for rw in runways:
        for end in rw["ends"]:
            tx, ty = to_xy(end["lat"], end["lon"])
            back = math.radians(end["landing_heading"] + 180.0)
            dx, dy = math.sin(back), math.cos(back)
            nx, ny = -dy, dx
            far = (tx + dx * 4000, ty + dy * 4000)
            poly = [
                (tx + nx * 250, ty + ny * 250),
                (far[0] + nx * 700, far[1] + ny * 700),
                (far[0] - nx * 700, far[1] - ny * 700),
                (tx - nx * 250, ty - ny * 250),
            ]
            funnels.append(
                {
                    "id": f"funnel-{rw['airport'][:3].lower()}-{end['label']}",
                    "name": f"{rw['airport']} runway {end['label']} approach",
                    "category": "approach",
                    "polygon": latlon_ring(poly),
                    "area_km2": round(polygon_area(poly) / 1e6, 3),
                    "osm": "derived from aeroway=runway",
                }
            )
    return funnels


def point_in_polygon(p: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            inside = not inside
    return inside


def build_restricted(refresh: bool) -> tuple[list[dict], list[dict]]:
    body = "".join(
        f'{sel}{BBOX};'
        for sel in (
            'nwr["aeroway"~"^(aerodrome|heliport)$"]',
            'nwr["landuse"="military"]',
            'nwr["leisure"="stadium"]',
            'way["building"="stadium"]',
            'nwr["leisure"="track"]["name"~"Meydan"]',
            'nwr["power"="plant"]',
            'way["landuse"="industrial"]["name"~"Power"]',
        )
    )
    elements = overpass("restricted", body, refresh)
    extra_ids = ",".join(str(i) for i in EXTRA_WAYS)
    elements += overpass("restricted_extra", f"way(id:{extra_ids});", refresh)

    zones: list[dict] = []
    seen_names: set[str] = set()
    for el in elements:
        tags = el.get("tags", {})
        xy = element_xy(el)
        if len(xy) < 3:
            continue
        if el["type"] == "way" and el["id"] in EXTRA_WAYS:
            name, category = EXTRA_WAYS[el["id"]]
        else:
            area = polygon_area(xy)
            category = classify(tags, area)
            name = english_name(tags)
            if category is None:
                continue
            if not name:
                name = {"stadium": "Stadium", "military": "Military area", "power": "Power plant"}.get(
                    category, category.title()
                )
        cx, cy = centroid(xy)
        if not in_bounds(*to_latlon(cx, cy)):
            continue
        key = f"{name}:{round(cx / 200)}:{round(cy / 200)}"
        if key in seen_names:
            continue
        seen_names.add(key)
        simple = douglas_peucker(xy + [xy[0]], 12.0)[:-1] if len(xy) > 8 else xy
        if len(simple) < 3:
            simple = convex_hull(xy)
        zones.append(
            {
                "id": f"osm-{el['type']}-{el['id']}",
                "name": name,
                "category": category,
                "polygon": latlon_ring(simple),
                "area_km2": round(polygon_area(simple) / 1e6, 3),
                "osm": f"{el['type']}/{el['id']}",
                "_xy": simple,
            }
        )

    airports = [z for z in zones if z["category"] == "airport"]
    runways = merge_runways(overpass("runways", f'way["aeroway"="runway"]{BBOX};', refresh), airports)
    zones += runway_funnels(runways)
    for z in zones:
        z.pop("_xy", None)
    zones.sort(key=lambda z: (z["category"], -z["area_km2"]))
    return zones, runways


# ---------------------------------------------------------------------------
# Places, roads, water
# ---------------------------------------------------------------------------


def named_points(elements: list[dict], min_area: float = 0.0) -> list[dict]:
    out: dict[str, dict] = {}
    for el in elements:
        tags = el.get("tags", {})
        name = english_name(tags)
        if not name:
            continue
        xy = element_xy(el)
        if not xy:
            continue
        area = polygon_area(xy) if len(xy) >= 3 else 0.0
        if area < min_area:
            continue
        cx, cy = centroid(xy) if len(xy) > 1 else xy[0]
        lat, lon = to_latlon(cx, cy)
        if not in_bounds(lat, lon):
            continue
        if name in out and out[name]["area_m2"] >= area:
            continue
        out[name] = {"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "area_m2": round(area)}
    return sorted(out.values(), key=lambda p: p["name"])


def build_roads(refresh: bool) -> list[dict]:
    elements = overpass("roads", f'way["highway"~"^(motorway|trunk)$"]{BBOX};', refresh)
    roads = []
    for el in elements:
        xy = element_xy(el)
        if len(xy) < 2:
            continue
        simple = douglas_peucker(xy, 20.0)
        tags = el.get("tags", {})
        roads.append(
            {
                "class": tags.get("highway"),
                "ref": tags.get("ref", ""),
                "name": english_name(tags),
                "line": latlon_ring(simple),
            }
        )
    return roads


def coastline_segments(coast: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Every coastline edge as (start, end) in metres, split to <=100 m so a midpoint KD-tree
    finds the true nearest edge, plus prev/next links across way boundaries.
    """
    starts: list[tuple[float, float]] = []
    ends: list[tuple[float, float]] = []
    for el in coast:
        pts = [to_xy(g["lat"], g["lon"]) for g in el.get("geometry", []) if g]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            pieces = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / 100.0)))
            for k in range(pieces):
                t0, t1 = k / pieces, (k + 1) / pieces
                starts.append((ax + (bx - ax) * t0, ay + (by - ay) * t0))
                ends.append((ax + (bx - ax) * t1, ay + (by - ay) * t1))
    A = np.array(starts)
    B = np.array(ends)
    key = lambda p: (round(p[0], 2), round(p[1], 2))  # noqa: E731
    by_start = {key(a): i for i, a in enumerate(starts)}
    by_end = {key(b): i for i, b in enumerate(ends)}
    nxt = np.array([by_start.get(key(b), -1) for b in ends])
    prv = np.array([by_end.get(key(a), -1) for a in starts])
    return A, B, prv, nxt


def water_mask(refresh: bool) -> tuple[dict, np.ndarray, float, float]:
    """
    Land/water raster from the coastline's orientation.

    OSM draws every coastline way with land on its left. Each cell takes the side of its
    nearest coastline edge (angle-weighted at shared vertices), so the answer is local: a
    gap somewhere in the data cannot flood a whole district the way a fill would.
    """
    from scipy.spatial import cKDTree

    coast = overpass("coastline", f'way["natural"="coastline"]{BBOX};', refresh)
    lakes = overpass("water", f'nwr["natural"="water"]{BBOX};', refresh)

    dlat = WATER_RES_M / M_PER_DEG_LAT
    dlon = WATER_RES_M / M_PER_DEG_LON
    rows = int(math.ceil((BOUNDS["north"] - BOUNDS["south"]) / dlat))
    cols = int(math.ceil((BOUNDS["east"] - BOUNDS["west"]) / dlon))

    def cell(lat: float, lon: float) -> tuple[int, int]:
        return int((lat - BOUNDS["south"]) / dlat), int((lon - BOUNDS["west"]) / dlon)

    lat_c = BOUNDS["south"] + (np.arange(rows) + 0.5) * dlat
    lon_c = BOUNDS["west"] + (np.arange(cols) + 0.5) * dlon
    glat, glon = np.meshgrid(lat_c, lon_c, indexing="ij")
    P = np.stack([(glon.ravel() - LON0) * M_PER_DEG_LON, (glat.ravel() - LAT0) * M_PER_DEG_LAT], axis=1)

    A, B, prv, nxt = coastline_segments(coast)
    D = B - A
    seg_len2 = np.maximum((D**2).sum(axis=1), 1e-9)
    left = np.stack([-D[:, 1], D[:, 0]], axis=1) / np.sqrt(seg_len2)[:, None]

    _, cand = cKDTree((A + B) / 2).query(P, k=12)
    AP = P[:, None, :] - A[cand]
    t = np.clip((AP * D[cand]).sum(axis=2) / seg_len2[cand], 0.0, 1.0)
    closest = A[cand] + t[..., None] * D[cand]
    dist2 = ((P[:, None, :] - closest) ** 2).sum(axis=2)
    pick = dist2.argmin(axis=1)
    rows_idx = np.arange(len(P))
    seg = cand[rows_idx, pick]
    tt = t[rows_idx, pick]

    normal = left[seg].copy()
    at_start = tt <= 1e-9
    at_end = tt >= 1 - 1e-9
    has_prev = at_start & (prv[seg] >= 0)
    has_next = at_end & (nxt[seg] >= 0)
    normal[has_prev] += left[prv[seg[has_prev]]]
    normal[has_next] += left[nxt[seg[has_next]]]
    anchor = closest[rows_idx, pick]
    land = ((P - anchor) * normal).sum(axis=1) > 0
    water = (~land).reshape(rows, cols)
    for el in lakes:
        # Relations collapse to convex hulls in element_xy; a hull of a curved canal or of
        # Dubai Creek would swallow whole districts. Closed ways are real outlines.
        if el["type"] != "way":
            continue
        xy = element_xy(el)
        if len(xy) < 3 or polygon_area(xy) < 50_000:
            continue
        ring = [to_latlon(x, y) for x, y in xy]
        lats = [p[0] for p in ring]
        lons = [p[1] for p in ring]
        r0, c0 = cell(min(lats), min(lons))
        r1, c1 = cell(max(lats), max(lons))
        for r in range(max(0, r0), min(rows, r1 + 1)):
            for c in range(max(0, c0), min(cols, c1 + 1)):
                if point_in_polygon(to_xy(lat_c[r], lon_c[c]), xy):
                    water[r, c] = True

    packed = base64.b64encode(np.packbits(water.ravel()).tobytes()).decode()
    meta = {
        "res_m": WATER_RES_M,
        "rows": rows,
        "cols": cols,
        "dlat": dlat,
        "dlon": dlon,
        "south": BOUNDS["south"],
        "west": BOUNDS["west"],
        "bits": packed,
    }
    return meta, water, dlat, dlon


def pick_drone_ports(districts: list[dict], restricted: list[dict], water: np.ndarray, dlat: float, dlon: float) -> list[dict]:
    """
    One port per preferred district: its own centre if that is on land and 800 m clear of
    restricted airspace, else the nearest qualifying district within 3 km.
    """
    polys = [[to_xy(lat, lon) for lat, lon in z["polygon"]] for z in restricted]

    def clear(lat: float, lon: float) -> bool:
        r = int((lat - BOUNDS["south"]) / dlat)
        c = int((lon - BOUNDS["west"]) / dlon)
        if water[min(max(r, 0), water.shape[0] - 1), min(max(c, 0), water.shape[1] - 1)]:
            return False
        p = to_xy(lat, lon)
        for poly in polys:
            if point_in_polygon(p, poly):
                return False
            if min(math.hypot(p[0] - x, p[1] - y) for x, y in poly) < 800:
                return False
        return True

    by_name = {d["name"].lower(): d for d in districts}
    ports: list[dict] = []
    used: set[str] = set()
    for wanted in DRONE_PORT_DISTRICTS:
        anchor = by_name.get(wanted.lower()) or next(
            (v for k, v in by_name.items() if k.startswith(wanted.lower())), None
        )
        if anchor is None:
            continue
        ax, ay = to_xy(anchor["lat"], anchor["lon"])
        options = sorted(districts, key=lambda d: math.hypot(to_xy(d["lat"], d["lon"])[0] - ax, to_xy(d["lat"], d["lon"])[1] - ay))
        for d in options:
            dx, dy = to_xy(d["lat"], d["lon"])
            if math.hypot(dx - ax, dy - ay) > 3000:
                break
            if d["name"] not in used and clear(d["lat"], d["lon"]):
                used.add(d["name"])
                ports.append({"id": f"port-{len(ports) + 1}", "name": f"{wanted} drone port", "lat": d["lat"], "lon": d["lon"]})
                break
    return ports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--refresh", action="store_true", help="re-download from Overpass")
    args = parser.parse_args()

    print("restricted airspace ...")
    restricted, runways = build_restricted(args.refresh)
    print("hospitals, malls, districts ...")
    hospitals = named_points(overpass("hospitals", f'nwr["amenity"="hospital"]{BBOX};', args.refresh))
    malls = named_points(overpass("malls", f'nwr["shop"="mall"]{BBOX};', args.refresh))
    districts = named_points(
        overpass("districts", f'node["place"~"^(suburb|neighbourhood|quarter)$"]{BBOX};', args.refresh)
    )
    print("roads ...")
    roads = build_roads(args.refresh)
    print("water mask ...")
    mask_meta, water, dlat, dlon = water_mask(args.refresh)

    def on_land(p: dict) -> bool:
        r = int((p["lat"] - BOUNDS["south"]) / dlat)
        c = int((p["lon"] - BOUNDS["west"]) / dlon)
        return 0 <= r < water.shape[0] and 0 <= c < water.shape[1] and not water[r, c]

    hospitals = [h for h in hospitals if on_land(h)]
    malls = [m for m in malls if on_land(m)]
    districts = [d for d in districts if on_land(d)]
    crowds = sorted(malls, key=lambda m: -m["area_m2"])[:10]
    ports = pick_drone_ports(districts, restricted, water, dlat, dlon)

    doc = {
        "source": "OpenStreetMap contributors via the Overpass API (overpass-api.de)",
        "license": "ODbL 1.0 - (c) OpenStreetMap contributors",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bounds": BOUNDS,
        "restricted": restricted,
        "runways": runways,
        "hospitals": hospitals,
        "malls": malls,
        "crowds": crowds,
        "districts": districts,
        "drone_ports": ports,
        "roads": roads,
        "water": mask_meta,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    cats: dict[str, int] = {}
    for z in restricted:
        cats[z["category"]] = cats.get(z["category"], 0) + 1
    print(f"wrote {OUT.name}: {OUT.stat().st_size / 1024:.0f} KB")
    print(f"  restricted {len(restricted)} {cats}")
    print(f"  hospitals {len(hospitals)}, malls {len(malls)}, districts {len(districts)}, ports {len(ports)}")
    print(f"  roads {len(roads)}, water {water.mean() * 100:.1f}% of the box")


if __name__ == "__main__":
    main()
