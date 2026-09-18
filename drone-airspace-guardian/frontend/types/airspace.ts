export type DroneStatus = "normal" | "rerouting" | "landing";

export type DroneBehavior = "cruise" | "orbit" | "hold" | "climb" | "descend";

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
  behavior?: DroneBehavior;
  trackSource?: string;
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

export type VisionDetection = {
  label: string;
  conf: number;
  xyxy: number[];
};

/** VisDrone ground-truth box for the current frame. No confidence: it is a label, not a guess. */
export type VisionTruthBox = {
  label: string;
  xyxy: number[];
};

export type VisionMetrics = {
  epochs?: number;
  images?: number;
  mAP50?: number;
  model?: string;
};

export type VisionFrame = {
  image: string;
  frame: string;
  model: string;
  ready: boolean;
  detections: VisionDetection[];
  truth: VisionTruthBox[];
  metrics: VisionMetrics | null;
  counts: Record<string, number>;
  width: number;
  height: number;
};
