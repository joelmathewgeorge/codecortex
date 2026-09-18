// server/index.js
// Entry point. Serves the frontend, exposes a small REST API for
// adding drones / triggering emergencies, runs the simulation loop, and
// broadcasts state to every connected browser over WebSocket.

const express = require('express');
const http = require('http');
const { WebSocketServer, WebSocket } = require('ws');
const path = require('path');

const airspace = require('./airspace');
const simulation = require('./simulation');
const conflict = require('./conflict');
const events = require('./events');
const groundZones = require('./data/groundZones');
const opensky = require('./data/opensky');
const maintenance = require('./data/maintenance');
const auair = require('./data/auair');
const dubaiMap = require('./data/dubaiMap');

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'public')));

function broadcast(payload) {
  const msg = JSON.stringify(payload);
  wss.clients.forEach(client => {
    if (client.readyState === WebSocket.OPEN) client.send(msg);
  });
}
events.setBroadcaster(broadcast);

// Seed some initial traffic so the map isn't empty on load.
for (let i = 0; i < 8; i++) simulation.createDrone();

// --- REST API ---

// Add a new simulated drone. Body fields are all optional:
// { start, destination, altitude, speed, priority, mission }
app.post('/api/drones', (req, res) => {
  const drone = simulation.createDrone(req.body || {});
  res.json(simulation.toPublicDrone(drone));
});

// Trigger "Emergency Airspace Activated": drops a new restricted zone,
// reroutes anyone whose path crosses it, then launches a critical-priority
// drone and clears a corridor for it. This is the hackathon demo's
// "wow moment" (see pitch doc, section 9).
app.post('/api/emergency', (req, res) => {
  const zone = airspace.addEmergencyZone({
    id: `EZ${Date.now()}`,
    x: req.body?.x ?? 450,
    y: req.body?.y ?? 450,
    w: req.body?.w ?? 150,
    h: req.body?.h ?? 150,
    label: 'Emergency Zone',
  });
  events.pushEvent(`Emergency airspace activated near (${zone.x}, ${zone.y})`, 'critical');

  // Emergency zones are meant to be temporary -- clear this one after 45s
  // so repeated demo triggers don't permanently clutter real Dubai airspace.
  setTimeout(() => {
    airspace.removeEmergencyZone(zone.id);
    events.pushEvent(`Emergency airspace near (${zone.x}, ${zone.y}) lifted`, 'info');
  }, 45000);

  let affected = 0;
  simulation.getDrones().forEach(d => {
    const crossesZone = d.path.some(p => airspace.pointInAnyZone(p.x, p.y, [zone]));
    if (crossesZone) {
      simulation.rerouteDrone(d, 'restricted zone activated on route');
      affected++;
    }
  });

  // Send the medical drone to the real hospital nearest the new zone,
  // instead of an arbitrary point.
  const destinationHospital = dubaiMap.nearestHospital(zone.x, zone.y);
  const critical = simulation.createDrone({
    priority: 'critical',
    mission: destinationHospital ? `Medical delivery -- ${destinationHospital.name}` : 'Medical delivery',
    destination: destinationHospital ? { x: destinationHospital.x, y: destinationHospital.y } : undefined,
    speed: 30,
  });

  // Small delay so the critical drone's path exists before we clear a
  // corridor for it.
  setTimeout(() => conflict.activateEmergencyCorridor(critical), 300);

  res.json({ zone, reroutedForZone: affected, criticalDrone: critical.id });
});

// Full current state -- used for the initial page load, before the
// WebSocket connection delivers live ticks.
app.get('/api/state', (req, res) => {
  res.json({
    drones: simulation.getPublicDrones(),
    zones: airspace.getAllZones(),
    events: events.getLog(),
    groundZones: groundZones.getZones(),
    hospitals: dubaiMap.getHospitals(),
    landmarks: dubaiMap.getLandmarks(),
    palmJumeirahOutline: dubaiMap.getPalmJumeirahOutline(),
  });
});

// Provenance for the dashboard's "Data Sources" panel -- what real
// datasets are actually loaded and driving the simulation right now.
app.get('/api/datasets', (req, res) => {
  res.json({
    dubaiGeography: { name: 'Dubai real geography (OpenStreetMap / Nominatim)', ...dubaiMap.stats() },
    flightTelemetry: { name: 'OpenSky Network ADS-B', ...opensky.stats() },
    predictiveMaintenance: { name: 'NASA C-MAPSS turbofan run-to-failure', ...maintenance.stats() },
    multimodalUav: { name: 'AU-AIR multimodal UAV', ...auair.stats() },
    aerialDetection: { name: 'VisDrone2019-DET', ...groundZones.stats() },
  });
});

// A tick of real synced flight-sensor + object-detection data from AU-AIR,
// for the "Live Aerial Detection Feed" panel.
app.get('/api/detection-feed', (req, res) => {
  res.json({ frames: auair.sample(3) });
});

// --- Simulation loop ---
const TICK_MS = 250;
setInterval(() => {
  simulation.tick(TICK_MS / 1000);
  const conflicts = conflict.detectAndResolve();
  broadcast({
    type: 'state',
    drones: simulation.getPublicDrones(),
    zones: airspace.getAllZones(),
    conflicts,
    groundZones: groundZones.getZones(),
  });
}, TICK_MS);

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`Drone Airspace Guardian running at http://localhost:${PORT}`);
});
