/** Wire types for the FastAPI backend (see backend/main.py for the message shapes). */

export type LatLon = [number, number];

export type Priority = "CRITICAL" | "HIGH" | "NORMAL" | "LOW";

export type DronePhase = "cruise" | "holding" | "escaping" | "rejoining" | "returning" | "landed" | "charging";

export type ConflictMark = "none" | "predicted" | "resolving" | "resolved";

export type Maneuver = {
  kind: string;
  label: string;
  conflict?: string | null;
  hazard?: string;
};

export type Drone = {
  id: string;
  lat: number;
  lon: number;
  alt: number;
  heading: number;
  speed: number;
  vspeed: number;
  battery: number;
  health: number;
  rul: number;
  healthStatus: "healthy" | "monitor" | "service_soon" | "ground_now";
  priority: Priority;
  missionType: string;
  mission: string;
  origin: string;
  destination: string;
  home: string;
  phase: DronePhase;
  conflict: ConflictMark;
  maneuver: Maneuver | null;
  routeKind: string;
  route: LatLon[];
  original: LatLon[] | null;
  cruiseAlt: number;
  etaS: number;
  distanceLeftM: number;
  abortReason: string | null;
};

export type Zone = {
  id: string;
  kind: "operator" | "emergency";
  lat: number;
  lon: number;
  radius: number;
  buffer: number;
  label: string;
  createdAt: number;
};

export type Aircraft = {
  id: string;
  callsign: string;
  kind: "airliner" | "helicopter";
  source: "opensky-live" | "opensky-replay" | "scheduled";
  country: string;
  lat: number;
  lon: number;
  alt: number;
  speed: number;
  heading: number;
  vrate: number;
  relevant: boolean;
  risk: "LOW" | "MEDIUM" | "HIGH";
  distanceKm: number | null;
  nearestDrone: string | null;
  predicted: LatLon[];
  trail: LatLon[];
  volumeM: number | null;
  verticalSepM: number;
};

export type Conflict = {
  id: string;
  kind: "drone" | "aircraft";
  a: string;
  b: string;
  bLabel: string;
  state: "predicted" | "resolving" | "resolved" | "unresolved";
  ttc: number;
  lat: number;
  lon: number;
  minH: number;
  dz: number;
  yielding: string | null;
  maneuver: string | null;
  observedMinH: number | null;
};

export type Crossing = {
  a: string;
  b: string;
  lat: number;
  lon: number;
  dt: number;
  dalt: number;
  inS: number;
  status: "conflict" | "altitude" | "time" | "watch";
};

export type GroundLevel = "LOW" | "MEDIUM" | "HIGH" | "VERY HIGH";

export type Box = { label: string; xyxy: number[]; conf?: number };

export type GroundSite = {
  id: string;
  name: string;
  road: string;
  lat: number;
  lon: number;
  radius: number;
  level: GroundLevel;
  score: number | null;
  counts: Record<string, number>;
  cost: number;
  image: string | null;
  frame: string | null;
  width: number | null;
  height: number | null;
  truth: Box[];
  detections: Box[];
  telemetry: {
    gps: { lat: number; lon: number; alt_m: number } | null;
    velocity: { x: number; y: number; z: number } | null;
    time: string | null;
  } | null;
  scoredBy: string;
  dataset: string;
  updatedAt: number;
  model?: string;
  metrics?: { model?: string; mAP50?: number; epochs?: number; images?: number } | null;
};

export type AirspaceStatus = "SAFE" | "CAUTION" | "CONFLICT" | "EMERGENCY";

export type Hud = {
  status: AirspaceStatus;
  activeDrones: number;
  totalDrones: number;
  activeAircraft: number;
  lowAircraft: number;
  predictedConflicts: number;
  unresolvedConflicts: number;
  resolvedConflicts: number;
  noFlyZones: number;
  operatorZones: number;
  emergencyZones: number;
  escaping: number;
  avgHealth: number | null;
  avgRul: number | null;
  avgBattery: number | null;
  groundAlerts: number;
  riskLevel: number;
  riskLabel: string;
};

export type SimState = {
  type: "state";
  t: number;
  speed: number;
  tick: number;
  drones: Drone[];
  zones: Zone[];
  aircraft: Aircraft[];
  conflicts: Conflict[];
  crossings: Crossing[];
  ground: GroundSite[];
  feed: GroundSite | null;
  hud: Hud;
  airTraffic: { mode: string; status: string };
  healthModel: { name: string; live: boolean };
};

export type Severity = "info" | "success" | "warning" | "alert" | "critical";

export type AirspaceEvent = {
  id: number;
  timestamp: string;
  simTime: number;
  type: string;
  severity: Severity;
  droneId: string | null;
  droneIds: string[];
  message: string;
  metadata: Record<string, unknown>;
};

export type RestrictedArea = {
  id: string;
  name: string;
  category: string;
  polygon: LatLon[];
  bufferM: number;
  bufferCost: number;
  buffer: LatLon[];
};

export type Place = { id: string; name: string; kind: string; lat: number; lon: number };

export type World = {
  bounds: { south: number; west: number; north: number; east: number };
  source: string;
  license: string;
  restricted: RestrictedArea[];
  ports: Place[];
  hospitals: Place[];
  crowds: Place[];
  groundSites: { id: string; name: string; road: string; lat: number; lon: number; radius: number }[];
  planner: {
    cellM: number;
    droneSeparation: { horizontalM: number; verticalM: number };
    aircraftSeparation: Record<string, { horizontalM: number; verticalM: number }>;
    predictionHorizonS: number;
    altitudeBandM: [number, number];
    costs: Record<string, number | string>;
    emergencyRadiusM: number;
    operatorRadiusM: number;
    simSpeeds: number[];
  };
};

export type FeedState = "connecting" | "live" | "disconnected";
