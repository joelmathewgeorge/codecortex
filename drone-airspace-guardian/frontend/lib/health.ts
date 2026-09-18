/** Bands match the ML side (ml/cmapss.py health_status): 75 / 50 / 25. */
export type HealthLevel = "healthy" | "monitor" | "service" | "critical";

export function getHealthLevel(health: number): HealthLevel {
  if (health >= 75) return "healthy";
  if (health >= 50) return "monitor";
  if (health >= 25) return "service";
  return "critical";
}

const HEALTH_COLOR: Record<HealthLevel, string> = {
  healthy: "#1ad1c4",
  monitor: "#b8d65a",
  service: "#e0b84a",
  critical: "#ff6b7a",
};

const HEALTH_LABEL: Record<HealthLevel, string> = {
  healthy: "Healthy",
  monitor: "Monitor",
  service: "Service soon",
  critical: "Ground now",
};

export function getHealthColor(health: number): string {
  return HEALTH_COLOR[getHealthLevel(health)];
}

export function getHealthLabel(health: number): string {
  return HEALTH_LABEL[getHealthLevel(health)];
}

export function getBatteryColor(battery: number): string {
  if (battery >= 50) return "#1ad1c4";
  if (battery >= 20) return "#e0b84a";
  return "#ff6b7a";
}
