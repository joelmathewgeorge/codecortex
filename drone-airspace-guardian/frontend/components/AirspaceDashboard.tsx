"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { BENGALURU, DEFAULT_ZONE_RADIUS_M } from "@/lib/config";
import { postEmergency, postZone } from "@/lib/api";
import { mockEmergencyZone } from "@/lib/fake-simulator";
import { useDroneFeed } from "@/hooks/useDroneFeed";
import ConflictBanner from "./ConflictBanner";
import DronePanel from "./DronePanel";
import ErrorNotice from "./ErrorNotice";
import MapControls from "./MapControls";

const DroneMap = dynamic(() => import("./DroneMap"), { ssr: false });

const FEED_LABEL = {
  simulation: "Simulation",
  connecting: "Connecting",
  live: "Live",
  disconnected: "Disconnected",
};

export default function AirspaceDashboard() {
  const { drones, zones, setZones, feed, alert, mode } = useDroneFeed();
  const [drawArmed, setDrawArmed] = useState(false);
  const [busy, setBusy] = useState(false);
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
      setZones((prev) => [...prev, optimistic]);
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
        await postEmergency(BENGALURU.lat, BENGALURU.lon, 2500);
      } else {
        setZones((prev) => [...prev.filter((z) => z.id !== "emergency-mock"), mockEmergencyZone()]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Emergency request failed");
    } finally {
      setBusy(false);
    }
  }, [busy, mode, setZones]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawArmed(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="dag-shell">
      <header className="dag-top">
        <div>
          <p className="kicker">CodeCortex</p>
          <h1>Drone Airspace Guardian</h1>
        </div>
        <p className={`feed is-${feed}`}>{FEED_LABEL[feed]}</p>
      </header>
      <ConflictBanner message={alert?.message ?? null} />
      <DroneMap drones={drones} zones={zones} drawArmed={drawArmed} onMapClick={onMapClick} />
      <DronePanel drones={drones} />
      <div className="dag-legend">
        <span><i className="g" /> Healthy &gt;70</span>
        <span><i className="y" /> Watch 30–70</span>
        <span><i className="r" /> Critical &lt;30</span>
        <span>Dashed = reroute</span>
      </div>
      <MapControls
        drawArmed={drawArmed}
        emergencyBusy={busy}
        onToggleDraw={() => setDrawArmed((v) => !v)}
        onEmergency={onEmergency}
      />
      <ErrorNotice text={error} onDismiss={() => setError(null)} />
    </div>
  );
}
