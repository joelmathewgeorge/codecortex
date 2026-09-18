"use client";

import { useEffect, useRef, useState } from "react";
import { getApiBase } from "@/lib/config";
import type { VisionFrame } from "@/types/airspace";

/** VisDrone class names, plus the COCO names the pretrained fallback emits before the fine-tune lands. */
const CLASS_COLORS: Record<string, string> = {
  pedestrian: "#ff8fa3",
  people: "#ff8fa3",
  person: "#ff8fa3",
  bicycle: "#9de24f",
  car: "#1ad1c4",
  van: "#5cc8ff",
  truck: "#e0b84a",
  tricycle: "#c08cff",
  "awning-tricycle": "#c08cff",
  bus: "#ff9f43",
  motor: "#ff6bd6",
  motorcycle: "#ff6bd6",
};

const FALLBACK_COLORS = ["#9fb4ff", "#ffd6a5", "#8ef0c8", "#f2a7c3", "#cfd96b"];

const LABEL_PX = 11;
const MAX_LISTED = 6;

function colorFor(label: string) {
  const key = label.trim().toLowerCase();
  const known = CLASS_COLORS[key];
  if (known) return known;
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  return FALLBACK_COLORS[hash % FALLBACK_COLORS.length];
}

function EmptyDock({ note }: { note: string }) {
  return (
    <aside className="dag-vision" aria-label="Aerial camera">
      <div className="dag-panel-head">
        <h2>Camera</h2>
      </div>
      <div className="frame is-empty" />
      <p className="muted">{note}</p>
    </aside>
  );
}

export default function VisionDock({ vision }: { vision: VisionFrame | null }) {
  const frameEl = useRef<HTMLDivElement>(null);
  // Image units per rendered CSS pixel. Label type is sized in image units, so it has to be
  // divided back down or the text is unreadable on a 1920 px frame shown at ~380 px.
  const [unitsPerPx, setUnitsPerPx] = useState(4);
  const [showTruth, setShowTruth] = useState(true);
  const [broken, setBroken] = useState(false);

  const w = vision?.width || 1920;
  const h = vision?.height || 1080;

  useEffect(() => {
    const node = frameEl.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const width = node.getBoundingClientRect().width;
      if (width > 0) setUnitsPerPx(w / width);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [w]);

  if (!vision) return <EmptyDock note="Waiting for camera frames from the detector." />;

  const src = vision.image.startsWith("http") ? vision.image : `${getApiBase()}${vision.image}`;
  const counts = Object.entries(vision.counts)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);
  const total = counts.reduce((sum, [, n]) => sum + n, 0) || vision.detections.length;
  const ranked = [...vision.detections].sort((a, b) => b.conf - a.conf);
  const font = LABEL_PX * unitsPerPx;
  const pad = font * 0.32;
  const metrics = vision.metrics;

  return (
    <aside className="dag-vision" aria-label="Aerial camera">
      <div className="dag-panel-head">
        <h2>Camera</h2>
        <span className={`count ${vision.ready ? "is-live" : ""}`}>
          {vision.ready ? `${total} detected` : "Loading"}
        </span>
      </div>

      <div className="frame" ref={frameEl} style={{ aspectRatio: `${w} / ${h}` }}>
        {/* Backend-served dataset frame on a dynamic host; next/image adds nothing here. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          key={src}
          src={src}
          alt={`VisDrone frame ${vision.frame}`}
          onError={() => setBroken(true)}
          onLoad={() => setBroken(false)}
        />
        <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
          {showTruth
            ? vision.truth.map((t, i) => {
                const [x1, y1, x2, y2] = t.xyxy;
                return (
                  <rect
                    key={`truth-${i}`}
                    className="truth"
                    x={x1}
                    y={y1}
                    width={x2 - x1}
                    height={y2 - y1}
                    vectorEffect="non-scaling-stroke"
                  />
                );
              })
            : null}
          {vision.detections.map((d, i) => {
            const [x1, y1, x2, y2] = d.xyxy;
            const color = colorFor(d.label);
            const text = `${d.label} ${Math.round(d.conf * 100)}%`;
            const chipW = text.length * font * 0.56 + pad * 2;
            const chipH = font * 1.45;
            const chipX = Math.max(0, Math.min(x1, w - chipW));
            const above = y1 - chipH > 0;
            const chipY = above ? y1 - chipH : Math.min(y1, h - chipH);
            return (
              <g key={`det-${d.label}-${i}`} className="det">
                <rect
                  className="box"
                  x={x1}
                  y={y1}
                  width={x2 - x1}
                  height={y2 - y1}
                  stroke={color}
                  vectorEffect="non-scaling-stroke"
                />
                <rect className="chip" x={chipX} y={chipY} width={chipW} height={chipH} fill={color} />
                <text x={chipX + pad} y={chipY + chipH * 0.74} fontSize={font}>
                  {text}
                </text>
              </g>
            );
          })}
        </svg>
        {broken ? <p className="frame-note">Frame unavailable — the detector is restarting.</p> : null}
        {vision.truth.length > 0 ? (
          <button
            type="button"
            className={`truth-toggle ${showTruth ? "is-on" : ""}`}
            aria-pressed={showTruth}
            onClick={() => setShowTruth((v) => !v)}
          >
            {vision.truth.length} dataset labels
          </button>
        ) : null}
      </div>

      {counts.length > 0 ? (
        <ul className="tally">
          {counts.map(([label, n]) => (
            <li key={label}>
              <i style={{ background: colorFor(label) }} />
              <b>{n}</b>
              {label}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">
          {vision.ready ? "No objects in this frame." : "Detector still loading weights."}
        </p>
      )}

      {ranked.length > 0 ? (
        <ol className="detections">
          {ranked.slice(0, MAX_LISTED).map((d, i) => (
            <li key={`row-${d.label}-${i}`}>
              <span className="name">
                <i style={{ background: colorFor(d.label) }} />
                {d.label}
              </span>
              <span className="conf">
                <span className="bar">
                  <span style={{ width: `${Math.round(d.conf * 100)}%`, background: colorFor(d.label) }} />
                </span>
                {Math.round(d.conf * 100)}%
              </span>
            </li>
          ))}
          {ranked.length > MAX_LISTED ? (
            <li className="more">{ranked.length - MAX_LISTED} more below the top scores</li>
          ) : null}
        </ol>
      ) : null}

      <dl className="model-meta">
        <div>
          <dt>model</dt>
          <dd>{metrics?.model || vision.model}</dd>
        </div>
        {metrics?.mAP50 !== undefined ? (
          <div>
            <dt>mAP50</dt>
            <dd>{metrics.mAP50.toFixed(3)}</dd>
          </div>
        ) : null}
        {metrics?.epochs !== undefined ? (
          <div>
            <dt>epochs</dt>
            <dd>{metrics.epochs}</dd>
          </div>
        ) : null}
        {metrics?.images !== undefined ? (
          <div>
            <dt>images</dt>
            <dd>{metrics.images}</dd>
          </div>
        ) : null}
      </dl>

      <p className="frame-id" title={vision.frame}>
        {vision.frame}
      </p>
    </aside>
  );
}
