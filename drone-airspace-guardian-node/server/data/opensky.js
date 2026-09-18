// server/data/opensky.js
// Loads real ADS-B state vectors (OpenSky Network) and turns them into
// world-space flight trajectories the simulator can fly a drone along,
// instead of a random two-point A* path.

const fs = require('fs');
const path = require('path');

const CSV_PATH = path.join(__dirname, '..', '..', 'datasets', 'flight-telemetry', 'opensky_trajectories.csv');

let aircraftById = new Map(); // icao24 -> array of rows, sorted by snapshot_time
let loaded = false;

function parseCsv(text) {
  const lines = text.split('\n').filter(l => l.trim().length > 0);
  const header = lines[0].split(',');
  const idx = Object.fromEntries(header.map((h, i) => [h.trim(), i]));

  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(',');
    const lon = parseFloat(cols[idx.longitude]);
    const lat = parseFloat(cols[idx.latitude]);
    if (Number.isNaN(lon) || Number.isNaN(lat)) continue;

    const row = {
      icao24: cols[idx.icao24],
      callsign: (cols[idx.callsign] || '').trim(),
      originCountry: cols[idx.origin_country],
      snapshotTime: parseInt(cols[idx.snapshot_time], 10),
      lon,
      lat,
      baroAltitude: parseFloat(cols[idx.baro_altitude]) || 0,
      velocity: parseFloat(cols[idx.velocity]) || 0,
      trueTrack: parseFloat(cols[idx.true_track]) || 0,
    };

    if (!aircraftById.has(row.icao24)) aircraftById.set(row.icao24, []);
    aircraftById.get(row.icao24).push(row);
  }

  for (const rows of aircraftById.values()) rows.sort((a, b) => a.snapshotTime - b.snapshotTime);
  loaded = true;
}

function load() {
  if (!fs.existsSync(CSV_PATH)) {
    console.warn('[opensky] dataset not found at', CSV_PATH);
    return;
  }
  parseCsv(fs.readFileSync(CSV_PATH, 'utf8'));
  console.log(`[opensky] loaded ${aircraftById.size} real aircraft trajectories`);
}

// Projects an aircraft's own lat/lon fixes onto a local, equirectangular
// x/y plane (metres-ish, first point at the origin). Using each aircraft's
// OWN local extent -- instead of one global bounding box over all 214
// aircraft, which are scattered across the whole Indian subcontinent --
// matters: a single aircraft's ~20 fixes span a few km at most, so
// normalizing by the global (thousand-km) box would collapse every real
// flight down to a single pixel in world-space.
function localProjection(rows) {
  const lat0 = rows[0].lat;
  const metresPerDegLat = 111320;
  const metresPerDegLon = 111320 * Math.cos(lat0 * Math.PI / 180);
  return rows.map(r => ({
    x: (r.lon - rows[0].lon) * metresPerDegLon,
    y: (rows[0].lat - r.lat) * metresPerDegLat, // lat grows north/up
  }));
}

// Returns a real flight's trajectory as *relative* waypoints (first point
// at 0,0, scaled to a visible span of world units) plus altitude/speed
// sampled from the same real state vectors, or null if no data loaded.
// The caller anchors these at a real position in the sim's world.
function pickRealTrajectory() {
  if (!loaded || aircraftById.size === 0) return null;

  const candidates = [...aircraftById.entries()]
    .filter(([, rows]) => rows.length >= 3)
    .map(([icao24, rows]) => {
      const local = localProjection(rows);
      const extent = Math.max(...local.map(p => Math.hypot(p.x, p.y)));
      return { icao24, rows, local, extent };
    })
    // Prefer aircraft that actually moved between fixes (not parked/holding)
    // so the real-flight demo visibly animates.
    .filter(c => c.extent > 200) // metres
    .sort((a, b) => b.extent - a.extent);
  if (candidates.length === 0) return null;

  const pick = candidates[Math.floor(Math.random() * Math.min(candidates.length, 30))];
  const { icao24, rows, local, extent } = pick;

  // Scale so the real (proportionally-preserved) flight shape spans a
  // reasonable chunk of the 1000x1000 world -- comparable to a normal
  // simulated drone's route -- rather than either a single pixel or
  // running off the map.
  const targetSpan = 250 + Math.random() * 250; // 250-500 world units
  const scale = targetSpan / extent;
  const waypoints = local.map(p => ({ x: p.x * scale, y: p.y * scale }));

  const avgVelocity = rows.reduce((s, r) => s + r.velocity, 0) / rows.length; // m/s, real ADS-B ground speed
  const avgAltitudeM = rows.reduce((s, r) => s + r.baroAltitude, 0) / rows.length;

  return {
    icao24,
    callsign: rows[0].callsign || icao24,
    waypoints, // relative to waypoints[0] == {x:0, y:0}
    // Real ground speed is 50-260 m/s for airliners; compress into the
    // sim's drone speed band (18-40 world units/s) rather than pretending
    // 1 world unit == 1 metre.
    speed: 18 + Math.min(1, avgVelocity / 260) * 22,
    // Real barometric altitude (metres) scaled the same way, clamped into
    // the sim's altitude band.
    altitude: Math.round(60 + Math.min(1, avgAltitudeM / 12000) * 200),
    originCountry: rows[0].originCountry,
  };
}

function stats() {
  return { aircraftCount: aircraftById.size, loaded };
}

load();

module.exports = { pickRealTrajectory, stats };
