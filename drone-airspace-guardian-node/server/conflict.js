// server/conflict.js
// The "Guardian Algorithm": predicts near-future positions for every pair
// of active drones and flags a conflict when they'd occupy the same space
// (within SAFE_DISTANCE) at a similar altitude, within the lookahead window.
// This is 4D deconfliction (x, y, altitude, time), not simple line-crossing.

const { pushEvent } = require('./events');
const simulation = require('./simulation');
const airspace = require('./airspace');

const SAFE_DISTANCE = 25;   // world units -- minimum horizontal separation
const ALT_SEPARATION = 20;  // metres -- minimum vertical separation
const LOOKAHEAD = 3;        // seconds -- how far ahead we predict

function predictPosition(drone, seconds) {
  const target = drone.path[drone.pathIndex];
  if (!target) return { x: drone.x, y: drone.y };
  const dx = target.x - drone.x;
  const dy = target.y - drone.y;
  const dist = Math.hypot(dx, dy) || 1;
  const travel = drone.speed * seconds;
  const ratio = Math.min(1, travel / dist);
  return { x: drone.x + dx * ratio, y: drone.y + dy * ratio };
}

// Runs every simulation tick. Returns the number of active conflicts found.
function detectAndResolve() {
  const drones = simulation.getDrones().filter(d => d.status !== 'arrived');
  let conflictCount = 0;

  for (const d of drones) d.conflict = false;

  for (let i = 0; i < drones.length; i++) {
    for (let j = i + 1; j < drones.length; j++) {
      const a = drones[i], b = drones[j];
      const pa = predictPosition(a, LOOKAHEAD);
      const pb = predictPosition(b, LOOKAHEAD);
      const dist = Math.hypot(pa.x - pb.x, pa.y - pb.y);
      const altDiff = Math.abs(a.altitude - b.altitude);

      if (dist < SAFE_DISTANCE && altDiff < ALT_SEPARATION) {
        conflictCount++;
        a.conflict = true;
        b.conflict = true;
        resolveConflict(a, b);
      }
    }
  }
  return conflictCount;
}

// Cheapest fix first: separate by altitude. Lower-priority drone yields.
function resolveConflict(a, b) {
  const rank = { critical: 3, high: 2, normal: 1 };
  const [yielding, holding] = rank[a.priority] >= rank[b.priority] ? [b, a] : [a, b];

  if (Math.abs(yielding.altitude - holding.altitude) < ALT_SEPARATION) {
    yielding.altitude = holding.altitude + 30;
    pushEvent(
      `Conflict predicted: ${a.id} vs ${b.id} -- ${yielding.id} climbing to ${yielding.altitude}m to separate`,
      'alert'
    );
  }
}

// Emergency Priority Mode: forces nearby drones out of a critical drone's way.
function activateEmergencyCorridor(criticalDrone) {
  const drones = simulation.getDrones().filter(
    d => d.id !== criticalDrone.id && d.status !== 'arrived'
  );
  let affected = 0;
  for (const d of drones) {
    const dist = Math.hypot(d.x - criticalDrone.x, d.y - criticalDrone.y);
    if (dist < 120) {
      simulation.rerouteDrone(d, `yielding emergency corridor to ${criticalDrone.id}`);
      affected++;
    }
  }
  pushEvent(
    `Emergency corridor established for ${criticalDrone.id} -- ${affected} drone(s) rerouted`,
    'critical'
  );
  return affected;
}

module.exports = { detectAndResolve, activateEmergencyCorridor, SAFE_DISTANCE };
