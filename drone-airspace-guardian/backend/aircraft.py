"""
Manned air traffic: one shared Aircraft Data Service for the whole fleet.

    OpenSky --> AircraftService --> shared aircraft state --> 75 s predictions
            --> safety volumes on the risk map --> drone planner / conflict predictor

Sources:
  live     The OpenSky Network REST API is polled for a box around Dubai every
           OPENSKY_POLL_S seconds on a background thread (anonymous by default, or the
           OAuth2 API client when OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET are set).
           Positions are dead-reckoned between polls. One poll serves every drone.
  replay   Used when live is switched off (AIR_TRAFFIC=replay) or after STALE_S with no
           healthy poll. Real OpenSky arrivals/departures from ml/air_traffic.json,
           re-anchored to DXB 30L. A merely stale live feed (status "live (stale)",
           still startswith "live") dead-reckons last tracks and does NOT launch replay.
  heli     Helicopters on scheduled low-level routes between real Dubai hospitals and
           landmarks. They are what shares the drones' altitude band.

Every aircraft is extrapolated with a constant turn-rate / vertical-rate model. Drones
must yield to all of it; mission priority never outranks a manned aircraft.
"""

from __future__ import annotations

import json
import math
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from config import AIR_TRAFFIC_FILE, AIRCRAFT_RELEVANT_ALT_M, AIRCRAFT_SEPARATION, CANDIDATE_HORIZON_S, PREDICT_STEP_S
from geo_utils import heading_of

PRED_DTS = np.arange(0.0, CANDIDATE_HORIZON_S + 1e-9, PREDICT_STEP_S)
OPENSKY_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
REPLAY_INTERVAL_S = 80.0
STALE_S = 60.0
BOX_MARGIN_M = 12_000.0

# Scheduled rotorcraft. Stops are real OSM hospitals; the tour and patrol use landmark
# coordinates, the patrol snapped onto Sheikh Zayed Road (E11) geometry.
HELI_ROUTES = [
    {"id": "HELI-MED1", "callsign": "MEDEVAC 1", "stops": ["Rashid Hospital", "Saudi German Hospital"], "alt": 170.0, "speed": 52.0, "dwell": 30.0, "offset": 0.0},
    {"id": "HELI-MED2", "callsign": "MEDEVAC 2", "stops": ["Dubai Hospital", "Kings Hospital"], "alt": 190.0, "speed": 50.0, "dwell": 30.0, "offset": 140.0},
    {
        "id": "HELI-POL2",
        "callsign": "POLICE 2",
        "points": [(25.2255, 55.2870), (25.2010, 55.2700), (25.1910, 55.2610), (25.1560, 55.2310), (25.1210, 55.2000), (25.1010, 55.1730), (25.0800, 55.1480)],
        "snap": "E11",
        "pingpong": True,
        "alt": 160.0,
        "speed": 45.0,
        "offset": 60.0,
    },
    {
        "id": "HELI-TOUR",
        "callsign": "TOUR 7",
        "points": [(25.1304, 55.1171), (25.1413, 55.1854), (25.1972, 55.2744), (25.2230, 55.1850), (25.1304, 55.1171)],
        "alt": 240.0,
        "speed": 42.0,
        "offset": 30.0,
    },
]


@dataclass
class Aircraft:
    id: str
    callsign: str
    kind: str  # airliner | helicopter
    source: str  # opensky-live | opensky-replay | scheduled
    x: float = 0.0
    y: float = 0.0
    alt: float = 0.0
    speed: float = 0.0
    heading: float = 0.0
    vrate: float = 0.0
    turn_rate: float = 0.0
    country: str = ""
    seen_at: float = 0.0
    pred: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    relevant: bool = False
    risk: str = "LOW"
    nearest_m: float = math.inf
    nearest_drone: str | None = None
    announced: bool = False
    trail: deque = field(default_factory=lambda: deque(maxlen=24))

    def extrapolate(self, dts: np.ndarray) -> np.ndarray:
        h0 = math.radians(self.heading)
        w = math.radians(self.turn_rate)
        if abs(w) < 1e-4:
            x = self.x + math.sin(h0) * self.speed * dts
            y = self.y + math.cos(h0) * self.speed * dts
        else:
            x = self.x + self.speed / w * (math.cos(h0) - np.cos(h0 + w * dts))
            y = self.y + self.speed / w * (np.sin(h0 + w * dts) - math.sin(h0))
        z = np.maximum(0.0, self.alt + self.vrate * dts)
        return np.stack([x, y, z], axis=1)


class Timeline:
    """Pre-sampled 1 s track (x, y, alt, speed, heading, vrate) played back with interpolation."""

    def __init__(self, t: np.ndarray, x, y, alt, speed, heading, vrate) -> None:
        self.t = t
        self.x, self.y, self.alt, self.speed, self.vrate = x, y, alt, speed, vrate
        self.heading_unwrapped = np.degrees(np.unwrap(np.radians(heading)))
        self.duration = float(t[-1])

    def state(self, tau: float) -> tuple[float, ...]:
        tau = min(max(tau, 0.0), self.duration)
        f = lambda arr: float(np.interp(tau, self.t, arr))  # noqa: E731
        return f(self.x), f(self.y), f(self.alt), f(self.speed), f(self.heading_unwrapped) % 360.0, f(self.vrate)


class AircraftService:
    def __init__(self, world, events) -> None:
        self.world = world
        self.events = events
        self.frame = world.frame
        self.aircraft: dict[str, Aircraft] = {}
        self.mode = os.environ.get("AIR_TRAFFIC", "live").lower()
        self.status = "starting"
        self._replay: list[dict] = []
        self._replay_idx = 0
        self._replay_active: dict[str, tuple[Timeline, float]] = {}
        self._next_launch = 5.0
        self._helis: list[tuple[dict, Timeline]] = []
        self._poller: OpenSkyPoller | None = None
        self._last_live: float = 0.0
        self.time_scale = 1.0  # sim seconds per wall second; live traffic moves in wall time
        self._load_replay()
        self._build_helis()
        if self.mode == "live":
            b = world.bounds
            pad = 0.25
            self._poller = OpenSkyPoller((b["south"] - pad, b["west"] - pad, b["north"] + pad, b["east"] + pad))
            self._poller.start()

    # --- sources ----------------------------------------------------------------------

    def _load_replay(self) -> None:
        try:
            data = json.loads(AIR_TRAFFIC_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[aircraft] no replay traffic: {exc}")
            return
        for flight in data.get("flights", []):
            s = np.array(flight["samples"], dtype=float)
            x, y = self.frame.to_xy(s[:, 1], s[:, 2])
            tl = Timeline(s[:, 0], x, y, s[:, 3], s[:, 4], s[:, 5], s[:, 6])
            near = np.nonzero(self._near_box(x, y, 9000.0))[0]
            start = float(s[near[0], 0]) - 5.0 if len(near) else 0.0
            self._replay.append({"flight": flight, "timeline": tl, "start": max(0.0, start)})

    def _near_box(self, x, y, margin):
        w = self.world
        return (x > w.x_min - margin) & (x < w.x_max + margin) & (y > w.y_min - margin) & (y < w.y_max + margin)

    def _build_helis(self) -> None:
        for spec in HELI_ROUTES:
            pts = self._heli_points(spec)
            if len(pts) < 2:
                continue
            self._helis.append((spec, self._heli_timeline(pts, spec)))

    def _heli_points(self, spec: dict) -> list[tuple[float, float]]:
        if "stops" in spec:
            places = [self.world.find(n) for n in spec["stops"]]
            if any(p is None for p in places):
                return []
            return [(p.x, p.y) for p in places]
        pts = [self.frame.point(lat, lon) for lat, lon in spec["points"]]
        if spec.get("snap"):
            lines = [r for r, m in zip(self.world.roads, self.world.road_meta) if m["ref"] == spec["snap"]]
            if lines:
                cloud = np.vstack(lines)
                pts = [tuple(cloud[np.argmin(np.hypot(cloud[:, 0] - x, cloud[:, 1] - y))]) for x, y in pts]
        return pts

    def _heli_timeline(self, pts: list[tuple[float, float]], spec: dict) -> Timeline:
        """Fly the legs at cruise, landing at each stop when the route has stops."""
        if spec.get("pingpong"):
            pts = pts + pts[-2::-1]
        elif "stops" in spec:
            pts = pts + [pts[0]]
        cruise, speed = spec["alt"], spec["speed"]
        dwell = spec.get("dwell", 0.0)
        vr = 6.0
        rows = []  # t, x, y, alt, speed, heading, vrate
        t = 0.0
        pad_alt = 30.0 if dwell else cruise
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            leg = math.hypot(bx - ax, by - ay)
            hdg = heading_of(bx - ax, by - ay)
            ramp = (cruise - pad_alt) / vr * speed if dwell else 0.0
            n = max(2, int(leg / speed) + 1)
            for k in range(n):
                d = leg * k / (n - 1)
                if dwell:
                    alt = min(cruise, pad_alt + (cruise - pad_alt) * min(d, leg - d) / max(ramp, 1.0))
                else:
                    alt = cruise
                rows.append((t + d / speed, ax + (bx - ax) * d / leg, ay + (by - ay) * d / leg, alt, speed, hdg, 0.0))
            t += leg / speed
            if dwell:
                for k in range(1, int(dwell) + 1):
                    rows.append((t + k, bx, by, pad_alt, 0.0, hdg, 0.0))
                t += dwell
        arr = np.array(rows)
        keep = np.concatenate([[True], np.diff(arr[:, 0]) > 1e-6])  # legs share their end timestamps
        arr = arr[keep]
        vrate = np.gradient(arr[:, 3], arr[:, 0]) if len(arr) > 2 else np.zeros(len(arr))
        return Timeline(arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5], vrate)

    # --- clock ------------------------------------------------------------------------

    def tick(self, now: float, dt: float) -> None:
        for spec, tl in self._helis:
            tau = (now + spec.get("offset", 0.0)) % tl.duration
            self._place(spec["id"], spec["callsign"], "helicopter", "scheduled", tl.state(tau), now)

        live_ok = self._pull_live(now)
        if live_ok:
            self.status = "live"
            for key in [k for k in self._replay_active]:
                self.aircraft.pop(key, None)
            self._replay_active.clear()
        elif self._poller is not None and self._poller.ok_once and now - self._last_live < STALE_S:
            # Keep dead-reckoning the last live tracks. Do NOT launch replay airliners
            # while the feed is merely stale — that used to mix fake DXB traffic on top.
            self.status = "live (stale)"
        else:
            self.status = "replay" if self.mode != "live" or self._poller is None else "replay (OpenSky unreachable)"
            self._run_replay(now)

        for ac in list(self.aircraft.values()):
            if ac.source == "opensky-live":
                if now - ac.seen_at > STALE_S * self.time_scale:
                    del self.aircraft[ac.id]
                    continue
                wall = dt / max(self.time_scale, 1e-6)
                h = math.radians(ac.heading)
                ac.x += math.sin(h) * ac.speed * wall
                ac.y += math.cos(h) * ac.speed * wall
                ac.alt = max(0.0, ac.alt + ac.vrate * wall)

    def _place(self, key: str, callsign: str, kind: str, source: str, state: tuple, now: float, country: str = "") -> None:
        x, y, alt, speed, heading, vrate = state
        ac = self.aircraft.get(key)
        if ac is None:
            ac = Aircraft(key, callsign, kind, source, country=country)
            self.aircraft[key] = ac
        elif now > ac.seen_at:
            dh = ((heading - ac.heading + 540.0) % 360.0) - 180.0
            limit = 6.0 if kind == "helicopter" else 3.0
            ac.turn_rate = max(-limit, min(limit, 0.6 * ac.turn_rate + 0.4 * dh / max(now - ac.seen_at, 0.25)))
        ac.x, ac.y, ac.alt, ac.speed, ac.heading, ac.vrate = x, y, alt, speed, heading, vrate
        ac.seen_at = now

    def _run_replay(self, now: float) -> None:
        if self._replay and now >= self._next_launch:
            item = self._replay[self._replay_idx % len(self._replay)]
            self._replay_idx += 1
            key = f"RP-{item['flight']['callsign']}-{self._replay_idx}"
            self._replay_active[key] = (item["timeline"], now - item["start"])
            self._next_launch = now + REPLAY_INTERVAL_S
        for key, (tl, t0) in list(self._replay_active.items()):
            tau = now - t0
            if tau > tl.duration:
                del self._replay_active[key]
                self.aircraft.pop(key, None)
                continue
            flight = next(r["flight"] for r in self._replay if r["timeline"] is tl)
            self._place(key, flight["callsign"], "airliner", "opensky-replay", tl.state(tau), now, flight.get("country", ""))

    def _pull_live(self, now: float) -> bool:
        if self._poller is None:
            return False
        batch = self._poller.take()
        if batch is not None:
            self._last_live = now
            seen = set()
            for st in batch:
                icao, callsign, country = st[0], (st[1] or "").strip() or st[0], st[2]
                lon, lat, alt, on_ground, vel, trk, vr = st[5], st[6], st[7], st[8], st[9], st[10], st[11]
                # No altitude means no vertical separation can be judged; on-ground traffic is the airport's problem.
                if lat is None or lon is None or on_ground or vel is None or (alt is None and st[13] is None):
                    continue
                category = st[17] if len(st) > 17 else None
                key = f"OS-{icao}"
                x, y = self.frame.point(lat, lon)
                # Dead-reckon from the report's own timestamp to now.
                age = max(0.0, min(30.0, time.time() - float(st[3] or st[4] or time.time())))
                h = math.radians(float(trk or 0.0))
                x += math.sin(h) * float(vel) * age
                y += math.cos(h) * float(vel) * age
                z = max(0.0, float(alt or st[13] or 0.0) + float(vr or 0.0) * age)
                kind = "helicopter" if category == 8 else "airliner"
                self._place(key, callsign, kind, "opensky-live", (x, y, z, float(vel), float(trk or 0.0), float(vr or 0.0)), now, country)
                seen.add(key)
            for key in [k for k, a in self.aircraft.items() if a.source == "opensky-live" and k not in seen]:
                del self.aircraft[key]
        return self._poller.healthy()

    # --- assessment -------------------------------------------------------------------

    def refresh(self, drones: list, now: float) -> None:
        """Predict every aircraft, decide which ones matter to the drone layer, rate the risk."""
        w = self.world
        for ac in self.aircraft.values():
            ac.pred = ac.extrapolate(PRED_DTS)
            lat, lon = self.frame.latlon(ac.x, ac.y)
            if not ac.trail or ac.trail[-1] != (round(lat, 5), round(lon, 5)):
                ac.trail.append((round(lat, 5), round(lon, 5)))
            in_box = bool(self._near_box(np.array([ac.x]), np.array([ac.y]), 3000.0)[0])
            ac.relevant = in_box and float(ac.pred[:, 2].min()) <= AIRCRAFT_RELEVANT_ALT_M
            if drones:
                d = [math.hypot(dr.x - ac.x, dr.y - ac.y) for dr in drones]
                i = int(np.argmin(d))
                ac.nearest_m, ac.nearest_drone = d[i], drones[i].id
            else:
                cx, cy = (w.x_min + w.x_max) / 2, (w.y_min + w.y_max) / 2
                ac.nearest_m, ac.nearest_drone = math.hypot(ac.x - cx, ac.y - cy), None
            ac.risk = "MEDIUM" if ac.relevant and ac.nearest_m < 3000.0 else "LOW"
            if ac.relevant and not ac.announced and ac.nearest_m < 8000.0:
                ac.announced = True
                self.events.emit(
                    "AIRCRAFT_DETECTED",
                    f"External aircraft {ac.callsign} ({ac.kind}, {ac.alt:.0f} m) detected near the operating region, "
                    f"{ac.nearest_m / 1000:.1f} km from the nearest drone.",
                    aircraft=ac.callsign,
                    kind=ac.kind,
                    source=ac.source,
                    alt_m=ac.alt,
                )

    def mark_conflicts(self, aircraft_ids: set[str]) -> None:
        for ac in self.aircraft.values():
            if ac.id in aircraft_ids:
                ac.risk = "HIGH"

    def relevant(self) -> list[Aircraft]:
        return [a for a in self.aircraft.values() if a.relevant]

    def get(self, key: str) -> Aircraft | None:
        return self.aircraft.get(key)

    def volumes(self) -> list[tuple[np.ndarray, float, float]]:
        out = []
        for ac in self.relevant():
            h_sep, _ = AIRCRAFT_SEPARATION[ac.kind]
            low = ac.pred[:, 2] <= AIRCRAFT_RELEVANT_ALT_M
            pts = ac.pred[:61][low[:61], :2]
            out.append((pts, h_sep, h_sep * 1.6))
        return out

    def reset(self) -> None:
        for key in [k for k, a in self.aircraft.items() if a.source != "opensky-live"]:
            del self.aircraft[key]
        self._replay_active.clear()
        self._next_launch = 5.0
        for ac in self.aircraft.values():
            ac.announced = False

    def to_list(self) -> list[dict]:
        out = []
        for ac in sorted(self.aircraft.values(), key=lambda a: a.nearest_m):
            lat, lon = self.frame.latlon(ac.x, ac.y)
            step = 5
            pred = ac.pred[::step] if len(ac.pred) else np.zeros((0, 3))
            plat, plon = self.frame.to_latlon(pred[:, 0], pred[:, 1]) if len(pred) else ([], [])
            h_sep, v_sep = AIRCRAFT_SEPARATION[ac.kind]
            out.append(
                {
                    "id": ac.id,
                    "callsign": ac.callsign,
                    "kind": ac.kind,
                    "source": ac.source,
                    "country": ac.country,
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "alt": round(ac.alt),
                    "speed": round(ac.speed, 1),
                    "heading": round(ac.heading, 1),
                    "vrate": round(ac.vrate, 1),
                    "relevant": ac.relevant,
                    "risk": ac.risk,
                    "distanceKm": round(ac.nearest_m / 1000.0, 2) if math.isfinite(ac.nearest_m) else None,
                    "nearestDrone": ac.nearest_drone,
                    "predicted": [[round(float(a), 5), round(float(b), 5)] for a, b in zip(plat, plon)],
                    "trail": [list(p) for p in ac.trail],
                    "volumeM": h_sep if ac.relevant else None,
                    "verticalSepM": v_sep,
                }
            )
        return out


class OpenSkyPoller(threading.Thread):
    """Background poll of the OpenSky states API for one bounding box."""

    def __init__(self, bbox: tuple[float, float, float, float]) -> None:
        super().__init__(daemon=True, name="opensky-poller")
        self.bbox = bbox
        self.client_id = os.environ.get("OPENSKY_CLIENT_ID")
        self.client_secret = os.environ.get("OPENSKY_CLIENT_SECRET")
        default_interval = 10.0 if self.client_id else 20.0
        self.interval = float(os.environ.get("OPENSKY_POLL_S", default_interval))
        self._lock = threading.Lock()
        self._batch: list | None = None
        self._token: tuple[str, float] | None = None
        self.last_ok = 0.0
        self.ok_once = False
        self.failures = 0
        self.last_error = ""

    def healthy(self) -> bool:
        return self.ok_once and time.time() - self.last_ok < self.interval * 3 + 5

    def take(self) -> list | None:
        with self._lock:
            batch, self._batch = self._batch, None
        return batch

    def run(self) -> None:
        while True:
            try:
                states = self._fetch()
                with self._lock:
                    self._batch = states
                self.last_ok = time.time()
                self.ok_once = True
                self.failures = 0
                wait = self.interval
            except Exception as exc:  # network down, 429 rate limit, auth failure
                self.failures += 1
                self.last_error = str(exc)
                wait = min(300.0, self.interval * (2 ** min(self.failures, 4)))
                if "429" in str(exc):
                    wait = min(300.0, max(wait, 90.0))
                    print(f"[aircraft] OpenSky HTTP 429; backing off {wait:.0f}s")
                elif self.failures in (1, 5):
                    print(f"[aircraft] OpenSky poll failed ({exc}); falling back to replay traffic")
            time.sleep(wait)

    def _ssl_context(self) -> ssl.SSLContext:
        try:
            import certifi

            return ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            return ssl.create_default_context()

    def _auth_header(self) -> dict:
        if not (self.client_id and self.client_secret):
            return {}
        if self._token is None or time.time() > self._token[1]:
            body = urllib.parse.urlencode(
                {"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret}
            ).encode()
            req = urllib.request.Request(OPENSKY_TOKEN_URL, data=body)
            with urllib.request.urlopen(req, timeout=20, context=self._ssl_context()) as resp:
                tok = json.loads(resp.read())
            self._token = (tok["access_token"], time.time() + float(tok.get("expires_in", 1800)) - 60)
        return {"Authorization": f"Bearer {self._token[0]}"}

    def _fetch(self) -> list:
        s, w, n, e = self.bbox
        query = urllib.parse.urlencode({"lamin": s, "lomin": w, "lamax": n, "lomax": e, "extended": 1})
        req = urllib.request.Request(f"{OPENSKY_URL}?{query}", headers={"User-Agent": "CodeCortex-airspace-sim", **self._auth_header()})
        try:
            with urllib.request.urlopen(req, timeout=20, context=self._ssl_context()) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise RuntimeError("OpenSky HTTP 429 rate limited") from exc
            raise
        return data.get("states") or []
