"use client";

import { useMemo, useState } from "react";
import type { AirspaceEvent, Severity } from "@/types/airspace";
import { clock, EVENT_GROUPS, eventGroup, eventName, SEVERITY_COLOR, simClock } from "@/lib/format";
import { useAirspace } from "./AirspaceProvider";

const SEVERITIES: Severity[] = ["critical", "alert", "warning", "success", "info"];
const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  alert: "Alert",
  warning: "Warning",
  success: "Resolved",
  info: "Info",
};

type Candidate = { kind: string; label: string; safe: boolean; cost: number | null; reason: string };

function CandidateTable({ rows }: { rows: Candidate[] }) {
  const best = rows.filter((r) => r.safe && r.cost !== null).sort((a, b) => (a.cost ?? 0) - (b.cost ?? 0))[0];
  return (
    <table className="candidates">
      <caption>Manoeuvres the planner evaluated</caption>
      <thead>
        <tr>
          <th scope="col">Option</th>
          <th scope="col">Safe</th>
          <th scope="col">Cost</th>
          <th scope="col">Why not</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className={r === best ? "is-chosen" : r.safe ? "" : "is-unsafe"}>
            <td>{r.label}</td>
            <td>{r.safe ? "yes" : "no"}</td>
            <td>{r.cost ?? "–"}</td>
            <td>{r === best ? "chosen: cheapest safe option" : r.reason || (r.safe ? "costlier" : "")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Details({ e }: { e: AirspaceEvent }) {
  const { candidates, ...rest } = e.metadata as { candidates?: Candidate[] } & Record<string, unknown>;
  const entries = Object.entries(rest).filter(([, v]) => v !== null && v !== undefined && v !== "");
  return (
    <div className="event-details">
      {Array.isArray(candidates) && candidates.length ? <CandidateTable rows={candidates} /> : null}
      {entries.length ? (
        <dl>
          {entries.map(([k, v]) => (
            <div key={k}>
              <dt>{k.replace(/_/g, " ")}</dt>
              <dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <p className="muted">
        Event #{e.id} at {new Date(e.timestamp).toLocaleString("en-GB")} (simulation {simClock(e.simTime)})
      </p>
    </div>
  );
}

export default function EventLog() {
  const { events, feed } = useAirspace();
  const [severity, setSeverity] = useState<Set<Severity>>(new Set(SEVERITIES));
  const [groups, setGroups] = useState<Set<string>>(new Set(EVENT_GROUPS.map((g) => g.id)));
  const [drone, setDrone] = useState("");
  const [paused, setPaused] = useState<AirspaceEvent[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  const source = paused ?? events;
  const waiting = paused ? events.length - paused.length : 0;
  const needle = drone.trim().toUpperCase();

  const shown = useMemo(
    () =>
      source
        .filter(
          (e) =>
            severity.has(e.severity) &&
            groups.has(eventGroup(e)) &&
            (!needle || e.droneIds.some((d) => d.toUpperCase().includes(needle)) || e.message.toUpperCase().includes(needle)),
        )
        .reverse(),
    [source, severity, groups, needle],
  );

  const bySeverity = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of source) c[e.severity] = (c[e.severity] || 0) + 1;
    return c;
  }, [source]);
  const byGroup = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of source) c[eventGroup(e)] = (c[eventGroup(e)] || 0) + 1;
    return c;
  }, [source]);
  const count = (type: string) => source.filter((e) => e.type === type).length;

  const toggle = <T,>(set: Set<T>, value: T, apply: (s: Set<T>) => void) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    apply(next);
  };

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(shown, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `airspace-events-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <main className="eventlog">
      <aside className="log-filters" aria-label="Filters">
        <h1>Event log</h1>
        <p className="lede">Every decision the planner makes, as it happens.</p>

        <dl className="log-totals">
          <div>
            <dt>Conflicts predicted</dt>
            <dd>{count("CONFLICT_PREDICTED") + count("AIRCRAFT_CONFLICT")}</dd>
          </div>
          <div>
            <dt>Resolved</dt>
            <dd>{count("CONFLICT_RESOLVED") + count("AIRCRAFT_CONFLICT_RESOLVED")}</dd>
          </div>
          <div>
            <dt>Reroutes</dt>
            <dd>{count("REROUTE_STARTED")}</dd>
          </div>
          <div>
            <dt>Emergencies</dt>
            <dd>{count("EMERGENCY_CREATED")}</dd>
          </div>
        </dl>

        <fieldset>
          <legend>Severity</legend>
          {SEVERITIES.map((s) => (
            <label key={s} className="check" style={{ ["--c" as string]: SEVERITY_COLOR[s] }}>
              <input type="checkbox" checked={severity.has(s)} onChange={() => toggle(severity, s, setSeverity)} />
              <span className="swatch" aria-hidden="true" />
              {SEVERITY_LABEL[s]}
              <em>{bySeverity[s] || 0}</em>
            </label>
          ))}
        </fieldset>

        <fieldset>
          <legend>Kind</legend>
          {EVENT_GROUPS.map((g) => (
            <label key={g.id} className="check">
              <input type="checkbox" checked={groups.has(g.id)} onChange={() => toggle(groups, g.id, setGroups)} />
              {g.label}
              <em>{byGroup[g.id] || 0}</em>
            </label>
          ))}
        </fieldset>

        <label className="search">
          <span>Drone or text</span>
          <input type="search" value={drone} placeholder="D07" onChange={(e) => setDrone(e.target.value)} />
        </label>

        <div className="log-actions">
          <button type="button" onClick={() => setPaused(paused ? null : events.slice())} aria-pressed={paused !== null}>
            {paused ? `Resume live${waiting ? ` (${waiting} new)` : ""}` : "Pause live updates"}
          </button>
          <button type="button" className="quiet" onClick={exportJson} disabled={shown.length === 0}>
            Export {shown.length} as JSON
          </button>
        </div>
      </aside>

      <section className="log-list" aria-label="Events">
        <header className="log-head">
          <span>
            Showing {shown.length} of {source.length} events
          </span>
          <span className={`feed is-${feed}`}>
            <i aria-hidden="true" />
            {paused ? "Paused" : feed === "live" ? "Streaming" : "Reconnecting"}
          </span>
        </header>
        {shown.length === 0 ? <p className="empty">No events match these filters yet.</p> : null}
        <ol>
          {shown.map((e) => {
            const expanded = open === e.id;
            return (
              <li key={e.id} className={`event sev-${e.severity} ${expanded ? "is-open" : ""}`} style={{ ["--c" as string]: SEVERITY_COLOR[e.severity] }}>
                <button type="button" onClick={() => setOpen(expanded ? null : e.id)} aria-expanded={expanded}>
                  <span className="when">
                    <b>{clock(e.timestamp)}</b>
                    <i>{simClock(e.simTime)}</i>
                  </span>
                  <span className="what">{eventName(e.type)}</span>
                  <span className="msg">{e.message}</span>
                  <span className="who">
                    {e.droneIds.map((d) => (
                      <em key={d}>{d}</em>
                    ))}
                  </span>
                </button>
                {expanded ? <Details e={e} /> : null}
              </li>
            );
          })}
        </ol>
      </section>
    </main>
  );
}
