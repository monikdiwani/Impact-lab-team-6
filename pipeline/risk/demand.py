"""Unmet demand: open issues per road.

Preferred source is M1's out_dir/open_issues.parquet (de-duplicated, Claude-cleaned
categories). Until M1 ships it, we build a simple stand-in from complaints.csv so the
planner still sees what citizens are reporting right now:

  1. keep complaints with status Open / In Progress
  2. locate each one: its own lat/lon, else the locality gazetteer (name or alias)
  3. attach to the nearest road segment, inside the complaint's ward when known
  4. one issue per (road, category); n_complaints and upvotes summed

Complaints with no usable location are counted per ward only (ward_open_unplaced).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from .load import Inputs, point_segment_dist_m

VAGUE = {"Road related", "Other"}


def _locality_lookup(data_dir: Path) -> dict[str, tuple[float, float, str]]:
    loc = pd.read_csv(data_dir / "localities.csv", encoding="utf-8")
    out = {}
    for r in loc.itertuples():
        names = [r.locality] + (str(r.aliases).split(";") if pd.notna(r.aliases) else [])
        for n in names:
            n = str(n).strip().lower()
            if n:
                out.setdefault(n, (r.lat, r.lon, r.ward_code))
    return out


def from_complaints(inp: Inputs, data_dir: Path) -> tuple[pd.DataFrame, pd.Series]:
    c = inp.complaints
    c = c[c.status.isin(C.OPEN_STATUSES)].copy()
    if c.empty:
        return _empty(), pd.Series(dtype=int)

    lookup = _locality_lookup(Path(data_dir))
    hit = c.locality_text.fillna("").str.strip().str.lower().map(lookup)
    need = c.lat.isna() & hit.notna()
    c.loc[need, "lat"] = hit[need].str[0]
    c.loc[need, "lon"] = hit[need].str[1]
    no_ward = c.ward_code.isna() & hit.notna()
    c.loc[no_ward, "ward_code"] = hit[no_ward].str[2]

    placed = c[c.lat.notna() & c.lon.notna()].copy()
    unplaced = c[~c.index.isin(placed.index)].groupby("ward_code").size()

    roads = inp.roads.reset_index(drop=True)
    if not placed.empty:
        d = point_segment_dist_m(placed.lat.values, placed.lon.values, roads)
        pw = placed.ward_code.astype(object).where(placed.ward_code.notna(), None).to_numpy(dtype=object)
        rw = roads.ward_code.astype(object).to_numpy(dtype=object)
        same_ward = pw[:, None] == rw[None, :]
        has_ward = placed.ward_code.notna().to_numpy()[:, None]
        d = np.where(has_ward & ~same_ward, d + 1e7, d)   # prefer roads in the same ward
        idx = d.argmin(axis=1)
        placed["road_id"] = roads.road_id.values[idx]
        placed["ward_code"] = roads.ward_code.values[idx]

    placed["category_clean"] = placed.category_reported.where(
        ~placed.category_reported.isin(VAGUE), "Unclassified")
    g = (placed.groupby(["ward_code", "road_id", "category_clean"], dropna=False)
               .agg(n_complaints=("complaint_id", "size"),
                    first_reported_at=("received_at", "min"),
                    total_upvotes=("upvotes", "sum"))
               .reset_index())
    g["severity_1_5"] = pd.NA
    g["issue_id"] = [f"OI-M3-{i:04d}" for i in range(1, len(g) + 1)]
    return g, unplaced


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["issue_id", "ward_code", "road_id", "category_clean", "severity_1_5",
                                 "n_complaints", "first_reported_at", "total_upvotes"])


def load_open_issues(inp: Inputs, data_dir: Path, out_dir: Path) -> tuple[pd.DataFrame, str, pd.Series]:
    """Return (issues, source, unplaced_per_ward). source is 'M1' or 'M3-fallback'."""
    p = Path(out_dir) / "open_issues.parquet"
    if p.exists():
        try:
            oi = pd.read_parquet(p)
            oi = oi[oi.road_id.isin(set(inp.roads.road_id))]
            return oi, "M1", pd.Series(dtype=int)
        except Exception as e:  # noqa: BLE001 - a bad M1 file must not break M3
            inp.issues.append(f"open_issues.parquet unreadable ({e}); using M3 fallback")
    oi, unplaced = from_complaints(inp, data_dir)
    return oi, "M3-fallback", unplaced
