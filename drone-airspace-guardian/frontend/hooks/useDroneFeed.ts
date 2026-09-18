"use client";

import { useEffect, useRef, useState } from "react";
import type { AlertPayload, Drone, FeedState, NoFlyZone } from "@/types/airspace";
import { getDataMode, getWsUrl, LIVE_RECONNECT_MS, MOCK_TICK_MS } from "@/lib/config";
import { adaptAlert, adaptDrones, adaptZones } from "@/lib/drone-adapter";
import { createMockDrones, stepMock } from "@/lib/fake-simulator";

export function useDroneFeed() {
  const mode = getDataMode();
  const [drones, setDrones] = useState<Drone[]>(mode === "mock" ? createMockDrones() : []);
  const [zones, setZones] = useState<NoFlyZone[]>([]);
  const [feed, setFeed] = useState<FeedState>(mode === "mock" ? "simulation" : "connecting");
  const [alert, setAlert] = useState<AlertPayload | null>(null);
  const indices = useRef([0, 0, 0, 0, 0]);
  const zonesRef = useRef(zones);
  zonesRef.current = zones;

  useEffect(() => {
    if (mode !== "mock") return;
    const id = window.setInterval(() => {
      setDrones((prev) => {
        const stepped = stepMock(prev, zonesRef.current, indices.current);
        indices.current = stepped.indices;
        const affected = stepped.drones.filter((d) => d.affected);
        setAlert(
          affected.length
            ? {
                message: `⚠ Airspace conflict — rerouting ${affected.length} drone(s)`,
                affectedIds: affected.map((d) => d.id),
              }
            : null,
        );
        return stepped.drones;
      });
    }, MOCK_TICK_MS);
    return () => window.clearInterval(id);
  }, [mode]);

  useEffect(() => {
    if (mode !== "live") return;
    let ws: WebSocket | undefined;
    let retry: number | undefined;
    let closed = false;

    const connect = () => {
      if (closed) return;
      setFeed("connecting");
      ws = new WebSocket(getWsUrl());
      ws.onopen = () => setFeed("live");
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "positions") {
            const next = adaptDrones(msg.drones);
            if (next.length) setDrones(next);
            if (msg.zones) setZones(adaptZones(msg.zones));
            const affected = next.filter((d) => d.affected);
            setAlert(
              affected.length
                ? {
                    message: `⚠ Airspace conflict — rerouting ${affected.length} drone(s)`,
                    affectedIds: affected.map((d) => d.id),
                  }
                : null,
            );
          }
          if (msg.type === "alert") {
            const parsed = adaptAlert(msg);
            if (parsed) setAlert(parsed);
            if (msg.zone) {
              const [zone] = adaptZones([msg.zone]);
              if (zone) setZones((prev) => [...prev.filter((z) => z.id !== zone.id), zone]);
            }
          }
        } catch (err) {
          console.warn("Ignored malformed feed message", err);
        }
      };
      ws.onclose = () => {
        setFeed("disconnected");
        if (!closed) retry = window.setTimeout(connect, LIVE_RECONNECT_MS);
      };
    };

    connect();
    return () => {
      closed = true;
      if (retry) window.clearTimeout(retry);
      ws?.close();
    };
  }, [mode]);

  return { drones, zones, setZones, feed, alert, mode };
}
