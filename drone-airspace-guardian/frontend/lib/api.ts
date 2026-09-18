import { getApiBase, DEFAULT_ZONE_RADIUS_M } from "./config";

export async function postZone(lat: number, lon: number, radius = DEFAULT_ZONE_RADIUS_M) {
  const res = await fetch(`${getApiBase()}/zones`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lat, lon, radius }),
  });
  if (!res.ok) throw new Error(`Zone request failed (${res.status})`);
  return res.json();
}

export async function postEmergency(lat: number, lon: number, radius = 700) {
  const res = await fetch(`${getApiBase()}/emergency`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lat, lon, radius }),
  });
  if (!res.ok) throw new Error(`Emergency request failed (${res.status})`);
  return res.json();
}
