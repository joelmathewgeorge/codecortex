"use client";

import { useState } from "react";
import type { Box, GroundSite } from "@/types/airspace";
import { mediaUrl } from "@/lib/config";
import { GROUND_COLOR } from "@/lib/format";
import { useAirspace } from "./AirspaceProvider";

const CLASS_COLORS: Record<string, string> = {
  person: "#ff8fa3",
  car: "#1ad1c4",
  van: "#5cc8ff",
  truck: "#e0b84a",
  bus: "#ff9f43",
  motor: "#ff6bd6",
  bicycle: "#9de24f",
  trailer: "#c08cff",
};

function colorFor(label: string) {
  return CLASS_COLORS[label.toLowerCase()] ?? "#cfd6e8";
}

function Boxes({ boxes, truth, w }: { boxes: Box[]; truth: boolean; w: number }) {
  const font = Math.max(10, w / 48);
  return (
    <>
      {boxes.map((b, i) => {
        const [x1, y1, x2, y2] = b.xyxy;
        const color = colorFor(b.label);
        if (truth) {
          return <rect key={`t${i}`} className="truth" x={x1} y={y1} width={x2 - x1} height={y2 - y1} />;
        }
        const text = b.conf !== undefined ? `${b.label} ${Math.round(b.conf * 100)}` : b.label;
        const chipW = text.length * font * 0.58 + font * 0.6;
        return (
          <g key={`d${i}`}>
            <rect className="box" x={x1} y={y1} width={x2 - x1} height={y2 - y1} stroke={color} />
            <rect x={x1} y={Math.max(0, y1 - font * 1.3)} width={chipW} height={font * 1.3} fill={color} />
            <text x={x1 + font * 0.3} y={Math.max(0, y1 - font * 1.3) + font * 0.98} fontSize={font}>
              {text}
            </text>
          </g>
        );
      })}
    </>
  );
}

function Frame({ s, showTruth }: { s: GroundSite; showTruth: boolean }) {
  const [broken, setBroken] = useState<string | null>(null);
  const w = s.width || 960;
  const h = s.height || 540;
  if (!s.image) return <div className="cam-frame is-empty" />;
  const src = mediaUrl(s.image);
  return (
    <div className="cam-frame" style={{ aspectRatio: `${w} / ${h}` }}>
      {/* Frames are served by the FastAPI backend on another port; next/image adds nothing here. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={`Aerial frame over ${s.name}`} onError={() => setBroken(src)} onLoad={() => setBroken(null)} />
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
        {showTruth ? <Boxes boxes={s.truth} truth w={w} /> : null}
        <Boxes boxes={s.detections} truth={false} w={w} />
      </svg>
      {broken === src ? <p className="cam-note">Frame unavailable. Run ml/export_auair_frames.py to export the camera footage.</p> : null}
    </div>
  );
}

export default function GroundCamera() {
  const { state, site, setSite } = useAirspace();
  const [showTruth, setShowTruth] = useState(false);
  const sites = state?.ground ?? [];
  const pinned = site ? sites.find((s) => s.id === site) ?? null : null;
  const current = pinned ?? state?.feed ?? null;

  if (!current) {
    return (
      <section className="camera" aria-label="Ground camera">
        <header className="section-head">
          <h2>Ground monitor</h2>
        </header>
        <div className="cam-frame is-empty" />
        <p className="empty">Waiting for the first frame from the ground cameras.</p>
      </section>
    );
  }

  const counts = Object.entries(current.counts).sort((a, b) => b[1] - a[1]);
  const gps = current.telemetry?.gps;

  return (
    <section className="camera" aria-label="Ground camera">
      <header className="section-head">
        <h2>Ground monitor</h2>
        <span className="count">{pinned ? "Pinned camera" : "Cycling cameras"}</span>
      </header>

      <div className="cam-sites" role="tablist" aria-label="Ground cameras">
        {sites.map((s) => (
          <button
            key={s.id}
            type="button"
            role="tab"
            aria-selected={current.id === s.id}
            className={current.id === s.id ? "is-on" : ""}
            style={{ ["--c" as string]: GROUND_COLOR[s.level] }}
            title={`${s.name}: ${s.level.toLowerCase()}`}
            onClick={() => setSite(site === s.id ? null : s.id)}
          >
            {s.id.replace("GM-", "")}
          </button>
        ))}
      </div>

      <p className="cam-title">
        <b>{current.name}</b>
        <span className="level" style={{ color: GROUND_COLOR[current.level] }}>
          {current.level.toLowerCase()} traffic
        </span>
      </p>

      <Frame s={current} showTruth={showTruth} />

      <div className="cam-meta">
        <ul className="tally">
          {counts.length === 0 ? <li className="muted">Nothing detected in this frame</li> : null}
          {counts.map(([label, n]) => (
            <li key={label}>
              <i style={{ background: colorFor(label) }} />
              <b>{n}</b> {label}
            </li>
          ))}
        </ul>
        <p className="muted">
          Overflight cost {current.cost}/m within {current.radius} m. Scored by {current.scoredBy}.
        </p>
        {gps ? (
          <p className="muted">
            {current.dataset} replay recorded at {gps.lat.toFixed(4)}, {gps.lon.toFixed(4)}, {gps.alt_m} m up.
          </p>
        ) : null}
        {current.truth.length ? (
          <label className="truth-toggle">
            <input type="checkbox" checked={showTruth} onChange={(e) => setShowTruth(e.target.checked)} />
            Show {current.truth.length} dataset labels
          </label>
        ) : null}
      </div>
    </section>
  );
}
