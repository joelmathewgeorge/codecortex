export const DUBAI = { lat: 25.1972, lon: 55.2744, zoom: 14 };
export const BENGALURU = DUBAI; // leftover alias — demo is Dubai
export const DEFAULT_ZONE_RADIUS_M = 450;
export const EMERGENCY_RADIUS_M = 900;
export const MOCK_TICK_MS = 1500;
export const LIVE_RECONNECT_MS = 2000;
export const INTERPOLATION_MS = 1000;

/** The aerial plates are context under the vector layers, so they sit well below full strength. */
export const AERIAL_OVERLAY_OPACITY = 0.22;
export const LABEL_LAYER_OPACITY = 0.7;

export const DUBAI_TILES = [
  { src: "/dubai/tile-a.png", bounds: [[25.1972, 55.2624], [25.2092, 55.2744]] as [[number, number], [number, number]] },
  { src: "/dubai/tile-b.png", bounds: [[25.1972, 55.2744], [25.2092, 55.2864]] as [[number, number], [number, number]] },
  { src: "/dubai/tile-c.png", bounds: [[25.1852, 55.2624], [25.1972, 55.2744]] as [[number, number], [number, number]] },
  { src: "/dubai/tile-d.png", bounds: [[25.1852, 55.2744], [25.1972, 55.2864]] as [[number, number], [number, number]] },
];

export function getDataMode(): "mock" | "live" {
  return process.env.NEXT_PUBLIC_DATA_MODE === "mock" ? "mock" : "live";
}

export function getApiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
}

export function getWsUrl(): string {
  return process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:8000/ws";
}
