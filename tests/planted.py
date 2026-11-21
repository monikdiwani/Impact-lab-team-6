"""Planted-anomaly generator: the closest thing we have to the judges' answer key.

Copies data/ to a temp dir and injects anomalies whose IDs we know, plus near-miss
controls that a correct rule set must NOT flag. Thresholds mirror docs/BLUEPRINT.md
(OVERBILL > 1.30x rate card, DOUBLE_BILL within 7 days with no linked complaint).
If M2 changes a threshold, change it here too, in the same PR.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

OVERBILL_RATIO = 1.30
DOUBLE_BILL_DAYS = 7
N = 10  # planted cases per type


@dataclass
class Planted:
    overbill: list[str] = field(default_factory=list)
    overbill_controls: list[str] = field(default_factory=list)      # x1.2: inside tolerance
    double_bill: list[str] = field(default_factory=list)
    double_bill_controls: list[str] = field(default_factory=list)   # +12 days: outside window
    dlp_paid: list[str] = field(default_factory=list)
    dlp_controls: list[str] = field(default_factory=list)           # road taken OFF dlp


def _expected_cost(wo: pd.DataFrame, rc: pd.DataFrame) -> pd.Series:
    m = wo.merge(rc, on="repair_method", how="left")
    exp = np.where(m.unit == "per sqm", m.area_sqm * m.standard_rate_inr, m.standard_rate_inr)
    return pd.Series(exp, index=wo.index)


def plant(data_dir: Path, seed: int = 7) -> Planted:
    rng = np.random.default_rng(seed)
    wo = pd.read_csv(data_dir / "work_orders.csv", encoding="utf-8")
    rc = pd.read_csv(data_dir / "rate_card.csv")
    roads = pd.read_csv(data_dir / "roads.csv", encoding="utf-8")
    p = Planted()

    ratio = wo.cost_inr / _expected_cost(wo, rc)
    dlp_roads = set(roads.loc[roads.under_dlp == "Y", "road_id"])
    clean = wo[(ratio.between(0.9, 1.1)) & wo.linked_complaint_ids.notna()
               & ~wo.road_id.isin(dlp_roads) & (wo.reopened_within_30d == "N")]

    pool = clean.index.to_numpy().copy()
    rng.shuffle(pool)
    pick = iter(pool)
    assigned = pd.to_datetime(wo.assigned_at)

    def quiet(i, days):
        """True if a copy of row i shifted by `days` has no real same-road,
        same-work-type job in the 7 days before it (so it is a fair control)."""
        d = assigned[i] + pd.Timedelta(days=days)
        same = (wo.road_id == wo.road_id[i]) & (wo.work_type == wo.work_type[i])
        near = same & (assigned < d) & (assigned >= d - pd.Timedelta(days=DOUBLE_BILL_DAYS))
        return not near.any()

    def take(k, days=None):
        out = []
        while len(out) < k:
            i = next(pick)
            if days is None or quiet(i, days):
                out.append(i)
        return out

    # OVERBILL: x2.0 must be flagged, x1.2 must not
    for i in take(N):
        wo.loc[i, "cost_inr"] = round(wo.loc[i, "cost_inr"] * 2.0)
        p.overbill.append(wo.loc[i, "work_order_id"])
    for i in take(N):
        wo.loc[i, "cost_inr"] = round(wo.loc[i, "cost_inr"] * 1.2 / ratio[i])  # exactly 1.2x
        p.overbill_controls.append(wo.loc[i, "work_order_id"])

    # DOUBLE_BILL: unlinked copy 2 days later must be flagged; 12 days later must not
    new_rows = []
    for k, (i, days, bucket) in enumerate(
        [(i, 2, p.double_bill) for i in take(N)]
        + [(i, 12, p.double_bill_controls) for i in take(N, days=12)]
    ):
        r = wo.loc[i].copy()
        shift = pd.Timedelta(days=days)
        for col in ("assigned_at", "work_started_at", "completed_at"):
            r[col] = (pd.to_datetime(r[col]) + shift).strftime("%Y-%m-%d %H:%M")
        r["work_order_id"] = f"WO25-9{k:04d}"
        r["linked_complaint_ids"] = np.nan
        r["reopened_within_30d"] = "N"
        new_rows.append(r)
        bucket.append(r["work_order_id"])
    wo = pd.concat([wo, pd.DataFrame(new_rows)], ignore_index=True)

    # DLP: put one non-DLP road under DLP (all its WOs must be flagged) and take one
    # DLP road off (none of its WOs may be flagged)
    jobs = wo.road_id.value_counts()
    on_candidates = [r for r in roads.loc[roads.under_dlp == "N", "road_id"]
                     if 3 <= jobs.get(r, 0) <= 15
                     and not wo.loc[wo.road_id == r, "work_order_id"].isin(
                         p.double_bill + p.double_bill_controls).any()]
    off_candidates = [r for r in dlp_roads if 3 <= jobs.get(r, 0) <= 15]
    road_on = sorted(on_candidates)[int(rng.integers(len(on_candidates)))]
    road_off = sorted(off_candidates)[int(rng.integers(len(off_candidates)))]
    roads.loc[roads.road_id == road_on, "under_dlp"] = "Y"
    roads.loc[roads.road_id == road_off, "under_dlp"] = "N"
    p.dlp_paid = wo.loc[wo.road_id == road_on, "work_order_id"].tolist()
    p.dlp_controls = wo.loc[wo.road_id == road_off, "work_order_id"].tolist()

    wo.to_csv(data_dir / "work_orders.csv", index=False, encoding="utf-8")
    roads.to_csv(data_dir / "roads.csv", index=False, encoding="utf-8")
    return p
