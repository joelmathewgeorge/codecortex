import type { AlertPayload, Coordinate, Drone, DroneStatus, NoFlyZone } from "@/types/airspace";
import { clampHealth, normalizeHeading } from "./health";

function asCoords(raw: unknown): Coordinate[] {
  if (!Array.isArray(raw)) return [];
  const out: Coordinate[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const rec = item as Record<string, unknown>;
    const lat = Number(rec.lat);
    const lon = Number(rec.lon);
    if (Number.isFinite(lat) && Number.isFinite(lon)) out.push({ lat, lon });
  }
  return out;
}

function mapStatus(raw: unknown): DroneStatus {
  const s = String(raw || "normal").toLowerCase();
  if (s.includes("rerout")) return "rerouting";
  if (s.includes("land")) return "landing";
  return "normal";
}

export function adaptDrone(raw: unknown): Drone | null {
  if (!raw || typeof raw !== "object") return null;
  const rec = raw as Record<string, unknown>;
  const id = String(rec.id || "");
  const lat = Number(rec.lat);
  const lon = Number(rec.lon);
  if (!id || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return {
    id,
    lat,
    lon,
    heading: normalizeHeading(rec.heading),
    health: clampHealth(rec.health),
    status: mapStatus(rec.status),
    affected: Boolean(rec.affected) || mapStatus(rec.status) === "rerouting",
    path: asCoords(rec.path),
    reroutePath: asCoords(rec.reroutePath),
    mission: typeof rec.mission === "string" ? rec.mission : undefined,
    speed: Number.isFinite(Number(rec.speed)) ? Number(rec.speed) : undefined,
    alt: Number.isFinite(Number(rec.alt)) ? Number(rec.alt) : undefined,
  };
}

export function adaptDrones(raw: unknown): Drone[] {
  if (!Array.isArray(raw)) return [];
  return raw.map(adaptDrone).filter((d): d is Drone => d !== null);
}

export function adaptZones(raw: unknown): NoFlyZone[] {
  if (!Array.isArray(raw)) return [];
  const out: NoFlyZone[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const rec = item as Record<string, unknown>;
    const lat = Number(rec.lat);
    const lon = Number(rec.lon);
    const radius = Number(rec.radius);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(radius)) continue;
    out.push({
      id: String(rec.id || `${lat},${lon}`),
      lat,
      lon,
      radius,
      source: rec.emergency ? "emergency" : "operator",
    });
  }
  return out;
}

export function adaptAlert(raw: unknown): AlertPayload | null {
  if (!raw || typeof raw !== "object") return null;
  const rec = raw as Record<string, unknown>;
  if (rec.type !== "alert") return null;
  const ids = Array.isArray(rec.affected_drones)
    ? rec.affected_drones.map(String)
    : [];
  const message =
    typeof rec.message === "string"
      ? rec.message
      : ids.length
        ? `Airspace conflict — rerouting ${ids.length} drone(s)`
        : "Emergency declared";
  return { message, affectedIds: ids };
}
