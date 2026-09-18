export type DroneStatus = "normal" | "rerouting" | "landing";

export type Coordinate = {
  lat: number;
  lon: number;
};

export type Drone = {
  id: string;
  lat: number;
  lon: number;
  heading: number;
  health: number;
  status: DroneStatus;
  affected: boolean;
  path: Coordinate[];
  reroutePath: Coordinate[];
  mission?: string;
  speed?: number;
  alt?: number;
};

export type NoFlyZone = {
  id: string;
  lat: number;
  lon: number;
  radius: number;
  source: "operator" | "emergency";
};

export type FeedState = "simulation" | "connecting" | "live" | "disconnected";

export type DataMode = "mock" | "live";

export type AlertPayload = {
  message: string;
  affectedIds: string[];
};
