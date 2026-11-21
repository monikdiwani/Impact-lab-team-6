"""Method durability and the per-ward budget plan ("where the next rupee goes")."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .load import Inputs


def method_durability(inp: Inputs) -> pd.DataFrame:
    """One row per (work_type, repair_method) with a shrunk re-open rate and the cost of
    a repair that lasts: est_cost / (1 - reopen_rate)."""
    wo = inp.work_orders
    # outcome is only known once 30 days have passed since completion
    known = wo[wo.completed_at.notna() & (wo.completed_at <= inp.as_of - pd.Timedelta(days=30))]
    if known.empty:
        known = wo
    g = known.groupby(["work_type", "repair_method"]).agg(
        n_jobs=("reopened", "size"), n_reopened=("reopened", "sum"),
        median_area_sqm=("area_sqm", "median"), median_billed_inr=("cost_inr", "median")).reset_index()
    wt = known.groupby("work_type").reopened.mean().rename("work_type_reopen")
    g = g.join(wt, on="work_type")
    k = C.REOPEN_PRIOR_STRENGTH
    g["reopen_rate_raw"] = (g.n_reopened / g.n_jobs).round(4)
    g["reopen_rate"] = ((g.n_reopened + k * g.work_type_reopen) / (g.n_jobs + k)).round(4)

    rc = inp.rate_card.set_index("repair_method")
    g["unit"] = g.repair_method.map(rc.unit)
    g["standard_rate_inr"] = g.repair_method.map(rc.standard_rate_inr)
    g = g[g.standard_rate_inr.notna()]          # only methods on the rate card can be recommended
    per_sqm = g.unit.str.contains("sqm", na=False)
    g["est_cost_inr"] = np.where(per_sqm, g.standard_rate_inr * g.median_area_sqm, g.standard_rate_inr).round(0)
    g["cost_per_lasting_repair_inr"] = (g.est_cost_inr / (1 - g.reopen_rate)).round(0)
    g["trusted"] = g.n_jobs >= C.MIN_METHOD_JOBS
    # preferred order inside a work type: most durable first, cheaper wins ties
    g = g.sort_values(["work_type", "trusted", "reopen_rate", "est_cost_inr"],
                      ascending=[True, False, True, True])
    g["method_rank"] = g.groupby("work_type").cumcount() + 1
    g["recommended"] = g.method_rank == 1
    return g.drop(columns=["work_type_reopen"]).reset_index(drop=True)


def needed_work(inp: Inputs, issues: pd.DataFrame, methods: pd.DataFrame) -> pd.DataFrame:
    """Work type each road most likely needs next, and how many jobs."""
    known_types = set(methods.work_type)
    roads = inp.roads[["road_id", "surface"]].copy()
    oi = issues[issues.category_clean.isin(known_types)] if len(issues) else issues
    from_issues = (oi.groupby(["road_id", "category_clean"]).n_complaints.sum()
                     .reset_index().sort_values("n_complaints", ascending=False)
                     .drop_duplicates("road_id").set_index("road_id").category_clean) if len(oi) else pd.Series(dtype=str)
    wo = inp.work_orders
    from_history = (wo.groupby(["road_id", "work_type"]).size().rename("n").reset_index()
                      .sort_values("n", ascending=False).drop_duplicates("road_id")
                      .set_index("road_id").work_type)
    default = roads.surface.map(C.SURFACE_DEFAULT_WORK).fillna(C.DEFAULT_WORK)
    roads["work_type"] = roads.road_id.map(from_issues)
    roads["work_source"] = np.where(roads.work_type.notna(), "open complaints", None)
    hist = roads.work_type.isna()
    roads.loc[hist, "work_type"] = roads.loc[hist, "road_id"].map(from_history)
    roads.loc[hist & roads.work_type.notna(), "work_source"] = "past work orders"
    rest = roads.work_type.isna()
    roads.loc[rest, "work_type"] = default[rest]
    roads.loc[rest, "work_source"] = "road surface default"
    n_issues = issues.groupby("road_id").size() if len(issues) else pd.Series(dtype=int)
    roads["n_jobs"] = roads.road_id.map(n_issues).fillna(1).clip(1, C.MAX_JOBS_PER_ROAD).astype(int)
    return roads[["road_id", "work_type", "work_source", "n_jobs"]]


def plan(inp: Inputs, roads: pd.DataFrame, wards: pd.DataFrame, methods: pd.DataFrame,
         need: pd.DataFrame, reason_fn) -> pd.DataFrame:
    """Greedy fill of each ward's remaining budget in descending road risk.

    - DLP road -> 'Invoke DLP', Rs 0 to BMC (the original contractor repairs it free)
    - ward already over budget -> every other road 'Monitor' (reallocate, no new spend)
    - road with no sign of need (below city-median risk and no open issue) -> 'Monitor'
    - otherwise 'Repair' with the most durable method that still fits the money left;
      if nothing fits -> 'Monitor'
    """
    by_type = {wt: g for wt, g in methods.groupby("work_type")}
    df = roads.merge(need, on="road_id", how="left")
    median_risk = df.risk_score.median()
    rows = []
    for w in wards.sort_values("ward_code").itertuples():
        remaining = float(w.remaining_budget_inr)
        left = max(remaining, 0.0)
        spent = 0.0
        g = df[df.ward_code == w.ward_code].sort_values(["risk_score", "road_id"], ascending=[False, True])
        for rank, r in enumerate(g.itertuples(), start=1):
            options = by_type.get(r.work_type)
            best = options.iloc[0] if options is not None else None
            method = best.repair_method if best is not None else ""
            cost = 0.0
            note = None
            if r.under_dlp == "Y":
                action, note = "Invoke DLP", "dlp"
            elif remaining <= 0:
                action, note = "Monitor", "over_budget"
            elif r.risk_score < median_risk and r.open_issues == 0:
                action, note = "Monitor", "low_need"
            else:
                action, note = "Monitor", "no_room"
                for o in (options.itertuples() if options is not None else []):
                    c = float(o.est_cost_inr) * r.n_jobs
                    if spent + c <= left:
                        action, method, cost = "Repair", o.repair_method, c
                        note = "durable" if o.method_rank == 1 else "cheaper_fit"
                        break
            if action == "Repair":
                spent += cost
            m = options.set_index("repair_method").loc[method] if options is not None and method else None
            rows.append({
                "ward_code": w.ward_code, "rank": rank, "road_id": r.road_id, "action": action,
                "recommended_method": method, "est_cost_inr": round(cost, 0),
                "cumulative_inr": round(spent, 0), "remaining_budget_inr": round(remaining, 0),
                "risk_score": r.risk_score,
                "reason": reason_fn(r, action, note, m, remaining),
                # extra context for the app (not in the frozen contract, safe to ignore)
                "work_type": r.work_type, "work_source": r.work_source, "n_jobs": r.n_jobs,
                "method_reopen_rate": float(m.reopen_rate) if m is not None else np.nan,
            })
    out = pd.DataFrame(rows)
    out["rank"] = out["rank"].astype(int)
    return out
