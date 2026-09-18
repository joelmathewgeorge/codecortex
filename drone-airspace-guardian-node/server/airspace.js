// server/airspace.js
// The simulated airspace: a 100x100 grid over a 1000x1000 world, restricted
// zones, emergency zones, and A* pathfinding that treats restricted cells
// as impassable.

const dubaiMap = require('./data/dubaiMap');

const GRID_SIZE = 100;   // cells per side
const CELL_SIZE = 10;    // world units per cell (world is 1000x1000)

// Restricted zones are real Dubai airports, government buildings and
// stadiums (OpenStreetMap, projected onto the world grid by
// server/data/dubaiMap.js), not hand-placed fictional rectangles.
let restrictedZones = [...dubaiMap.getNoFlyZones()];

// Temporary zones added at runtime (e.g. "Emergency Airspace Activated")
let emergencyZones = [];

function isCellRestricted(cx, cy) {
  const wx = cx * CELL_SIZE;
  const wy = cy * CELL_SIZE;
  const zones = [...restrictedZones, ...emergencyZones];
  return zones.some(z => wx >= z.x && wx < z.x + z.w && wy >= z.y && wy < z.y + z.h);
}

function worldToCell(x, y) {
  return {
    cx: Math.min(GRID_SIZE - 1, Math.max(0, Math.floor(x / CELL_SIZE))),
    cy: Math.min(GRID_SIZE - 1, Math.max(0, Math.floor(y / CELL_SIZE))),
  };
}

function cellToWorld(cx, cy) {
  return { x: cx * CELL_SIZE + CELL_SIZE / 2, y: cy * CELL_SIZE + CELL_SIZE / 2 };
}

function addEmergencyZone(zone) {
  emergencyZones.push(zone);
  return zone;
}

function removeEmergencyZone(id) {
  emergencyZones = emergencyZones.filter(z => z.id !== id);
}

function clearEmergencyZones() {
  emergencyZones = [];
}

function getAllZones() {
  return [...restrictedZones, ...emergencyZones];
}

function pointInAnyZone(x, y, zones) {
  return zones.some(z => x >= z.x && x < z.x + z.w && y >= z.y && y < z.y + z.h);
}

// --- A* pathfinding over the grid ---

function heuristic(a, b) {
  return Math.hypot(a.cx - b.cx, a.cy - b.cy);
}

function neighbors(node) {
  const dirs = [
    [1, 0], [-1, 0], [0, 1], [0, -1],
    [1, 1], [1, -1], [-1, 1], [-1, -1],
  ];
  return dirs
    .map(([dx, dy]) => ({ cx: node.cx + dx, cy: node.cy + dy }))
    .filter(n => n.cx >= 0 && n.cx < GRID_SIZE && n.cy >= 0 && n.cy < GRID_SIZE);
}

// Returns an array of {x, y} world-space waypoints from start to end,
// avoiding restricted cells. Falls back to a straight line if no path
// is found within the iteration budget (keeps the simulation responsive).
function findPath(startWorld, endWorld) {
  const start = worldToCell(startWorld.x, startWorld.y);
  const end = worldToCell(endWorld.x, endWorld.y);
  const key = (n) => `${n.cx},${n.cy}`;

  const openSet = [start];
  const cameFrom = new Map();
  const gScore = new Map([[key(start), 0]]);
  const fScore = new Map([[key(start), heuristic(start, end)]]);
  const openKeys = new Set([key(start)]);

  let iterations = 0;
  const MAX_ITERATIONS = 4000;

  while (openSet.length > 0 && iterations < MAX_ITERATIONS) {
    iterations++;
    openSet.sort((a, b) => (fScore.get(key(a)) ?? Infinity) - (fScore.get(key(b)) ?? Infinity));
    const current = openSet.shift();
    openKeys.delete(key(current));

    if (current.cx === end.cx && current.cy === end.cy) {
      const path = [current];
      let c = current;
      while (cameFrom.has(key(c))) {
        c = cameFrom.get(key(c));
        path.unshift(c);
      }
      return simplify(path.map(n => cellToWorld(n.cx, n.cy)));
    }

    for (const n of neighbors(current)) {
      if (isCellRestricted(n.cx, n.cy)) continue;
      const stepCost = (n.cx !== current.cx && n.cy !== current.cy) ? Math.SQRT2 : 1;
      const tentative = (gScore.get(key(current)) ?? Infinity) + stepCost;
      if (tentative < (gScore.get(key(n)) ?? Infinity)) {
        cameFrom.set(key(n), current);
        gScore.set(key(n), tentative);
        fScore.set(key(n), tentative + heuristic(n, end));
        if (!openKeys.has(key(n))) {
          openSet.push(n);
          openKeys.add(key(n));
        }
      }
    }
  }

  // No path found (or budget exceeded) -> straight line fallback.
  return [startWorld, endWorld];
}

// Collapse collinear consecutive waypoints so paths aren't a jagged
// staircase of every single grid cell.
function simplify(points) {
  if (points.length < 3) return points;
  const out = [points[0]];
  for (let i = 1; i < points.length - 1; i++) {
    const a = out[out.length - 1], b = points[i], c = points[i + 1];
    const cross = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
    if (Math.abs(cross) > 0.01) out.push(b);
  }
  out.push(points[points.length - 1]);
  return out;
}

module.exports = {
  GRID_SIZE,
  CELL_SIZE,
  isCellRestricted,
  worldToCell,
  cellToWorld,
  addEmergencyZone,
  removeEmergencyZone,
  clearEmergencyZones,
  getAllZones,
  pointInAnyZone,
  findPath,
};
