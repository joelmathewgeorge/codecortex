# Drone Airspace Guardian Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-screen Next.js airspace dashboard that demonstrates five moving drones in offline simulation mode and can switch cleanly to Pranav's live WebSocket and HTTP backend.

**Architecture:** `AirspaceDashboard` owns application state and composes focused map and overlay components. Both mock and live data flow through a normalized `Drone` domain model; the backend wire format is isolated in `drone-adapter.ts`, while Leaflet is isolated behind a client-only `DroneMap` boundary.

**Tech Stack:** Next.js App Router, React, TypeScript, Leaflet, react-leaflet, native WebSocket, browser fetch, Vitest, React Testing Library, jsdom, ESLint, CSS

**Spec:** `docs/superpowers/specs/2026-09-18-drone-airspace-frontend-design.md`

## Global Constraints

- Keep every product-code change inside `drone-airspace-guardian/frontend/`; do not modify `backend/` or `ml/`.
- Center the initial map at latitude `12.9716`, longitude `77.5946`, zoom `13`.
- Default to `NEXT_PUBLIC_DATA_MODE=mock`; live mode uses `NEXT_PUBLIC_WS_URL` and `NEXT_PUBLIC_API_BASE_URL`.
- Use Leaflet with OpenStreetMap tiles and retain visible OpenStreetMap attribution.
- Use native browser WebSocket, not Socket.IO, unless the backend contract explicitly changes.
- Use a 1.5-second mock update interval, a 2-second live reconnect delay, and a 500-metre default no-fly-zone radius.
- Health is green above `70`, yellow from `30` through `70`, and red below `30`.
- All controls must be keyboard accessible, retain visible focus, and communicate state without relying on color alone.
- Respect `prefers-reduced-motion` and remain presentation-readable at `1920x1080` and `1366x768`.
- Never pass unvalidated backend data into map components.

## Planned File Structure

```text
drone-airspace-guardian/frontend/
├── .env.example                         # mock/live and backend URL examples
├── app/
│   ├── globals.css                      # full dashboard and marker styling
│   ├── layout.tsx                       # metadata and Leaflet CSS import
│   └── page.tsx                         # client-only dashboard entry
├── components/
│   ├── AirspaceDashboard.tsx            # state and operator workflow coordinator
│   ├── ConflictBanner.tsx               # affected-drone summary
│   ├── DroneMap.tsx                     # Leaflet map and click handling
│   ├── DroneMarker.tsx                  # interpolated directional marker
│   ├── DronePanel.tsx                   # drone status list
│   ├── ErrorNotice.tsx                  # dismissible request error
│   ├── MapControls.tsx                  # draw-zone and emergency controls
│   ├── MissionPath.tsx                  # normal and reroute polylines
│   └── NoFlyZoneLayer.tsx               # translucent zone circles
├── hooks/
│   ├── useDroneFeed.ts                  # mock/live feed selection and reconnect
│   └── useInterpolatedPosition.ts       # requestAnimationFrame movement
├── lib/
│   ├── api.ts                           # POST /zones and /emergency
│   ├── config.ts                        # numeric and environment constants
│   ├── drone-adapter.ts                 # unknown JSON to Drone[] validation
│   ├── fake-simulator.ts                # deterministic five-drone simulation
│   ├── geometry.ts                      # distance/conflict/reroute helpers
│   └── health.ts                        # clamp, heading, and health presentation
├── test/
│   └── setup.ts                         # jest-dom registration and cleanup
├── types/
│   └── airspace.ts                      # shared domain types
├── vitest.config.ts
└── package.json
```

---

### Task 1: Scaffold the App and Establish Domain Primitives

**Files:**
- Create: `drone-airspace-guardian/frontend/` with `create-next-app`
- Modify: `drone-airspace-guardian/frontend/package.json`
- Create: `drone-airspace-guardian/frontend/vitest.config.ts`
- Create: `drone-airspace-guardian/frontend/test/setup.ts`
- Create: `drone-airspace-guardian/frontend/types/airspace.ts`
- Create: `drone-airspace-guardian/frontend/lib/config.ts`
- Create: `drone-airspace-guardian/frontend/lib/health.ts`
- Create: `drone-airspace-guardian/frontend/lib/health.test.ts`
- Create: `drone-airspace-guardian/frontend/.env.example`

**Interfaces:**
- Consumes: no application code; uses the approved spec and global constraints.
- Produces: `Coordinate`, `Drone`, `DroneStatus`, `NoFlyZone`, `FeedState`, `DataMode`, `getHealthLevel()`, `getHealthColor()`, `clampHealth()`, `normalizeHeading()`, and shared configuration constants.

- [ ] **Step 1: Scaffold Next.js without prompting**

Run from `drone-airspace-guardian/`:

```powershell
Remove-Item -LiteralPath frontend\.gitkeep
npx create-next-app@latest frontend --ts --eslint --app --use-npm --no-tailwind --import-alias "@/*"
cd frontend
npm install leaflet react-leaflet
npm install --save-dev @types/leaflet vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

Expected: `frontend/package.json` exists and the install exits successfully.

- [ ] **Step 2: Add deterministic test configuration**

Add scripts to `package.json`:

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

Create `vitest.config.ts`:

```ts
import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./test/setup.ts"],
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, ".") },
  },
});
```

Create `test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);
```

- [ ] **Step 3: Write failing primitive tests**

Create `lib/health.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  clampHealth,
  getHealthColor,
  getHealthLevel,
  normalizeHeading,
} from "./health";

describe("health presentation", () => {
  it.each([
    [71, "healthy", "#35d07f"],
    [70, "warning", "#f7c948"],
    [30, "warning", "#f7c948"],
    [29, "critical", "#ff5b5b"],
  ] as const)("maps %i to %s", (health, level, color) => {
    expect(getHealthLevel(health)).toBe(level);
    expect(getHealthColor(health)).toBe(color);
  });

  it("clamps health and wraps headings", () => {
    expect(clampHealth(125)).toBe(100);
    expect(clampHealth(-5)).toBe(0);
    expect(normalizeHeading(-10)).toBe(350);
    expect(normalizeHeading(725)).toBe(5);
  });
});
```

- [ ] **Step 4: Run the test and confirm the expected failure**

Run:

```powershell
npm test -- lib/health.test.ts
```

Expected: FAIL because `lib/health.ts` does not exist.

- [ ] **Step 5: Implement the domain model and helpers**

Create `types/airspace.ts`:

```ts
export type DroneStatus = "normal" | "rerouting" | "landing";
export type FeedState = "simulation" | "connecting" | "live" | "disconnected";
export type DataMode = "mock" | "live";

export interface Coordinate { lat: number; lon: number }

export interface Drone extends Coordinate {
  id: string;
  heading: number;
  health: number;
  status: DroneStatus;
  affected: boolean;
  path: Coordinate[];
  reroutePath: Coordinate[];
}

export interface NoFlyZone extends Coordinate {
  id: string;
  radius: number;
  source: "operator" | "emergency";
  synchronized: boolean;
}
```

Create `lib/config.ts`:

```ts
import type { DataMode } from "@/types/airspace";

export const MAP_CENTER = { lat: 12.9716, lon: 77.5946 } as const;
export const MAP_ZOOM = 13;
export const ZONE_RADIUS_METRES = 500;
export const MOCK_TICK_MS = 1_500;
export const RECONNECT_DELAY_MS = 2_000;
export const MOVEMENT_DURATION_MS = 1_400;

export const DATA_MODE: DataMode =
  process.env.NEXT_PUBLIC_DATA_MODE === "live" ? "live" : "mock";
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
```

Create `lib/health.ts`:

```ts
export type HealthLevel = "healthy" | "warning" | "critical";

export function clampHealth(value: number): number {
  return Math.min(100, Math.max(0, value));
}

export function normalizeHeading(value: number): number {
  return ((value % 360) + 360) % 360;
}

export function getHealthLevel(health: number): HealthLevel {
  if (health > 70) return "healthy";
  if (health >= 30) return "warning";
  return "critical";
}

export function getHealthColor(health: number): string {
  return { healthy: "#35d07f", warning: "#f7c948", critical: "#ff5b5b" }[
    getHealthLevel(health)
  ];
}
```

Create `.env.example`:

```dotenv
NEXT_PUBLIC_DATA_MODE=mock
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

- [ ] **Step 6: Run tests, lint, and commit**

Run:

```powershell
npm test -- lib/health.test.ts
npm run lint
```

Expected: both commands PASS.

Commit:

```powershell
git add drone-airspace-guardian/frontend
git commit -m "chore: scaffold drone frontend"
```

---

### Task 2: Validate and Normalize Drone Feed Messages

**Files:**
- Create: `drone-airspace-guardian/frontend/lib/drone-adapter.ts`
- Create: `drone-airspace-guardian/frontend/lib/drone-adapter.test.ts`

**Interfaces:**
- Consumes: `Drone`, `Coordinate`, `DroneStatus`, `clampHealth()`, and `normalizeHeading()` from Task 1.
- Produces: `parseDroneMessage(raw: unknown): Drone[] | null`; this is the only function allowed to convert unknown WebSocket JSON into map-ready drones.

- [ ] **Step 1: Write adapter behavior tests**

Create `lib/drone-adapter.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parseDroneMessage } from "./drone-adapter";

const valid = {
  drones: [{
    id: "DG-01", lat: 12.9716, lon: 77.5946, heading: 370, health: 104,
    status: "rerouting", affected: true,
    path: [{ lat: 12.98, lon: 77.60 }],
    reroutePath: [{ lat: 12.975, lon: 77.61 }],
  }],
};

describe("parseDroneMessage", () => {
  it("normalizes a canonical drone envelope", () => {
    expect(parseDroneMessage(valid)).toEqual([{ ...valid.drones[0], heading: 10, health: 100 }]);
  });

  it.each([null, {}, { drones: "wrong" }, { drones: [{ id: "broken" }] }])(
    "rejects malformed payload %#",
    (payload) => expect(parseDroneMessage(payload)).toBeNull(),
  );
});
```

- [ ] **Step 2: Run the test and confirm it fails**

Run `npm test -- lib/drone-adapter.test.ts`.

Expected: FAIL because `parseDroneMessage` is missing.

- [ ] **Step 3: Implement strict boundary validation**

Create `lib/drone-adapter.ts` with small type guards:

```ts
import { clampHealth, normalizeHeading } from "./health";
import type { Coordinate, Drone, DroneStatus } from "@/types/airspace";

const statuses = new Set<DroneStatus>(["normal", "rerouting", "landing"]);
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const coordinate = (value: unknown): value is Coordinate => {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return finite(item.lat) && finite(item.lon);
};
const coordinates = (value: unknown): value is Coordinate[] =>
  Array.isArray(value) && value.every(coordinate);

function parseDrone(value: unknown): Drone | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  if (
    typeof item.id !== "string" || !finite(item.lat) || !finite(item.lon) ||
    !finite(item.heading) || !finite(item.health) ||
    typeof item.status !== "string" || !statuses.has(item.status as DroneStatus) ||
    typeof item.affected !== "boolean" || !coordinates(item.path) ||
    !coordinates(item.reroutePath)
  ) return null;
  return {
    id: item.id, lat: item.lat, lon: item.lon,
    heading: normalizeHeading(item.heading), health: clampHealth(item.health),
    status: item.status as DroneStatus, affected: item.affected,
    path: item.path, reroutePath: item.reroutePath,
  };
}

export function parseDroneMessage(raw: unknown): Drone[] | null {
  if (!raw || typeof raw !== "object") return null;
  const drones = (raw as Record<string, unknown>).drones;
  if (!Array.isArray(drones)) return null;
  const parsed = drones.map(parseDrone);
  return parsed.every((drone): drone is Drone => drone !== null) ? parsed : null;
}
```

- [ ] **Step 4: Verify and commit**

Run:

```powershell
npm test -- lib/drone-adapter.test.ts
npm run lint
```

Expected: PASS.

Commit:

```powershell
git add drone-airspace-guardian/frontend/lib
git commit -m "feat: validate drone feed messages"
```

---

### Task 3: Build Deterministic Simulation and Conflict Geometry

**Files:**
- Create: `drone-airspace-guardian/frontend/lib/geometry.ts`
- Create: `drone-airspace-guardian/frontend/lib/geometry.test.ts`
- Create: `drone-airspace-guardian/frontend/lib/fake-simulator.ts`
- Create: `drone-airspace-guardian/frontend/lib/fake-simulator.test.ts`

**Interfaces:**
- Consumes: domain types and Bengaluru constants from Task 1.
- Produces: `INITIAL_DRONES`, `advanceDrones(drones)`, `applyMockZone(drones, zone)`, `createMockEmergency(drones)`, `distanceMetres(a, b)`, and `pathIntersectsZone(path, zone)`.

- [ ] **Step 1: Write geometry and simulator tests**

Create `lib/geometry.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { distanceMetres, pathIntersectsZone } from "./geometry";

describe("airspace geometry", () => {
  it("measures nearby coordinates in metres", () => {
    expect(distanceMetres({ lat: 12.9716, lon: 77.5946 }, { lat: 12.9761, lon: 77.5946 }))
      .toBeGreaterThan(490);
  });
  it("detects a waypoint inside a zone", () => {
    expect(pathIntersectsZone(
      [{ lat: 12.9716, lon: 77.5946 }],
      { id: "z", lat: 12.9716, lon: 77.5946, radius: 500, source: "operator", synchronized: true },
    )).toBe(true);
  });
});
```

Create `lib/fake-simulator.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { INITIAL_DRONES, advanceDrones, createMockEmergency } from "./fake-simulator";

describe("fake simulator", () => {
  it("starts exactly five distinct Bengaluru drones", () => {
    expect(INITIAL_DRONES).toHaveLength(5);
    expect(new Set(INITIAL_DRONES.map((drone) => drone.id)).size).toBe(5);
  });
  it("moves drones toward their next waypoint", () => {
    expect(advanceDrones(INITIAL_DRONES)[0]).not.toMatchObject({
      lat: INITIAL_DRONES[0].lat,
      lon: INITIAL_DRONES[0].lon,
    });
  });
  it("creates a visible emergency conflict and reroute", () => {
    const result = createMockEmergency(INITIAL_DRONES);
    expect(result.zone.source).toBe("emergency");
    expect(result.drones.some((drone) => drone.affected && drone.reroutePath.length > 0)).toBe(true);
  });
});
```

- [ ] **Step 2: Confirm both tests fail**

Run `npm test -- lib/geometry.test.ts lib/fake-simulator.test.ts`.

Expected: FAIL because both modules are missing.

- [ ] **Step 3: Implement geometry**

Create `lib/geometry.ts`:

```ts
import type { Coordinate, NoFlyZone } from "@/types/airspace";

export function distanceMetres(a: Coordinate, b: Coordinate): number {
  const radians = (degrees: number) => degrees * Math.PI / 180;
  const dLat = radians(b.lat - a.lat);
  const dLon = radians(b.lon - a.lon);
  const lat1 = radians(a.lat);
  const lat2 = radians(b.lat);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 6_371_000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

export function pathIntersectsZone(path: Coordinate[], zone: NoFlyZone): boolean {
  return path.some((point) => distanceMetres(point, zone) <= zone.radius);
}
```

- [ ] **Step 4: Implement the simulator**

Create `lib/fake-simulator.ts` with five immutable seed routes near `MAP_CENTER`. Implement `advanceDrones()` by moving each drone 18% toward `path[0]`, shifting to the next waypoint when within 20 metres, and recalculating heading with `Math.atan2`. Implement `applyMockZone()` by using `pathIntersectsZone()` and, for affected drones, creating a two-point east-offset `reroutePath`, setting `affected: true` and `status: "rerouting"`. Implement `createMockEmergency()` with a 500-metre zone centered on the first drone's next waypoint:

```ts
export function createMockEmergency(drones: Drone[]): { drones: Drone[]; zone: NoFlyZone } {
  const target = drones[0].path[0] ?? drones[0];
  const zone: NoFlyZone = {
    id: `emergency-${Date.now()}`,
    ...target,
    radius: ZONE_RADIUS_METRES,
    source: "emergency",
    synchronized: true,
  };
  return { drones: applyMockZone(drones, zone), zone };
}
```

- [ ] **Step 5: Verify deterministic behavior and commit**

Run:

```powershell
npm test -- lib/geometry.test.ts lib/fake-simulator.test.ts
npm run lint
```

Expected: PASS with exactly five initial drones and at least one mock emergency conflict.

Commit:

```powershell
git add drone-airspace-guardian/frontend/lib
git commit -m "feat: add offline drone simulation"
```

---

### Task 4: Implement the Mock and Live Drone Feed Hook

**Files:**
- Create: `drone-airspace-guardian/frontend/hooks/useDroneFeed.ts`
- Create: `drone-airspace-guardian/frontend/hooks/useDroneFeed.test.tsx`

**Interfaces:**
- Consumes: `DataMode`, `Drone`, `FeedState`, `INITIAL_DRONES`, `advanceDrones()`, `parseDroneMessage()`, `MOCK_TICK_MS`, and `RECONNECT_DELAY_MS`.
- Produces: `useDroneFeed({ mode, wsUrl }): { drones, setDrones, feedState }`.

- [ ] **Step 1: Write feed lifecycle tests with a controllable WebSocket**

Create `hooks/useDroneFeed.test.tsx` using `renderHook`, fake timers, and a `FakeWebSocket` class that records instances and exposes `open()`, `message(value)`, and `close()` methods. Cover these exact assertions:

```ts
it("advances mock drones every 1.5 seconds", () => {
  const { result } = renderHook(() => useDroneFeed({ mode: "mock", wsUrl: "unused" }));
  const initialLat = result.current.drones[0].lat;
  act(() => vi.advanceTimersByTime(1_500));
  expect(result.current.feedState).toBe("simulation");
  expect(result.current.drones[0].lat).not.toBe(initialLat);
});

it("keeps the last valid live state and reconnects two seconds after close", () => {
  const { result, unmount } = renderHook(() => useDroneFeed({ mode: "live", wsUrl: "ws://test/ws" }));
  act(() => sockets[0].open());
  act(() => sockets[0].message(validEnvelope));
  act(() => sockets[0].message({ bad: true }));
  expect(result.current.drones).toEqual(expectedDrones);
  act(() => sockets[0].close());
  act(() => vi.advanceTimersByTime(1_999));
  expect(sockets).toHaveLength(1);
  act(() => vi.advanceTimersByTime(1));
  expect(sockets).toHaveLength(2);
  unmount();
  expect(sockets[1].readyState).toBe(FakeWebSocket.CLOSED);
});
```

- [ ] **Step 2: Run the test and confirm it fails**

Run `npm test -- hooks/useDroneFeed.test.tsx`.

Expected: FAIL because the hook does not exist.

- [ ] **Step 3: Implement feed selection and cleanup**

Create `hooks/useDroneFeed.ts`:

```ts
"use client";

import { useEffect, useState } from "react";
import { MOCK_TICK_MS, RECONNECT_DELAY_MS } from "@/lib/config";
import { parseDroneMessage } from "@/lib/drone-adapter";
import { advanceDrones, INITIAL_DRONES } from "@/lib/fake-simulator";
import type { DataMode, Drone, FeedState } from "@/types/airspace";

export function useDroneFeed({ mode, wsUrl }: { mode: DataMode; wsUrl: string }) {
  const [drones, setDrones] = useState<Drone[]>(INITIAL_DRONES);
  const [feedState, setFeedState] = useState<FeedState>(
    mode === "mock" ? "simulation" : "connecting",
  );

  useEffect(() => {
    if (mode !== "mock") return;
    setFeedState("simulation");
    const timer = window.setInterval(() => setDrones(advanceDrones), MOCK_TICK_MS);
    return () => window.clearInterval(timer);
  }, [mode]);

  useEffect(() => {
    if (mode !== "live") return;
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let stopped = false;
    const connect = () => {
      setFeedState("connecting");
      socket = new WebSocket(wsUrl);
      socket.onopen = () => setFeedState("live");
      socket.onmessage = (event) => {
        try {
          const parsed = parseDroneMessage(JSON.parse(event.data));
          if (parsed) setDrones(parsed);
          else console.warn("Ignored invalid drone message");
        } catch { console.warn("Ignored non-JSON drone message"); }
      };
      socket.onclose = () => {
        if (stopped) return;
        setFeedState("disconnected");
        retry = window.setTimeout(connect, RECONNECT_DELAY_MS);
      };
    };
    connect();
    return () => {
      stopped = true;
      if (retry !== undefined) window.clearTimeout(retry);
      socket?.close();
    };
  }, [mode, wsUrl]);

  return { drones, setDrones, feedState };
}
```

- [ ] **Step 4: Verify timers, reconnection, cleanup, and commit**

Run:

```powershell
npm test -- hooks/useDroneFeed.test.tsx
npm run lint
```

Expected: PASS with no pending timer warnings.

Commit:

```powershell
git add drone-airspace-guardian/frontend/hooks
git commit -m "feat: add resilient drone data feed"
```

---

### Task 5: Implement HTTP Operator Actions

**Files:**
- Create: `drone-airspace-guardian/frontend/lib/api.ts`
- Create: `drone-airspace-guardian/frontend/lib/api.test.ts`

**Interfaces:**
- Consumes: `Coordinate` and API base URL supplied by the caller.
- Produces: `createZone(apiBaseUrl, { lat, lon, radius }): Promise<void>` and `triggerEmergency(apiBaseUrl): Promise<void>`.

- [ ] **Step 1: Write request contract tests**

Create `lib/api.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createZone, triggerEmergency } from "./api";

beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true })));

it("posts the exact zone contract", async () => {
  await createZone("http://api", { lat: 12.97, lon: 77.59, radius: 500 });
  expect(fetch).toHaveBeenCalledWith("http://api/zones", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lat: 12.97, lon: 77.59, radius: 500 }),
  });
});

it("posts an empty emergency request", async () => {
  await triggerEmergency("http://api/");
  expect(fetch).toHaveBeenCalledWith("http://api/emergency", { method: "POST" });
});

it("throws a readable error for a failed response", async () => {
  vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 503 } as Response);
  await expect(triggerEmergency("http://api")).rejects.toThrow("Emergency request failed (503)");
});
```

- [ ] **Step 2: Run the test and confirm it fails**

Run `npm test -- lib/api.test.ts`.

Expected: FAIL because `lib/api.ts` does not exist.

- [ ] **Step 3: Implement the two requests**

Create `lib/api.ts`:

```ts
const base = (url: string) => url.replace(/\/$/, "");

export async function createZone(
  apiBaseUrl: string,
  zone: { lat: number; lon: number; radius: number },
): Promise<void> {
  const response = await fetch(`${base(apiBaseUrl)}/zones`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(zone),
  });
  if (!response.ok) throw new Error(`Zone request failed (${response.status})`);
}

export async function triggerEmergency(apiBaseUrl: string): Promise<void> {
  const response = await fetch(`${base(apiBaseUrl)}/emergency`, { method: "POST" });
  if (!response.ok) throw new Error(`Emergency request failed (${response.status})`);
}
```

- [ ] **Step 4: Verify and commit**

Run `npm test -- lib/api.test.ts` and `npm run lint`; expect PASS.

Commit:

```powershell
git add drone-airspace-guardian/frontend/lib/api.ts drone-airspace-guardian/frontend/lib/api.test.ts
git commit -m "feat: add airspace operator API client"
```

---

### Task 6: Build Dashboard Overlays and Controls

**Files:**
- Create: `drone-airspace-guardian/frontend/components/ConflictBanner.tsx`
- Create: `drone-airspace-guardian/frontend/components/DronePanel.tsx`
- Create: `drone-airspace-guardian/frontend/components/MapControls.tsx`
- Create: `drone-airspace-guardian/frontend/components/ErrorNotice.tsx`
- Create: `drone-airspace-guardian/frontend/components/dashboard-overlays.test.tsx`

**Interfaces:**
- Consumes: normalized `Drone[]`, `FeedState`, and callback props.
- Produces: accessible overlay components with no Leaflet dependency.

- [ ] **Step 1: Write component behavior tests**

Create `components/dashboard-overlays.test.tsx` with fixtures from `Drone` and these assertions:

```tsx
it("announces affected drone counts", () => {
  const { rerender } = render(<ConflictBanner affectedCount={1} />);
  expect(screen.getByRole("alert")).toHaveTextContent("rerouting 1 drone");
  rerender(<ConflictBanner affectedCount={2} />);
  expect(screen.getByRole("alert")).toHaveTextContent("rerouting 2 drones");
});

it("lists ID, health, and plain-language status", () => {
  render(<DronePanel drones={[reroutingDrone]} collapsed={false} onToggle={vi.fn()} />);
  expect(screen.getByText("DG-01")).toBeVisible();
  expect(screen.getByText("64% health")).toBeVisible();
  expect(screen.getByText("Rerouting")).toBeVisible();
});

it("toggles draw mode and prevents duplicate emergency requests", async () => {
  const user = userEvent.setup();
  const onDrawToggle = vi.fn();
  const onEmergency = vi.fn();
  render(<MapControls drawingZone={false} emergencyPending={true} onDrawToggle={onDrawToggle} onEmergency={onEmergency} />);
  await user.click(screen.getByRole("button", { name: /draw zone/i }));
  expect(onDrawToggle).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: /emergency/i })).toBeDisabled();
});
```

- [ ] **Step 2: Confirm tests fail**

Run `npm test -- components/dashboard-overlays.test.tsx`.

Expected: FAIL because the four components are missing.

- [ ] **Step 3: Implement semantic overlays**

Implement components with these signatures:

```ts
export function ConflictBanner({ affectedCount }: { affectedCount: number }): React.ReactNode;
export function DronePanel(props: {
  drones: Drone[]; collapsed: boolean; onToggle: () => void;
}): React.ReactNode;
export function MapControls(props: {
  drawingZone: boolean; emergencyPending: boolean;
  onDrawToggle: () => void; onEmergency: () => void;
}): React.ReactNode;
export function ErrorNotice(props: {
  message: string | null; onDismiss: () => void;
}): React.ReactNode;
```

Use `role="alert"` for conflicts and errors, `aria-expanded` for the panel toggle, `aria-pressed` for draw mode, and button text `🚨 Emergency: helicopter inbound`. Return `null` from `ConflictBanner` when `affectedCount === 0` and from `ErrorNotice` when `message === null`.

- [ ] **Step 4: Verify and commit**

Run `npm test -- components/dashboard-overlays.test.tsx` and `npm run lint`; expect PASS.

Commit:

```powershell
git add drone-airspace-guardian/frontend/components
git commit -m "feat: add airspace dashboard controls"
```

---

### Task 7: Animate Drone Coordinates

**Files:**
- Create: `drone-airspace-guardian/frontend/hooks/useInterpolatedPosition.ts`
- Create: `drone-airspace-guardian/frontend/hooks/useInterpolatedPosition.test.tsx`

**Interfaces:**
- Consumes: a target `Coordinate` and optional duration in milliseconds.
- Produces: `useInterpolatedPosition(target, duration): Coordinate`.

- [ ] **Step 1: Write animation tests with a mocked animation frame clock**

Create `hooks/useInterpolatedPosition.test.tsx` and mock `requestAnimationFrame` so callbacks receive timestamps `0`, `500`, and `1000`:

```ts
it("starts at the first coordinate and interpolates to a changed target", () => {
  const { result, rerender } = renderHook(
    ({ target }) => useInterpolatedPosition(target, 1_000),
    { initialProps: { target: { lat: 10, lon: 20 } } },
  );
  expect(result.current).toEqual({ lat: 10, lon: 20 });
  rerender({ target: { lat: 12, lon: 24 } });
  advanceAnimationFrame(500);
  expect(result.current).toEqual({ lat: 11, lon: 22 });
  advanceAnimationFrame(1_000);
  expect(result.current).toEqual({ lat: 12, lon: 24 });
});

it("cancels the pending frame on unmount", () => {
  const { unmount } = renderHook(() => useInterpolatedPosition({ lat: 10, lon: 20 }, 1_000));
  unmount();
  expect(cancelAnimationFrame).toHaveBeenCalled();
});
```

- [ ] **Step 2: Confirm the test fails**

Run `npm test -- hooks/useInterpolatedPosition.test.tsx`.

Expected: FAIL because the hook is missing.

- [ ] **Step 3: Implement requestAnimationFrame interpolation**

Create `hooks/useInterpolatedPosition.ts`:

```ts
"use client";
import { useEffect, useRef, useState } from "react";
import type { Coordinate } from "@/types/airspace";

export function useInterpolatedPosition(target: Coordinate, duration: number): Coordinate {
  const [displayed, setDisplayed] = useState(target);
  const current = useRef(target);
  useEffect(() => {
    const start = current.current;
    let frame = 0;
    let started: number | null = null;
    const tick = (time: number) => {
      started ??= time;
      const progress = Math.min(1, (time - started) / duration);
      const next = {
        lat: start.lat + (target.lat - start.lat) * progress,
        lon: start.lon + (target.lon - start.lon) * progress,
      };
      current.current = next;
      setDisplayed(next);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target.lat, target.lon, duration]);
  return displayed;
}
```

- [ ] **Step 4: Verify and commit**

Run `npm test -- hooks/useInterpolatedPosition.test.tsx` and `npm run lint`; expect PASS.

Commit:

```powershell
git add drone-airspace-guardian/frontend/hooks
git commit -m "feat: animate drone movement"
```

---

### Task 8: Render the Leaflet Map, Markers, Paths, and Zones

**Files:**
- Create: `drone-airspace-guardian/frontend/components/DroneMarker.tsx`
- Create: `drone-airspace-guardian/frontend/components/MissionPath.tsx`
- Create: `drone-airspace-guardian/frontend/components/NoFlyZoneLayer.tsx`
- Create: `drone-airspace-guardian/frontend/components/DroneMap.tsx`
- Create: `drone-airspace-guardian/frontend/components/DroneMap.test.tsx`

**Interfaces:**
- Consumes: `Drone[]`, `NoFlyZone[]`, `drawingZone`, `onMapClick(coordinate)`, health helpers, map constants, and interpolated positions.
- Produces: the complete Leaflet visualization surface.

- [ ] **Step 1: Write a Leaflet-mocked map smoke test**

In `components/DroneMap.test.tsx`, mock `react-leaflet` components as semantic test elements and capture `useMapEvents` handlers. Assert:

```tsx
it("renders one marker, its paths, zones, attribution tile layer, and forwards armed clicks", async () => {
  const onMapClick = vi.fn();
  render(<DroneMap drones={[affectedDrone]} zones={[zone]} drawingZone onMapClick={onMapClick} />);
  expect(screen.getByTestId("map-container")).toHaveAttribute("data-center", "12.9716,77.5946");
  expect(screen.getByTestId("tile-layer")).toHaveAttribute("data-attribution", expect.stringContaining("OpenStreetMap"));
  expect(screen.getAllByTestId("marker")).toHaveLength(1);
  expect(screen.getAllByTestId("polyline")).toHaveLength(2);
  expect(screen.getAllByTestId("circle")).toHaveLength(1);
  act(() => capturedClick({ latlng: { lat: 12.98, lng: 77.60 } }));
  expect(onMapClick).toHaveBeenCalledWith({ lat: 12.98, lon: 77.60 });
});
```

- [ ] **Step 2: Confirm the smoke test fails**

Run `npm test -- components/DroneMap.test.tsx`.

Expected: FAIL because the map components are missing.

- [ ] **Step 3: Implement focused Leaflet layers**

Implement:

```tsx
// MissionPath.tsx
export function MissionPath({ drone }: { drone: Drone }) {
  const color = getHealthColor(drone.health);
  return <>
    {drone.path.length > 0 && <Polyline positions={drone.path.map(p => [p.lat, p.lon])} pathOptions={{ color, weight: 2, opacity: 0.65 }} />}
    {drone.reroutePath.length > 0 && <Polyline positions={drone.reroutePath.map(p => [p.lat, p.lon])} pathOptions={{ color: "#ff6b35", weight: 4, dashArray: "10 8" }} />}
  </>;
}

// NoFlyZoneLayer.tsx
export function NoFlyZoneLayer({ zone }: { zone: NoFlyZone }) {
  return <Circle center={[zone.lat, zone.lon]} radius={zone.radius} pathOptions={{ color: zone.synchronized ? "#ff5b5b" : "#f7c948", fillColor: "#ff5b5b", fillOpacity: 0.18, dashArray: zone.synchronized ? undefined : "6 6" }} />;
}
```

In `DroneMarker.tsx`, create a memoized `L.divIcon` containing an arrow rotated by `drone.heading`, a health-color CSS custom property, a visible drone ID, and class `drone-marker--affected` when needed. Pass the coordinate returned by `useInterpolatedPosition(drone, MOVEMENT_DURATION_MS)` to `<Marker>`.

- [ ] **Step 4: Implement the map shell and armed click handler**

In `DroneMap.tsx`, render `MapContainer` with `MAP_CENTER`, `MAP_ZOOM`, `zoomControl={false}`, and `className` reflecting draw mode. Add `TileLayer` with URL `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` and attribution `&copy; OpenStreetMap contributors`. A nested `MapClickHandler` must call `onMapClick({ lat, lon: lng })` only when `drawingZone` is true. Render each drone's `MissionPath` before its `DroneMarker`, then all `NoFlyZoneLayer` instances.

- [ ] **Step 5: Verify and commit**

Run:

```powershell
npm test -- components/DroneMap.test.tsx
npm run lint
```

Expected: PASS.

Commit:

```powershell
git add drone-airspace-guardian/frontend/components
git commit -m "feat: render live airspace map"
```

---

### Task 9: Orchestrate Zone, Emergency, and Feed State

**Files:**
- Create: `drone-airspace-guardian/frontend/components/AirspaceDashboard.tsx`
- Create: `drone-airspace-guardian/frontend/components/AirspaceDashboard.test.tsx`
- Modify: `drone-airspace-guardian/frontend/app/page.tsx`
- Modify: `drone-airspace-guardian/frontend/app/layout.tsx`

**Interfaces:**
- Consumes: all hooks, API functions, overlay components, `DroneMap`, and configuration.
- Produces: the complete interactive application entry point.

- [ ] **Step 1: Write dashboard workflow tests with the map mocked**

Mock `DroneMap` as a button that calls `onMapClick({ lat: 12.98, lon: 77.60 })`. Mock `useDroneFeed` with five drones and a `setDrones` spy. Test both modes:

```tsx
it("creates a local zone, exits draw mode, and evaluates mock conflicts", async () => {
  const user = userEvent.setup();
  render(<AirspaceDashboard mode="mock" />);
  await user.click(screen.getByRole("button", { name: /draw zone/i }));
  expect(screen.getByRole("button", { name: /cancel zone drawing/i })).toHaveAttribute("aria-pressed", "true");
  await user.click(screen.getByRole("button", { name: /mock map click/i }));
  expect(mockSetDrones).toHaveBeenCalled();
  expect(screen.getByRole("button", { name: /draw zone/i })).toHaveAttribute("aria-pressed", "false");
});

it("posts live zones and marks a failed optimistic zone unsynchronized", async () => {
  mockCreateZone.mockRejectedValueOnce(new Error("Zone request failed (503)"));
  render(<AirspaceDashboard mode="live" />);
  // enter draw mode and click the mocked map
  expect(await screen.findByRole("alert")).toHaveTextContent("Zone request failed (503)");
  expect(mockCreateZone).toHaveBeenCalledWith(expect.any(String), { lat: 12.98, lon: 77.60, radius: 500 });
});

it("runs the offline emergency demonstration and blocks duplicate live requests", async () => {
  const user = userEvent.setup();
  const { rerender } = render(<AirspaceDashboard mode="mock" />);
  await user.click(screen.getByRole("button", { name: /emergency/i }));
  expect(mockCreateMockEmergency).toHaveBeenCalledOnce();
  expect(mockSetDrones).toHaveBeenCalled();

  let resolveRequest!: () => void;
  mockTriggerEmergency.mockReturnValueOnce(new Promise<void>((resolve) => { resolveRequest = resolve; }));
  rerender(<AirspaceDashboard mode="live" />);
  await user.click(screen.getByRole("button", { name: /emergency/i }));
  expect(screen.getByRole("button", { name: /emergency/i })).toBeDisabled();
  resolveRequest();
  expect(await screen.findByRole("button", { name: /emergency/i })).toBeEnabled();
});

it("cancels draw mode with Escape", async () => {
  const user = userEvent.setup();
  render(<AirspaceDashboard mode="mock" />);
  await user.click(screen.getByRole("button", { name: /draw zone/i }));
  await user.keyboard("{Escape}");
  expect(screen.getByRole("button", { name: /draw zone/i })).toHaveAttribute("aria-pressed", "false");
});
```

- [ ] **Step 2: Confirm workflow tests fail**

Run `npm test -- components/AirspaceDashboard.test.tsx`.

Expected: FAIL because `AirspaceDashboard` is missing.

- [ ] **Step 3: Implement dashboard state and actions**

Create `components/AirspaceDashboard.tsx` as a client component. It must:

```ts
const { drones, setDrones, feedState } = useDroneFeed({ mode, wsUrl: WS_URL });
const [zones, setZones] = useState<NoFlyZone[]>([]);
const [drawingZone, setDrawingZone] = useState(false);
const [panelCollapsed, setPanelCollapsed] = useState(false);
const [emergencyPending, setEmergencyPending] = useState(false);
const [error, setError] = useState<string | null>(null);
const affectedCount = drones.filter((drone) => drone.affected).length;
```

`handleMapClick` creates an optimistic operator zone with `crypto.randomUUID()`. In mock mode, set synchronized true and call `setDrones(current => applyMockZone(current, zone))`. In live mode, append with synchronized false, await `createZone`, then replace that zone with `{ ...zone, synchronized: true }`; preserve the unsynchronized zone and show the thrown message on failure. Always exit draw mode after a click.

`handleEmergency` uses `createMockEmergency()` in mock mode. In live mode, set `emergencyPending`, await `triggerEmergency`, show errors, and reset pending in `finally`. An effect listens for Escape only while drawing and cancels draw mode.

Render title, feed-state badge, simulation label when applicable, `DroneMap`, `DronePanel`, `ConflictBanner`, `MapControls`, `ErrorNotice`, and a visible health/route legend.

- [ ] **Step 4: Install the client-only page boundary**

Update `app/page.tsx`:

```tsx
"use client";

import dynamic from "next/dynamic";
import { DATA_MODE } from "@/lib/config";

const AirspaceDashboard = dynamic(
  () => import("@/components/AirspaceDashboard").then((module) => module.AirspaceDashboard),
  { ssr: false },
);

export default function Home() {
  return <AirspaceDashboard mode={DATA_MODE} />;
}
```

Update `app/layout.tsx` to import `leaflet/dist/leaflet.css` and set metadata title `Drone Airspace Guardian` and description `Live drone conflict and rerouting simulation`.

- [ ] **Step 5: Verify workflows, lint, and build**

Run:

```powershell
npm test -- components/AirspaceDashboard.test.tsx
npm run lint
npm run build
```

Expected: all PASS; the build must not report `window is not defined`.

- [ ] **Step 6: Commit**

```powershell
git add drone-airspace-guardian/frontend
git commit -m "feat: orchestrate airspace dashboard"
```

---

### Task 10: Apply Presentation Styling and Accessibility

**Files:**
- Modify: `drone-airspace-guardian/frontend/app/globals.css`
- Modify: `drone-airspace-guardian/frontend/components/AirspaceDashboard.tsx`
- Modify: `drone-airspace-guardian/frontend/components/ConflictBanner.tsx`
- Modify: `drone-airspace-guardian/frontend/components/DronePanel.tsx`
- Modify: `drone-airspace-guardian/frontend/components/ErrorNotice.tsx`
- Modify: `drone-airspace-guardian/frontend/components/MapControls.tsx`
- Create: `drone-airspace-guardian/frontend/components/accessibility.test.tsx`

**Interfaces:**
- Consumes: the complete semantic component tree from Tasks 6–9.
- Produces: projector-ready responsive visuals, marker animations, keyboard focus, and reduced-motion behavior.

- [ ] **Step 1: Add accessibility regression tests**

Create `components/accessibility.test.tsx`:

```tsx
it("labels feed state, controls, legend, and panel toggle", () => {
  render(<AirspaceDashboard mode="mock" />);
  expect(screen.getByText("Simulation")).toBeVisible();
  expect(screen.getByRole("button", { name: /draw zone/i })).toBeVisible();
  expect(screen.getByRole("button", { name: /emergency/i })).toBeVisible();
  expect(screen.getByRole("button", { name: /collapse drone panel/i })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByLabelText(/map legend/i)).toHaveTextContent("Healthy");
});
```

- [ ] **Step 2: Confirm the regression test fails on missing labels**

Run `npm test -- components/accessibility.test.tsx`.

Expected: FAIL for any labels not yet connected.

- [ ] **Step 3: Replace generated CSS with the dashboard visual system**

In `app/globals.css`, define:

```css
:root {
  --panel: rgba(9, 18, 31, 0.92);
  --panel-border: rgba(255, 255, 255, 0.14);
  --text: #f4f8ff;
  --muted: #a8b4c8;
  --accent: #55d6ff;
  --danger: #ff4d57;
}
* { box-sizing: border-box; }
html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; }
body { color: var(--text); background: #07111f; font-family: Arial, Helvetica, sans-serif; }
button { font: inherit; }
button:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
.dashboard, .map-shell, .leaflet-container { width: 100vw; height: 100vh; }
.dashboard__overlay { position: absolute; z-index: 1000; }
.drone-marker { transform-origin: center; color: var(--health-color); }
.drone-marker--affected::before { animation: conflict-pulse 1.2s ease-out infinite; }
@keyframes conflict-pulse { from { transform: scale(.8); opacity: 1; } to { transform: scale(2.1); opacity: 0; } }
@media (max-width: 760px), (max-height: 700px) { .drone-panel { max-height: 44vh; } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.001ms !important; animation-iteration-count: 1 !important; transition-duration: 0.001ms !important; }
  .drone-marker--affected { outline: 4px solid var(--danger); }
}
```

Complete the classes for the translucent panel, feed badge states, conflict banner slide-in, legend, responsive panel overlay, active draw cursor, map controls, error notice, health dots, route swatches, and marker arrow/label. Use minimum 44px button hit targets and at least 16px body text for primary controls.

- [ ] **Step 4: Add any missing semantic labels and verify**

Connect `aria-label="Map legend"`, feed badge text, panel `aria-expanded`, active draw instructions, and status text so the test passes without selecting by CSS class.

Run:

```powershell
npm test -- components/accessibility.test.tsx
npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add drone-airspace-guardian/frontend
git commit -m "style: polish airspace presentation"
```

---

### Task 11: Full Verification and Demo Runbook

**Files:**
- Modify: `drone-airspace-guardian/frontend/README.md`
- Modify: `drone-airspace-guardian/frontend/.env.example` only if verification finds a mismatch

**Interfaces:**
- Consumes: the finished dashboard and all configuration variables.
- Produces: reproducible setup/demo instructions and final verification evidence.

- [ ] **Step 1: Run the complete automated suite**

Run from `drone-airspace-guardian/frontend/`:

```powershell
npm test
npm run lint
npm run build
```

Expected: all tests pass, ESLint reports no errors, and Next.js produces a successful production build.

- [ ] **Step 2: Start mock mode and manually verify the primary demo**

Run:

```powershell
$env:NEXT_PUBLIC_DATA_MODE='mock'
npm run dev
```

Verify in a browser at both `1920x1080` and `1366x768`:

1. The map starts over Bengaluru and displays OpenStreetMap attribution.
2. Exactly five drones move smoothly and show IDs, headings, health colors, and solid paths.
3. The side panel matches map state and can collapse.
4. Drawing two zones leaves both visible and exits draw mode after each click.
5. Escape and a second click on the active Draw button both cancel drawing.
6. Emergency creates a temporary danger zone, conflict banner, pulsing affected marker, and dashed reroute.
7. Reduced-motion mode removes pulsing while leaving affected outlines visible.

- [ ] **Step 3: Verify backend-offline live behavior**

Stop the server, then run:

```powershell
$env:NEXT_PUBLIC_DATA_MODE='live'
$env:NEXT_PUBLIC_WS_URL='ws://localhost:65530/ws'
$env:NEXT_PUBLIC_API_BASE_URL='http://localhost:65530'
npm run dev
```

Expected: the dashboard stays rendered with its last/initial positions, the feed badge cycles through connecting/disconnected as retries occur, and failed zone/emergency actions show dismissible errors without crashing.

- [ ] **Step 4: Document exact local and live startup commands**

Replace the generated `frontend/README.md` with sections `Setup`, `Mock demo`, `Live backend`, `Environment variables`, `Demo sequence`, and `Verification`. Include:

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

Document the canonical live envelope expected by `drone-adapter.ts`, the `{ lat, lon, radius }` zone body, the empty `POST /emergency`, and the note that only `lib/drone-adapter.ts` should change when Pranav supplies different field names.

- [ ] **Step 5: Run final verification after documentation**

Run:

```powershell
npm test
npm run lint
npm run build
git diff --check
git status --short
```

Expected: tests/lint/build/diff checks PASS; status shows only intended frontend and plan/spec changes.

- [ ] **Step 6: Commit the verified deliverable**

```powershell
git add drone-airspace-guardian/frontend docs/superpowers
git commit -m "docs: add drone frontend demo runbook"
```

## Completion Checklist

- [ ] Five simulated drones move smoothly over Bengaluru.
- [ ] Health thresholds, heading, paths, affected state, and status panel agree.
- [ ] Zone drawing works repeatedly and can be cancelled.
- [ ] Emergency mode produces an obvious offline demonstration.
- [ ] Native WebSocket reconnects after two seconds and retains valid state.
- [ ] Live zone and emergency requests match the documented contract.
- [ ] Malformed feed data and HTTP failures do not crash the UI.
- [ ] Projector and reduced-motion checks pass.
- [ ] `npm test`, `npm run lint`, `npm run build`, and `git diff --check` pass.
