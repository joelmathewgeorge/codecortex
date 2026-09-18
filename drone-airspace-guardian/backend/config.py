"""
Simulation parameters in one place.

Numbers here are simulation policy chosen to make a laptop demo legible, not certified
separation standards. Costs follow the Dynamic Risk Map table in the planning spec and are
per metre flown: a cell costing 15 makes one metre over it as expensive as 15 metres of
open airspace.
"""

from __future__ import annotations

from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent / "ml"
AIRSPACE_FILE = ML_DIR / "dubai_airspace.json"
AIR_TRAFFIC_FILE = ML_DIR / "air_traffic.json"
AUAIR_DIR = ML_DIR / "auair_frames"

# --- clock ------------------------------------------------------------------
TICK_S = 1.0  # wall seconds between broadcasts
SUBSTEP_S = 0.25  # physics step in sim seconds
SIM_SPEEDS = (1, 2, 4)

# --- risk map ---------------------------------------------------------------
CELL_M = 150.0

COST_NORMAL = 1.0
COST_LOW_BUFFER = 5.0
COST_CONGESTION = 10.0
COST_GROUND_AREA = 15.0
COST_NEAR_RESTRICTED = 25.0
COST_AIRCRAFT = 100.0
COST_EMERGENCY_BUFFER = 500.0

# Ground-risk levels -> extra cost per metre. EXTREME is handled as a hard block.
GROUND_LEVELS = ("LOW", "MEDIUM", "HIGH", "VERY HIGH", "EXTREME")
GROUND_COST = {"LOW": 0.0, "MEDIUM": 5.0, "HIGH": COST_GROUND_AREA, "VERY HIGH": 40.0}
URBAN_GROUND_COST = 0.3  # people live under most of Dubai; open water carries none
ROAD_HALF_WIDTH_M = 90.0
CROWD_RADIUS_M = 450.0

# category -> (buffer width m, buffer cost)
RESTRICTED_POLICY = {
    "airport": (1500.0, COST_NEAR_RESTRICTED),
    "approach": (300.0, COST_NEAR_RESTRICTED),
    "airfield": (500.0, COST_NEAR_RESTRICTED),
    "military": (400.0, COST_NEAR_RESTRICTED),
    "palace": (400.0, COST_NEAR_RESTRICTED),
    "government": (250.0, COST_LOW_BUFFER),
    "power": (250.0, COST_LOW_BUFFER),
    "stadium": (300.0, COST_LOW_BUFFER),
    "racecourse": (300.0, COST_LOW_BUFFER),
}
# Drones inside an airport's buffer ring must stay at or below this altitude.
AIRPORT_CEILING_M = 60.0

OPERATOR_ZONE_RADIUS_M = 450.0
OPERATOR_ZONE_BUFFER_M = 200.0
MAX_OPERATOR_ZONES = 4
EMERGENCY_RADIUS_M = 700.0
EMERGENCY_BUFFER_M = 350.0
MAX_EMERGENCY_ZONES = 3

# --- drones -----------------------------------------------------------------
ALT_MIN_M = 40.0
ALT_MAX_M = 150.0
CRUISE_ALTS = (60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0)
CLIMB_RATE = 4.0  # m/s
MAX_VERTICAL_RATE = 5.0
SPEED_RANGE = (14.0, 21.0)
ESCAPE_SPEED_FACTOR = 1.35
MAX_SPEED = 26.0

# battery, in percent
BATTERY_PER_KM = 1.6
BATTERY_PER_CLIMB_M = 0.012
BATTERY_HOVER_PER_S = 0.035
BATTERY_IDLE_PER_S = 0.002
CHARGE_PER_S = 1.2
LOW_BATTERY = 50.0
CRITICAL_BATTERY = 20.0

# health bands from the C-MAPSS model (0-100, derived from predicted RUL)
HEALTH_MONITOR = 75.0
HEALTH_SERVICE = 50.0
HEALTH_CRITICAL = 25.0
HEALTH_MODEL_EVERY_S = 15.0  # one model cycle per this many airborne sim seconds

TURNAROUND_S = 8.0

# --- separation and prediction --------------------------------------------------
DRONE_H_SEP_M = 150.0
DRONE_V_SEP_M = 30.0
PREDICT_HORIZON_S = 45.0
PREDICT_STEP_S = 1.0
CANDIDATE_HORIZON_S = 75.0
DECISION_DELAY_S = 2.0  # a predicted conflict shows red this long before the resolver acts
IMMEDIATE_TTC_S = 8.0
RESOLVED_DISPLAY_S = 5.0

AIRCRAFT_HORIZON_S = 60.0
AIRCRAFT_SEPARATION = {  # kind -> (horizontal m, vertical m)
    "helicopter": (450.0, 90.0),
    "airliner": (900.0, 150.0),
}
# Aircraft above this altitude cannot come within vertical separation of the drone layer.
AIRCRAFT_RELEVANT_ALT_M = ALT_MAX_M + 160.0

PRIORITY_RANK = {"CRITICAL": 4, "HIGH": 3, "NORMAL": 2, "LOW": 1}

# --- planner ------------------------------------------------------------------
ASTAR_EPSILON = 1.25
ASTAR_MAX_EXPANSIONS = 250_000
REPLANS_PER_TICK = 6
