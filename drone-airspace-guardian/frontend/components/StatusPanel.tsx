"use client";

import type { Hud } from "@/types/airspace";
import { useAirspace } from "./AirspaceProvider";

function reason(h: Hud): string {
  if (h.status === "EMERGENCY") {
    const zones = `${h.emergencyZones} emergency zone${h.emergencyZones === 1 ? "" : "s"} active`;
    return h.escaping ? `${zones}, ${h.escaping} drone${h.escaping === 1 ? "" : "s"} escaping` : zones;
  }
  if (h.status === "CONFLICT") {
    return h.unresolvedConflicts
      ? `${h.unresolvedConflicts} predicted conflict${h.unresolvedConflicts === 1 ? "" : "s"} awaiting a manoeuvre`
      : "Manned aircraft inside a drone safety volume";
  }
  if (h.status === "CAUTION") {
    if (h.predictedConflicts) return `${h.predictedConflicts} conflict${h.predictedConflicts === 1 ? "" : "s"} being resolved`;
    if (h.groundAlerts) return `Heavy ground traffic at ${h.groundAlerts} monitored road${h.groundAlerts === 1 ? "" : "s"}`;
    return "Low-flying aircraft or a degraded drone nearby";
  }
  return "Every drone is separated in time or height";
}

function Metric({ label, value, unit, hot }: { label: string; value: string | number; unit?: string; hot?: boolean }) {
  return (
    <div className={hot ? "is-hot" : undefined}>
      <dt>{label}</dt>
      <dd>
        {value}
        {unit ? <small>{unit}</small> : null}
      </dd>
    </div>
  );
}

export default function StatusPanel() {
  const { state } = useAirspace();
  const h = state?.hud;

  if (!h) {
    return (
      <section className="status" aria-label="Airspace status">
        <div className="annunciator is-waiting">
          <span className="word">Waiting</span>
          <span className="why">Connecting to the airspace simulator on port 8000.</span>
        </div>
      </section>
    );
  }

  const pct = (v: number | null) => (v === null ? "–" : Math.round(v));

  return (
    <section className="status" aria-label="Airspace status">
      <div className={`annunciator is-${h.status.toLowerCase()}`} role="status" aria-live="polite">
        <span className="word">{h.status}</span>
        <span className="why">{reason(h)}</span>
      </div>

      <div className="risk" aria-label={`Airspace risk ${h.riskLevel} of 100, ${h.riskLabel.toLowerCase()}`}>
        <div className="risk-row">
          <span>Airspace risk</span>
          <b>{h.riskLevel}</b>
          <em>{h.riskLabel.toLowerCase()}</em>
        </div>
        <div className="risk-bar">
          <span style={{ width: `${Math.min(100, h.riskLevel)}%` }} />
        </div>
      </div>

      <dl className="metrics">
        <Metric label="Active drones" value={h.activeDrones} unit={`of ${h.totalDrones}`} />
        <Metric label="Manned aircraft" value={h.activeAircraft} unit={`${h.lowAircraft} low`} />
        <Metric label="Predicted conflicts" value={h.predictedConflicts} hot={h.predictedConflicts > 0} />
        <Metric label="Resolved conflicts" value={h.resolvedConflicts} />
        <Metric label="No-fly zones" value={h.noFlyZones} unit={h.operatorZones ? `+${h.operatorZones} drawn` : "real"} />
        <Metric label="Emergency zones" value={h.emergencyZones} hot={h.emergencyZones > 0} />
        <Metric label="Fleet health" value={pct(h.avgHealth)} unit="%" />
        <Metric label="Average RUL" value={pct(h.avgRul)} unit="cycles" />
        <Metric label="Average battery" value={pct(h.avgBattery)} unit="%" />
        <Metric label="Ground alerts" value={h.groundAlerts} hot={h.groundAlerts > 0} />
      </dl>
    </section>
  );
}
