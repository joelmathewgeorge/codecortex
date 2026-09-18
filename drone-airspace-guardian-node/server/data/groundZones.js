// server/data/groundZones.js
// Loads a sample of real VisDrone detection frames (drone-captured aerial
// traffic scenes with real bounding-box object counts) and pins each one
// to a fixed spot in the sim's airspace as a "ground monitoring zone".
// Drones flying near a zone with heavy real recorded ground traffic get an
// advisory event -- a real coupling between the dataset and sim behaviour,
// not just a static overlay.

const fs = require('fs');
const path = require('path');

const BASE = path.join(__dirname, '..', '..', 'datasets', 'aerial-detection');
const SAMPLE_IMAGES_DIR = path.join(BASE, 'sample-images');
const ANNOTATIONS_DIR = path.join(BASE, 'VisDrone2019-DET-val', 'annotations');

// VisDrone category ids -> names (0 and 11 are "ignored"/"other", skipped).
const CATEGORY_NAMES = {
  1: 'pedestrian', 2: 'people', 3: 'bicycle', 4: 'car', 5: 'van',
  6: 'truck', 7: 'tricycle', 8: 'awning-tricycle', 9: 'bus', 10: 'motor',
};

let zones = [];

// Spread zones across the world, away from the map edges and roughly
// clear of the hand-placed restricted zones in airspace.js.
const ZONE_POSITIONS = [
  { x: 300, y: 350 }, { x: 700, y: 300 }, { x: 850, y: 700 },
  { x: 150, y: 750 }, { x: 500, y: 500 }, { x: 750, y: 500 },
];

function parseAnnotation(text) {
  const counts = {};
  let total = 0;
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    const [, , , , , category] = line.split(',').map(Number);
    const name = CATEGORY_NAMES[category];
    if (!name) continue;
    counts[name] = (counts[name] || 0) + 1;
    total++;
  }
  return { counts, total };
}

function load() {
  if (!fs.existsSync(SAMPLE_IMAGES_DIR)) {
    console.warn('[groundZones] VisDrone sample images not found at', SAMPLE_IMAGES_DIR);
    return;
  }
  const images = fs.readdirSync(SAMPLE_IMAGES_DIR).filter(f => f.endsWith('.jpg'));
  // Pick a handful of distinct scenes, spread through the sample so they
  // aren't all consecutive video frames of the same spot.
  const picks = [];
  const step = Math.max(1, Math.floor(images.length / ZONE_POSITIONS.length));
  for (let i = 0; i < ZONE_POSITIONS.length && i * step < images.length; i++) {
    picks.push(images[i * step]);
  }

  zones = picks.map((imageName, i) => {
    const base = imageName.replace(/\.jpg$/, '');
    const annPath = path.join(ANNOTATIONS_DIR, `${base}.txt`);
    const { counts, total } = fs.existsSync(annPath)
      ? parseAnnotation(fs.readFileSync(annPath, 'utf8'))
      : { counts: {}, total: 0 };

    return {
      id: `GZ${i + 1}`,
      ...ZONE_POSITIONS[i],
      label: `Ground Monitor ${i + 1}`,
      sourceImage: imageName,
      counts,
      total,
      density: total > 25 ? 'high' : total > 10 ? 'moderate' : 'low',
    };
  });

  console.log(`[groundZones] loaded ${zones.length} real VisDrone ground-traffic zones`);
}

function getZones() {
  return zones;
}

function stats() {
  return { zoneCount: zones.length, loaded: zones.length > 0 };
}

load();

module.exports = { getZones, stats };
