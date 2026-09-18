# Drone Airspace Guardian

Team split by folder. Stay in your area unless a change is coordinated.

| Path | Owner | GitHub |
| --- | --- | --- |
| `backend/` | Pranav | [@pranav3086](https://github.com/pranav3086) |
| `frontend/` | Joel | [@joelmathewgeorge](https://github.com/joelmathewgeorge) |
| `ml/` | Rohit | [@vrrroro](https://github.com/vrrroro) |

Ownership is recorded in the repo-root [`.github/CODEOWNERS`](../.github/CODEOWNERS).

## Review-one MVP

Pranav's FastAPI simulation + Joel's Next.js dashboard + Rohit's health model.

- Live Bangalore map, five drones, mission paths shaped from OpenSky ADS-B
- Health scores from the trained C-MAPSS model (not random jitter)
- Draw no-fly zones, emergency helicopter inbound, live reroute + alert banner

```bash
# backend
cd drone-airspace-guardian/backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000

# frontend
cd drone-airspace-guardian/frontend
npm install
npm run dev
```

Open http://localhost:3000. Click **Emergency: helicopter inbound**.
