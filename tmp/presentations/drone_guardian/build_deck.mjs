import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = path.resolve(".");
const buildDir = path.join(workspaceDir, "tmp", "presentations", "drone_guardian");
const assetDir = path.join(buildDir, "assets");
const outputDir = path.join(workspaceDir, "output", "presentations");
const FINAL_PPTX = path.join(outputDir, "Drone_Airspace_Guardian_Hackathon_Pitch.pptx");
const SKILL_DIR = "C:/Users/GEORGE/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const RUNTIME_PYTHON = "C:/Users/GEORGE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
const utils = await import(pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href);
const { resolvePresentationFont, applyPresentationChartFont, finalizePresentation } = utils;

await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(path.join(buildDir, "previews"), { recursive: true });

const font = resolvePresentationFont();
const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });

const C = {
  navy: "#061322",
  navy2: "#0A1C2E",
  panel: "#10283C",
  cyan: "#45D7FF",
  cyan2: "#8AE8FF",
  white: "#F4F8FC",
  muted: "#9FB5C6",
  green: "#36DA91",
  amber: "#FFB14A",
  red: "#FF5A64",
  line: "#24445C",
};

const hero = new Uint8Array(await fs.readFile(path.join(assetDir, "hero.png")));
const dashboard = new Uint8Array(await fs.readFile(path.join(assetDir, "dashboard-concept.png")));
const healthImage = new Uint8Array(await fs.readFile(path.join(assetDir, "health-degradation.png")));

function addText(slide, text, left, top, width, height, size, color = C.white, opts = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    typeface: font,
    fontSize: size,
    bold: opts.bold ?? false,
    color,
    alignment: opts.align ?? "left",
    verticalAlignment: opts.valign ?? "top",
    autoFit: opts.autoFit ?? "shrinkText",
    wrap: "square",
    lineSpacing: opts.lineSpacing ?? 1,
    insets: opts.insets ?? { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function addRect(slide, left, top, width, height, fill, line = "none", radius = 0) {
  return slide.shapes.add({
    geometry: radius ? "roundRect" : "rect",
    position: { left, top, width, height },
    fill,
    line: { style: "solid", fill: line, width: line === "none" ? 0 : 1 },
    ...(radius ? { borderRadius: radius } : {}),
  });
}

function addLine(slide, left, top, width, height, color = C.line, weight = 2, dashed = false) {
  return slide.shapes.add({
    geometry: "line",
    position: { left, top, width, height },
    fill: "none",
    line: { style: dashed ? "dashed" : "solid", fill: color, width: weight },
  });
}

function baseSlide(title, index, section) {
  const slide = presentation.slides.add();
  slide.background.fill = C.navy;
  addText(slide, section.toUpperCase(), 70, 34, 310, 24, 14, C.cyan, { bold: true });
  addText(slide, title, 70, 70, 1140, 58, 32, C.white, { bold: true });
  addLine(slide, 70, 137, 1140, 1, C.line, 1);
  addText(slide, String(index).padStart(2, "0"), 1160, 672, 50, 22, 13, C.muted, { align: "right" });
  return slide;
}

function note(slide, text) {
  slide.speakerNotes.textFrame.setText(text);
}

function statusMark(slide, x, y, color, label, detail) {
  addRect(slide, x, y + 5, 10, 10, color, "none", 5);
  addText(slide, label, x + 24, y, 260, 28, 19, C.white, { bold: true });
  addText(slide, detail, x + 24, y + 32, 400, 48, 15, C.muted);
}

// 1. Cover
{
  const slide = presentation.slides.add();
  slide.images.add({ blob: hero, contentType: "image/png", alt: "Drone over a city with mapped flight paths", fit: "cover", position: { left: 0, top: 0, width: 1280, height: 720 } });
  addRect(slide, 0, 0, 1280, 720, "linear(90deg, #04101F 0%, #04101F/84 42%, #04101F/10 100%)");
  addText(slide, "DRONE AIRSPACE\nGUARDIAN", 78, 154, 560, 190, 54, C.white, { bold: true, lineSpacing: 0.9 });
  addText(slide, "Real-time conflict detection, autonomous rerouting and predictive health", 82, 370, 510, 72, 21, C.cyan2);
  addLine(slide, 82, 464, 250, 1, C.cyan, 3);
  addText(slide, "Hackathon presentation", 82, 490, 320, 28, 15, C.muted, { bold: true });
  addText(slide, "Joel, Pranav, Rohit", 82, 528, 360, 30, 18, C.white);
  addText(slide, "Bengaluru  |  18 September 2026", 82, 574, 420, 26, 14, C.muted);
  note(slide, "Sources: Drone Airspace Guardian Hackathon Roadmap, pp. 1 and 10. Background visual generated for this presentation with OpenAI image generation.");
}

// 2. Problem and solution
{
  const slide = baseSlide("Shared drone airspace needs an automated safety layer", 2, "Problem and solution");
  addText(slide, "Airports, hospitals and dense cities will host many low-altitude missions at once. Manual oversight cannot continuously predict every route conflict.", 70, 175, 500, 132, 24, C.white, { bold: true });
  addText(slide, "The product combines live tracking with rule-based conflict checks, automatic detours and ML health signals.", 70, 340, 470, 86, 19, C.muted);
  addLine(slide, 610, 192, 0, 350, C.line, 1);
  addText(slide, "5", 676, 170, 150, 84, 58, C.cyan, { bold: true });
  addText(slide, "simulated drones\nwith named missions", 676, 254, 220, 60, 18, C.white, { bold: true });
  addText(slide, "1 s", 932, 170, 180, 84, 58, C.green, { bold: true });
  addText(slide, "backend update\ninterval", 932, 254, 210, 60, 18, C.white, { bold: true });
  addText(slide, "The demo moment", 676, 382, 250, 28, 15, C.amber, { bold: true });
  addText(slide, "Emergency zone appears\nAffected drones are identified\nAlternate routes are inserted", 676, 425, 420, 132, 23, C.white, { bold: true, lineSpacing: 1.15 });
  addText(slide, "All actions run without a page reload or manual reroute", 676, 585, 430, 38, 16, C.muted);
  note(slide, "Sources: Roadmap pp. 1, 4-5 and 8-10; backend/main.py and backend/drones.py. The one-second interval and five-drone count come from the current backend implementation.");
}

// 3. UI/UX
{
  const slide = presentation.slides.add();
  slide.background.fill = C.navy;
  slide.images.add({ blob: dashboard, contentType: "image/png", alt: "Concept operator dashboard for Drone Airspace Guardian", fit: "cover", position: { left: 0, top: 0, width: 1280, height: 720 } });
  addRect(slide, 0, 0, 1280, 720, "#03101A/28");
  addRect(slide, 48, 44, 350, 94, "#061322/92", C.line, 12);
  addText(slide, "Target operator experience", 72, 62, 300, 34, 26, C.white, { bold: true });
  addText(slide, "Concept view, not a current product screenshot", 72, 104, 290, 20, 13, C.amber, { bold: true });
  addRect(slide, 48, 594, 1184, 82, "#061322/94", C.line, 10);
  addText(slide, "Map first", 76, 610, 145, 24, 17, C.cyan, { bold: true });
  addText(slide, "Health at a glance", 352, 610, 210, 24, 17, C.green, { bold: true });
  addText(slide, "Conflict state dominates", 670, 610, 240, 24, 17, C.red, { bold: true });
  addText(slide, "Two operator actions", 1010, 610, 190, 24, 17, C.amber, { bold: true });
  addText(slide, "The mission map remains the primary surface", 76, 640, 240, 20, 13, C.muted);
  addText(slide, "Color plus labels support fast scanning", 352, 640, 260, 20, 13, C.muted);
  addText(slide, "Banner, route and marker change together", 670, 640, 290, 20, 13, C.muted);
  addText(slide, "Draw zone and emergency", 1010, 640, 190, 20, 13, C.muted);
  note(slide, "Sources: Approved frontend design spec in docs/superpowers/specs/2026-09-18-drone-airspace-frontend-design.md. Dashboard visual is an AI-generated concept and is explicitly labeled as such on the slide.");
}

// 4. Architecture
{
  const slide = baseSlide("System architecture", 4, "Architecture");
  const sim = addRect(slide, 70, 194, 220, 96, C.panel, C.cyan, 12);
  addText(slide, "Simulation engine", 92, 214, 180, 28, 20, C.white, { bold: true, align: "center" });
  addText(slide, "movement + missions", 92, 252, 180, 20, 14, C.muted, { align: "center" });
  const ws = addRect(slide, 360, 194, 200, 96, C.panel, C.cyan, 12);
  addText(slide, "WebSocket", 382, 214, 156, 28, 20, C.white, { bold: true, align: "center" });
  addText(slide, "positions every tick", 382, 252, 156, 20, 14, C.muted, { align: "center" });
  const ui = addRect(slide, 632, 194, 220, 96, C.panel, C.cyan, 12);
  addText(slide, "Map UI", 654, 214, 176, 28, 20, C.white, { bold: true, align: "center" });
  addText(slide, "routes, zones, alerts", 654, 252, 176, 20, 14, C.muted, { align: "center" });
  const api = addRect(slide, 924, 194, 220, 96, C.panel, C.amber, 12);
  addText(slide, "REST API", 946, 214, 176, 28, 20, C.white, { bold: true, align: "center" });
  addText(slide, "zones + emergency", 946, 252, 176, 20, 14, C.muted, { align: "center" });
  const detect = addRect(slide, 300, 420, 240, 104, C.panel, C.red, 12);
  addText(slide, "Conflict detector", 324, 442, 192, 28, 20, C.white, { bold: true, align: "center" });
  addText(slide, "Haversine distance checks", 324, 481, 192, 24, 14, C.muted, { align: "center" });
  const reroute = addRect(slide, 664, 420, 240, 104, C.panel, C.amber, 12);
  addText(slide, "Reroute calculator", 688, 442, 192, 28, 20, C.white, { bold: true, align: "center" });
  addText(slide, "perpendicular detour point", 688, 481, 192, 24, 14, C.muted, { align: "center" });
  const ml = addRect(slide, 102, 574, 270, 66, C.panel, C.green, 12);
  addText(slide, "ML health model", 126, 590, 220, 26, 19, C.white, { bold: true, align: "center" });
  const state = addRect(slide, 892, 574, 270, 66, C.panel, C.line, 12);
  addText(slide, "In-memory state", 916, 590, 220, 26, 19, C.white, { bold: true, align: "center" });
  slide.shapes.connect(sim, ws, { kind: "straight", fromSide: "right", toSide: "left", line: { style: "solid", fill: C.cyan, width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(ws, ui, { kind: "straight", fromSide: "right", toSide: "left", line: { style: "solid", fill: C.cyan, width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(ui, api, { kind: "straight", fromSide: "right", toSide: "left", line: { style: "solid", fill: C.amber, width: 2 }, tail: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(api, detect, { kind: "elbow", fromSide: "bottom", toSide: "right", line: { style: "solid", fill: C.red, width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(detect, reroute, { kind: "straight", fromSide: "right", toSide: "left", line: { style: "solid", fill: C.amber, width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(reroute, sim, { kind: "elbow", fromSide: "top", toSide: "bottom", line: { style: "solid", fill: C.cyan, width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(ml, sim, { kind: "elbow", fromSide: "top", toSide: "bottom", line: { style: "dashed", fill: C.green, width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  slide.shapes.connect(state, sim, { kind: "elbow", fromSide: "top", toSide: "bottom", line: { style: "dashed", fill: C.muted, width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  note(slide, "Sources: Roadmap pp. 4-5; backend/main.py, backend/drones.py, backend/zones.py, backend/geo_utils.py; ml/predict.py. Solid connectors show implemented runtime flow. The dashed ML connector represents the intended integration because the backend still uses placeholder health jitter.");
}

// 5. Implementation
{
  const slide = baseSlide("Implementation: a small loop drives the full safety response", 5, "Implementation");
  const steps = [
    ["01", "Advance", "Each drone moves toward its next waypoint every second", C.cyan],
    ["02", "Detect", "The next waypoint is checked against every active zone", C.red],
    ["03", "Reroute", "A detour point is inserted outside the zone plus a 100 m buffer", C.amber],
    ["04", "Broadcast", "WebSocket clients receive the new status and position", C.green],
  ];
  steps.forEach((s, i) => {
    const y = 182 + i * 106;
    addText(slide, s[0], 80, y, 60, 42, 30, s[3], { bold: true });
    addText(slide, s[1], 158, y, 180, 34, 22, C.white, { bold: true });
    addText(slide, s[2], 350, y + 2, 500, 52, 17, C.muted);
    if (i < steps.length - 1) addLine(slide, 104, y + 58, 0, 42, C.line, 2);
  });
  addLine(slide, 900, 180, 0, 410, C.line, 1);
  addText(slide, "Live interfaces", 950, 182, 220, 28, 17, C.cyan, { bold: true });
  addText(slide, "WS  /ws", 950, 230, 210, 30, 21, C.white, { bold: true });
  addText(slide, "positions every second", 950, 264, 210, 22, 14, C.muted);
  addText(slide, "POST  /zones", 950, 326, 210, 30, 21, C.white, { bold: true });
  addText(slide, "store a circular restriction", 950, 360, 220, 22, 14, C.muted);
  addText(slide, "POST  /emergency", 950, 422, 230, 30, 21, C.white, { bold: true });
  addText(slide, "check and broadcast immediately", 950, 456, 230, 40, 14, C.muted);
  addText(slide, "GET  /zones", 950, 524, 210, 30, 21, C.white, { bold: true });
  addText(slide, "return all active zones", 950, 558, 210, 22, 14, C.muted);
  note(slide, "Sources: backend/main.py, backend/drones.py and backend/zones.py. Current emergency endpoint requires lat, lon and radius in the request body.");
}

// 6. Machine learning
{
  const slide = baseSlide("The health model is trained and tested on held-out engines", 6, "Machine learning");
  slide.images.add({ blob: healthImage, contentType: "image/png", alt: "Health degradation validation chart", fit: "contain", geometry: "roundRect", borderRadius: 10, position: { left: 64, top: 168, width: 630, height: 420 } });
  const chart = slide.charts.add("bar", {
    position: { left: 740, top: 190, width: 430, height: 220 },
    categories: ["HistGradientBoosting", "RandomForest"],
    series: [{ name: "RMSE", values: [14.78, 15.62], fill: C.cyan }],
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 50 },
    hasLegend: false,
    xAxis: { visible: true, min: 0, max: 18, majorUnit: 3, textStyle: { fill: C.muted, fontSize: 12 }, line: { style: "solid", fill: C.line, width: 1 }, majorGridlines: { style: "solid", fill: C.line, width: 1 } },
    yAxis: { visible: true, textStyle: { fill: C.white, fontSize: 12 }, line: { style: "solid", fill: C.line, width: 1 } },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { fill: C.white, fontSize: 13, bold: true } },
    chartFill: C.navy,
    chartLine: { style: "solid", fill: C.navy, width: 0 },
    plotAreaFill: C.navy,
    plotAreaLine: { style: "solid", fill: C.navy, width: 0 },
  });
  applyPresentationChartFont(chart, { fontFamily: font });
  addText(slide, "14.78", 744, 442, 150, 52, 38, C.cyan, { bold: true });
  addText(slide, "held-out RMSE", 744, 492, 170, 22, 14, C.muted);
  addText(slide, "0.877", 944, 442, 150, 52, 38, C.green, { bold: true });
  addText(slide, "R²", 944, 492, 100, 22, 14, C.muted);
  addText(slide, "160,359 training cycles", 744, 548, 220, 28, 17, C.white, { bold: true });
  addText(slide, "709 training engines  |  707 test engines", 744, 582, 360, 24, 14, C.muted);
  addText(slide, "Current limitation: the model uses turbofan degradation as a proxy. Real drone telemetry should replace it before deployment.", 744, 625, 420, 38, 13, C.amber);
  note(slide, "Sources: ml/model_metadata.json and ml/README.md. Metrics come from NASA C-MAPSS FD001-FD004 held-out test engines. The left image is ml/health_degradation.png. Lower RMSE is better.");
}

// 7. Tech stack
{
  const slide = baseSlide("Technology stack", 7, "Tech stack");
  addText(slide, "Frontend", 78, 190, 250, 36, 25, C.cyan, { bold: true });
  addText(slide, "Next.js 16\nReact 19\nTypeScript\nLeaflet + OpenStreetMap\nNative WebSocket client", 78, 244, 290, 214, 20, C.white, { lineSpacing: 1.28 });
  addText(slide, "Current state: scaffolded", 78, 504, 260, 26, 15, C.amber, { bold: true });
  addLine(slide, 414, 184, 0, 390, C.line, 1);
  addText(slide, "Backend", 458, 190, 250, 36, 25, C.cyan, { bold: true });
  addText(slide, "Python\nFastAPI\nUvicorn\nNative WebSockets\nPydantic validation\nHaversine geometry", 458, 244, 290, 244, 20, C.white, { lineSpacing: 1.28 });
  addText(slide, "Current state: prototype built", 458, 504, 270, 26, 15, C.green, { bold: true });
  addLine(slide, 800, 184, 0, 390, C.line, 1);
  addText(slide, "ML and data", 844, 190, 300, 36, 25, C.cyan, { bold: true });
  addText(slide, "Python\nscikit-learn\npandas + NumPy\nHistGradientBoosting\nNASA C-MAPSS\nOpenSky ADS-B paths", 844, 244, 310, 244, 20, C.white, { lineSpacing: 1.28 });
  addText(slide, "Current state: trained assets built", 844, 504, 300, 26, 15, C.green, { bold: true });
  addRect(slide, 78, 594, 1070, 2, C.line);
  addText(slide, "One repository, one folder per layer, one documented API boundary", 78, 618, 1070, 36, 19, C.muted, { align: "center", bold: true });
  note(slide, "Sources: frontend/package.json; backend/requirements.txt and backend source; ml/README.md and ml/requirements.txt; repository CODEOWNERS.");
}

// 8. Scalability and feasibility
{
  const slide = baseSlide("Feasible for the demo, structured to scale", 8, "Scalability and feasibility");
  addText(slide, "Prototype choices", 76, 180, 320, 32, 24, C.cyan, { bold: true });
  statusMark(slide, 78, 240, C.green, "In-memory state", "Fast setup and no database failure point during the hackathon");
  statusMark(slide, 78, 348, C.green, "Circular zones", "Cheap Haversine checks keep conflict logic understandable");
  statusMark(slide, 78, 456, C.green, "One-second broadcast", "Enough visual continuity for a five-drone local demo");
  addLine(slide, 626, 180, 0, 420, C.line, 1);
  addText(slide, "Production evolution", 680, 180, 360, 32, 24, C.amber, { bold: true });
  statusMark(slide, 682, 240, C.cyan, "Persistent event store", "PostgreSQL or a time-series store for replay and audit");
  statusMark(slide, 682, 348, C.cyan, "Spatial indexing", "Geofences and route segments indexed for larger fleets");
  statusMark(slide, 682, 456, C.cyan, "Distributed simulation", "Partition drones by region and publish through a message broker");
  addText(slide, "Feasibility judgment", 76, 610, 220, 22, 15, C.white, { bold: true });
  addText(slide, "The current architecture is appropriate for a local demonstration. The same boundaries support later replacement of storage, routing and transport components.", 292, 605, 840, 50, 17, C.muted);
  note(slide, "Sources: Roadmap pp. 4, 8 and 10; backend/zones.py architecture note. Production evolution items are proposed next steps, not current implementation claims.");
}

// 9. Progress
{
  const slide = baseSlide("Progress so far", 9, "Delivery status");
  const rows = [
    ["Backend simulation + WebSocket", "BUILT", C.green, "5 drones, missions and one-second position feed"],
    ["Zones + emergency rerouting", "BUILT", C.green, "REST endpoints, conflict checks and detour insertion"],
    ["ML model + trajectory assets", "BUILT", C.green, "trained model, held-out metrics and 8 OpenSky paths"],
    ["Frontend map and controls", "SCAFFOLDED", C.amber, "Next.js exists; Leaflet dashboard still needs implementation"],
    ["End-to-end integration", "PENDING", C.red, "health and route payloads need a shared live contract"],
  ];
  rows.forEach((r, i) => {
    const y = 178 + i * 82;
    addText(slide, r[0], 78, y, 370, 30, 20, C.white, { bold: true });
    addRect(slide, 470, y + 2, 160, 30, `${r[2]}/18`, r[2], 15);
    addText(slide, r[1], 486, y + 7, 128, 20, 13, r[2], { bold: true, align: "center" });
    addText(slide, r[3], 670, y, 490, 42, 16, C.muted);
    addLine(slide, 78, y + 56, 1080, 1, C.line, 1);
  });
  addRect(slide, 78, 606, 1080, 48, "#0F2A3E", C.cyan, 10);
  addText(slide, "Next critical milestone: connect the real WebSocket payload to the Leaflet map, then rehearse the emergency flow end to end", 104, 619, 1030, 24, 17, C.white, { bold: true, align: "center" });
  note(slide, "Sources: repository state at commit 3e4a331 on 18 September 2026; git history; frontend/package.json; backend source; ml/model_metadata.json. Status labels reflect code present in the repository, not verbal claims.");
}

// 10. Closing
{
  const slide = presentation.slides.add();
  slide.images.add({ blob: hero, contentType: "image/png", alt: "Drone over a city with mapped flight paths", fit: "cover", position: { left: 0, top: 0, width: 1280, height: 720 } });
  addRect(slide, 0, 0, 1280, 720, "linear(90deg, #04101F 0%, #04101F/86 55%, #04101F/20 100%)");
  addText(slide, "A missing safety layer\nfor shared drone airspace", 76, 86, 650, 126, 42, C.white, { bold: true, lineSpacing: 0.95 });
  addText(slide, "What the judges should remember", 80, 266, 320, 26, 16, C.cyan, { bold: true });
  addText(slide, "Working safety logic", 80, 318, 300, 30, 23, C.white, { bold: true });
  addText(slide, "Automatic zone detection and geometric rerouting", 80, 354, 500, 28, 17, C.muted);
  addText(slide, "Real machine learning", 80, 412, 300, 30, 23, C.white, { bold: true });
  addText(slide, "Held-out RUL prediction feeds a future routing decision", 80, 448, 520, 28, 17, C.muted);
  addText(slide, "Clear path to scale", 80, 506, 300, 30, 23, C.white, { bold: true });
  addText(slide, "Replace components without changing the operator workflow", 80, 542, 540, 28, 17, C.muted);
  addLine(slide, 80, 608, 260, 1, C.cyan, 3);
  addText(slide, "Demo peak: trigger emergency, watch affected drones reroute", 80, 632, 630, 28, 18, C.amber, { bold: true });
  note(slide, "Sources: Roadmap pp. 1, 9 and 10. The ML-to-routing connection is a planned integration; the current backend still uses placeholder health values. Background visual generated for this presentation with OpenAI image generation.");
}

// Per-slide previews for visual QA.
for (let i = 0; i < presentation.slides.items.length; i++) {
  const preview = await presentation.export({ slide: presentation.slides.items[i], format: "png", scale: 1 });
  await fs.writeFile(path.join(buildDir, "previews", `slide-${String(i + 1).padStart(2, "0")}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const stagingDir = path.join(buildDir, ".codex-finalizer");
await fs.mkdir(stagingDir, { recursive: true });
const candidatePath = path.join(stagingDir, "candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const requirements = {
  explicitTotalSlideCount: 10,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [6],
  requiredEmbeddedWorkbookChartOwnerSlides: [],
  materializeLiteralChartWorkbooks: true,
};
const fontPolicy = { basis: "design", families: [font] };
const result = await finalizePresentation({
  ...requirements,
  workspaceDir,
  candidatePath,
  finalPath: FINAL_PPTX,
  pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", "12192000,6858000",
    "--validate-bullet-geometry",
    "--validate-heading-fit",
  ],
  requiredNativeTableOwnerSlides: [],
  fontPolicy,
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "Drone_Airspace_Guardian_Hackathon_Pitch.validation.json"),
});

console.log(JSON.stringify({ finalPath: FINAL_PPTX, font, result }, null, 2));
