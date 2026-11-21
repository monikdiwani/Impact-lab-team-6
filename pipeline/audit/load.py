"""Minimal loaders for the tables M2 needs.

M1 owns the shared loaders (pipeline/common/io.py). Until those land, M2 reads the
CSVs directly here so the audit does not block on them. Swap to the shared loaders
once they exist; the returned columns are the raw CSV columns plus parsed datetimes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _csv(data_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(Path(data_dir) / f"{name}.csv", encoding="utf-8")


def load_frames(data_dir: Path) -> dict[str, pd.DataFrame]:
    wo = _csv(data_dir, "work_orders")
    for col in ("assigned_at", "work_started_at", "completed_at"):
        wo[col] = pd.to_datetime(wo[col], errors="coerce")
    wo["linked_complaint_ids"] = wo["linked_complaint_ids"].where(
        wo["linked_complaint_ids"].fillna("").str.strip() != "", None)

    complaints = _csv(data_dir, "complaints")[["complaint_id", "received_at"]]
    complaints["received_at"] = pd.to_datetime(complaints["received_at"], errors="coerce")

    return {
        "work_orders": wo,
        "rate_card": _csv(data_dir, "rate_card"),
        "roads": _csv(data_dir, "roads"),
        "contractors": _csv(data_dir, "contractors"),
        "wards": _csv(data_dir, "wards"),
        "complaints": complaints,
    }


def enrich_work_orders(f: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per WO with rate-card expected cost, cost ratio, DLP status and first complaint time."""
    wo = f["work_orders"].merge(f["rate_card"], on="repair_method", how="left")
    wo = wo.merge(f["roads"][["road_id", "road_name", "under_dlp"]], on="road_id", how="left")
    wo["expected_inr"] = np.where(wo["unit"] == "per sqm",
                                  wo["area_sqm"] * wo["standard_rate_inr"], wo["standard_rate_inr"])
    wo["cost_ratio"] = wo["cost_inr"] / wo["expected_inr"]

    # first linked complaint (SLA is measured from it, not from assigned_at)
    links = (wo[["work_order_id", "linked_complaint_ids"]].dropna()
             .assign(complaint_id=lambda d: d.linked_complaint_ids.str.split("|"))
             .explode("complaint_id"))
    links["complaint_id"] = links["complaint_id"].str.strip()
    first = (links.merge(f["complaints"], on="complaint_id", how="left")
             .groupby("work_order_id").received_at.min().rename("first_complaint_at"))
    wo = wo.merge(first, on="work_order_id", how="left")
    wo["hours_to_complete"] = (wo["completed_at"] - wo["first_complaint_at"]).dt.total_seconds() / 3600
    return wo
