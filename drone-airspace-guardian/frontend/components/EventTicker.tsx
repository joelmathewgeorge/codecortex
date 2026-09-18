"use client";

import Link from "next/link";
import { clock, eventName, SEVERITY_COLOR } from "@/lib/format";
import { useAirspace } from "./AirspaceProvider";

const QUIET = new Set(["RUL_UPDATED", "AIRCRAFT_DETECTED"]);

export default function EventTicker() {
  const { events } = useAirspace();
  const recent = events.filter((e) => !QUIET.has(e.type)).slice(-6).reverse();

  return (
    <section className="ticker" aria-label="Latest events">
      <header className="section-head">
        <h2>Latest events</h2>
        <Link href="/events" className="more">
          Open event log
        </Link>
      </header>
      {recent.length === 0 ? <p className="empty">Events appear here as the planner acts.</p> : null}
      <ol>
        {recent.map((e) => (
          <li key={e.id} style={{ ["--c" as string]: SEVERITY_COLOR[e.severity] }}>
            <span className="when">{clock(e.timestamp)}</span>
            <span className="what">{eventName(e.type)}</span>
            <span className="msg">{e.message}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
