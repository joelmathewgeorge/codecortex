// server/simulation.js
// Owns the list of simulated drones and advances their positions each tick.
// No physical drones involved -- everything here is a simulated object.

const airspace = require('./airspace');
const { pushEvent } = require('./events');
const opensky = require('./data/opensky');
const maintenance = require('./data/maintenance');
const groundZones = require('./data/groundZones');

let drones = [];
let nextId = 1;

// A drone "lives" this many real seconds per real engine's full recorded
// lifecycle -- short enough that degradation is visible during a demo,
// long enough to not be instant.
const SECONDS_PER_LIFECYCLE = 90;
const GROUND_ZONE_RADIUS = 60; // world units -- advisory trigger distance

function randomPointOutsideZones() {
  let x, y, tries = 0;
  do {
    x = Math.random() * 1000;
    y = Math.random() * 1000;
    tries++;
  } while (airspace.pointInAnyZone(x, y, airspace.getAllZones()) && tries < 50);
  return { x, y };
}

// Builds a drone whose path/altitude/speed come from a real recorded
// OpenSky ADS-B trajectory instead of a random A*-routed start/end pair.
// opensky.pickRealTrajectory() returns waypoints relative to (0,0); anchor
// them at a real valid spot in the world, clamped to stay in bounds.
function buildRealFlightPlan() {
  const real = opensky.pickRealTrajectory();
  if (!real) return null;

  const anchor = randomPointOutsideZones();
  const clamp = (v) => Math.max(40, Math.min(960, v));
  const waypoints = real.waypoints.map(p => ({
    x: clamp(anchor.x + p.x),
    y: clamp(anchor.y + p.y),
  }));

  return {
    start: waypoints[0],
    destination: waypoints[waypoints.length - 1],
    path: waypoints.slice(1),
    altitude: real.altitude,
    speed: real.speed,
    mission: `Real flight replay (OpenSky ${real.callsign})`,
  };
}

function createDrone(opts = {}) {
  const id = opts.id || `D${String(nextId++).padStart(2, '0')}`;

  const realPlan = opts.real ? buildRealFlightPlan() : null;
  const start = realPlan?.start || opts.start || randomPointOutsideZones();
  const destination = realPlan?.destination || opts.destination || randomPointOutsideZones();
  const path = realPlan?.path || airspace.findPath(start, destination);
  const altitude = opts.altitude || realPlan?.altitude || (80 + Math.floor(Math.random() * 5) * 10);
  const engine = maintenance.assignEngine();

  const drone = {
    id,
    x: start.x,
    y: start.y,
    altitude,
    speed: opts.speed || realPlan?.speed || (18 + Math.random() * 12), // world units / second
    battery: 100,
    engineId: engine?.engineId || null, // real C-MAPSS engine driving this drone's health
    flightSeconds: 0,
    destination,
    path,
    pathIndex: 0,
    priority: opts.priority || 'normal', // normal | high | critical
    mission: realPlan?.mission || opts.mission || 'Delivery',
    status: 'active', // active | rerouting | low-battery | arrived
    conflict: false,
    delayUntil: 0,
    arrivedAt: null,
    _engine: engine,
    _visitedGroundZones: new Set(),
  };

  drones.push(drone);
  pushEvent(`${drone.id} mission started (${drone.mission}, priority: ${drone.priority})`, 'info');
  return drone;
}

function removeDrone(id) {
  drones = drones.filter(d => d.id !== id);
}

function stepDrone(drone, dt) {
  if (drone.status === 'arrived') return;
  if (Date.now() < drone.delayUntil) return; // waiting out an imposed delay

  const target = drone.path[drone.pathIndex];
  if (!target) {
    drone.status = 'arrived';
    drone.arrivedAt = Date.now();
    return;
  }

  const dx = target.x - drone.x;
  const dy = target.y - drone.y;
  const dist = Math.hypot(dx, dy);
  const step = drone.speed * dt;

  if (dist < step || dist === 0) {
    drone.x = target.x;
    drone.y = target.y;
    drone.pathIndex++;
    if (drone.pathIndex >= drone.path.length) {
      drone.status = 'arrived';
      drone.arrivedAt = Date.now();
      pushEvent(`${drone.id} arrived at destination`, 'success');
    }
  } else {
    drone.x += (dx / dist) * step;
    drone.y += (dy / dist) * step;
  }

  drone.flightSeconds += dt;
  const cycleProgress = Math.min(1, drone.flightSeconds / SECONDS_PER_LIFECYCLE);
  drone.battery = drone._engine ? maintenance.healthAt(drone._engine, cycleProgress) : 100;
  if (drone.battery < 15 && drone.status !== 'low-battery') {
    drone.status = 'low-battery';
    pushEvent(
      `${drone.id} battery low (${drone.battery.toFixed(0)}%) -- real degradation trend from engine ${drone.engineId}`,
      'warning'
    );
  }

  for (const zone of groundZones.getZones()) {
    const dist = Math.hypot(drone.x - zone.x, drone.y - zone.y);
    if (dist < GROUND_ZONE_RADIUS && !drone._visitedGroundZones.has(zone.id)) {
      drone._visitedGroundZones.add(zone.id);
      if (zone.density === 'high') {
        pushEvent(
          `${drone.id} over ${zone.label} -- ${zone.total} objects detected in real VisDrone scene (dense ground traffic)`,
          'warning'
        );
      }
    }
  }
}

function tick(dt) {
  for (const d of drones) stepDrone(d, dt);
  // Keep arrived drones visible for a few seconds, then drop them.
  drones = drones.filter(d => d.status !== 'arrived' || Date.now() - (d.arrivedAt || 0) < 5000);
}

function getDrones() {
  return drones;
}

// Drone objects carry internal fields (_engine's full sensor curve,
// _visitedGroundZones) that don't need to cross the wire to the browser.
function toPublicDrone(drone) {
  const { _engine, _visitedGroundZones, ...pub } = drone;
  return pub;
}

function getPublicDrones() {
  return drones.map(toPublicDrone);
}

function rerouteDrone(drone, reason) {
  drone.path = airspace.findPath({ x: drone.x, y: drone.y }, drone.destination);
  drone.pathIndex = 0;
  drone.status = 'rerouting';
  pushEvent(`${drone.id} rerouting: ${reason}`, 'warning');
}

module.exports = { createDrone, removeDrone, tick, getDrones, getPublicDrones, toPublicDrone, rerouteDrone };
