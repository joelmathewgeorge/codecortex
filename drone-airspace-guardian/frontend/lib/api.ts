import type { World } from "@/types/airspace";
import { getApiBase } from "./config";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : "";
    } catch {
      // non-JSON error body
    }
    throw new Error(detail || `${path} failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  world: () => call<World>("/world"),
  addDrone: (mode: "auto" | "random" | "encounter" = "auto") =>
    call<{ drone: { id: string }; predictedConflicts: string[] }>("/drones", {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
  addZone: (lat: number, lon: number, radius?: number) =>
    call<{ zone: { id: string }; inside: string[]; approaching: string[] }>("/zones", {
      method: "POST",
      body: JSON.stringify({ lat, lon, radius }),
    }),
  addEmergency: (lat: number, lon: number, radius?: number) =>
    call<{ zone: { id: string }; inside: string[]; approaching: string[] }>("/emergency", {
      method: "POST",
      body: JSON.stringify({ lat, lon, radius }),
    }),
  removeZone: (id: string) => call<{ removed: string }>(`/zones/${encodeURIComponent(id)}`, { method: "DELETE" }),
  reset: () => call<{ status: string }>("/reset", { method: "POST" }),
  setSpeed: (speed: number) => call<{ speed: number }>("/sim", { method: "POST", body: JSON.stringify({ speed }) }),
};
