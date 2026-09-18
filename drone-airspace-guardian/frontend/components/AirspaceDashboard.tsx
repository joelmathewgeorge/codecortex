"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { DUBAI, DEFAULT_ZONE_RADIUS_M, EMERGENCY_RADIUS_M } from "@/lib/config";
import { postEmergency, postReset, postZone } from "@/lib/api";
import { mockEmergencyZone } from "@/lib/fake-simulator";
import { useDroneFeed } from "@/hooks/useDroneFeed";
import ConflictBanner from "./ConflictBanner";
import DronePanel from "./DronePanel";
import ErrorNotice from "./ErrorNotice";
import MapControls from "./MapControls";
import VisionDock from "./VisionDock";

const DroneMap = dynamic(() => import("./DroneMap"), { ssr: false });

const FEED_LABEL = {
  simulation: "Simulation",
  connecting: "Connecting",
  live: "Live",
  disconnected: "Disconnected",
};

export default function AirspaceDashboard() {
  const { drones, zones, setZones, feed, alert, mode, vision } = useDroneFeed();
  const [drawArmed, setDrawArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [resetBusy, setResetBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onMapClick = useCallback(
    async (lat: number, lon: number) => {
      if (!drawArmed) return;
      setDrawArmed(false);
      const optimistic = {
        id: `local-${Date.now()}`,
        lat,
        lon,
        radius: DEFAULT_ZONE_RADIUS_M,
        source: "operator" as const,
      };
      setZones((prev) => [...prev.filter((z) => z.source === "emergency"), optimistic].slice(-5));
      if (mode === "live") {
        try {
          await postZone(lat, lon, DEFAULT_ZONE_RADIUS_M);
        } catch (err) {
          setError(err instanceof Error ? err.message : "Could not save zone");
        }
      }
    },
    [drawArmed, mode, setZones],
  );

  const onEmergency = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (mode === "live") {
        await postEmergency(DUBAI.lat, DUBAI.lon, EMERGENCY_RADIUS_M);
      } else {
        setZones((prev) => [...prev.filter((z) => z.source !== "emergency"), mockEmergencyZone()]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Emergency request failed");
    } finally {
      setBusy(false);
    }
  }, [busy, mode, setZones]);

  const onReset = useCallback(async () => {
    if (resetBusy) return;
    setResetBusy(true);
    try {
      if (mode === "live") await postReset();
      setZones([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setResetBusy(false);
    }
  }, [mode, resetBusy, setZones]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawArmed(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const rerouting = useMemo(() => drones.filter((d) => d.affected).length, [drones]);
  const emergencyActive = useMemo(() => zones.some((z) => z.source === "emergency"), [zones]);

  return (
    <div className="dag-shell">
      <header className="dag-top">
        <div className="dag-identity">
          <span className="dag-mark" aria-hidden="true" />
          <div>
            <h1>Airspace Guardian</h1>
            <p className="lede">
              Downtown Dubai corridor. Live drone tracks, operator no-fly rings and camera detection.
            </p>
          </div>
        </div>
        <div className="dag-readout">
          <span className="stat">
            <b>{drones.length}</b>
            <i>tracked</i>
          </span>
          <span className={`stat ${rerouting ? "is-hot" : ""}`}>
            <b>{rerouting}</b>
            <i>rerouting</i>
          </span>
          <span className={`stat ${emergencyActive ? "is-hot" : ""}`}>
            <b>{zones.length}</b>
            <i>restricted</i>
          </span>
          <p className={`feed is-${feed}`}>
            <i aria-hidden="true" />
            {FEED_LABEL[feed]}
          </p>
        </div>
      </header>

      <main className="dag-body">
        <DronePanel drones={drones} />

        <section className="dag-stage" aria-label="Airspace map">
          <div className="dag-stage-bar">
            <h2>Live airspace</h2>
            <p className="kicker">25.1972 N &nbsp; 55.2744 E</p>
            <MapControls
              drawArmed={drawArmed}
              emergencyBusy={busy}
              resetBusy={resetBusy}
              onToggleDraw={() => setDrawArmed((v) => !v)}
              onEmergency={onEmergency}
              onReset={onReset}
            />
          </div>

          <div className="dag-map-frame">
            <DroneMap drones={drones} zones={zones} drawArmed={drawArmed} onMapClick={onMapClick} />
            <ConflictBanner message={alert?.message ?? null} />
            <p className={`dag-hint ${drawArmed ? "is-on" : ""}`} role="status">
              Click the map to place a {DEFAULT_ZONE_RADIUS_M} m no-fly ring. Escape cancels.
            </p>
          </div>

          <div className="dag-legend">
            <span>
              <i className="g" /> Healthy
            </span>
            <span>
              <i className="y" /> Watch
            </span>
            <span>
              <i className="r" /> Critical
            </span>
            <span>
              <i className="line reroute" /> Reroute
            </span>
            <span>
              <i className="ring nofly" /> No-fly
            </span>
            <span>
              <i className="ring emergency" /> Emergency
            </span>
          </div>
        </section>

        <VisionDock vision={vision} />
      </main>

      <ErrorNotice text={error} onDismiss={() => setError(null)} />
    </div>
  );
}
