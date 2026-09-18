"use client";

import { useAirspace } from "./AirspaceProvider";

/** The single most urgent situation, pinned to the top of the map. */
export function AlertBanner() {
  const { state } = useAirspace();
  if (!state) return null;
  const escaping = state.drones.filter((d) => d.phase === "escaping");
  const emergencies = state.zones.filter((z) => z.kind === "emergency");
  const predicted = state.conflicts.filter((c) => c.state === "predicted" || c.state === "unresolved").sort((a, b) => a.ttc - b.ttc);

  let tone = "";
  let text = "";
  if (escaping.length) {
    tone = "emergency";
    text = `${escaping.map((d) => d.id).join(", ")} escaping the emergency zone by the shortest safe exit`;
  } else if (predicted.length) {
    const c = predicted[0];
    tone = "conflict";
    text =
      c.kind === "aircraft"
        ? `${c.a} will enter ${c.bLabel}'s safety volume in ${Math.round(c.ttc)} s. The drone yields.`
        : `${c.a} and ${c.b} predicted to conflict in ${Math.round(c.ttc)} s. Choosing who yields.`;
  } else if (emergencies.length) {
    tone = "watch";
    text = `${emergencies.map((z) => z.label).join(", ")} active. Traffic is routed around it.`;
  }

  return (
    <div className={`alert-banner ${tone ? `is-on is-${tone}` : ""}`} role="alert" aria-live="assertive">
      {tone ? (
        <>
          <span className="pip" aria-hidden="true" />
          <span>{text}</span>
        </>
      ) : null}
    </div>
  );
}

export function PlacingHint() {
  const { tool, emergencyRadius, world } = useAirspace();
  if (!tool) return null;
  const radius = tool === "emergency" ? emergencyRadius : world?.planner.operatorRadiusM ?? 450;
  return (
    <p className={`placing-hint is-${tool}`} role="status">
      Click the map to place a {radius} m {tool === "emergency" ? "emergency zone" : "no-fly zone"}. Press Escape to cancel.
    </p>
  );
}

export function Notices() {
  const { notice, error, clearError } = useAirspace();
  return (
    <div className="notices" aria-live="polite">
      {notice ? <p className="notice">{notice}</p> : null}
      {error ? (
        <p className="notice is-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={clearError}>
            Dismiss
          </button>
        </p>
      ) : null}
    </div>
  );
}

export function Legend() {
  return (
    <ul className="legend" aria-label="Map legend">
      <li>
        <i className="lg-route" /> Planned route
      </li>
      <li>
        <i className="lg-conflict" /> Predicted conflict
      </li>
      <li>
        <i className="lg-maneuver" /> Manoeuvre or detour
      </li>
      <li>
        <i className="lg-escape" /> Emergency escape
      </li>
      <li>
        <i className="lg-original" /> Original route
      </li>
      <li>
        <i className="lg-nfz" /> Restricted core
      </li>
      <li>
        <i className="lg-buffer" /> Soft buffer
      </li>
      <li>
        <i className="lg-aircraft" /> Manned aircraft
      </li>
      <li>
        <i className="lg-cross" /> Routes cross, separated
      </li>
      <li>
        <i className="lg-ground" /> Ground monitor
      </li>
    </ul>
  );
}
