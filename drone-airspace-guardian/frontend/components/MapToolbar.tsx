"use client";

import { EMERGENCY_RADII } from "@/lib/config";
import { useAirspace } from "./AirspaceProvider";

export default function MapToolbar() {
  const { tool, setTool, emergencyRadius, setEmergencyRadius, addDrone, reset, busy, feed } = useAirspace();
  const offline = feed !== "live";

  return (
    <div className="toolbar" role="group" aria-label="Airspace controls">
      <button type="button" className="primary" disabled={busy.drone || offline} onClick={addDrone}>
        {busy.drone ? "Planning route" : "Add drone"}
      </button>
      <button
        type="button"
        className={tool === "nofly" ? "is-on" : ""}
        aria-pressed={tool === "nofly"}
        disabled={offline}
        onClick={() => setTool(tool === "nofly" ? null : "nofly")}
      >
        {tool === "nofly" ? "Cancel no-fly" : "Draw no-fly"}
      </button>
      <span className="emergency-group">
        <button
          type="button"
          className={`danger ${tool === "emergency" ? "is-on" : ""}`}
          aria-pressed={tool === "emergency"}
          disabled={offline}
          onClick={() => setTool(tool === "emergency" ? null : "emergency")}
        >
          {tool === "emergency" ? "Cancel emergency" : "Trigger emergency"}
        </button>
        <label className="radius">
          <span className="sr-only">Emergency radius</span>
          <select value={emergencyRadius} onChange={(e) => setEmergencyRadius(Number(e.target.value))} aria-label="Emergency radius">
            {EMERGENCY_RADII.map((r) => (
              <option key={r} value={r}>
                {r} m
              </option>
            ))}
          </select>
        </label>
      </span>
      <button type="button" className="quiet" disabled={busy.reset || offline} onClick={reset}>
        {busy.reset ? "Resetting" : "Reset"}
      </button>
    </div>
  );
}
