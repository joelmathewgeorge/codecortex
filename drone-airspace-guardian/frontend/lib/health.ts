export type HealthLevel = "healthy" | "watch" | "critical";

export function clampHealth(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

export function normalizeHeading(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return 0;
  return ((n % 360) + 360) % 360;
}

export function getHealthLevel(health: number): HealthLevel {
  if (health > 70) return "healthy";
  if (health >= 30) return "watch";
  return "critical";
}

export function getHealthColor(health: number): string {
  const level = getHealthLevel(health);
  if (level === "healthy") return "#1ad1c4";
  if (level === "watch") return "#e0b84a";
  return "#ff6b7a";
}

export function getHealthLabel(health: number): string {
  const level = getHealthLevel(health);
  if (level === "healthy") return "Healthy";
  if (level === "watch") return "Watch";
  return "Critical";
}
