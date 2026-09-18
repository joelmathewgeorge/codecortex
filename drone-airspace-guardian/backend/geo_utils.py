"""
Geospatial utility functions.

WHY THIS FILE EXISTS:
    Latitude/longitude coordinates live on a sphere (the Earth).
    You can't just do sqrt((x2-x1)^2 + (y2-y1)^2) — that's Euclidean
    distance and it gives wildly wrong answers for points far apart.

    The Haversine formula computes the great-circle distance between
    two points on a sphere. It's the standard tool for this.
"""

import math

# Earth's radius in metres — we work in metres everywhere
EARTH_RADIUS_M = 6_371_000


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Distance in metres between two lat/lon points using the Haversine formula.

    How it works (conceptually):
        1. Convert degrees → radians  (trig functions need radians)
        2. Compute the "haversine" of the central angle:
           a = sin²(Δlat/2) + cos(lat1) * cos(lat2) * sin²(Δlon/2)
        3. Central angle c = 2 * atan2(√a, √(1-a))
        4. Distance = Earth's radius * c

    Returns: distance in metres (float)
    """
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_M * c


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Compute the initial bearing (forward azimuth) from point 1 to point 2.

    WHY WE NEED THIS:
        When rerouting a drone around a zone, we need to know the
        direction from the zone center to the drone's waypoint, then
        push the waypoint perpendicular to that direction (i.e., to the
        "side" of the zone).

    Returns: bearing in degrees (0-360, where 0=North, 90=East)
    """
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1

    x = math.sin(dlon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))

    initial_bearing = math.atan2(x, y)
    # atan2 returns -π to π, convert to 0-360 degrees
    return (math.degrees(initial_bearing) + 360) % 360


def offset_point(lat: float, lon: float, bearing_deg: float,
                 distance_m: float) -> tuple[float, float]:
    """
    Given a starting point and a bearing, compute a new point at the
    given distance along that bearing.

    This is the inverse of haversine — instead of "how far apart are
    these points?", it's "if I walk X metres in direction Y, where do
    I end up?"

    Used by the reroute logic to push a waypoint to the side of a zone.

    Returns: (new_lat, new_lon) in degrees
    """
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    brng_r = math.radians(bearing_deg)
    d = distance_m / EARTH_RADIUS_M  # angular distance

    new_lat = math.asin(
        math.sin(lat_r) * math.cos(d)
        + math.cos(lat_r) * math.sin(d) * math.cos(brng_r)
    )
    new_lon = lon_r + math.atan2(
        math.sin(brng_r) * math.sin(d) * math.cos(lat_r),
        math.cos(d) - math.sin(lat_r) * math.sin(new_lat)
    )

    return math.degrees(new_lat), math.degrees(new_lon)
