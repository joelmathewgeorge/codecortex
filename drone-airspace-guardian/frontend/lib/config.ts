export const BENGALURU = { lat: 12.9716, lon: 77.5946, zoom: 13 };
export const DEFAULT_ZONE_RADIUS_M = 500;
export const MOCK_TICK_MS = 1500;
export const LIVE_RECONNECT_MS = 2000;
export const INTERPOLATION_MS = 1000;

export function getDataMode(): "mock" | "live" {
  return process.env.NEXT_PUBLIC_DATA_MODE === "mock" ? "mock" : "live";
}

export function getApiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
}

export function getWsUrl(): string {
  return process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:8000/ws";
}
