"use client";

import { useEffect, useState } from "react";
import { INTERPOLATION_MS } from "@/lib/config";

export function useInterpolatedPosition(lat: number, lon: number) {
  const [pos, setPos] = useState({ lat, lon });

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setPos({ lat, lon });
      return;
    }
    const from = { ...pos };
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / INTERPOLATION_MS);
      setPos({
        lat: from.lat + (lat - from.lat) * t,
        lon: from.lon + (lon - from.lon) * t,
      });
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lat, lon]);

  return pos;
}
