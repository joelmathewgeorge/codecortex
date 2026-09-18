"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { AirspaceEvent, FeedState, SimState, World } from "@/types/airspace";
import { api } from "@/lib/api";
import { EMERGENCY_RADII, EVENT_BUFFER, getWsUrl, LIVE_RECONNECT_MS } from "@/lib/config";

export type Tool = "nofly" | "emergency" | null;

type Busy = "drone" | "zone" | "reset" | "speed";

type AirspaceContext = {
  world: World | null;
  state: SimState | null;
  events: AirspaceEvent[];
  feed: FeedState;
  tool: Tool;
  setTool: (tool: Tool) => void;
  emergencyRadius: number;
  setEmergencyRadius: (r: number) => void;
  selected: string | null;
  select: (id: string | null) => void;
  site: string | null;
  setSite: (id: string | null) => void;
  busy: Partial<Record<Busy, boolean>>;
  notice: string | null;
  error: string | null;
  clearError: () => void;
  addDrone: () => Promise<void>;
  placeZone: (lat: number, lon: number) => Promise<void>;
  removeZone: (id: string) => Promise<void>;
  reset: () => Promise<void>;
  setSpeed: (speed: number) => Promise<void>;
};

const Ctx = createContext<AirspaceContext | null>(null);

export function useAirspace(): AirspaceContext {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAirspace must be used inside <AirspaceProvider>");
  return ctx;
}

function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export default function AirspaceProvider({ children }: { children: React.ReactNode }) {
  const [world, setWorld] = useState<World | null>(null);
  const [state, setState] = useState<SimState | null>(null);
  const [events, setEvents] = useState<AirspaceEvent[]>([]);
  const [feed, setFeed] = useState<FeedState>("connecting");
  const [tool, setTool] = useState<Tool>(null);
  const [emergencyRadius, setEmergencyRadius] = useState(EMERGENCY_RADII[1]);
  const [selected, select] = useState<string | null>(null);
  const [site, setSite] = useState<string | null>(null);
  const [busy, setBusy] = useState<Partial<Record<Busy, boolean>>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const noticeTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    let retry: number | undefined;
    const load = () => {
      api
        .world()
        .then((w) => !cancelled && setWorld(w))
        .catch(() => {
          if (!cancelled) retry = window.setTimeout(load, LIVE_RECONNECT_MS);
        });
    };
    load();
    return () => {
      cancelled = true;
      window.clearTimeout(retry);
    };
  }, []);

  useEffect(() => {
    let ws: WebSocket | undefined;
    let retry: number | undefined;
    let closed = false;
    const connect = () => {
      if (closed) return;
      setFeed("connecting");
      ws = new WebSocket(getWsUrl());
      ws.onopen = () => setFeed("live");
      ws.onmessage = (ev) => {
        let msg: { type?: string; events?: AirspaceEvent[]; reset?: boolean };
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (msg.type === "state") {
          setState(msg as unknown as SimState);
        } else if (msg.type === "events" && Array.isArray(msg.events)) {
          const fresh = msg.events;
          setEvents((prev) => {
            const last = prev.length ? prev[prev.length - 1].id : 0;
            const next = fresh.filter((e) => e.id > last);
            return next.length ? [...prev, ...next].slice(-EVENT_BUFFER) : prev;
          });
        } else if (msg.type === "hello" && Array.isArray(msg.events)) {
          setEvents(msg.events.slice(-EVENT_BUFFER));
          if (msg.reset) select(null);
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
      window.clearTimeout(retry);
      ws?.close();
    };
  }, []);

  const flash = useCallback((text: string) => {
    setNotice(text);
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 6000);
  }, []);

  const run = useCallback(async (key: Busy, job: () => Promise<void>) => {
    setBusy((b) => ({ ...b, [key]: true }));
    try {
      await job();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The request failed.");
    } finally {
      setBusy((b) => ({ ...b, [key]: false }));
    }
  }, []);

  const addDrone = useCallback(
    () =>
      run("drone", async () => {
        const res = await api.addDrone("auto");
        select(res.drone.id);
        flash(
          res.predictedConflicts.length
            ? `${res.drone.id} launched. Conflict predicted with ${res.predictedConflicts.join(", ")}.`
            : `${res.drone.id} launched on a clear route.`,
        );
      }),
    [flash, run],
  );

  const placeZone = useCallback(
    (lat: number, lon: number) =>
      run("zone", async () => {
        const emergency = tool === "emergency";
        setTool(null);
        const res = emergency ? await api.addEmergency(lat, lon, emergencyRadius) : await api.addZone(lat, lon);
        const parts = [
          res.inside.length ? `${plural(res.inside.length, "drone")} escaping` : "",
          res.approaching.length ? `${plural(res.approaching.length, "drone")} rerouting` : "",
        ].filter(Boolean);
        flash(`${emergency ? "Emergency" : "No-fly zone"} ${res.zone.id} placed. ${parts.length ? parts.join(", ") + "." : "No drones affected."}`);
      }),
    [emergencyRadius, flash, run, tool],
  );

  const removeZone = useCallback(
    (id: string) =>
      run("zone", async () => {
        await api.removeZone(id);
        flash(`${id} lifted.`);
      }),
    [flash, run],
  );

  const reset = useCallback(
    () =>
      run("reset", async () => {
        await api.reset();
        setTool(null);
        flash("Airspace reset to the opening fleet.");
      }),
    [flash, run],
  );

  const setSpeed = useCallback((speed: number) => run("speed", async () => void (await api.setSpeed(speed))), [run]);

  const value = useMemo<AirspaceContext>(
    () => ({
      world,
      state,
      events,
      feed,
      tool,
      setTool,
      emergencyRadius,
      setEmergencyRadius,
      selected,
      select,
      site,
      setSite,
      busy,
      notice,
      error,
      clearError: () => setError(null),
      addDrone,
      placeZone,
      removeZone,
      reset,
      setSpeed,
    }),
    [world, state, events, feed, tool, emergencyRadius, selected, site, busy, notice, error, addDrone, placeZone, removeZone, reset, setSpeed],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
