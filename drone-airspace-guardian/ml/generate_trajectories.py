"""
Generate realistic drone flight trajectories.

SIMPLE EXPLANATION:
Creates paths that drones can follow in the sky.
Each path is a list of GPS coordinates (latitude, longitude, altitude).

Think of it like connecting dots on a map!
"""

import json
import numpy as np

np.random.seed(42)

def generate_smooth_trajectory(start_lat, start_lon, num_waypoints=20, 
                                flight_radius_km=5, altitude_m=100):
    """
    Generate a smooth, realistic flight path.
    
    Args:
        start_lat: Starting latitude
        start_lon: Starting longitude  
        num_waypoints: How many points in the path
        flight_radius_km: How far the drone travels
        altitude_m: Flying height in meters
    
    Returns:
        List of [lat, lon, alt] waypoints
    """
    
    waypoints = []
    
    # Degrees per km (approximate)
    lat_per_km = 0.009
    lon_per_km = 0.009
    
    current_lat = start_lat
    current_lon = start_lon
    current_alt = altitude_m
    
    for i in range(num_waypoints):
        # Smooth movement with some randomness
        # Move in a slightly curved path
        angle = (i / num_waypoints) * 2 * np.pi + np.random.normal(0, 0.2)
        distance_km = (flight_radius_km / num_waypoints) + np.random.normal(0, 0.1)
        
        # Calculate next position
        dlat = distance_km * lat_per_km * np.cos(angle)
        dlon = distance_km * lon_per_km * np.sin(angle)
        
        current_lat += dlat
        current_lon += dlon
        
        # Vary altitude slightly
        current_alt += np.random.uniform(-5, 5)
        current_alt = max(50, min(150, current_alt))  # Keep between 50-150m
        
        waypoints.append([
            round(current_lat, 6),
            round(current_lon, 6),
            round(current_alt, 1)
        ])
    
    return waypoints


print("="*60)
print("GENERATING DRONE FLIGHT TRAJECTORIES")
print("="*60)

# Generate trajectories for different starting locations
# These represent different mission areas
trajectories = {}

locations = [
    {"name": "patrol_north", "lat": 40.7589, "lon": -73.9851, "desc": "Northern patrol route"},
    {"name": "patrol_south", "lat": 40.7489, "lon": -73.9681, "desc": "Southern patrol route"},
    {"name": "delivery_urban", "lat": 40.7689, "lon": -73.9781, "desc": "Urban delivery path"},
    {"name": "survey_east", "lat": 40.7389, "lon": -73.9551, "desc": "Eastern survey mission"},
    {"name": "monitoring_west", "lat": 40.7289, "lon": -73.9951, "desc": "Western monitoring route"},
    {"name": "inspection_center", "lat": 40.7589, "lon": -73.9751, "desc": "Central inspection path"},
    {"name": "emergency_response", "lat": 40.7689, "lon": -73.9651, "desc": "Emergency response route"},
]

print(f"\nGenerating {len(locations)} trajectories...\n")

for loc in locations:
    print(f"  [{loc['name']}] {loc['desc']}")
    
    # Generate trajectory
    waypoints = generate_smooth_trajectory(
        start_lat=loc['lat'],
        start_lon=loc['lon'],
        num_waypoints=20,
        flight_radius_km=np.random.uniform(3, 7),
        altitude_m=np.random.uniform(80, 120)
    )
    
    trajectories[loc['name']] = {
        "description": loc['desc'],
        "waypoints": waypoints,
        "num_waypoints": len(waypoints),
        "start_location": [loc['lat'], loc['lon']]
    }

# Save to JSON
output_file = "trajectories.json"
with open(output_file, 'w') as f:
    json.dump(trajectories, f, indent=2)

print(f"\n{'='*60}")
print(f"SUCCESS! Saved {len(trajectories)} trajectories")
print(f"Output file: {output_file}")
print(f"{'='*60}")

print("\nSample trajectory (patrol_north):")
print(f"  Start: {trajectories['patrol_north']['start_location']}")
print(f"  Waypoints: {trajectories['patrol_north']['num_waypoints']}")
print(f"  First 3 points:")
for i, wp in enumerate(trajectories['patrol_north']['waypoints'][:3]):
    print(f"    {i+1}. Lat={wp[0]}, Lon={wp[1]}, Alt={wp[2]}m")

print("\nPranav can now use these trajectories in the backend!")
print("Each trajectory has:")
print("  - description: What the mission is for")
print("  - waypoints: List of [latitude, longitude, altitude]")
print("  - start_location: Where to begin")
