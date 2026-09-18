// server/data/auair.js
// Loads the AU-AIR multimodal UAV dataset: real drone frames where each
// one carries both flight sensors (GPS, altitude, IMU, velocity) and
// object-detection boxes recorded at the same instant. Exposed as a
// ticking "live telemetry + detection" feed for the dashboard.

const fs = require('fs');
const path = require('path');

const ANNOTATIONS_PATH = path.join(
  __dirname, '..', '..', 'datasets', 'multimodal-uav', 'annotations.json'
);

const CATEGORIES = ['Human', 'Car', 'Truck', 'Van', 'Motorbike', 'Bicycle', 'Bus', 'Trailer'];

let frames = [];
let cursor = 0;

function load() {
  if (!fs.existsSync(ANNOTATIONS_PATH)) {
    console.warn('[auair] dataset not found at', ANNOTATIONS_PATH);
    return;
  }
  const raw = JSON.parse(fs.readFileSync(ANNOTATIONS_PATH, 'utf8'));
  frames = (raw.annotations || []).map(a => ({
    imageName: a.image_name,
    platform: a.platform,
    time: a.time,
    longitude: a.longtitude, // dataset's own field name/typo
    latitude: a.latitude,
    altitude: a.altitude,
    linearVelocity: { x: a.linear_x, y: a.linear_y, z: a.linear_z },
    objectCounts: countByCategory(a.bbox || []),
    objectTotal: (a.bbox || []).length,
  }));
  console.log(`[auair] loaded ${frames.length} real synced flight-sensor + detection frames`);
}

function countByCategory(bboxes) {
  const counts = Object.fromEntries(CATEGORIES.map(c => [c, 0]));
  for (const b of bboxes) {
    const label = CATEGORIES[b.class];
    if (label) counts[label]++;
  }
  return counts;
}

// Advances a shared cursor through the real recorded frames each time it's
// called, so repeated polling looks like a live sensor feed.
function nextFrame() {
  if (frames.length === 0) return null;
  const frame = frames[cursor % frames.length];
  cursor++;
  return frame;
}

function sample(n = 5) {
  const out = [];
  for (let i = 0; i < n; i++) out.push(nextFrame());
  return out;
}

function stats() {
  return { frameCount: frames.length, loaded: frames.length > 0, categories: CATEGORIES };
}

load();

module.exports = { nextFrame, sample, stats, CATEGORIES };
