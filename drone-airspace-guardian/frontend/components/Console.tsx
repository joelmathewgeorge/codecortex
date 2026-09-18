"use client";

import dynamic from "next/dynamic";
import EventTicker from "./EventTicker";
import FleetList from "./FleetList";
import GroundCamera from "./GroundCamera";
import MapToolbar from "./MapToolbar";
import { AlertBanner, Legend, Notices, PlacingHint } from "./MapOverlays";
import StatusPanel from "./StatusPanel";
import TrafficFeed from "./TrafficFeed";

const AirspaceMap = dynamic(() => import("./AirspaceMap"), { ssr: false });

export default function Console() {
  return (
    <main className="console">
      <aside className="rail rail-left">
        <StatusPanel />
        <FleetList />
      </aside>

      <section className="stage" aria-label="Airspace map">
        <div className="stage-bar">
          <h1>Dubai drone airspace</h1>
          <MapToolbar />
        </div>
        <div className="map-frame">
          <AirspaceMap />
          <AlertBanner />
          <PlacingHint />
          <Notices />
        </div>
        <Legend />
      </section>

      <aside className="rail rail-right">
        <TrafficFeed />
        <GroundCamera />
        <EventTicker />
      </aside>
    </main>
  );
}
