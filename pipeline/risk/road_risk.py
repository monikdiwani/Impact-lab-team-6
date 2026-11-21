"""Road risk (0-100, one row per segment) and ward risk.

Each component is scaled to 0-1 and risk_score = 100 * sum(weight * component),
so the score can always be rebuilt from the columns (see config.WEIGHTS).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .load import Inputs, haversine_m, point_segment_dist_m


def _scale(x: pd.Series, log: bool = False) -> pd.Series:
    """Robust 0-1 scaling: divide by the 95th percentile (of non-zero values), clip at 1."""
    x = pd.Series(x, dtype=float).fillna(0).clip(lower=0)
    if log:
        x = np.log1p(x)
    nz = x[x > 0]
    ref = nz.quantile(0.95) if len(nz) else 0
    return (x / ref).clip(0, 1) if ref > 0 else x * 0


# ---- components ------------------------------------------------------------------------

def exposure(inp: Inputs) -> pd.DataFrame:
    t = inp.roads[["road_id"]].merge(inp.traffic, on="road_id", how="left")
    veh = _scale(t.peak_hour_vehicles, log=True)
    cong = (pd.to_numeric(t.congestion_index_0_10, errors="coerce").fillna(0) / 10).clip(0, 1)
    bus = (pd.to_numeric(t.bus_routes_count, errors="coerce").fillna(0) / C.BUS_ROUTES_CAP).clip(0, 1)
    bus = np.maximum(bus, (inp.roads.set_index("road_id").bus_route.reindex(t.road_id).values == "Y") * 0.2)
    e = C.EXPOSURE
    return pd.DataFrame({"road_id": t.road_id,
                         "c_exposure": e["vehicles"] * veh + e["congestion"] * cong + e["bus"] * bus,
                         "peak_hour_vehicles": t.peak_hour_vehicles,
                         "bus_routes_count": t.bus_routes_count})


def safety(inp: Inputs) -> pd.DataFrame:
    a = inp.accidents.copy()
    age = (inp.as_of - a.occurred_at).dt.days.clip(lower=0)
    a["w"] = (a.severity.map(C.SEVERITY_W).fillna(1.0)
              * a.probable_cause.map(C.CAUSE_W).fillna(C.CAUSE_W_OTHER)
              * 0.5 ** (age / C.ACCIDENT_HALF_LIFE_DAYS))
    road_cause = a.probable_cause.isin(["Pothole", "Waterlogged road", "Uneven road / open chamber"])
    g = a.groupby("road_id").agg(acc_w=("w", "sum"), n_acc=("w", "size"))
    g["n_road_acc"] = a[road_cause].groupby("road_id").size()
    g["n_serious"] = a[a.severity.isin(["Fatal", "Grievous"])].groupby("road_id").size()
    out = inp.roads[["road_id"]].merge(g.reset_index(), on="road_id", how="left").fillna(0)
    out["c_safety"] = _scale(out.acc_w, log=True)
    return out.drop(columns="acc_w")


def criticality(inp: Inputs) -> pd.DataFrame:
    f = inp.facilities.copy()
    w = C.FACILITY_W
    f["w"] = np.where(f.type.eq("Hospital") & f.emergency_services.eq("Y"), w["hospital_emergency"],
                      np.where(f.type.eq("Hospital"), w["hospital"], w["school"]))
    f = f.sort_values("w", ascending=False)
    g = f.groupby("ambulance_entry_road").agg(
        w_max=("w", "max"), w_sum=("w", "sum"),
        top_facility=("name", "first"), top_type=("type", "first"),
        n_facilities=("name", "size"))
    # strongest facility counts fully, the rest add a little, capped at 1
    g["c_critical"] = (g.w_max + 0.25 * (g.w_sum - g.w_max)).clip(0, 1)
    out = inp.roads[["road_id"]].merge(g.reset_index().rename(columns={"ambulance_entry_road": "road_id"}),
                                       on="road_id", how="left")
    out["c_critical"] = out.c_critical.fillna(0)
    out["n_facilities"] = out.n_facilities.fillna(0).astype(int)
    return out[["road_id", "c_critical", "top_facility", "top_type", "n_facilities"]]


def hotspot_flood_days(inp: Inputs) -> pd.DataFrame:
    """Days each hotspot likely flooded: rain at its nearest station >= its threshold,
    or a big tide on a tide-sensitive hotspot with rain >= 70% of the threshold."""
    hs = inp.hotspots.copy()
    st = list(C.STATIONS)
    d = np.column_stack([haversine_m(hs.lat, hs.lon, *C.STATIONS[s]) for s in st])
    hs["station"] = [st[i] for i in d.argmin(axis=1)]
    rt = inp.rain.merge(inp.tides[["date", "big_tide"]], on="date", how="left").fillna({"big_tide": False})
    days = []
    for h in hs.itertuples():
        mm = rt[h.station]
        flood = mm >= h.flood_threshold_mm_per_day
        if h.tide_sensitive == "Y":
            flood |= rt.big_tide.astype(bool) & (mm >= 0.7 * h.flood_threshold_mm_per_day)
        days.append(int(flood.sum()))
    hs["flood_days"] = days
    return hs


def flood(inp: Inputs, hs: pd.DataFrame, wards: pd.DataFrame) -> pd.DataFrame:
    roads = inp.roads.reset_index(drop=True)
    max_days = max(hs.flood_days.max(), 1) if len(hs) else 1
    sev = (0.5 * hs.years_flagged_last_5.astype(float) / 5 + 0.5 * hs.flood_days / max_days)
    sev = sev * (1 + C.TIDE_BOOST * (hs.tide_sensitive == "Y")) / (1 + C.TIDE_BOOST)
    if len(hs):
        d = point_segment_dist_m(hs.lat.values, hs.lon.values, roads)   # (hotspots, roads)
        prox = np.exp(-d / C.HOTSPOT_DECAY_M) * sev.values[:, None]
        best = prox.argmax(axis=0)
        near = prox.max(axis=0)
        dist = d[best, np.arange(len(roads))]
        name = hs.name.values[best]
    else:
        near = np.zeros(len(roads)); dist = np.full(len(roads), np.inf); name = np.array([None] * len(roads))
    lli = roads.ward_code.map(wards.set_index("ward_code").low_lying_index).fillna(0).values
    return pd.DataFrame({"road_id": roads.road_id,
                         "c_flood": ((1 - C.FLOOD_WARD_SHARE) * near + C.FLOOD_WARD_SHARE * lli).clip(0, 1),
                         "hotspot": name, "hotspot_dist_m": dist})


def condition(inp: Inputs, issues: pd.DataFrame) -> pd.DataFrame:
    wo = inp.work_orders
    recent = wo[wo.assigned_at >= inp.as_of - pd.Timedelta(days=C.RECENT_DAYS)]
    g = pd.DataFrame({
        "n_wo": wo.groupby("road_id").size(),
        "n_recent_wo": recent.groupby("road_id").size(),
        "n_reopened": wo[wo.reopened].groupby("road_id").size(),
        "billed_inr": wo.groupby("road_id").cost_inr.sum(),
    })
    oi = issues.groupby("road_id").agg(open_issues=("issue_id", "size"),
                                       open_complaints=("n_complaints", "sum"))
    out = (inp.roads[["road_id", "ward_code", "last_resurfaced"]].set_index("road_id")
           .join(g).join(oi).fillna({"n_wo": 0, "n_recent_wo": 0, "n_reopened": 0, "billed_inr": 0,
                                     "open_issues": 0, "open_complaints": 0}).reset_index())
    years = ((inp.as_of - out.last_resurfaced).dt.days / 365.25).fillna(C.AGE_CAP_YEARS)
    out["years_since_resurfaced"] = years.round(1)
    w = C.CONDITION
    road_part = (w["past_work_orders"] * _scale(out.n_wo, log=True)
                 + w["recent_work_orders"] * _scale(out.n_recent_wo, log=True)
                 + w["reopens"] * _scale(out.n_reopened, log=True)
                 + w["open_issues"] * _scale(out.open_complaints, log=True)
                 + w["age"] * (years / C.AGE_CAP_YEARS).clip(0, 1))
    ward_part = _scale(out.groupby("ward_code").n_wo.transform("mean"))
    out["c_condition"] = (1 - C.CONDITION_WARD_SHARE) * road_part + C.CONDITION_WARD_SHARE * ward_part
    return out.drop(columns=["last_resurfaced", "ward_code"])


# ---- assembly ----------------------------------------------------------------------------

COMPONENTS = list(C.WEIGHTS)


def road_risk(inp: Inputs, issues: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (road_risk table with extra fact columns, hotspot table)."""
    assert abs(sum(C.WEIGHTS.values()) - 1) < 1e-9, "risk weights must sum to 1"
    hs = hotspot_flood_days(inp)
    df = inp.roads[["road_id", "ward_code", "road_name", "road_type", "surface", "under_dlp"]]
    for part in (exposure(inp), safety(inp), criticality(inp), flood(inp, hs, inp.wards),
                 condition(inp, issues)):
        df = df.merge(part, on="road_id", how="left")
    for c in COMPONENTS:
        df[c] = df[c].fillna(0).clip(0, 1).round(4)
    df["risk_score"] = (100 * sum(C.WEIGHTS[c] * df[c] for c in COMPONENTS)).round(2)
    df["open_issues"] = df.open_issues.fillna(0).astype(int)
    return df, hs


def ward_risk(inp: Inputs, roads: pd.DataFrame, hs: pd.DataFrame, issues: pd.DataFrame,
              unplaced: pd.Series) -> pd.DataFrame:
    w = inp.wards[["ward_code", "low_lying_index", "monsoon_repair_budget_inr_2025"]].copy()
    billed = inp.work_orders.groupby("ward_code").cost_inr.sum()
    w["billed_inr"] = w.ward_code.map(billed).fillna(0)
    w["remaining_budget_inr"] = w.monsoon_repair_budget_inr_2025 - w.billed_inr

    rs = roads.groupby("ward_code").risk_score.agg(["mean", "max"])
    w = w.join(rs, on="ward_code")

    # flood days: hotspot days in the ward; wards with no hotspot use the nearest station
    hs_days = hs.groupby("ward_code").flood_days.max()
    st = list(C.STATIONS)
    wd = inp.wards.set_index("ward_code")
    near = {wc: st[int(np.argmin([haversine_m(r.centroid_lat, r.centroid_lon, *C.STATIONS[s]) for s in st]))]
            for wc, r in wd.iterrows()}
    fallback = {wc: int((inp.rain[s] >= C.WARD_FLOOD_THRESHOLD_MM).sum()) for wc, s in near.items()}
    w["flood_days"] = [int(hs_days.get(wc, fallback[wc])) for wc in w.ward_code]

    oi = issues.groupby("ward_code").n_complaints.sum() if len(issues) else pd.Series(dtype=float)
    w["open_issues"] = (w.ward_code.map(issues.groupby("ward_code").size()).fillna(0)
                        + w.ward_code.map(unplaced).fillna(0)).astype(int)
    w["open_complaints"] = (w.ward_code.map(oi).fillna(0) + w.ward_code.map(unplaced).fillna(0)).astype(int)

    score = (0.25 * w.low_lying_index
             + 0.25 * w["mean"] / 100
             + 0.15 * w["max"] / 100
             + 0.15 * _scale(w.flood_days)
             + 0.20 * _scale(w.open_complaints, log=True))
    w["risk_score"] = (100 * score).round(2)
    w["mean_road_risk"] = w["mean"].round(2)
    w["max_road_risk"] = w["max"].round(2)
    return w.drop(columns=["mean", "max"])
