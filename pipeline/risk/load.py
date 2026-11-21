"""Load and clean the CSVs M3 needs.

M1 owns the shared loaders (pipeline/common/io.py). They don't exist yet, so M3
reads its own inputs here. Every step is defensive because evals/backtest_risk.py
feeds us a truncated copy of data/ (blank completed_at, fewer rows).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C


@dataclass
class Inputs:
    roads: pd.DataFrame
    traffic: pd.DataFrame
    work_orders: pd.DataFrame
    accidents: pd.DataFrame
    facilities: pd.DataFrame
    hotspots: pd.DataFrame
    rain: pd.DataFrame          # one row per date: date, santacruz_mm, colaba_mm
    tides: pd.DataFrame         # one row per date: date, max_height_m, big_tide
    wards: pd.DataFrame
    rate_card: pd.DataFrame
    complaints: pd.DataFrame
    as_of: pd.Timestamp         # latest timestamp in the data = "today" for the model
    issues: list[str]           # cleaning notes, written to the run report


def _read(data_dir: Path, name: str) -> pd.DataFrame:
    df = pd.read_csv(data_dir / f"{name}.csv", encoding="utf-8")
    df.columns = [c.strip() for c in df.columns]
    # plain numpy object columns (not pandas' nullable "string"), so numpy maths stays simple
    for c in df.select_dtypes(include=["object", "string"]).columns:
        s = df[c].astype(object)
        s = s.where(s.isna(), s.astype(str).str.strip())
        df[c] = s.replace("", np.nan).astype(object)
    return df


def _yn(s: pd.Series) -> pd.Series:
    return s.fillna("N").astype(str).str.strip().str.upper().str[:1].replace("", "N").astype(object)


def load(data_dir: Path) -> Inputs:
    data_dir = Path(data_dir)
    notes: list[str] = []

    roads = _read(data_dir, "roads").drop_duplicates("road_id")
    roads["under_dlp"] = _yn(roads.under_dlp)
    roads["bus_route"] = _yn(roads.bus_route)
    roads["last_resurfaced"] = pd.to_datetime(roads.last_resurfaced, errors="coerce")
    for c in ("start_lat", "start_lon", "end_lat", "end_lon", "length_m"):
        roads[c] = pd.to_numeric(roads[c], errors="coerce")
    roads["mid_lat"] = (roads.start_lat + roads.end_lat) / 2
    roads["mid_lon"] = (roads.start_lon + roads.end_lon) / 2
    road_ids = set(roads.road_id)

    traffic = _read(data_dir, "traffic").drop_duplicates("road_id")
    traffic = traffic[traffic.road_id.isin(road_ids)]
    missing = road_ids - set(traffic.road_id)
    if missing:
        notes.append(f"traffic: {len(missing)} roads have no traffic row; scored as 0 exposure")

    wo = _read(data_dir, "work_orders").drop_duplicates("work_order_id")
    for c in ("assigned_at", "work_started_at", "completed_at"):
        wo[c] = pd.to_datetime(wo[c], errors="coerce")
    wo["cost_inr"] = pd.to_numeric(wo.cost_inr, errors="coerce")
    wo["area_sqm"] = pd.to_numeric(wo.area_sqm, errors="coerce")
    wo["reopened"] = _yn(wo.reopened_within_30d) == "Y"
    bad = ~wo.road_id.isin(road_ids) | wo.assigned_at.isna()
    if bad.any():
        notes.append(f"work_orders: dropped {int(bad.sum())} rows with unknown road or no assigned_at")
        wo = wo[~bad]

    acc = _read(data_dir, "accidents").drop_duplicates("accident_id")
    acc["occurred_at"] = pd.to_datetime(acc.occurred_at, errors="coerce")
    acc = acc[acc.road_id.isin(road_ids) & acc.occurred_at.notna()]

    fac = _read(data_dir, "facilities").drop_duplicates("facility_id")
    fac["emergency_services"] = _yn(fac.emergency_services)
    fac = fac[fac.ambulance_entry_road.isin(road_ids)]

    hs = _read(data_dir, "flood_hotspots").drop_duplicates("hotspot_id")
    hs["tide_sensitive"] = _yn(hs.tide_sensitive)

    # rain: 2 stations per date -> one wide row per date
    rf = _read(data_dir, "rainfall_daily")
    rf["date"] = pd.to_datetime(rf.date, errors="coerce").dt.normalize()
    rf["rainfall_mm"] = pd.to_numeric(rf.rainfall_mm, errors="coerce").fillna(0)
    rain = (rf.pivot_table(index="date", columns="station", values="rainfall_mm", aggfunc="max")
              .reindex(columns=list(C.STATIONS)).fillna(0).reset_index())
    rain.columns.name = None

    # tides: 2 high tides per date -> one row per date
    td = _read(data_dir, "tides")
    td["date"] = pd.to_datetime(td.date, errors="coerce").dt.normalize()
    td["height_m"] = pd.to_numeric(td.height_m, errors="coerce")
    tides = (td.assign(big=_yn(td.big_tide_flag) == "Y")
               .groupby("date").agg(max_height_m=("height_m", "max"), big_tide=("big", "any"))
               .reset_index())

    wards = _read(data_dir, "wards").drop_duplicates("ward_code")
    wards["monsoon_repair_budget_inr_2025"] = pd.to_numeric(wards.monsoon_repair_budget_inr_2025)
    wards["low_lying_index"] = pd.to_numeric(wards.low_lying_index)

    rc = _read(data_dir, "rate_card").drop_duplicates("repair_method")
    rc["standard_rate_inr"] = pd.to_numeric(rc.standard_rate_inr)

    comp = _read(data_dir, "complaints")
    comp["received_at"] = pd.to_datetime(comp.received_at, errors="coerce")
    for c in ("lat", "lon", "upvotes"):
        comp[c] = pd.to_numeric(comp[c], errors="coerce")

    stamps = [wo.assigned_at.max(), wo.completed_at.max(), comp.received_at.max()]
    as_of = max(t for t in stamps if pd.notna(t)).normalize() + pd.Timedelta(days=1)

    return Inputs(roads, traffic, wo, acc, fac, hs, rain, tides, wards, rc, comp, as_of, notes)


# ---- small geo helpers --------------------------------------------------------------

M_PER_DEG_LAT = 111_320.0


def _xy(lat, lon, lat0):
    return (np.asarray(lon) * M_PER_DEG_LAT * np.cos(np.radians(lat0)),
            np.asarray(lat) * M_PER_DEG_LAT)


def point_segment_dist_m(plat, plon, roads: pd.DataFrame) -> np.ndarray:
    """Distance in metres from points (n,) to each road segment (m,). Returns (n, m)."""
    lat0 = 19.05
    px, py = _xy(np.atleast_1d(plat), np.atleast_1d(plon), lat0)
    ax, ay = _xy(roads.start_lat.values, roads.start_lon.values, lat0)
    bx, by = _xy(roads.end_lat.values, roads.end_lon.values, lat0)
    dx, dy = bx - ax, by - ay
    L2 = np.where(dx**2 + dy**2 == 0, 1e-9, dx**2 + dy**2)
    t = ((px[:, None] - ax) * dx + (py[:, None] - ay) * dy) / L2
    t = np.clip(t, 0, 1)
    cx, cy = ax + t * dx, ay + t * dy
    return np.hypot(px[:, None] - cx, py[:, None] - cy)


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * np.arcsin(np.sqrt(a))
