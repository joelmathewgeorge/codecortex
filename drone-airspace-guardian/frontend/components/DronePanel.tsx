"use client";

import type { Drone, DroneBehavior } from "@/types/airspace";
import { getHealthColor, getHealthLabel, getHealthLevel } from "@/lib/health";

const STATUS: Record<string, string> = {
  normal: "En route",
  rerouting: "Rerouting",
  landing: "Landing",
};

const BEHAVIOR: Record<DroneBehavior, string> = {
  cruise: "Cruise",
  orbit: "Orbit",
  hold: "Hold",
  climb: "Climb",
  descend: "Descend",
};

export default function DronePanel({ drones }: { drones: Drone[] }) {
  const sources = Array.from(
    new Set(drones.map((d) => d.trackSource).filter((s): s is string => Boolean(s))),
  );

  return (
    <aside className="dag-panel" aria-label="Drone fleet">
      <div className="dag-panel-head">
        <h2>Fleet</h2>
        <span className="count">{drones.length}</span>
      </div>
      {sources.length > 0 ? (
        <p className="provenance">Tracks replayed from {sources.join(", ")}</p>
      ) : null}
      <ul>
        {drones.map((d) => {
          const level = getHealthLevel(d.health);
          const color = getHealthColor(d.health);
          return (
            <li key={d.id} className={d.affected ? "is-affected" : ""}>
              <div className="row">
                <strong>{d.id}</strong>
                <span className={`status is-${d.status}`}>{STATUS[d.status] ?? d.status}</span>
              </div>
              <p className="mission">{d.mission || "Unassigned"}</p>
              <div className={`health is-${level}`}>
                <span className="bar">
                  <span style={{ width: `${Math.round(d.health)}%`, background: color }} />
                </span>
                <span className="value">{Math.round(d.health)}</span>
                <span className="label">{getHealthLabel(d.health)}</span>
              </div>
              <div className="telemetry">
                {d.behavior ? <span className="behavior">{BEHAVIOR[d.behavior]}</span> : null}
                {Number.isFinite(d.alt) ? <span>{Math.round(d.alt as number)} m</span> : null}
                {Number.isFinite(d.speed) ? <span>{Math.round(d.speed as number)} m/s</span> : null}
                {d.trackSource ? <span className="track">{d.trackSource}</span> : null}
              </div>
            </li>
          );
        })}
      </ul>
      {drones.length === 0 ? <p className="empty">Waiting for the first track update.</p> : null}
    </aside>
  );
}
