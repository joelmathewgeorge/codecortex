// server/data/maintenance.js
// Loads NASA C-MAPSS turbofan run-to-failure data and turns each recorded
// engine into a real degradation curve a drone can "fly on" instead of a
// synthetic linear battery drain. Every engine in the dataset really did
// run from healthy to failure over its own number of cycles with its own
// noisy sensor trend, so drones assigned different engines age differently.

const fs = require('fs');
const path = require('path');

const DATA_PATH = path.join(
  __dirname, '..', '..', 'datasets', 'predictive-maintenance', 'CMAPSSData', 'train_FD001.txt'
);

// 0-indexed column 8 in each row = "sensor measurement 4" (columns are:
// 0 unit, 1 cycle, 2-4 op settings, 5-25 sensors 1-21) -- LPT outlet
// temperature, one of the sensors with a clear, well-documented
// degradation trend in FD001 (rises as the engine wears toward failure).
const DEGRADATION_SENSOR_COL = 8;

let engines = []; // [{ engineId, lifeCycles, healthByCycle: number[] }]

function load() {
  if (!fs.existsSync(DATA_PATH)) {
    console.warn('[maintenance] dataset not found at', DATA_PATH);
    return;
  }
  const lines = fs.readFileSync(DATA_PATH, 'utf8').split('\n').filter(l => l.trim().length > 0);
  const byUnit = new Map();

  for (const line of lines) {
    const cols = line.trim().split(/\s+/).map(Number);
    const unit = cols[0];
    const cycle = cols[1];
    const sensor = cols[DEGRADATION_SENSOR_COL];
    if (!byUnit.has(unit)) byUnit.set(unit, []);
    byUnit.get(unit).push({ cycle, sensor });
  }

  for (const [unit, rows] of byUnit.entries()) {
    rows.sort((a, b) => a.cycle - b.cycle);
    const values = rows.map(r => r.sensor);
    const min = Math.min(...values), max = Math.max(...values);
    // Sensor rises with wear in this engine's real recorded run, so invert
    // the normalized value: 100 at cycle 1 (healthy), trending toward 0 by
    // the engine's real last recorded cycle (failure).
    const healthByCycle = values.map(v => {
      const norm = max === min ? 0 : (v - min) / (max - min);
      return Math.max(0, Math.min(100, 100 * (1 - norm)));
    });
    engines.push({ engineId: `FD001-${unit}`, lifeCycles: rows.length, healthByCycle });
  }

  console.log(`[maintenance] loaded ${engines.length} real run-to-failure engine traces`);
}

// Assigns a random real engine trace to a new drone.
function assignEngine() {
  if (engines.length === 0) return null;
  return engines[Math.floor(Math.random() * engines.length)];
}

// cycleProgress is 0..1 through the engine's real recorded lifetime.
function healthAt(engine, cycleProgress) {
  if (!engine) return 100;
  const idx = Math.min(
    engine.healthByCycle.length - 1,
    Math.floor(cycleProgress * (engine.healthByCycle.length - 1))
  );
  return engine.healthByCycle[Math.max(0, idx)];
}

function stats() {
  return { engineCount: engines.length, loaded: engines.length > 0 };
}

load();

module.exports = { assignEngine, healthAt, stats };
