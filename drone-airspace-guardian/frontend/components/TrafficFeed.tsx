"use client";

import { useAirspace } from "./AirspaceProvider";

const SOURCE = { "opensky-live": "OpenSky live", "opensky-replay": "OpenSky replay", scheduled: "Scheduled route" } as const;

function Glyph({ kind }: { kind: "airliner" | "helicopter" }) {
  return kind === "helicopter" ? (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="10" r="8.6" fill="none" strokeWidth="1.3" strokeDasharray="3 2" />
      <ellipse cx="12" cy="10.6" rx="3" ry="4.3" />
      <rect x="11.35" y="14.2" width="1.3" height="7.4" rx=".6" />
    </svg>
  ) : (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 1.8c.7 0 1.1.6 1.1 1.4v5.9l7.6 4.5v1.9l-7.6-2.2v4.8l2.3 1.7v1.8L12 20.8l-3.4.9v-1.8l2.3-1.7v-4.8l-7.6 2.2v-1.9l7.6-4.5V3.2c0-.8.4-1.4 1.1-1.4z" />
    </svg>
  );
}

export default function TrafficFeed() {
  const { state } = useAirspace();
  const all = state?.aircraft ?? [];
  const list = all.slice(0, 7);
  const low = all.filter((a) => a.relevant).length;

  return (
    <section className="traffic-feed" aria-label="Aerial detection feed">
      <header className="section-head">
        <h2>Aerial detection feed</h2>
        <span className="count">
          {all.length} aircraft, {low} in the drone layer
        </span>
      </header>
      {list.length === 0 ? <p className="empty">No manned traffic near the operating area.</p> : null}
      <ul>
        {list.map((a) => (
          <li key={a.id} className={`ac risk-${a.risk.toLowerCase()} ${a.relevant ? "" : "is-high"}`}>
            <span className="ac-glyph" style={{ transform: `rotate(${a.heading}deg)` }}>
              <Glyph kind={a.kind} />
            </span>
            <span className="ac-id">
              <b>{a.callsign}</b>
              <i>
                {a.kind === "helicopter" ? "Helicopter" : "Airliner"}, {SOURCE[a.source]}
              </i>
            </span>
            <span className="ac-num">
              <b>{a.alt.toLocaleString("en-GB")}</b> m
            </span>
            <span className="ac-num">
              <b>{a.distanceKm !== null ? a.distanceKm.toFixed(1) : "–"}</b> km
            </span>
            <span className="ac-risk">{a.risk.toLowerCase()}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
