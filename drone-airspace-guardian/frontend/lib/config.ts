/** Fallback view until /world answers; the map then fits the real operating box. */
export const DUBAI_CENTER = { lat: 25.16, lon: 55.265, zoom: 12 };

export const INTERPOLATION_MS = 1000;
export const LIVE_RECONNECT_MS = 2000;
export const EVENT_BUFFER = 2000;

export const EMERGENCY_RADII = [500, 700, 1000, 1400];

export function getApiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
}

export function getWsUrl(): string {
  return process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:8000/ws";
}

export function mediaUrl(path: string): string {
  return path.startsWith("http") ? path : `${getApiBase()}${path}`;
}
