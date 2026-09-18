"use client";

import type { Drone } from "@/types/airspace";
import { getHealthColor, getHealthLabel } from "@/lib/health";

const STATUS: Record<string, string> = {
  normal: "Normal",
  rerouting: "Rerouting",
  landing: "Landing",
};

export default function DronePanel({ drones }: { drones: Drone[] }) {
  return (
    <aside className="dag-panel" aria-label="Drone fleet">
      <h2>Fleet</h2>
      <ul>
        {drones.map((d) => (
          <li key={d.id} className={d.affected ? "is-affected" : ""}>
            <div className="row">
              <strong>{d.id}</strong>
              <span className="status">{STATUS[d.status]}</span>
            </div>
            <p className="mission">{d.mission || "Mission"}</p>
            <div className="health">
              <span className="dot" style={{ background: getHealthColor(d.health) }} />
              {Math.round(d.health)}% · {getHealthLabel(d.health)}
            </div>
          </li>
        ))}
      </ul>
    </aside>
  );
}
