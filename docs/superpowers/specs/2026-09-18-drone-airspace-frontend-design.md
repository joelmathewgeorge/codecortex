# Drone Airspace Guardian Frontend Design

**Date:** 2026-09-18  
**Status:** Approved
**Scope:** `drone-airspace-guardian/frontend/` only

## Purpose

Build a presentation-ready frontend for the Drone Airspace Guardian hackathon project. The application will visualize simulated or live drones on an interactive map, make health and conflict state immediately visible, let an operator create no-fly zones, and provide a one-click emergency demonstration.

The frontend must remain fully demonstrable without the backend. A fake in-browser simulator and the live backend will implement the same frontend-facing data-source interface, allowing the active source to change without changing map components.

## Success Criteria

- The application opens as a full-screen airspace dashboard centered on Bengaluru at latitude `12.9716`, longitude `77.5946`, zoom `13`.
- Five drones move smoothly along visible mission paths when mock mode is active.
- Drone health is legible at a glance: green above `70`, yellow from `30` through `70`, and red below `30`.
- Operators can place multiple fixed-radius no-fly zones and trigger an emergency from obvious controls.
- Affected drones pulse, their reroutes are visible, and a prominent conflict banner reports the number affected.
- The UI remains usable when the backend is unavailable and clearly labels whether it is using simulated data, connecting, live, or disconnected.
- The production build, lint checks, and focused logic/component tests pass.

## Technology Choices

- Next.js App Router with TypeScript
- React
- Leaflet with `react-leaflet`
- OpenStreetMap raster tiles
- Native browser `WebSocket`
- Browser `fetch` for HTTP endpoints
- CSS animations and `requestAnimationFrame` for movement
- Vitest, React Testing Library, and jsdom for unit and component tests

No external map account, API key, global state library, or Socket.IO dependency will be required. If the backend later chooses Socket.IO, only the live feed implementation will change.

## Page Layout

The dashboard occupies the full viewport.

- **Map:** The primary background and largest visual element.
- **Top-left:** Product title, `Simulation` label, and feed connection state.
- **Left side:** Collapsible drone panel showing ID, health, and status.
- **Top-center:** Animated red conflict banner, displayed only while drones are affected.
- **Bottom-left:** Compact health and route legend.
- **Bottom-right:** `Draw zone` control and the visually dominant `🚨 Emergency: helicopter inbound` button.

Controls will use large text and high-contrast surfaces suitable for viewing on a projector. On narrow screens, the drone panel becomes an overlay rather than reducing the map width.

## Frontend Domain Model

Map components consume normalized frontend types rather than backend payloads directly.

```ts
type DroneStatus = "normal" | "rerouting" | "landing";

type Coordinate = {
  lat: number;
  lon: number;
};

type Drone = {
  id: string;
  lat: number;
  lon: number;
  heading: number;
  health: number;
  status: DroneStatus;
  affected: boolean;
  path: Coordinate[];
  reroutePath: Coordinate[];
};

type NoFlyZone = {
  id: string;
  lat: number;
  lon: number;
  radius: number;
  source: "operator" | "emergency";
};

type FeedState = "simulation" | "connecting" | "live" | "disconnected";
```

Health values are clamped to `0–100`, headings are normalized to `0–359`, and malformed drone records are rejected at the feed boundary rather than passed to the map.

## Architecture and Components

`AirspaceDashboard` owns the normalized drone collection, visible zones, draw-mode state, feed state, and operator actions. It composes focused components:

- `DroneMap` owns Leaflet setup, the Bengaluru view, map-click handling, and map layers.
- `DroneMarker` renders one directional health-colored marker and its affected-state pulse.
- `MissionPath` renders a thin solid normal path and a dashed reroute path.
- `NoFlyZoneLayer` renders translucent red/orange circles.
- `DronePanel` renders the operational list of drones.
- `ConflictBanner` summarizes active conflicts.
- `MapControls` exposes zone drawing and emergency actions.

Browser-only Leaflet components will be loaded without server-side rendering to avoid access to `window` during Next.js server rendering.

Supporting modules remain independent of presentation:

- `fake-simulator` produces deterministic initial drones and periodic position updates.
- `drone-adapter` validates and normalizes live messages into the frontend domain model.
- `api` sends zone and emergency HTTP requests.
- `useDroneFeed` selects the feed, manages WebSocket lifecycle, and exposes feed state.
- `useInterpolatedPosition` animates each marker from its previous coordinate to its latest coordinate.

## Data Sources and Configuration

The application supports two modes selected by `NEXT_PUBLIC_DATA_MODE`:

- `mock`: use the local five-drone simulator; this is the safe default.
- `live`: connect to `NEXT_PUBLIC_WS_URL` and use `NEXT_PUBLIC_API_BASE_URL` for HTTP actions.

An `.env.example` will document all three values. The live feed owns a single browser WebSocket, parses each incoming JSON message, passes it through `drone-adapter`, and publishes only validated normalized drones. Unexpected messages are ignored and reported in the browser console without destroying the last valid map state.

When a live connection closes, the feed enters `disconnected` state and retries after two seconds. Unmounting the dashboard closes the socket and cancels retries. The UI retains the most recent valid drone positions while reconnecting.

The backend's exact field names are intentionally isolated inside `drone-adapter`. The canonical frontend model above remains stable when Pranav supplies the final wire payload.

## Mock Simulation

Mock mode starts five drones on short routes within the visible Bengaluru map area. Each drone has a distinct ID, heading, health value, status, path, and initial coordinate. A timer advances them every 1.5 seconds along straight segments and loops or progresses to the next waypoint.

The simulator is deterministic enough for repeatable tests and presentation rehearsal. Health may vary gradually but will not flicker randomly on every React render. Mock mode can demonstrate conflict styling by marking drones affected when their projected route enters a locally drawn zone; live mode treats the backend as authoritative for conflict and reroute state.

## Map Rendering and Movement

The base map uses OpenStreetMap tiles with the required attribution. Each drone marker is a lightweight HTML-based Leaflet icon so color, rotation, and pulse animation can be controlled with CSS.

On a new feed update, `useInterpolatedPosition` animates from the displayed coordinate to the new coordinate using `requestAnimationFrame`. The animation duration follows the expected feed interval and is capped so delayed messages do not cause indefinitely moving markers. A newly discovered drone appears immediately at its first coordinate. Removed drones disappear on the next valid feed update.

Normal remaining paths use thin solid lines in the drone's health color. Reroute paths use thicker dashed red/orange lines. Affected markers receive a pulsing red outer ring while preserving their health-colored center.

## No-Fly Zone Workflow

Pressing `Draw zone` arms a one-click placement mode and changes the cursor/instruction state. The next map click:

1. Creates an optimistic fixed-radius zone at that coordinate.
2. Exits draw mode.
3. In live mode, sends `POST /zones` with JSON `{ "lat": number, "lon": number, "radius": number }`.
4. In mock mode, evaluates projected paths locally so the demo behaves without a backend.

The initial radius is `500` metres and is defined as a single configurable frontend constant. Several zones may remain visible simultaneously. If the live request fails, the optimistic zone is marked as unsynchronized and a concise error notice appears; the rest of the dashboard remains interactive.

## Emergency Workflow

Pressing `🚨 Emergency: helicopter inbound` sends `POST /emergency` in live mode. The button is disabled only while that request is in flight, preventing accidental duplicate requests while keeping the map active.

In mock mode, the action creates a temporary danger zone near active drone paths, marks intersecting drones affected, and supplies a visible reroute so the full presentation can be rehearsed offline. A failed live request produces a dismissible error notice and does not invent a successful emergency response.

## Conflict Presentation

When one or more drones have `affected: true`, an animated banner reads `⚠ Airspace conflict — rerouting N drone(s)`. The banner disappears after the feed reports no affected drones. Affected markers pulse continuously and their dashed reroute paths remain visible for as long as the affected state is active.

The drone panel mirrors the same state with plain-language statuses: `Normal`, `Rerouting`, or `Landing`. Color is never the only state indicator.

## Error Handling

- Tile-loading or attribution behavior remains Leaflet's responsibility; application controls stay usable if individual tiles are slow.
- Invalid feed messages do not replace the last valid state.
- WebSocket disconnections trigger the two-second retry loop and visible connection state.
- HTTP failures display a small dismissible notice near the controls.
- Repeated button presses cannot create concurrent emergency requests.
- Zone placement can be cancelled by pressing the active `Draw zone` control again or pressing Escape.
- Leaflet is loaded only in the browser, avoiding server-render failures.

## Accessibility and Presentation Requirements

- All controls are reachable by keyboard and have visible focus states.
- Buttons include text labels rather than icon-only meanings.
- Health and conflict states use text or shapes in addition to color.
- The map container, overlays, and controls maintain readable contrast.
- Fonts and primary controls remain readable at common presentation resolutions, including `1920×1080` and `1366×768`.
- Motion respects `prefers-reduced-motion`; affected state remains visible without pulsing when reduced motion is requested.

## Testing Strategy

Focused automated tests will cover:

- Health thresholds and input clamping.
- Heading normalization.
- Feed-message validation and normalization.
- Mock simulator progression.
- WebSocket reconnect scheduling and cleanup using fake timers/mocks.
- No-fly-zone request bodies and HTTP failure behavior.
- Conflict banner count and singular/plural wording.
- Drone panel rendering for normal, rerouting, and landing states.

Because Leaflet depends on browser layout APIs, map integration will receive a component smoke test with Leaflet mocked, followed by manual browser verification. Completion also requires passing lint checks and a production Next.js build.

## Delivery Boundaries

All implementation changes remain under `drone-airspace-guardian/frontend/`, apart from the repository-level design and implementation-plan documents. No backend or ML files will be modified.

The first delivery is independently demonstrable in mock mode. Live integration uses the configurable boundary described above; incorporating Pranav's final field names changes only `drone-adapter` and, if Socket.IO is selected, the live feed transport.
