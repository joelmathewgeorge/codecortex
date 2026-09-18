# OpenSky - ADS-B Flight Telemetry

Real aircraft position data from the OpenSky Network, which collects ADS-B broadcasts
from a global network of receivers. Each record is a live state vector: callsign,
latitude, longitude, altitude, ground speed, heading, and vertical rate. Good for
flight-telemetry, trajectory, and airspace projects.

## What is in this folder
- `opensky_trajectories.csv` - a live capture over the Indian subcontinent, roughly 180
  aircraft sampled across 20 timesteps, so each aircraft forms a short trajectory
- `authenticated_pull.py` - script to pull more data with your own OpenSky account
  (higher rate limits and historical access; uses the OAuth2 API client, not a password)

License: non-commercial research use. Share trimmed slices, do not rebundle broadly.
