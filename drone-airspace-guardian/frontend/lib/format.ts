import type { AirspaceEvent, AirspaceStatus, Drone, GroundLevel, Severity } from "@/types/airspace";

export function clock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "--:--:--" : d.toLocaleTimeString("en-GB", { hour12: false });
}

export function simClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return `T+${h ? `${h}:` : ""}${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

export function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${String(s % 60).padStart(2, "0")} s`;
}

export function km(meters: number): string {
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
}

export const STATUS_COLOR: Record<AirspaceStatus, string> = {
  SAFE: "#1ad1c4",
  CAUTION: "#e0b84a",
  CONFLICT: "#ff8a3d",
  EMERGENCY: "#ff4d63",
};

export const SEVERITY_COLOR: Record<Severity, string> = {
  info: "#8fa3c8",
  success: "#1ad1c4",
  warning: "#e0b84a",
  alert: "#ff8a3d",
  critical: "#ff4d63",
};

export const GROUND_COLOR: Record<GroundLevel, string> = {
  LOW: "#1ad1c4",
  MEDIUM: "#e0b84a",
  HIGH: "#ff8a3d",
  "VERY HIGH": "#ff4d63",
};

export const PRIORITY_ORDER = { CRITICAL: 0, HIGH: 1, NORMAL: 2, LOW: 3 } as const;

/** Event families for the log filters, keyed by the backend event type. */
export const EVENT_GROUPS: { id: string; label: string; types: string[] }[] = [
  {
    id: "conflict",
    label: "Conflicts",
    types: [
      "CONFLICT_PREDICTED",
      "DECONFLICTION_STARTED",
      "ALTITUDE_MANEUVER",
      "HOLD_MANEUVER",
      "DETOUR_MANEUVER",
      "CONFLICT_RESOLVED",
      "CONFLICT_UNRESOLVED",
    ],
  },
  { id: "emergency", label: "Emergencies", types: ["EMERGENCY_CREATED", "EMERGENCY_ESCAPE_STARTED", "EMERGENCY_ESCAPE_COMPLETED"] },
  {
    id: "route",
    label: "Routing",
    types: ["ROUTE_GENERATED", "REROUTE_STARTED", "REROUTE_COMPLETED", "NO_FLY_AVOIDED", "ZONE_CREATED", "ZONE_CLEARED"],
  },
  {
    id: "health",
    label: "Health and battery",
    types: ["RUL_UPDATED", "HEALTH_DEGRADED", "CRITICAL_HEALTH", "LOW_BATTERY", "CRITICAL_BATTERY"],
  },
  { id: "aircraft", label: "Manned aircraft", types: ["AIRCRAFT_DETECTED", "AIRCRAFT_CONFLICT", "AIRCRAFT_CONFLICT_RESOLVED"] },
  { id: "ground", label: "Ground risk", types: ["GROUND_RISK_DETECTED", "GROUND_RISK_CLEARED"] },
  { id: "fleet", label: "Fleet", types: ["DRONE_ADDED", "MISSION_COMPLETED", "MISSION_ABORTED", "SIM_RESET"] },
];

const GROUP_OF = new Map(EVENT_GROUPS.flatMap((g) => g.types.map((t) => [t, g.id] as const)));

export function eventGroup(e: AirspaceEvent): string {
  return GROUP_OF.get(e.type) ?? "fleet";
}

/** "CONFLICT_PREDICTED" -> "Conflict predicted" */
export function eventName(type: string): string {
  const s = type.toLowerCase().replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function droneState(d: Drone): string {
  if (d.phase === "charging") return d.battery >= 95 ? "At port" : `Charging ${Math.round(d.battery)}%`;
  if (d.phase === "landed") return "Delivering";
  if (d.maneuver) return d.maneuver.label;
  if (d.phase === "escaping") return "Escaping emergency";
  if (d.phase === "rejoining") return "Rejoining route";
  if (d.phase === "returning") return `Returning to ${d.destination}`;
  return "En route";
}
