"use client";

import { useEffect, useRef } from "react";
import type * as Leaflet from "leaflet";
import type { Aircraft, Conflict, Crossing, Drone, GroundSite, LatLon, World, Zone } from "@/types/airspace";
import { DUBAI_CENTER, INTERPOLATION_MS } from "@/lib/config";
import { GROUND_COLOR } from "@/lib/format";
import { getHealthColor } from "@/lib/health";
import { useAirspace } from "./AirspaceProvider";

type L = typeof Leaflet;

const CASING = "#03060c";
const AIRCRAFT_RISK = { LOW: "#9fb4ff", MEDIUM: "#e0b84a", HIGH: "#ff4d63" } as const;
const BUFFER_STRONG = "#ff8a6b";
const BUFFER_SOFT = "#e0b84a";

const PLANE_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1.8c.7 0 1.1.6 1.1 1.4v5.9l7.6 4.5v1.9l-7.6-2.2v4.8l2.3 1.7v1.8L12 20.8l-3.4.9v-1.8l2.3-1.7v-4.8l-7.6 2.2v-1.9l7.6-4.5V3.2c0-.8.4-1.4 1.1-1.4z"/></svg>';
const HELI_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><circle class="rotor" cx="12" cy="10" r="8.6"/><ellipse cx="12" cy="10.6" rx="3" ry="4.3"/><rect x="11.35" y="14.2" width="1.3" height="7.4" rx=".6"/><rect x="9.2" y="20.6" width="5.6" height="1.3" rx=".6"/></svg>';
const CAMERA_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h3l1.6-2h6.8L17 7h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1zm8 3a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z"/></svg>';

type Anim = { marker: Leaflet.Marker; fromLat: number; fromLon: number; lat: number; lon: number; t0: number; shownLat: number; shownLon: number };
type RouteLayers = { casing: Leaflet.Polyline; core: Leaflet.Polyline; original: Leaflet.Polyline };
type ZoneLayers = { ring: Leaflet.Circle; buffer: Leaflet.Circle; pulse?: Leaflet.Circle; key: string };
type AircraftLayers = { track: Leaflet.Polyline; trail: Leaflet.Polyline; volume: Leaflet.Circle };

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}

function droneClasses(d: Drone, selected: boolean) {
  return [
    "craft",
    d.conflict !== "none" ? `is-${d.conflict}` : "",
    d.phase === "escaping" ? "is-escaping" : "",
    d.phase === "landed" || d.phase === "charging" ? "is-parked" : "",
    selected ? "is-selected" : "",
  ]
    .filter(Boolean)
    .join(" ");
}

function routeClass(d: Drone, selected: boolean) {
  const parts = ["route"];
  if (d.conflict === "predicted") parts.push("is-conflict");
  else if (d.phase === "escaping" || d.routeKind === "escape") parts.push("is-escape");
  else if (d.conflict === "resolving" || ["detour", "replan", "avoid"].includes(d.routeKind)) parts.push("is-maneuver");
  else if (d.routeKind === "return") parts.push("is-return");
  if (selected) parts.push("is-selected");
  return parts.join(" ");
}

type Registry = {
  drones: Map<string, Anim>;
  routes: Map<string, RouteLayers>;
  zones: Map<string, ZoneLayers>;
  aircraft: Map<string, Anim>;
  aircraftLayers: Map<string, AircraftLayers>;
  conflicts: Map<string, Leaflet.Marker>;
  sites: Map<string, { ring: Leaflet.Circle; marker: Leaflet.Marker }>;
  crossings: Leaflet.LayerGroup | null;
};

function drawRestricted(Lf: L, map: Leaflet.Map, w: World) {
  for (const z of w.restricted) {
    const strong = z.bufferCost >= 25;
    Lf.polygon(z.buffer as LatLon[], {
      pane: "zones",
      color: strong ? BUFFER_STRONG : BUFFER_SOFT,
      weight: 1,
      opacity: 0.55,
      dashArray: "3 5",
      fill: false,
      interactive: false,
    }).addTo(map);
    Lf.polygon(z.polygon as LatLon[], {
      pane: "zones",
      color: "#ff6b7a",
      weight: 1.6,
      opacity: 0.95,
      fillColor: "#ff6b7a",
      fillOpacity: 1,
      className: "nfz-core",
    })
      .bindTooltip(
        `<b>${escapeHtml(z.name)}</b><br>${escapeHtml(z.category)} &mdash; no-fly core, ${Math.round(z.bufferM)} m buffer`,
        { sticky: true, className: "map-tip" },
      )
      .addTo(map);
  }
}

function syncDrones(Lf: L, map: Leaflet.Map, reg: Registry, list: Drone[], sel: string | null, now: number, onSelect: (id: string) => void) {
  const seen = new Set<string>();
  for (const d of list) {
    seen.add(d.id);
    const color = getHealthColor(d.health);
    const isSel = sel === d.id;
    let a = reg.drones.get(d.id);
    if (!a) {
      const marker = Lf.marker([d.lat, d.lon], {
        pane: "craft",
        icon: Lf.divIcon({
          className: "map-icon",
          html: `<div class="craft"><span class="halo"></span><span class="rotor r1"></span><span class="rotor r2"></span><span class="rotor r3"></span><span class="rotor r4"></span><span class="body"></span><b class="tag"></b></div>`,
          iconSize: [44, 44],
          iconAnchor: [22, 22],
        }),
        keyboard: true,
        title: d.id,
        riseOnHover: true,
      }).addTo(map);
      marker.on("click", () => onSelect(d.id));
      a = { marker, fromLat: d.lat, fromLon: d.lon, lat: d.lat, lon: d.lon, t0: now, shownLat: d.lat, shownLon: d.lon };
      reg.drones.set(d.id, a);
    } else {
      a.fromLat = a.shownLat;
      a.fromLon = a.shownLon;
      a.lat = d.lat;
      a.lon = d.lon;
      a.t0 = now;
    }
    const node = a.marker.getElement()?.querySelector<HTMLElement>(".craft");
    if (node) {
      node.className = droneClasses(d, isSel);
      node.style.setProperty("--h", `${d.heading}deg`);
      node.style.setProperty("--c", color);
      const tag = node.querySelector(".tag");
      if (tag) tag.textContent = d.phase === "charging" || d.phase === "landed" ? d.id : `${d.id} ${Math.round(d.alt)}m`;
    }
    a.marker.setZIndexOffset(isSel ? 1000 : d.conflict !== "none" ? 500 : 0);

    let r = reg.routes.get(d.id);
    if (!r) {
      r = {
        original: Lf.polyline([], { pane: "routes", color: "#fff6dc", weight: 1.5, opacity: 0.55, dashArray: "1 6", lineCap: "round", interactive: false }).addTo(map),
        casing: Lf.polyline([], { pane: "routes", color: CASING, weight: 5, opacity: 0.55, lineCap: "round", lineJoin: "round", interactive: false }).addTo(map),
        core: Lf.polyline([], { pane: "routes", weight: 2.4, opacity: 0.9, lineCap: "round", lineJoin: "round", interactive: false }).addTo(map),
      };
      reg.routes.set(d.id, r);
    }
    const path = d.route.length ? ([[d.lat, d.lon], ...d.route.slice(1)] as LatLon[]) : [];
    r.casing.setLatLngs(path);
    r.core.setLatLngs(path).setStyle({ color });
    r.original.setLatLngs(d.original ?? []);
    const coreEl = r.core.getElement();
    if (coreEl) coreEl.setAttribute("class", routeClass(d, isSel));
    r.casing.setStyle({ weight: isSel ? 8 : 5, opacity: isSel ? 0.8 : 0.5 });
  }
  for (const [id, a] of reg.drones) {
    if (seen.has(id)) continue;
    map.removeLayer(a.marker);
    reg.drones.delete(id);
    const r = reg.routes.get(id);
    if (r) {
      map.removeLayer(r.casing);
      map.removeLayer(r.core);
      map.removeLayer(r.original);
      reg.routes.delete(id);
    }
  }
}

function syncZones(Lf: L, map: Leaflet.Map, reg: Registry, list: Zone[], onRemove: (id: string) => void) {
  const seen = new Set<string>();
  for (const z of list) {
    seen.add(z.id);
    const key = `${z.lat}:${z.lon}:${z.radius}`;
    const existing = reg.zones.get(z.id);
    if (existing && existing.key === key) continue;
    if (existing) removeZoneLayers(map, existing);
    const emergency = z.kind === "emergency";
    const color = emergency ? "#ff4d63" : "#e0b84a";
    const buffer = Lf.circle([z.lat, z.lon], {
      pane: "zones",
      radius: z.radius + z.buffer,
      color,
      weight: 1,
      opacity: 0.7,
      dashArray: "4 6",
      fillColor: color,
      fillOpacity: emergency ? 0.06 : 0.03,
      interactive: false,
    }).addTo(map);
    const ring = Lf.circle([z.lat, z.lon], {
      pane: "zones",
      radius: z.radius,
      color,
      weight: emergency ? 2.6 : 2,
      opacity: 1,
      dashArray: emergency ? undefined : "9 7",
      fillColor: color,
      fillOpacity: 1,
      className: emergency ? "zone-core is-emergency" : "zone-core",
    }).addTo(map);
    const pop = document.createElement("div");
    pop.className = "zone-pop";
    pop.innerHTML = `<b>${escapeHtml(z.label)}</b><span>${z.id}, ${Math.round(z.radius)} m radius plus ${Math.round(z.buffer)} m buffer</span>`;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = emergency ? "Lift emergency" : "Lift no-fly zone";
    btn.onclick = () => {
      map.closePopup();
      onRemove(z.id);
    };
    pop.appendChild(btn);
    ring.bindPopup(pop, { className: "map-pop" });
    const pulse = emergency
      ? Lf.circle([z.lat, z.lon], { pane: "zones", radius: z.radius, color, weight: 2, fill: false, interactive: false, className: "zone-pulse" }).addTo(map)
      : undefined;
    reg.zones.set(z.id, { ring, buffer, pulse, key });
  }
  for (const [id, layers] of reg.zones) {
    if (seen.has(id)) continue;
    removeZoneLayers(map, layers);
    reg.zones.delete(id);
  }
}

function removeZoneLayers(map: Leaflet.Map, z: ZoneLayers) {
  map.removeLayer(z.ring);
  map.removeLayer(z.buffer);
  if (z.pulse) map.removeLayer(z.pulse);
}

function syncAircraft(Lf: L, map: Leaflet.Map, reg: Registry, list: Aircraft[], now: number) {
  const seen = new Set<string>();
  for (const ac of list) {
    seen.add(ac.id);
    const color = AIRCRAFT_RISK[ac.risk];
    let a = reg.aircraft.get(ac.id);
    if (!a) {
      const marker = Lf.marker([ac.lat, ac.lon], {
        pane: "craft",
        icon: Lf.divIcon({
          className: "map-icon",
          html: `<div class="plane ${ac.kind}"><span class="glyph">${ac.kind === "helicopter" ? HELI_SVG : PLANE_SVG}</span><b class="tag"></b></div>`,
          iconSize: [34, 34],
          iconAnchor: [17, 17],
        }),
        keyboard: false,
      }).addTo(map);
      marker.bindTooltip("", { direction: "right", offset: [14, 0], className: "map-tip" });
      a = { marker, fromLat: ac.lat, fromLon: ac.lon, lat: ac.lat, lon: ac.lon, t0: now, shownLat: ac.lat, shownLon: ac.lon };
      reg.aircraft.set(ac.id, a);
      reg.aircraftLayers.set(ac.id, {
        trail: Lf.polyline([], { pane: "routes", color: "#9fb4ff", weight: 1.5, opacity: 0.35, interactive: false }).addTo(map),
        track: Lf.polyline([], { pane: "routes", weight: 1.8, opacity: 0.9, dashArray: "2 7", lineCap: "round", interactive: false }).addTo(map),
        volume: Lf.circle([ac.lat, ac.lon], { pane: "zones", radius: 1, weight: 1, opacity: 0.8, fillOpacity: 0.08, interactive: false }).addTo(map),
      });
    } else {
      a.fromLat = a.shownLat;
      a.fromLon = a.shownLon;
      a.lat = ac.lat;
      a.lon = ac.lon;
      a.t0 = now;
    }
    const node = a.marker.getElement()?.querySelector<HTMLElement>(".plane");
    if (node) {
      node.className = `plane ${ac.kind} risk-${ac.risk.toLowerCase()} ${ac.relevant ? "is-low" : "is-high-alt"}`;
      node.style.setProperty("--h", `${ac.heading}deg`);
      node.style.setProperty("--c", color);
      const tag = node.querySelector(".tag");
      if (tag) tag.textContent = `${ac.callsign} ${ac.alt}m`;
    }
    a.marker.setTooltipContent(
      `<b>${escapeHtml(ac.callsign)}</b> ${ac.kind}, ${ac.alt} m, ${Math.round(ac.speed * 3.6)} km/h<br>` +
        `${ac.source === "opensky-live" ? "OpenSky live" : ac.source === "opensky-replay" ? "OpenSky replay" : "Scheduled route"}` +
        `${ac.distanceKm !== null ? `, ${ac.distanceKm.toFixed(1)} km from ${escapeHtml(ac.nearestDrone ?? "the area")}` : ""}`,
    );
    const layers = reg.aircraftLayers.get(ac.id)!;
    layers.trail.setLatLngs(ac.trail);
    layers.track.setLatLngs(ac.relevant ? ac.predicted : []).setStyle({ color });
    if (ac.relevant && ac.volumeM) {
      layers.volume.setLatLng([ac.lat, ac.lon]).setRadius(ac.volumeM).setStyle({ color, fillColor: color, opacity: 0.8, fillOpacity: ac.risk === "HIGH" ? 0.16 : 0.07 });
    } else {
      layers.volume.setStyle({ opacity: 0, fillOpacity: 0 });
    }
  }
  for (const [id, a] of reg.aircraft) {
    if (seen.has(id)) continue;
    map.removeLayer(a.marker);
    reg.aircraft.delete(id);
    const layers = reg.aircraftLayers.get(id);
    if (layers) {
      map.removeLayer(layers.trail);
      map.removeLayer(layers.track);
      map.removeLayer(layers.volume);
      reg.aircraftLayers.delete(id);
    }
  }
}

function syncConflicts(Lf: L, map: Leaflet.Map, reg: Registry, list: Conflict[]) {
  const seen = new Set<string>();
  for (const c of list) {
    seen.add(c.id);
    const label =
      c.state === "predicted" ? `${Math.round(c.ttc)} s` : c.state === "resolved" ? "Clear" : c.state === "unresolved" ? "Holding" : "Resolving";
    let m = reg.conflicts.get(c.id);
    const html = `<div class="cmark is-${c.state} kind-${c.kind}"><i></i><b>${label}</b></div>`;
    if (!m) {
      m = Lf.marker([c.lat, c.lon], {
        pane: "marks",
        icon: Lf.divIcon({ className: "map-icon", html, iconSize: [40, 40], iconAnchor: [20, 20] }),
        keyboard: false,
        interactive: true,
      }).addTo(map);
      m.bindTooltip("", { direction: "top", offset: [0, -16], className: "map-tip" });
      reg.conflicts.set(c.id, m);
    } else {
      m.setLatLng([c.lat, c.lon]);
      const node = m.getElement()?.querySelector<HTMLElement>(".cmark");
      if (node) {
        node.className = `cmark is-${c.state} kind-${c.kind}`;
        const b = node.querySelector("b");
        if (b) b.textContent = label;
      }
    }
    const who = c.kind === "aircraft" ? `${c.a} vs ${c.bLabel}` : `${c.a} vs ${c.b}`;
    const detail =
      c.state === "predicted"
        ? `predicted in ${Math.round(c.ttc)} s, ${c.minH} m apart at ${c.dz} m height difference`
        : c.state === "resolved"
          ? `resolved${c.maneuver ? ` by ${c.maneuver.toLowerCase()}` : ""}`
          : `${c.yielding ?? c.a} yielding${c.maneuver ? `: ${c.maneuver.toLowerCase()}` : ""}`;
    m.setTooltipContent(`<b>${escapeHtml(who)}</b><br>${escapeHtml(detail)}`);
  }
  for (const [id, m] of reg.conflicts) {
    if (seen.has(id)) continue;
    map.removeLayer(m);
    reg.conflicts.delete(id);
  }
}

function syncCrossings(Lf: L, reg: Registry, list: Crossing[]) {
  const group = reg.crossings;
  if (!group) return;
  group.clearLayers();
  for (const x of list) {
    if (x.status === "conflict") continue; // the conflict marker already covers it
    const why =
      x.status === "altitude"
        ? `separated by ${Math.round(x.dalt)} m of height`
        : x.status === "time"
          ? `separated by ${Math.round(x.dt)} s in time`
          : `same height, ${Math.round(x.dt)} s apart: still outside the prediction window`;
    Lf.marker([x.lat, x.lon], {
      pane: "marks",
      icon: Lf.divIcon({ className: "map-icon", html: `<div class="xmark is-${x.status}"></div>`, iconSize: [12, 12], iconAnchor: [6, 6] }),
      keyboard: false,
    })
      .bindTooltip(`<b>${x.a} and ${x.b} routes cross</b> in ${Math.round(x.inS)} s<br>${why}`, { className: "map-tip", direction: "top" })
      .addTo(group);
  }
}

function syncSites(Lf: L, map: Leaflet.Map, reg: Registry, list: GroundSite[], onSite: (id: string) => void) {
  for (const s of list) {
    const color = GROUND_COLOR[s.level];
    let entry = reg.sites.get(s.id);
    if (!entry) {
      const ring = Lf.circle([s.lat, s.lon], { pane: "zones", radius: s.radius, weight: 1.2, dashArray: "1 5", lineCap: "round", interactive: false }).addTo(map);
      const marker = Lf.marker([s.lat, s.lon], {
        pane: "marks",
        icon: Lf.divIcon({ className: "map-icon", html: `<div class="gsite">${CAMERA_SVG}</div>`, iconSize: [22, 22], iconAnchor: [11, 11] }),
        keyboard: true,
        title: s.name,
      }).addTo(map);
      marker.bindTooltip("", { direction: "top", offset: [0, -12], className: "map-tip" });
      marker.on("click", () => onSite(s.id));
      entry = { ring, marker };
      reg.sites.set(s.id, entry);
    }
    entry.ring.setStyle({ color, fillColor: color, fillOpacity: s.level === "HIGH" || s.level === "VERY HIGH" ? 0.14 : 0.05, opacity: 0.9 });
    const node = entry.marker.getElement()?.querySelector<HTMLElement>(".gsite");
    if (node) node.style.setProperty("--c", color);
    entry.marker.setTooltipContent(`<b>${escapeHtml(s.name)}</b><br>Ground traffic ${s.level.toLowerCase()}, overflight cost ${s.cost}/m`);
  }
}

export default function AirspaceMap() {
  const { world, state, tool, setTool, placeZone, selected, select, removeZone, setSite } = useAirspace();
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Leaflet.Map | null>(null);
  const LRef = useRef<L | null>(null);
  const handlers = useRef({ tool, placeZone, select, removeZone, setSite });
  const reg = useRef<Registry>({
    drones: new Map(),
    routes: new Map(),
    zones: new Map(),
    aircraft: new Map(),
    aircraftLayers: new Map(),
    conflicts: new Map(),
    sites: new Map(),
    crossings: null,
  });
  const staticDone = useRef(false);

  useEffect(() => {
    handlers.current = { tool, placeZone, select, removeZone, setSite };
  });

  // --- map bootstrap -------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const mod = await import("leaflet");
      const Lf = (mod.default ?? mod) as L;
      if (cancelled || !el.current || mapRef.current) return;
      const map = Lf.map(el.current, { zoomControl: true, attributionControl: true, zoomSnap: 0.25, preferCanvas: false }).setView(
        [DUBAI_CENTER.lat, DUBAI_CENTER.lon],
        DUBAI_CENTER.zoom,
      );
      map.createPane("zones").style.zIndex = "350";
      map.createPane("routes").style.zIndex = "420";
      map.createPane("marks").style.zIndex = "600";
      map.createPane("craft").style.zIndex = "650";
      map.createPane("labels").style.zIndex = "450";
      map.getPane("labels")!.style.pointerEvents = "none";
      Lf.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
        attribution: "Imagery &copy; Esri &middot; Airspace &copy; OpenStreetMap contributors",
        className: "base-imagery",
      }).addTo(map);
      Lf.tileLayer("https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png", {
        attribution: "&copy; CARTO",
        pane: "labels",
        opacity: 0.75,
      }).addTo(map);
      reg.current.crossings = Lf.layerGroup().addTo(map);
      map.on("click", (e: Leaflet.LeafletMouseEvent) => {
        const h = handlers.current;
        if (h.tool) h.placeZone(e.latlng.lat, e.latlng.lng);
        else h.select(null);
      });
      mapRef.current = map;
      LRef.current = Lf;
      map.invalidateSize({ animate: false });
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const node = el.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => mapRef.current?.invalidateSize({ animate: false }));
    });
    observer.observe(node);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setTool(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setTool]);

  // Ease markers between 1 Hz updates so motion reads as flight, not teleporting.
  useEffect(() => {
    let frame = 0;
    const reduce = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const loop = (now: number) => {
      for (const registry of [reg.current.drones, reg.current.aircraft]) {
        for (const a of registry.values()) {
          const u = reduce() ? 1 : Math.min(1, (now - a.t0) / INTERPOLATION_MS);
          const ease = 1 - (1 - u) * (1 - u);
          a.shownLat = a.fromLat + (a.lat - a.fromLat) * ease;
          a.shownLon = a.fromLon + (a.lon - a.fromLon) * ease;
          a.marker.setLatLng([a.shownLat, a.shownLon]);
        }
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, []);

  // --- static world ----------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    const Lf = LRef.current;
    if (!map || !Lf || !world || staticDone.current) return;
    staticDone.current = true;
    const b = world.bounds;
    map.fitBounds(
      [
        [b.south, b.west],
        [b.north, b.east],
      ],
      { padding: [12, 12] },
    );
    Lf.rectangle(
      [
        [b.south, b.west],
        [b.north, b.east],
      ],
      { pane: "zones", color: "#e0b84a", weight: 1, opacity: 0.35, fill: false, dashArray: "2 6", interactive: false },
    ).addTo(map);
    drawRestricted(Lf, map, world);
    for (const p of world.ports) {
      Lf.marker([p.lat, p.lon], {
        pane: "marks",
        icon: Lf.divIcon({ className: "map-icon", html: '<div class="port" aria-hidden="true"></div>', iconSize: [14, 14], iconAnchor: [7, 7] }),
        keyboard: false,
      })
        .bindTooltip(p.name, { direction: "top", offset: [0, -8], className: "map-tip" })
        .addTo(map);
    }
  }, [world, state]);

  // --- dynamic layers --------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    const Lf = LRef.current;
    if (!map || !Lf || !state) return;
    const now = performance.now();
    const r = reg.current;
    syncDrones(Lf, map, r, state.drones, selected, now, (id) => handlers.current.select(id));
    syncZones(Lf, map, r, state.zones, (id) => handlers.current.removeZone(id));
    syncAircraft(Lf, map, r, state.aircraft, now);
    syncConflicts(Lf, map, r, state.conflicts);
    syncCrossings(Lf, r, state.crossings);
    syncSites(Lf, map, r, state.ground, (id) => handlers.current.setSite(id));
  }, [state, selected]);

  return (
    <>
      <svg className="map-defs" width="0" height="0" aria-hidden="true" focusable="false">
        <defs>
          <pattern id="hatch-nfz" patternUnits="userSpaceOnUse" width="7" height="7" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="7" stroke="#ff6b7a" strokeWidth="1.6" strokeOpacity="0.6" />
          </pattern>
          <pattern id="hatch-emergency" patternUnits="userSpaceOnUse" width="9" height="9" patternTransform="rotate(-45)">
            <line x1="0" y1="0" x2="0" y2="9" stroke="#ff4d63" strokeWidth="2.2" strokeOpacity="0.45" />
          </pattern>
          <pattern id="hatch-operator" patternUnits="userSpaceOnUse" width="9" height="9" patternTransform="rotate(-45)">
            <line x1="0" y1="0" x2="0" y2="9" stroke="#e0b84a" strokeWidth="1.6" strokeOpacity="0.35" />
          </pattern>
        </defs>
      </svg>
      <div
        ref={el}
        className={`airspace-map ${tool ? `is-placing is-${tool}` : ""}`}
        role="application"
        aria-label="Dubai airspace map"
      />
    </>
  );
}
