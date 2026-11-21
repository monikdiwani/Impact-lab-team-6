"""Geo helpers (owner: M1). numpy haversine + shapely point-in-polygon only."""
from __future__ import annotations

import numpy as np
from shapely.geometry import Point, shape
from shapely.prepared import prep

R_EARTH_M = 6_371_000.0


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance in metres; broadcasts over numpy arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R_EARTH_M * np.arcsin(np.sqrt(a))


class WardLocator:
    def __init__(self, geojson: dict):
        self._polys = [(f["properties"]["ward_code"], prep(shape(f["geometry"])))
                       for f in geojson["features"]]

    def locate(self, lat, lon):
        if lat is None or lon is None or np.isnan(lat) or np.isnan(lon):
            return None
        pt = Point(lon, lat)
        for code, poly in self._polys:
            if poly.covers(pt):
                return code
        return None
