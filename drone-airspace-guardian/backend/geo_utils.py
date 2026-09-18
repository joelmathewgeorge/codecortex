"""
Local flat-earth frame for the Dubai operating box.

Everything in the planner works in metres (x east, y north) around the box centre and only
converts to latitude/longitude at the edges: loading world data and writing the wire format.
"""

import math

import numpy as np


class LocalFrame:
    """
    Equirectangular metres around a reference point.

    Accurate to ~0.1% across the 30 km Dubai box, far below the 150 m planning grid, and it
    keeps distance and heading maths as plain vectors. Accepts floats or numpy arrays.
    """

    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0 = lat0
        self.lon0 = lon0
        self.m_per_deg_lat = 110_574.0
        self.m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))

    def to_xy(self, lat, lon):
        return (np.asarray(lon) - self.lon0) * self.m_per_deg_lon, (np.asarray(lat) - self.lat0) * self.m_per_deg_lat

    def to_latlon(self, x, y):
        return self.lat0 + np.asarray(y) / self.m_per_deg_lat, self.lon0 + np.asarray(x) / self.m_per_deg_lon

    def point(self, lat: float, lon: float) -> tuple[float, float]:
        x, y = self.to_xy(lat, lon)
        return float(x), float(y)

    def latlon(self, x: float, y: float) -> tuple[float, float]:
        lat, lon = self.to_latlon(x, y)
        return float(lat), float(lon)


def heading_of(dx: float, dy: float) -> float:
    """Compass heading in degrees for a local-frame displacement."""
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
