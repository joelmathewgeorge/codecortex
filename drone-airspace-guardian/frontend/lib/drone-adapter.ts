import type {
  AlertPayload,
  Coordinate,
  Drone,
  DroneBehavior,
  DroneStatus,
  NoFlyZone,
  VisionFrame,
  VisionMetrics,
  VisionTruthBox,
} from "@/types/airspace";
import { clampHealth, normalizeHeading } from "./health";

const BEHAVIORS: DroneBehavior[] = ["cruise", "orbit", "hold", "climb", "descend"];

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

function mapBehavior(raw: unknown): DroneBehavior | undefined {
  if (typeof raw !== "string") return undefined;
  const s = raw.trim().toLowerCase();
  return BEHAVIORS.find((b) => b === s);
}

/** Short free-text provenance ("opensky", "auair"). Bounded so a junk payload cannot blow up a row. */
function mapText(raw: unknown, max = 24): string | undefined {
  if (typeof raw !== "string") return undefined;
  const s = raw.trim();
  if (!s) return undefined;
  return s.slice(0, max);
}

function pick(rec: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    if (rec[key] !== undefined && rec[key] !== null) return rec[key];
  }
  return undefined;
}

function asFiniteNumber(raw: unknown): number | undefined {
  if (raw === null || raw === undefined || raw === "") return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

/** Returns a normalised [x1, y1, x2, y2] or null. Corners are sorted so width/height are never negative. */
function asBox(raw: unknown): number[] | null {
  if (!Array.isArray(raw) || raw.length < 4) return null;
  const nums = raw.slice(0, 4).map(Number);
  if (!nums.every((n) => Number.isFinite(n))) return null;
  const [a, b, c, d] = nums;
  const x1 = Math.min(a, c);
  const x2 = Math.max(a, c);
  const y1 = Math.min(b, d);
  const y2 = Math.max(b, d);
  if (x2 - x1 <= 0 || y2 - y1 <= 0) return null;
  return [x1, y1, x2, y2];
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
    speed: asFiniteNumber(rec.speed),
    alt: asFiniteNumber(rec.alt),
    behavior: mapBehavior(pick(rec, "behavior", "behaviour")),
    trackSource: mapText(pick(rec, "trackSource", "track_source", "source")),
  };
}

export function adaptDrones(raw: unknown): Drone[] {
  if (!Array.isArray(raw)) return [];
  return raw.map(adaptDrone).filter((d): d is Drone => d !== null);
}

export function adaptZones(raw: unknown): NoFlyZone[] {
  if (!Array.isArray(raw)) return [];
  const out: NoFlyZone[] = [];
  const seen = new Set<string>();
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const rec = item as Record<string, unknown>;
    const lat = Number(rec.lat);
    const lon = Number(rec.lon);
    const radius = Number(rec.radius);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(radius)) continue;
    const source = rec.emergency ? "emergency" : "operator";
    const id = String(rec.id || `${lat},${lon}`);
    // Repeated "Helicopter inbound" presses can re-declare the same circle. Collapse identical
    // rings so stacked fills never darken into an unreadable blob.
    const shape = `${source}:${lat.toFixed(5)}:${lon.toFixed(5)}:${Math.round(radius)}`;
    if (seen.has(id) || seen.has(shape)) continue;
    seen.add(id);
    seen.add(shape);
    out.push({ id, lat, lon, radius, source });
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

function adaptTruth(raw: unknown): VisionTruthBox[] {
  if (!Array.isArray(raw)) return [];
  const out: VisionTruthBox[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const rec = item as Record<string, unknown>;
    const xyxy = asBox(pick(rec, "xyxy", "bbox", "box"));
    if (!xyxy) continue;
    out.push({ label: String(rec.label || "object"), xyxy });
  }
  return out;
}

function adaptMetrics(raw: unknown): VisionMetrics | null {
  if (!raw || typeof raw !== "object") return null;
  const rec = raw as Record<string, unknown>;
  const metrics: VisionMetrics = {
    epochs: asFiniteNumber(rec.epochs),
    images: asFiniteNumber(pick(rec, "images", "image_count")),
    mAP50: asFiniteNumber(pick(rec, "mAP50", "map50", "mAP_50", "mAP@50")),
    model: mapText(rec.model, 40),
  };
  const hasAny = Object.values(metrics).some((v) => v !== undefined);
  return hasAny ? metrics : null;
}

function basename(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export function adaptVision(raw: unknown): VisionFrame | null {
  if (!raw || typeof raw !== "object") return null;
  const rec = raw as Record<string, unknown>;
  const image = typeof rec.image === "string" ? rec.image : "";
  if (!image) return null;
  const detections: VisionFrame["detections"] = [];
  if (Array.isArray(rec.detections)) {
    for (const item of rec.detections) {
      if (!item || typeof item !== "object") continue;
      const d = item as Record<string, unknown>;
      const xyxy = asBox(pick(d, "xyxy", "bbox", "box"));
      if (!xyxy) continue;
      detections.push({
        label: String(d.label || "object"),
        conf: Number(d.conf) || 0,
        xyxy,
      });
    }
  }
  const counts: Record<string, number> = {};
  if (rec.counts && typeof rec.counts === "object") {
    for (const [k, v] of Object.entries(rec.counts as Record<string, unknown>)) {
      counts[k] = Number(v) || 0;
    }
  }
  return {
    image,
    frame: mapText(rec.frame, 80) ?? basename(image),
    model: String(rec.model || "yolov8n"),
    ready: Boolean(rec.ready),
    detections,
    truth: adaptTruth(rec.truth),
    metrics: adaptMetrics(rec.metrics),
    counts,
    width: Number(rec.width) || 0,
    height: Number(rec.height) || 0,
  };
}
