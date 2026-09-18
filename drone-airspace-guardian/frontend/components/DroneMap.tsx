"use client";

import { useEffect, useRef } from "react";
import type { Drone, NoFlyZone } from "@/types/airspace";
import { BENGALURU } from "@/lib/config";
import { getHealthColor } from "@/lib/health";

type Props = {
  drones: Drone[];
  zones: NoFlyZone[];
  drawArmed: boolean;
  onMapClick: (lat: number, lon: number) => void;
};

export default function DroneMap({ drones, zones, drawArmed, onMapClick }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const markers = useRef<Record<string, any>>({});
  const paths = useRef<Record<string, any>>({});
  const reroutes = useRef<Record<string, any>>({});
  const zoneLayers = useRef<Record<string, any>>({});
  const clickRef = useRef(onMapClick);
  clickRef.current = onMapClick;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const leaflet = await import("leaflet");
      const L = leaflet.default ?? leaflet;
      if (cancelled || !el.current || mapRef.current) return;
      const map = L.map(el.current, { zoomControl: true }).setView(
        [BENGALURU.lat, BENGALURU.lon],
        BENGALURU.zoom,
      );
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap",
      }).addTo(map);
      map.on("click", (e: any) => clickRef.current(e.latlng.lat, e.latlng.lng));
      mapRef.current = map;
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    import("leaflet").then((leaflet) => {
      const L = leaflet.default ?? leaflet;
      const seen = new Set(drones.map((d) => d.id));
      for (const drone of drones) {
        const color = getHealthColor(drone.health);
        const html = `<div class="dag-marker ${drone.affected ? "is-affected" : ""}" style="--h:${drone.heading}deg;--c:${color}"><i></i></div>`;
        if (!markers.current[drone.id]) {
          const icon = L.divIcon({ className: "dag-icon", html, iconSize: [22, 22], iconAnchor: [11, 11] });
          markers.current[drone.id] = L.marker([drone.lat, drone.lon], { icon, keyboard: true, title: drone.id }).addTo(map);
        } else {
          markers.current[drone.id].setLatLng([drone.lat, drone.lon]);
          markers.current[drone.id].setIcon(L.divIcon({ className: "dag-icon", html, iconSize: [22, 22], iconAnchor: [11, 11] }));
        }
        const latlngs = drone.path.map((p) => [p.lat, p.lon]);
        if (!paths.current[drone.id]) {
          paths.current[drone.id] = L.polyline(latlngs, { color, weight: 2, opacity: 0.55 }).addTo(map);
        } else {
          paths.current[drone.id].setLatLngs(latlngs).setStyle({ color });
        }
        const detour = drone.reroutePath.map((p) => [p.lat, p.lon]);
        if (detour.length) {
          if (!reroutes.current[drone.id]) {
            reroutes.current[drone.id] = L.polyline(detour, {
              color: "#ff8a3d",
              weight: 3,
              dashArray: "8 6",
            }).addTo(map);
          } else {
            reroutes.current[drone.id].setLatLngs(detour);
          }
        } else if (reroutes.current[drone.id]) {
          map.removeLayer(reroutes.current[drone.id]);
          delete reroutes.current[drone.id];
        }
      }
      for (const id of Object.keys(markers.current)) {
        if (!seen.has(id)) {
          map.removeLayer(markers.current[id]);
          delete markers.current[id];
        }
      }

      const zoneIds = new Set(zones.map((z) => z.id));
      for (const zone of zones) {
        const color = zone.source === "emergency" ? "#ff4d5a" : "#ff9f43";
        if (!zoneLayers.current[zone.id]) {
          zoneLayers.current[zone.id] = L.circle([zone.lat, zone.lon], {
            radius: zone.radius,
            color,
            fillColor: color,
            fillOpacity: 0.18,
            weight: 2,
          }).addTo(map);
        }
      }
      for (const id of Object.keys(zoneLayers.current)) {
        if (!zoneIds.has(id)) {
          map.removeLayer(zoneLayers.current[id]);
          delete zoneLayers.current[id];
        }
      }
    });
  }, [drones, zones]);

  return <div ref={el} className={`dag-map ${drawArmed ? "is-drawing" : ""}`} role="application" aria-label="Airspace map" />;
}
