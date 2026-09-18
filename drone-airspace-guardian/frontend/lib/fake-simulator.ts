import type { Coordinate, Drone, DroneBehavior, NoFlyZone } from "@/types/airspace";
import { DUBAI } from "./config";

const ROUTES: Coordinate[][] = [
  [
    { lat: 25.1972, lon: 55.2744 },
    { lat: 25.204, lon: 55.27 },
    { lat: 25.21, lon: 55.265 },
    { lat: 25.1972, lon: 55.2744 },
  ],
  [
    { lat: 25.189, lon: 55.282 },
    { lat: 25.193, lon: 55.276 },
    { lat: 25.198, lon: 55.269 },
    { lat: 25.189, lon: 55.282 },
  ],
  [
    { lat: 25.205, lon: 55.264 },
    { lat: 25.199, lon: 55.27 },
    { lat: 25.192, lon: 55.278 },
    { lat: 25.205, lon: 55.264 },
  ],
  [
    { lat: 25.186, lon: 55.268 },
    { lat: 25.192, lon: 55.274 },
    { lat: 25.199, lon: 55.28 },
    { lat: 25.186, lon: 55.268 },
  ],
  [
    { lat: 25.211, lon: 55.281 },
    { lat: 25.204, lon: 55.276 },
    { lat: 25.196, lon: 55.27 },
    { lat: 25.211, lon: 55.281 },
  ],
];

const NAMES = [
  "Marina clinic run",
  "Palm grocery drop",
  "Sheikh Zayed survey",
  "DIFC parts delivery",
  "Organ to Emirates Hospital",
];

const BEHAVIORS: DroneBehavior[] = ["cruise", "climb", "orbit", "cruise", "descend"];

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
    alt: [120, 95, 140, 110, 85][i],
    speed: [12, 9, 14, 11, 8][i],
    behavior: BEHAVIORS[i],
    // Mock mode is synthetic, and the provenance chip should say so rather than claim a dataset.
    trackSource: "sim",
  }));
}

export function stepMock(
  drones: Drone[],
  zones: NoFlyZone[],
  indices: number[],
): { drones: Drone[]; indices: number[] } {
  const nextIdx = [...indices];
  const next = drones.map((d, i) => {
    const path = d.path.length ? d.path : [{ lat: DUBAI.lat, lon: DUBAI.lon }];
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
      behavior: hit ? "orbit" : (BEHAVIORS[i] ?? "cruise"),
      reroutePath: hit
        ? [
            { lat, lon },
            { lat: hit.lat + 0.004, lon: hit.lon + 0.004 },
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
    lat: DUBAI.lat,
    lon: DUBAI.lon,
    radius: 900,
    source: "emergency",
  };
}
