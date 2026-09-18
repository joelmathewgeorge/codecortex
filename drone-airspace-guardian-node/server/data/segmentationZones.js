// server/data/segmentationZones.js
// Decodes a real Dubai aerial semantic-segmentation mask (MBRSC satellite
// imagery, pixel-labelled Building/Road/Water/Land/Vegetation) and turns
// its real building footprints into no-fly zone rectangles for the sim's
// airspace grid -- replacing hand-placed rectangles with real geometry.

const fs = require('fs');
const path = require('path');
const { PNG } = require('pngjs');

const MASK_PATH = path.join(
  __dirname, '..', '..', 'datasets', 'aerial-segmentation', 'masks', 'tile_020.png'
);

// The actual RGB palette baked into this dataset's mask PNGs (Humans in
// the Loop / MBRSC release) -- not the same as the display colors listed
// in classes.json, which are just the annotation tool's editor colors.
const PALETTE = [
  { title: 'Building', rgb: [60, 16, 152] },
  { title: 'Land', rgb: [132, 41, 246] },
  { title: 'Road', rgb: [110, 193, 228] },
  { title: 'Vegetation', rgb: [254, 221, 58] },
  { title: 'Water', rgb: [226, 169, 41] },
  { title: 'Unlabeled', rgb: [155, 155, 155] },
];

// Where in the sim's 1000x1000 world this real segmentation tile is placed.
const REGION = { x: 600, y: 600, size: 400 };
const GRID = 40;          // cells across the region
const CELL_WORLD = REGION.size / GRID; // 10 world units/cell, matches airspace.js CELL_SIZE

function nearestClass(r, g, b) {
  let best = null, bestDist = Infinity;
  for (const p of PALETTE) {
    const d = (r - p.rgb[0]) ** 2 + (g - p.rgb[1]) ** 2 + (b - p.rgb[2]) ** 2;
    if (d < bestDist) { bestDist = d; best = p.title; }
  }
  return best;
}

function buildBuildingGrid(png) {
  const grid = [];
  const cellPxW = png.width / GRID;
  const cellPxH = png.height / GRID;
  for (let gy = 0; gy < GRID; gy++) {
    const row = [];
    for (let gx = 0; gx < GRID; gx++) {
      const px = Math.min(png.width - 1, Math.floor((gx + 0.5) * cellPxW));
      const py = Math.min(png.height - 1, Math.floor((gy + 0.5) * cellPxH));
      const idx = (png.width * py + px) << 2;
      row.push(nearestClass(png.data[idx], png.data[idx + 1], png.data[idx + 2]) === 'Building');
    }
    grid.push(row);
  }
  return grid;
}

// Row-run-length + vertical-merge: collapses same-range building runs
// across consecutive rows into single rectangles, so we don't hand A*
// hundreds of 1-cell zones.
function gridToRects(grid) {
  const rects = [];
  let open = []; // { gxStart, gxEnd, gyStart, gyEnd }

  for (let gy = 0; gy <= GRID; gy++) {
    const runs = [];
    if (gy < GRID) {
      let runStart = null;
      for (let gx = 0; gx <= GRID; gx++) {
        const on = gx < GRID && grid[gy][gx];
        if (on && runStart === null) runStart = gx;
        if (!on && runStart !== null) { runs.push({ gxStart: runStart, gxEnd: gx }); runStart = null; }
      }
    }

    const stillOpen = [];
    for (const o of open) {
      const match = runs.find(r => r.gxStart === o.gxStart && r.gxEnd === o.gxEnd && !r.used);
      if (match) { match.used = true; o.gyEnd = gy + 1; stillOpen.push(o); }
      else rects.push(o);
    }
    for (const r of runs) {
      if (!r.used) stillOpen.push({ gxStart: r.gxStart, gxEnd: r.gxEnd, gyStart: gy, gyEnd: gy + 1 });
    }
    open = stillOpen;
  }

  return rects.map((r, i) => ({
    id: `SEG-B${i + 1}`,
    x: REGION.x + r.gxStart * CELL_WORLD,
    y: REGION.y + r.gyStart * CELL_WORLD,
    w: (r.gxEnd - r.gxStart) * CELL_WORLD,
    h: (r.gyEnd - r.gyStart) * CELL_WORLD,
    label: 'Building (Dubai real segmentation)',
  }));
}

let zones = [];

function load() {
  if (!fs.existsSync(MASK_PATH)) {
    console.warn('[segmentationZones] mask not found at', MASK_PATH);
    return;
  }
  const png = PNG.sync.read(fs.readFileSync(MASK_PATH));
  const grid = buildBuildingGrid(png);
  zones = gridToRects(grid);
  console.log(`[segmentationZones] derived ${zones.length} real no-fly zones from Dubai segmentation mask`);
}

function getZones() {
  return zones;
}

function stats() {
  return { zoneCount: zones.length, loaded: zones.length > 0, sourceTile: 'tile_020.png' };
}

load();

module.exports = { getZones, stats };
