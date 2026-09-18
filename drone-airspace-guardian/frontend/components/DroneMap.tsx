"use client";

import { useEffect, useRef } from "react";
import type { Drone, NoFlyZone } from "@/types/airspace";
import {
  AERIAL_OVERLAY_OPACITY,
  DUBAI,
  DUBAI_TILES,
  INTERPOLATION_MS,
  LABEL_LAYER_OPACITY,
} from "@/lib/config";
import { getHealthColor } from "@/lib/health";

type Props = {
  drones: Drone[];
  zones: NoFlyZone[];
  drawArmed: boolean;
  onMapClick: (lat: number, lon: number) => void;
};

/** Near-black casing drawn under every bright stroke so vectors survive over sunlit imagery. */
const CASING = "#03060c";
const REROUTE = "#ffcf5c";
const OPERATOR_ZONE = "#e0b84a";
const EMERGENCY_ZONE = "#ff6b7a";

type PairedLine = { casing: any; core: any };
type ZoneLayers = { casing: any; ring: any; pulse?: any; lat: number; lon: number; radius: number };

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (c) => {
    if (c === "&") return "&amp;";
    if (c === "<") return "&lt;";
    if (c === ">") return "&gt;";
    if (c === '"') return "&quot;";
    return "&#39;";
  });
}

function markerHtml(drone: Drone, color: string) {
  const tag = escapeHtml(drone.id.replace("drone-", "D"));
  return `<div class="dag-craft ${drone.affected ? "is-affected" : ""}" style="--h:${drone.heading}deg;--c:${color}">
    <span class="halo"></span>
    <span class="rotor r1"></span><span class="rotor r2"></span>
    <span class="rotor r3"></span><span class="rotor r4"></span>
    <span class="body"></span>
    <b>${tag}</b>
  </div>`;
}

function makeIcon(L: any, drone: Drone, color: string) {
  return L.divIcon({
    className: "dag-icon",
    html: markerHtml(drone, color),
    iconSize: [46, 46],
    iconAnchor: [23, 23],
  });
}

export default function DroneMap({ drones, zones, drawArmed, onMapClick }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const markers = useRef<Record<string, any>>({});
  const paths = useRef<Record<string, PairedLine>>({});
  const reroutes = useRef<Record<string, PairedLine>>({});
  const zoneLayers = useRef<Record<string, ZoneLayers>>({});
  const clickRef = useRef(onMapClick);
  const display = useRef<Record<string, { lat: number; lon: number }>>({});
  const targets = useRef<
    Record<string, { lat: number; lon: number; fromLat: number; fromLon: number; t0: number }>
  >({});
  const dronesRef = useRef(drones);
  clickRef.current = onMapClick;
  dronesRef.current = drones;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const leaflet = await import("leaflet");
      const L = leaflet.default ?? leaflet;
      if (cancelled || !el.current || mapRef.current) return;
      const map = L.map(el.current, { zoomControl: true, attributionControl: true }).setView(
        [DUBAI.lat, DUBAI.lon],
        DUBAI.zoom,
      );
      // Aerial plates sit between the satellite basemap and the vectors so routes are never
      // competing with photographic detail for the same layer.
      map.createPane("aerial").style.zIndex = "250";
      map.createPane("zones").style.zIndex = "350";
      map.createPane("labels").style.zIndex = "450";
      map.createPane("craft").style.zIndex = "650";
      L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        { attribution: "Tiles &copy; Esri" },
      ).addTo(map);
      L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png", {
        attribution: "&copy; OSM &copy; CARTO",
        pane: "labels",
        opacity: LABEL_LAYER_OPACITY,
      }).addTo(map);
      for (const tile of DUBAI_TILES) {
        L.imageOverlay(tile.src, tile.bounds, {
          opacity: AERIAL_OVERLAY_OPACITY,
          pane: "aerial",
          interactive: false,
        }).addTo(map);
      }
      map.on("click", (e: any) => clickRef.current(e.latlng.lat, e.latlng.lng));
      mapRef.current = map;
      map.invalidateSize({ animate: false });
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // The map is an inset panel now, so its box changes with the surrounding layout.
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
    let frame = 0;
    const reduce = () =>
      typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const loop = (now: number) => {
      const map = mapRef.current;
      if (map) {
        for (const drone of dronesRef.current) {
          const t = targets.current[drone.id];
          const marker = markers.current[drone.id];
          if (!t || !marker) continue;
          const u = reduce() ? 1 : Math.min(1, (now - t.t0) / INTERPOLATION_MS);
          const ease = 1 - (1 - u) * (1 - u);
          const lat = t.fromLat + (t.lat - t.fromLat) * ease;
          const lon = t.fromLon + (t.lon - t.fromLon) * ease;
          display.current[drone.id] = { lat, lon };
          marker.setLatLng([lat, lon]);
        }
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    import("leaflet").then((leaflet) => {
      const L = leaflet.default ?? leaflet;
      const seen = new Set(drones.map((d) => d.id));
      const now = performance.now();

      for (const drone of drones) {
        const color = getHealthColor(drone.health);
        const shown = display.current[drone.id] || { lat: drone.lat, lon: drone.lon };
        if (!markers.current[drone.id]) {
          display.current[drone.id] = { lat: drone.lat, lon: drone.lon };
          markers.current[drone.id] = L.marker([drone.lat, drone.lon], {
            icon: makeIcon(L, drone, color),
            keyboard: true,
            title: drone.id,
            pane: "craft",
            riseOnHover: true,
          }).addTo(map);
        } else {
          markers.current[drone.id].setIcon(makeIcon(L, drone, color));
        }
        targets.current[drone.id] = {
          lat: drone.lat,
          lon: drone.lon,
          fromLat: shown.lat,
          fromLon: shown.lon,
          t0: now,
        };

        const latlngs = drone.path.map((p) => [p.lat, p.lon]);
        if (!paths.current[drone.id]) {
          paths.current[drone.id] = {
            casing: L.polyline(latlngs, {
              color: CASING,
              weight: 6,
              opacity: 0.8,
              lineCap: "round",
              lineJoin: "round",
              interactive: false,
              pane: "overlayPane",
            }).addTo(map),
            core: L.polyline(latlngs, {
              color,
              weight: 2.5,
              opacity: 0.95,
              lineCap: "round",
              lineJoin: "round",
              className: "dag-route",
              interactive: false,
              pane: "overlayPane",
            }).addTo(map),
          };
        } else {
          paths.current[drone.id].casing.setLatLngs(latlngs);
          paths.current[drone.id].core.setLatLngs(latlngs).setStyle({ color });
        }

        const detour = drone.reroutePath.map((p) => [p.lat, p.lon]);
        if (detour.length) {
          if (!reroutes.current[drone.id]) {
            reroutes.current[drone.id] = {
              casing: L.polyline(detour, {
                color: CASING,
                weight: 8,
                opacity: 0.85,
                lineCap: "round",
                lineJoin: "round",
                interactive: false,
                pane: "overlayPane",
              }).addTo(map),
              core: L.polyline(detour, {
                color: REROUTE,
                weight: 3.5,
                opacity: 1,
                dashArray: "10 9",
                lineCap: "butt",
                className: "dag-reroute",
                interactive: false,
                pane: "overlayPane",
              }).addTo(map),
            };
          } else {
            reroutes.current[drone.id].casing.setLatLngs(detour);
            reroutes.current[drone.id].core.setLatLngs(detour);
          }
        } else if (reroutes.current[drone.id]) {
          map.removeLayer(reroutes.current[drone.id].casing);
          map.removeLayer(reroutes.current[drone.id].core);
          delete reroutes.current[drone.id];
        }
      }

      for (const id of Object.keys(markers.current)) {
        if (seen.has(id)) continue;
        map.removeLayer(markers.current[id]);
        delete markers.current[id];
        delete targets.current[id];
        delete display.current[id];
        if (paths.current[id]) {
          map.removeLayer(paths.current[id].casing);
          map.removeLayer(paths.current[id].core);
          delete paths.current[id];
        }
        if (reroutes.current[id]) {
          map.removeLayer(reroutes.current[id].casing);
          map.removeLayer(reroutes.current[id].core);
          delete reroutes.current[id];
        }
      }

      const zoneIds = new Set(zones.map((z) => z.id));
      for (const zone of zones) {
        const emergency = zone.source === "emergency";
        const color = emergency ? EMERGENCY_ZONE : OPERATOR_ZONE;
        const existing = zoneLayers.current[zone.id];
        const moved =
          existing &&
          (existing.lat !== zone.lat || existing.lon !== zone.lon || existing.radius !== zone.radius);
        if (existing && moved) {
          map.removeLayer(existing.casing);
          map.removeLayer(existing.ring);
          if (existing.pulse) map.removeLayer(existing.pulse);
          delete zoneLayers.current[zone.id];
        }
        if (zoneLayers.current[zone.id]) continue;
        const center: [number, number] = [zone.lat, zone.lon];
        const casing = L.circle(center, {
          radius: zone.radius,
          color: CASING,
          weight: emergency ? 10 : 7,
          opacity: 0.6,
          fill: false,
          interactive: false,
          pane: "zones",
        }).addTo(map);
        // Fills stay faint by design: several overlapping rings must never mask the drones.
        const ring = L.circle(center, {
          radius: zone.radius,
          color,
          weight: emergency ? 3.5 : 2.5,
          opacity: 1,
          dashArray: emergency ? undefined : "10 8",
          fillColor: color,
          fillOpacity: emergency ? 0.1 : 0.05,
          interactive: false,
          className: emergency ? "dag-zone is-emergency" : "dag-zone",
          pane: "zones",
        }).addTo(map);
        const pulse = emergency
          ? L.circle(center, {
              radius: zone.radius,
              color: EMERGENCY_ZONE,
              weight: 2,
              fill: false,
              interactive: false,
              className: "dag-zone-pulse",
              pane: "zones",
            }).addTo(map)
          : undefined;
        zoneLayers.current[zone.id] = {
          casing,
          ring,
          pulse,
          lat: zone.lat,
          lon: zone.lon,
          radius: zone.radius,
        };
      }
      for (const id of Object.keys(zoneLayers.current)) {
        if (zoneIds.has(id)) continue;
        const layers = zoneLayers.current[id];
        map.removeLayer(layers.casing);
        map.removeLayer(layers.ring);
        if (layers.pulse) map.removeLayer(layers.pulse);
        delete zoneLayers.current[id];
      }
    });
  }, [drones, zones]);

  return (
    <div
      ref={el}
      className={`dag-map ${drawArmed ? "is-drawing" : ""}`}
      role="application"
      aria-label="Downtown Dubai airspace map"
    />
  );
}
