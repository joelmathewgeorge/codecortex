// server/data/dubaiMap.js
// Loads real Dubai geography (OpenStreetMap, via Nominatim) and projects it
// onto the sim's 1000x1000 world, replacing the old hand-placed fictional
// zones with real airports, hospitals, government buildings and stadiums
// at their real relative positions.

const fs = require('fs');
const path = require('path');

const DATA_PATH = path.join(__dirname, '..', '..', 'datasets', 'dubai-map', 'dubai_landmarks.json');

// Covers Dubai's main urbanized coastal strip, from Al Maktoum
// International Airport in the south to Deira in the north.
const BOUNDS = { minLon: 54.95, maxLon: 55.55, minLat: 24.85, maxLat: 25.35 };
const MARGIN = 40;
const SPAN = 1000 - MARGIN * 2;
const MIN_ZONE_SIZE = 40; // world units -- keeps point-ish POIs visible/blocking

let noFlyZones = [];
let hospitals = [];
let landmarks = [];
let palmJumeirahOutline = [];
let loaded = false;

function project(lat, lon) {
  return {
    x: MARGIN + ((lon - BOUNDS.minLon) / (BOUNDS.maxLon - BOUNDS.minLon)) * SPAN,
    y: MARGIN + ((BOUNDS.maxLat - lat) / (BOUNDS.maxLat - BOUNDS.minLat)) * SPAN, // north = up
  };
}

// boundingbox is Nominatim's [minLat, maxLat, minLon, maxLon].
function projectRect(boundingbox) {
  const [minLat, maxLat, minLon, maxLon] = boundingbox;
  const topLeft = project(maxLat, minLon);
  const bottomRight = project(minLat, maxLon);
  const w = Math.max(MIN_ZONE_SIZE, bottomRight.x - topLeft.x);
  const h = Math.max(MIN_ZONE_SIZE, bottomRight.y - topLeft.y);
  return { x: topLeft.x, y: topLeft.y, w, h };
}

function load() {
  if (!fs.existsSync(DATA_PATH)) {
    console.warn('[dubaiMap] real Dubai landmark data not found at', DATA_PATH);
    return;
  }
  const data = JSON.parse(fs.readFileSync(DATA_PATH, 'utf8'));

  let n = 1;
  for (const place of data.places) {
    if (place.category === 'airport' || place.category === 'government' || place.category === 'stadium') {
      const rect = projectRect(place.boundingbox);
      noFlyZones.push({ id: `DXB-NFZ${n++}`, ...rect, label: place.englishName });
    } else if (place.category === 'hospital') {
      hospitals.push({ id: `HOSP${hospitals.length + 1}`, name: place.englishName, ...project(place.lat, place.lon) });
    } else if (place.category === 'landmark') {
      landmarks.push({ id: `LM${landmarks.length + 1}`, name: place.englishName, ...project(place.lat, place.lon) });
    }
  }

  palmJumeirahOutline = (data.palmJumeirahOutline || []).map(p => project(p.lat, p.lon));

  loaded = true;
  console.log(
    `[dubaiMap] loaded real Dubai geography: ${noFlyZones.length} no-fly zones, ` +
    `${hospitals.length} hospitals, ${landmarks.length} landmarks`
  );
}

function getNoFlyZones() { return noFlyZones; }
function getHospitals() { return hospitals; }
function getLandmarks() { return landmarks; }
function getPalmJumeirahOutline() { return palmJumeirahOutline; }

// Straight-line nearest hospital to a world point -- used to send the
// emergency "medical delivery" drone to a real hospital instead of a
// fixed default coordinate.
function nearestHospital(x, y) {
  if (hospitals.length === 0) return null;
  return hospitals.reduce((best, h) => {
    const d = Math.hypot(h.x - x, h.y - y);
    return d < best.d ? { hospital: h, d } : best;
  }, { hospital: hospitals[0], d: Infinity }).hospital;
}

function stats() {
  return {
    loaded,
    noFlyZoneCount: noFlyZones.length,
    hospitalCount: hospitals.length,
    landmarkCount: landmarks.length,
  };
}

load();

module.exports = {
  getNoFlyZones, getHospitals, getLandmarks, getPalmJumeirahOutline, nearestHospital, project, stats,
};
