import type { Coordinate, Drone, NoFlyZone } from "@/types/airspace";
import { BENGALURU } from "./config";

const ROUTES: Coordinate[][] = [
  [
    { lat: 12.9716, lon: 77.5946 },
    { lat: 12.978, lon: 77.59 },
    { lat: 12.985, lon: 77.585 },
    { lat: 12.9716, lon: 77.5946 },
  ],
  [
    { lat: 12.96, lon: 77.58 },
    { lat: 12.965, lon: 77.59 },
    { lat: 12.97, lon: 77.6 },
    { lat: 12.96, lon: 77.58 },
  ],
  [
    { lat: 12.98, lon: 77.61 },
    { lat: 12.975, lon: 77.6 },
    { lat: 12.968, lon: 77.592 },
    { lat: 12.98, lon: 77.61 },
  ],
  [
    { lat: 12.955, lon: 77.6 },
    { lat: 12.962, lon: 77.605 },
    { lat: 12.97, lon: 77.598 },
    { lat: 12.955, lon: 77.6 },
  ],
  [
    { lat: 12.99, lon: 77.58 },
    { lat: 12.984, lon: 77.588 },
    { lat: 12.976, lon: 77.595 },
    { lat: 12.99, lon: 77.58 },
  ],
];

const NAMES = [
  "Delivery A — Medical Supplies",
  "Delivery B — Food Package",
  "Survey — Traffic Monitoring",
  "Delivery C — Electronics",
  "Emergency — Organ Transport",
];

export function createMockDrones(): Drone[] {
  return ROUTES.map((path, i) => ({
    id: `drone-${i + 1}`,
    lat: path[0].lat,
    lon: path[0].lon,
    heading: 0,
    health: [92, 74, 61, 81, 38][i],
    status: "normal" as const,
    affected: false,
    path,
    reroutePath: [],
    mission: NAMES[i],
  }));
}

export function stepMock(
  drones: Drone[],
  zones: NoFlyZone[],
  indices: number[],
): { drones: Drone[]; indices: number[] } {
  const nextIdx = [...indices];
  const next = drones.map((d, i) => {
    const path = d.path.length ? d.path : [{ lat: BENGALURU.lat, lon: BENGALURU.lon }];
    const idx = nextIdx[i] ?? 0;
    const a = path[idx % path.length];
    const b = path[(idx + 1) % path.length];
    const lat = a.lat + (b.lat - a.lat) * 0.35;
    const lon = a.lon + (b.lon - a.lon) * 0.35;
    const dist = Math.hypot(b.lat - lat, b.lon - lon);
    if (dist < 0.0008) nextIdx[i] = (idx + 1) % path.length;
    const hit = zones.find((z) => {
      const dy = (lat - z.lat) * 111_320;
      const dx = (lon - z.lon) * 111_320 * Math.cos((lat * Math.PI) / 180);
      return Math.hypot(dx, dy) < z.radius;
    });
    return {
      ...d,
      lat,
      lon,
      heading: (Math.atan2(b.lon - a.lon, b.lat - a.lat) * 180) / Math.PI,
      affected: Boolean(hit),
      status: hit ? "rerouting" : "normal",
      reroutePath: hit
        ? [
            { lat, lon },
            { lat: hit.lat + 0.008, lon: hit.lon + 0.008 },
            b,
          ]
        : [],
    } satisfies Drone;
  });
  return { drones: next, indices: nextIdx };
}

export function mockEmergencyZone(): NoFlyZone {
  return {
    id: "emergency-mock",
    lat: 12.9716,
    lon: 77.5946,
    radius: 700,
    source: "emergency",
  };
}
