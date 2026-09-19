"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAirspace } from "./AirspaceProvider";
import { simClock } from "@/lib/format";

const FEED_LABEL = { connecting: "Connecting", live: "Live", disconnected: "Offline" } as const;

function trafficLabel(status: string | undefined) {
  if (!status) return "Air traffic";
  if (status.startsWith("live")) return status === "live" ? "OpenSky live" : "OpenSky stale";
  return "OpenSky replay";
}

export default function TopBar() {
  const { state, feed, setSpeed, busy, world, events } = useAirspace();
  const path = usePathname();
  const speeds = world?.planner.simSpeeds ?? [1, 2, 4];
  const alerts = events.filter((e) => e.severity === "critical" || e.severity === "alert").length;

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <div>
          <p className="brand-name">AirGuard</p>
          <p className="brand-sub">Dubai drone operations</p>
        </div>
      </div>

      <nav className="tabs" aria-label="Pages">
        <Link href="/" className={path === "/" ? "is-active" : ""} aria-current={path === "/" ? "page" : undefined}>
          Console
        </Link>
        <Link href="/events" className={path === "/events" ? "is-active" : ""} aria-current={path === "/events" ? "page" : undefined}>
          Event log
          {alerts > 0 ? <span className="tab-count">{alerts}</span> : null}
        </Link>
      </nav>

      <div className="topbar-right">
        <span className="sim-clock" title="Simulation clock">
          {state ? simClock(state.t) : "T+00:00"}
        </span>
        <div className="speed" role="group" aria-label="Simulation speed">
          {speeds.map((s) => (
            <button
              key={s}
              type="button"
              className={state?.speed === s ? "is-on" : ""}
              aria-pressed={state?.speed === s}
              disabled={busy.speed}
              onClick={() => setSpeed(s)}
            >
              {s}×
            </button>
          ))}
        </div>
        <span className={`traffic ${state?.airTraffic.status.startsWith("live") ? "is-live" : ""}`} title={state?.airTraffic.status}>
          {trafficLabel(state?.airTraffic.status)}
        </span>
        <span className={`feed is-${feed}`}>
          <i aria-hidden="true" />
          {FEED_LABEL[feed]}
        </span>
      </div>
    </header>
  );
}
