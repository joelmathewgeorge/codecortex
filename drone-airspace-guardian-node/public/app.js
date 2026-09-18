// public/app.js
// Renders the sim on a real Leaflet/OpenStreetMap basemap of Dubai and
// keeps the dashboard in sync with server state pushed over WebSocket.
// The server still simulates everything in an abstract 0-1000 "world
// unit" grid (see server/airspace.js) -- these constants mirror
// server/data/dubaiMap.js's projection so we can convert world x/y back
// into real lat/lon for plotting on the map.
const DUBAI_BOUNDS = { minLon: 54.95, maxLon: 55.55, minLat: 24.85, maxLat: 25.35 };
const MARGIN = 40;
const SPAN = 1000 - MARGIN * 2;
const GROUND_ZONE_RADIUS = 60; // world units, matches server/simulation.js

function worldToLatLng(x, y) {
  const lon = DUBAI_BOUNDS.minLon + ((x - MARGIN) / SPAN) * (DUBAI_BOUNDS.maxLon - DUBAI_BOUNDS.minLon);
  const lat = DUBAI_BOUNDS.maxLat - ((y - MARGIN) / SPAN) * (DUBAI_BOUNDS.maxLat - DUBAI_BOUNDS.minLat);
  return [lat, lon];
}

// Rough real-world metres per world-unit, for sizing circles (ground
// monitoring radius) correctly on the real map.
const centerLatRad = ((DUBAI_BOUNDS.minLat + DUBAI_BOUNDS.maxLat) / 2) * Math.PI / 180;
const lonSpanMeters = (DUBAI_BOUNDS.maxLon - DUBAI_BOUNDS.minLon) * 111320 * Math.cos(centerLatRad);
const METERS_PER_UNIT = lonSpanMeters / SPAN;

const statsEl = document.getElementById('stats');
const logEl = document.getElementById('event-log');
const groundZonesEl = document.getElementById('ground-zones');
const hospitalsEl = document.getElementById('hospitals');
const detectionFeedEl = document.getElementById('detection-feed');
const dataSourcesEl = document.getElementById('data-sources');

let state = { drones: [], zones: [], groundZones: [], hospitals: [], landmarks: [] };

const priorityColor = { normal: '#3ddc84', high: '#ffb020', critical: '#ff4d4d' };

// --- Real map setup (OpenStreetMap tiles via Leaflet) ---
const map = L.map('map', { zoomControl: true, attributionControl: true });
map.fitBounds([
  [DUBAI_BOUNDS.minLat, DUBAI_BOUNDS.minLon],
  [DUBAI_BOUNDS.maxLat, DUBAI_BOUNDS.maxLon],
]);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 19,
}).addTo(map);

const zonesLayer = L.layerGroup().addTo(map);
const dronesLayer = L.layerGroup().addTo(map);
const groundZonesLayer = L.layerGroup().addTo(map);
const hospitalsLayer = L.layerGroup().addTo(map);

function drawZones() {
  zonesLayer.clearLayers();
  state.zones.forEach(z => {
    const topLeft = worldToLatLng(z.x, z.y);
    const bottomRight = worldToLatLng(z.x + z.w, z.y + z.h);
    L.rectangle([topLeft, bottomRight], {
      color: '#ff4d4d', weight: 1.5, fillColor: '#ff4d4d', fillOpacity: 0.22,
    })
      .bindTooltip(z.label, { permanent: true, direction: 'center', className: 'drone-label' })
      .addTo(zonesLayer);
  });
}

function drawGroundZones() {
  groundZonesLayer.clearLayers();
  state.groundZones.forEach(z => {
    L.circle(worldToLatLng(z.x, z.y), {
      radius: GROUND_ZONE_RADIUS * METERS_PER_UNIT,
      color: z.density === 'high' ? '#ffb020' : 'rgba(255,176,32,0.5)',
      dashArray: '5,4',
      fillOpacity: 0.05,
    })
      .bindTooltip(`${z.label} (${z.total} objects)`, { permanent: true, direction: 'top', className: 'drone-label' })
      .addTo(groundZonesLayer);
  });
}

function drawHospitals() {
  hospitalsLayer.clearLayers();
  state.hospitals.forEach(h => {
    const icon = L.divIcon({ className: 'hospital-icon', html: '+', iconSize: [16, 16] });
    L.marker(worldToLatLng(h.x, h.y), { icon })
      .bindTooltip(h.name, { permanent: true, direction: 'right', className: 'drone-label' })
      .addTo(hospitalsLayer);
  });
}

function drawDrones() {
  dronesLayer.clearLayers();
  state.drones.forEach(d => {
    const pathLatLngs = [worldToLatLng(d.x, d.y), ...d.path.slice(d.pathIndex).map(p => worldToLatLng(p.x, p.y))];
    L.polyline(pathLatLngs, {
      color: d.conflict ? 'rgba(255,80,80,0.75)' : 'rgba(120,180,255,0.5)',
      weight: 2,
    }).addTo(dronesLayer);

    L.circleMarker(worldToLatLng(d.x, d.y), {
      radius: 6,
      color: '#05070d',
      weight: 1,
      fillColor: d.conflict ? '#ff4d4d' : (priorityColor[d.priority] || '#3ddc84'),
      fillOpacity: 1,
    })
      .bindTooltip(`${d.id} · ${Math.round(d.altitude)}m`, { permanent: true, direction: 'right', className: 'drone-label' })
      .addTo(dronesLayer);
  });
}

function renderStats() {
  const active = state.drones.filter(d => d.status !== 'arrived').length;
  const conflictCount = Math.ceil(state.drones.filter(d => d.conflict).length / 2);
  const avgHealth = active
    ? Math.round(state.drones.filter(d => d.status !== 'arrived').reduce((s, d) => s + d.battery, 0) / active)
    : 0;
  statsEl.innerHTML = `
    <li><span>Active drones</span><b>${active}</b></li>
    <li><span>Conflicts</span><b>${conflictCount}</b></li>
    <li><span>Real no-fly zones (Dubai)</span><b>${state.zones.length}</b></li>
    <li><span>Avg. fleet health (real engine data)</span><b>${active ? avgHealth + '%' : '—'}</b></li>
  `;
}

function renderGroundZones() {
  groundZonesEl.innerHTML = state.groundZones.map(z => `
    <li><span>${z.label} (${z.density})</span><b>${z.total} objects</b></li>
  `).join('');
}

function renderHospitals() {
  hospitalsEl.innerHTML = state.hospitals.map(h => `<li><span>${h.name}</span><b>real</b></li>`).join('');
}

function renderDataSources(sources) {
  const rows = Object.values(sources).map(s => {
    const count = s.aircraftCount ?? s.engineCount ?? s.frameCount ?? s.zoneCount ?? s.noFlyZoneCount ?? 0;
    return `<li><span>${s.name}</span><b>${s.loaded ? `✅ ${count}` : '⚠️ not loaded'}</b></li>`;
  });
  dataSourcesEl.innerHTML = rows.join('');
}

function renderDetectionFeed(frames) {
  detectionFeedEl.innerHTML = frames.map(f => {
    if (!f) return '';
    const top = Object.entries(f.objectCounts).filter(([, n]) => n > 0)
      .sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, n]) => `${k}:${n}`).join(', ');
    return `<li><span>${f.imageName}</span><b>${f.objectTotal} obj (${top || 'none'})</b></li>`;
  }).join('');
}

function addEvent(evt) {
  const li = document.createElement('li');
  li.className = evt.type;
  li.textContent = `[${evt.time}] ${evt.message}`;
  logEl.prepend(li);
  while (logEl.children.length > 30) logEl.removeChild(logEl.lastChild);
}

const wsProtocol = location.protocol === 'https:' ? 'wss' : 'ws';
const ws = new WebSocket(`${wsProtocol}://${location.host}`);

ws.onmessage = (msg) => {
  const data = JSON.parse(msg.data);
  if (data.type === 'state') {
    state.drones = data.drones;
    state.zones = data.zones;
    if (data.groundZones) state.groundZones = data.groundZones;
    drawZones();
    drawDrones();
    renderStats();
    renderGroundZones();
  } else if (data.type === 'event') {
    addEvent(data.event);
  }
};

ws.onclose = () => {
  document.getElementById('status-indicator').textContent = '🔴 DISCONNECTED';
};

document.getElementById('add-drone-btn').addEventListener('click', () => {
  fetch('/api/drones', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  });
});

document.getElementById('emergency-btn').addEventListener('click', () => {
  fetch('/api/emergency', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  });
});

document.getElementById('real-flight-btn').addEventListener('click', () => {
  fetch('/api/drones', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ real: true }),
  });
});

// Initial paint before the first WebSocket tick arrives.
fetch('/api/state')
  .then(r => r.json())
  .then(data => {
    state.drones = data.drones;
    state.zones = data.zones;
    state.groundZones = data.groundZones || [];
    state.hospitals = data.hospitals || [];
    state.landmarks = data.landmarks || [];
    drawZones();
    drawDrones();
    drawGroundZones();
    drawHospitals();
    renderStats();
    renderGroundZones();
    renderHospitals();
    data.events.slice().reverse().forEach(addEvent);
  });

fetch('/api/datasets').then(r => r.json()).then(renderDataSources);

function pollDetectionFeed() {
  fetch('/api/detection-feed').then(r => r.json()).then(data => renderDetectionFeed(data.frames));
}
pollDetectionFeed();
setInterval(pollDetectionFeed, 3000);
