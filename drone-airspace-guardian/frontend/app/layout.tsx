import type { Metadata } from "next";
import { IBM_Plex_Mono, Outfit } from "next/font/google";
import AirspaceProvider from "@/components/AirspaceProvider";
import TopBar from "@/components/TopBar";
import "./globals.css";

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
});

const ibm = IBM_Plex_Mono({
  variable: "--font-ibm",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: { default: "Airspace Guardian", template: "%s | Airspace Guardian" },
  description: "Dubai drone operations: weighted A* routing, 4-D conflict prediction and emergency escape over real restricted airspace.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${outfit.variable} ${ibm.variable}`}>
      <head>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
      </head>
      <body>
        <AirspaceProvider>
          <div className="app">
            <TopBar />
            {children}
          </div>
        </AirspaceProvider>
      </body>
    </html>
  );
}
