"use client";

import { useEffect, useRef } from "react";
import type { Drone } from "@/types/airspace";
import { droneState, duration, km } from "@/lib/format";
import { getBatteryColor, getHealthColor, getHealthLabel } from "@/lib/health";
import { useAirspace } from "./AirspaceProvider";

function Bar({ value, color, label }: { value: number; color: string; label: string }) {
  return (
    <span className="bar" role="meter" aria-label={label} aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
      <span style={{ width: `${Math.max(2, Math.min(100, value))}%`, background: color }} />
    </span>
  );
}

function Row({ d, selected, onSelect }: { d: Drone; selected: boolean; onSelect: () => void }) {
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);
  const parked = d.phase === "landed" || d.phase === "charging";
  return (
    <li ref={ref} className={`drone conflict-${d.conflict} ${selected ? "is-selected" : ""} ${parked ? "is-parked" : ""}`}>
      <button type="button" onClick={onSelect} aria-pressed={selected}>
        <span className="line1">
          <strong>{d.id}</strong>
          <span className={`prio prio-${d.priority.toLowerCase()}`}>{d.priority.toLowerCase()}</span>
          <span className="state">{droneState(d)}</span>
        </span>
        <span className="mission">{d.mission}</span>
        <span className="gauges">
          <span className="gauge">
            <i>Battery</i>
            <Bar value={d.battery} color={getBatteryColor(d.battery)} label={`${d.id} battery`} />
            <b>{Math.round(d.battery)}%</b>
          </span>
          <span className="gauge">
            <i>Health</i>
            <Bar value={d.health} color={getHealthColor(d.health)} label={`${d.id} health`} />
            <b>{Math.round(d.health)}%</b>
          </span>
        </span>
        {selected ? (
          <span className="details">
            <span>
              RUL <b>{Math.round(d.rul)}</b> cycles, {getHealthLabel(d.health).toLowerCase()}
            </span>
            {parked ? (
              <span>On the pad at {d.destination}</span>
            ) : (
              <>
                <span>
                  <b>{Math.round(d.alt)} m</b> at <b>{Math.round(d.speed)} m/s</b>, cruise {Math.round(d.cruiseAlt)} m
                </span>
                <span>
                  {km(d.distanceLeftM)} to go, about {duration(d.etaS)}
                </span>
              </>
            )}
            <span>Home port {d.home}</span>
          </span>
        ) : null}
      </button>
    </li>
  );
}

export default function FleetList() {
  const { state, selected, select } = useAirspace();
  const drones = state?.drones ?? [];
  const flying = drones.filter((d) => d.phase !== "landed" && d.phase !== "charging").length;

  return (
    <section className="fleet" aria-label="Fleet">
      <header className="section-head">
        <h2>Fleet</h2>
        <span className="count">
          {flying} flying, {drones.length - flying} on the ground
        </span>
      </header>
      {drones.length === 0 ? <p className="empty">No drones yet. Add one from the map toolbar.</p> : null}
      <ul>
        {drones.map((d) => (
          <Row key={d.id} d={d} selected={selected === d.id} onSelect={() => select(selected === d.id ? null : d.id)} />
        ))}
      </ul>
    </section>
  );
}
