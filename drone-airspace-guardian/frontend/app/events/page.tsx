import type { Metadata } from "next";
import EventLog from "@/components/EventLog";

export const metadata: Metadata = { title: "Event log" };

export default function EventsPage() {
  return <EventLog />;
}
