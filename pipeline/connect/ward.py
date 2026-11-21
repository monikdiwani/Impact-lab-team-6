"""Ward recovery for complaints with a blank ward_code (owner: M1).

Order: given -> GPS point-in-polygon -> locality gazetteer (name/alias, then description).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from pipeline.common.geo import WardLocator


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower()) if pd.notna(s) else ""


class Gazetteer:
    def __init__(self, localities: pd.DataFrame):
        self.names: dict[str, tuple] = {}
        for r in localities.itertuples():
            rec = (r.locality, r.ward_code, r.lat, r.lon)
            self.names[_norm(r.locality)] = rec
            if pd.notna(r.aliases):
                for a in str(r.aliases).split(";"):
                    if a.strip():
                        self.names[_norm(a)] = rec
        self._by_len = sorted(self.names, key=len, reverse=True)

    def match(self, text, description=None):
        t = _norm(text)
        if t in self.names:
            return self.names[t]
        # partial names such as "Malad" -> first gazetteer entry that starts with it
        if t:
            cands = sorted(k for k in self.names if k.startswith(t + " "))
            if cands:
                return self.names[cands[0]]
        d = _norm(description)
        for k in self._by_len:  # longest (most specific) name first
            if len(k) >= 4 and k in d:
                return self.names[k]
        return None


def recover_wards(df: pd.DataFrame, localities: pd.DataFrame, geojson: dict) -> pd.DataFrame:
    """Adds filled ward_code, ward_source, locality_norm, loc_lat, loc_lon."""
    loc, gaz = WardLocator(geojson), Gazetteer(localities)
    wards, srcs, lnorm, llat, llon = [], [], [], [], []
    for r in df.itertuples():
        hit = gaz.match(r.locality_text, r.description)
        lnorm.append(hit[0] if hit else None)
        llat.append(hit[2] if hit else np.nan)
        llon.append(hit[3] if hit else np.nan)
        if pd.notna(r.ward_code):
            wards.append(r.ward_code); srcs.append("given"); continue
        w = loc.locate(r.lat, r.lon)
        if w:
            wards.append(w); srcs.append("gps"); continue
        if hit:
            wards.append(hit[1]); srcs.append("locality"); continue
        wards.append(None); srcs.append(None)
    out = df.copy()
    out["ward_code"], out["ward_source"] = wards, srcs
    out["locality_norm"], out["loc_lat"], out["loc_lon"] = lnorm, llat, llon
    return out
