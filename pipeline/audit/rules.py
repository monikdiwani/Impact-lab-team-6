"""The five audit rules (blueprint §7 M2). Each returns rows in the AuditFlag schema
(contracts/schemas.py "audit_flags"), minus flag_id and explanation, which run() adds.

All numbers are computed here with pandas. Claude never computes a number.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.audit import config as C

FLAG_COLS = ["flag_type", "severity", "work_order_id", "related_work_order_id", "ward_code",
             "road_id", "contractor_id", "billed_inr", "expected_inr", "amount_at_risk_inr", "evidence"]


def _inr(x: float) -> str:
    return C.inr(float(x))


def _base(wo: pd.DataFrame, flag_type: str) -> pd.DataFrame:
    out = pd.DataFrame({
        "flag_type": flag_type,
        "work_order_id": wo["work_order_id"].to_numpy(),
        "related_work_order_id": None,
        "ward_code": wo["ward_code"].to_numpy(),
        "road_id": wo["road_id"].to_numpy(),
        "contractor_id": wo["contractor_id"].to_numpy(),
        "billed_inr": wo["cost_inr"].astype(float).to_numpy(),
    }, index=wo.index)
    return out


def overbill(wo: pd.DataFrame) -> pd.DataFrame:
    hit = wo[wo["cost_ratio"] > C.OVERBILL_RATIO]
    out = _base(hit, "OVERBILL")
    out["severity"] = np.where(hit["cost_ratio"] > C.OVERBILL_HIGH_RATIO, "high", "medium")
    out["expected_inr"] = hit["expected_inr"].astype(float)
    out["amount_at_risk_inr"] = (hit["cost_inr"] - C.OVERBILL_RATIO * hit["expected_inr"]).clip(lower=0).round(0)
    out["evidence"] = [
        f"billed {r:.2f}x the rate card ({_inr(b)} vs {_inr(e)} for {m}); "
        f"{_inr(a)} above the {C.OVERBILL_RATIO:.2f}x tolerance"
        for r, b, e, m, a in zip(hit.cost_ratio, hit.cost_inr, hit.expected_inr, hit.repair_method,
                                 out.amount_at_risk_inr)]
    return out[FLAG_COLS]


def double_bill(wo: pd.DataFrame) -> pd.DataFrame:
    s = wo.sort_values(["road_id", "work_type", "assigned_at", "work_order_id"])
    g = s.groupby(["road_id", "work_type"], sort=False)
    prev_id = g["work_order_id"].shift()
    gap = s["assigned_at"] - g["assigned_at"].shift()
    mask = (s["linked_complaint_ids"].isna() & prev_id.notna()
            & (gap <= pd.Timedelta(days=C.DOUBLE_BILL_DAYS)))
    hit = s[mask]
    out = _base(hit, "DOUBLE_BILL")
    out["related_work_order_id"] = prev_id[mask]
    out["severity"] = "high"
    out["expected_inr"] = 0.0
    out["amount_at_risk_inr"] = hit["cost_inr"].astype(float)
    gap_days = (gap[mask].dt.total_seconds() / 86400).round(1)
    out["evidence"] = [
        f"no complaint linked; same road and work type ({wt}) as {p}, assigned {d:g} days earlier; "
        f"{_inr(b)} billed again"
        for wt, p, d, b in zip(hit.work_type, out.related_work_order_id, gap_days, hit.cost_inr)]
    return out[FLAG_COLS]


def dlp_paid(wo: pd.DataFrame) -> pd.DataFrame:
    hit = wo[(wo["under_dlp"] == "Y") & (wo["cost_inr"] > 0)]
    out = _base(hit, "DLP_PAID")
    out["severity"] = "medium"
    out["expected_inr"] = 0.0
    out["amount_at_risk_inr"] = hit["cost_inr"].astype(float)
    out["evidence"] = [
        f"road {rd} ({rn}) is under the defect liability period (DLP); {_inr(b)} billed to BMC "
        f"that the original contractor should cover; recoverable"
        for rd, rn, b in zip(hit.road_id, hit.road_name, hit.cost_inr)]
    return out[FLAG_COLS]


def sla_miss(wo: pd.DataFrame) -> pd.DataFrame:
    hit = wo[wo["sla_met"] == "N"]
    out = _base(hit, "SLA_MISS")
    late = (hit["hours_to_complete"] - hit["sla_hours"]).round(1)
    out["severity"] = np.select(
        [late > hit["sla_hours"] * C.SLA_HIGH_LATE_FACTOR, late > C.SLA_MEDIUM_LATE_HOURS],
        ["high", "medium"], default="low")
    out["expected_inr"] = np.nan
    out["amount_at_risk_inr"] = 0.0
    out["evidence"] = [
        (f"completed {h:.0f} h after the first complaint against a {s:.0f} h deadline ({l:g} h late)"
         if pd.notna(h) else f"marked as missing the {s:.0f} h deadline (no linked complaint time)")
        for h, s, l in zip(hit.hours_to_complete, hit.sla_hours, late)]
    return out[FLAG_COLS]


def repeat_repair(wo: pd.DataFrame) -> pd.DataFrame:
    hit = wo[wo["reopened_within_30d"] == "Y"]
    cand = hit[["work_order_id", "road_id", "completed_at"]].merge(
        wo[["work_order_id", "road_id", "assigned_at", "cost_inr"]].rename(
            columns={"work_order_id": "fu_id", "assigned_at": "fu_at", "cost_inr": "fu_cost"}),
        on="road_id")
    cand = cand[(cand.fu_id != cand.work_order_id) & (cand.fu_at >= cand.completed_at)
                & (cand.fu_at <= cand.completed_at + pd.Timedelta(days=C.REPEAT_WINDOW_DAYS))]
    first = cand.sort_values(["fu_at", "fu_id"]).drop_duplicates("work_order_id").set_index("work_order_id")

    out = _base(hit, "REPEAT_REPAIR")
    fu_id = hit["work_order_id"].map(first["fu_id"])
    fu_cost = hit["work_order_id"].map(first["fu_cost"]).astype(float)
    out["related_work_order_id"] = fu_id.where(fu_id.notna(), None)
    out["severity"] = np.where(fu_id.notna(), "medium", "low")
    out["expected_inr"] = np.nan
    out["amount_at_risk_inr"] = fu_cost.fillna(0.0)
    days = ((hit["work_order_id"].map(first["fu_at"]) - hit["completed_at"]).dt.total_seconds() / 86400).round(0)
    out["evidence"] = [
        (f"re-opened within {C.REPEAT_WINDOW_DAYS} days; follow-up {f} on the same road {d:.0f} days later "
         f"billed {_inr(c)} (paid twice)")
        if isinstance(f, str) else
        f"re-opened within {C.REPEAT_WINDOW_DAYS} days; no follow-up work order found on the same road"
        for f, d, c in zip(out.related_work_order_id, days, fu_cost)]
    return out[FLAG_COLS]


RULES = {"OVERBILL": overbill, "DOUBLE_BILL": double_bill, "DLP_PAID": dlp_paid,
         "SLA_MISS": sla_miss, "REPEAT_REPAIR": repeat_repair}


def all_flags(wo: pd.DataFrame) -> pd.DataFrame:
    """All flags, with stable IDs like F-DLP_PAID-0001 (numbered in work-order order)."""
    parts = []
    for name, rule in RULES.items():
        df = rule(wo).sort_values("work_order_id").reset_index(drop=True)
        df.insert(0, "flag_id", [f"F-{name}-{i + 1:04d}" for i in range(len(df))])
        parts.append(df)
    flags = pd.concat(parts, ignore_index=True)
    flags["related_work_order_id"] = flags["related_work_order_id"].astype(object).where(
        flags["related_work_order_id"].notna(), None)
    return flags
