"""Contractor and ward scorecards (blueprint §7 M2 steps 3-4).

Fairness choices (also listed in FAIRNESS_NOTES for the app's "fairness notes" panel):
- Only rates are scored, never counts, so doing more work is not penalised.
- Re-open rate is compared with what the contractor's own repair-method mix would
  predict city-wide (cold mix re-opens far more often than dewatering, for example).
- DLP_PAID is shown but not scored against the repairing contractor: the original
  warranty contractor is not in the data.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from pipeline.audit import config as C

FAIRNESS_NOTES = [
    "Every contractor works in all 24 wards, so geography does not explain the gaps between them.",
    "Re-open rates are adjusted for each contractor's mix of repair methods.",
    "Scores use rates, not counts, so a contractor is not penalised for doing more work.",
    "Bills on roads under warranty (DLP) are flagged on the road, not scored against the repairing contractor.",
    "Ward low-lying index correlates slightly negatively with re-open rate, so flooding alone does not explain poor durability.",
    "SLA is measured from the first linked complaint to completion.",
    "Wording is neutral: a flag means the job needs review, not that anyone did wrong. All data is synthetic.",
]


def _pct(s: pd.Series) -> float:
    return round(100 * float(s.mean()), 1) if len(s) else 0.0


def _grade(score: float) -> str:
    return next(g for cut, g in C.GRADE_CUTOFFS if score >= cut)


def _money_by_wo(flags: pd.DataFrame) -> pd.Series:
    """₹ at risk per WO, taking the largest single flag so one job is never counted twice."""
    m = flags[flags.flag_type.isin(C.MONEY_FLAGS)]
    return m.groupby("work_order_id").amount_at_risk_inr.max()


def city_average(wo: pd.DataFrame) -> dict:
    return {"sla_met_pct": _pct(wo.sla_met == "Y"), "reopened_pct": _pct(wo.reopened_within_30d == "Y")}


def contractor_facts(g: pd.DataFrame, flags: pd.DataFrame, city: dict) -> dict:
    """Facts packet in the shape evals/build_cases.py uses, so the eval and the app see the same thing."""
    fl = flags[flags.work_order_id.isin(g.work_order_id)]
    over = fl[fl.flag_type == "OVERBILL"].merge(g[["work_order_id", "cost_ratio"]], on="work_order_id")
    dbl = fl[fl.flag_type == "DOUBLE_BILL"]
    rep = fl[fl.flag_type == "REPEAT_REPAIR"]
    dlp = g[g.under_dlp == "Y"]
    examples = (
        [{"work_order_id": r.work_order_id, "issue": "billed above rate card", "billed_inr": int(r.billed_inr),
          "rate_card_inr": int(round(r.expected_inr)), "ratio": round(float(r.cost_ratio), 2)}
         for r in over.nlargest(2, "cost_ratio").itertuples()]
        + [{"work_order_id": r.work_order_id, "issue": "possible double bill",
            "earlier_work_order_id": r.related_work_order_id, "billed_inr": int(r.billed_inr)}
           for r in dbl.head(1).itertuples()]
        + [{"work_order_id": r.work_order_id, "issue": "re-opened within 30 days", "billed_inr": int(r.billed_inr)}
           for r in rep.head(1).itertuples()]
    )
    return {
        "contractor_id": g.contractor_id.iloc[0], "contractor_name": g.contractor_name.iloc[0],
        "n_jobs": int(len(g)), "wards_active": int(g.ward_code.nunique()),
        "billed_inr": int(g.cost_inr.sum()),
        "sla_met_pct": _pct(g.sla_met == "Y"),
        "reopened_pct": _pct(g.reopened_within_30d == "Y"),
        "median_cost_vs_rate_card": round(float(g.cost_ratio.median()), 2),
        "n_above_rate_card_tolerance": int(len(over)),
        "n_possible_double_bills": int(len(dbl)),
        "n_jobs_on_roads_under_dlp": int(len(dlp)),
        "billed_on_dlp_roads_inr": int(dlp.cost_inr.sum()),
        "city_average": city, "example_work_orders": examples,
        "context": ["Every contractor works in all 24 wards, so geography is comparable.",
                    "Re-open rate is compared with what this contractor's mix of repair methods would predict."],
        "definitions": C.DEFINITIONS,
    }


def contractor_scorecard(wo: pd.DataFrame, flags: pd.DataFrame, contractors: pd.DataFrame,
                         text_fn=None) -> tuple[pd.DataFrame, dict]:
    method_rate = wo.groupby("repair_method").reopened_within_30d.apply(lambda s: (s == "Y").mean())
    wo = wo.assign(_exp_reopen=wo.repair_method.map(method_rate))
    city = city_average(wo)
    money = _money_by_wo(flags)
    names = contractors.set_index("contractor_id").contractor_name

    rows, facts_by_id = [], {}
    for cid, g in wo.groupby("contractor_id"):
        fl = flags[flags.contractor_id == cid]
        n = len(g)
        actual = (g.reopened_within_30d == "Y").mean()
        expected = g._exp_reopen.mean()
        ratio = actual / expected if expected > 0 else 1.0
        sla = (g.sla_met == "Y").mean()
        n_bill = int(fl.flag_type.isin(["OVERBILL", "DOUBLE_BILL"]).sum())

        comp = {
            "durability": float(np.clip(1.5 - ratio, 0, 1)),
            "sla": float(sla),
            "billing": float(np.clip(1 - C.BILLING_PENALTY * n_bill / n, 0, 1)),
        }
        score = round(100 * sum(C.SCORE_WEIGHTS[k] * v for k, v in comp.items()), 1)
        counts = {t: int((fl.flag_type == t).sum()) for t in
                  ("OVERBILL", "DOUBLE_BILL", "DLP_PAID", "SLA_MISS", "REPEAT_REPAIR")}

        facts = contractor_facts(g, flags, city)
        facts_by_id[cid] = facts
        rows.append({
            "contractor_id": cid,
            "contractor_name": names.get(cid, g.contractor_name.iloc[0]),
            "n_jobs": n,
            "billed_inr": float(g.cost_inr.sum()),
            "sla_pct": round(100 * sla, 1),
            "reopen_pct": round(100 * actual, 1),
            "reopen_expected_pct": round(100 * expected, 1),
            "durability_index": round(1 / ratio if ratio > 0 else 3.0, 2),   # >1 = lasts better than its method mix predicts
            "median_cost_ratio": round(float(g.cost_ratio.median()), 3),
            "n_flags_by_type": json.dumps(counts),
            "amount_flagged_inr": float(money.reindex(g.work_order_id).fillna(0).sum()),
            "score_0_100": score,
            "grade": _grade(score),
            "summary_text": text_fn(facts) if text_fn else "",
            "_components": comp,
        })
    df = pd.DataFrame(rows).sort_values("score_0_100", ascending=False).reset_index(drop=True)
    components = dict(zip(df.contractor_id, df._components))
    return df.drop(columns="_components"), {"facts": facts_by_id, "components": components}


def ward_facts(g: pd.DataFrame, w: pd.Series, heavy_days: int | None) -> dict:
    budget = float(w.monsoon_repair_budget_inr_2025)
    over = g[g.cost_ratio > C.OVERBILL_RATIO]
    context = []
    if heavy_days is not None:
        context.append(f"The city had {heavy_days} days of heavy or worse rain this season.")
    if w.low_lying_index >= 0.6:
        context.append(f"Low-lying ward (low_lying_index {w.low_lying_index}); flooding is common.")
    return {
        "ward_code": w.ward_code, "ward_name": w.ward_name, "budget_inr": int(budget),
        "billed_inr": int(g.cost_inr.sum()),
        "budget_used_pct": round(100 * g.cost_inr.sum() / budget, 1) if budget else 0.0,
        "n_jobs": int(len(g)),
        "reopened_pct": _pct(g.reopened_within_30d == "Y"),
        "sla_met_pct": _pct(g.sla_met == "Y"),
        "low_lying_index": float(w.low_lying_index),
        "billed_on_dlp_roads_inr": int(g[g.under_dlp == "Y"].cost_inr.sum()),
        "n_above_rate_card_tolerance": int(len(over)),
        "top_contractor_by_spend": (g.groupby("contractor_name").cost_inr.sum().idxmax() if len(g) else None),
        "example_work_orders": [r.work_order_id for r in over.sort_values("work_order_id").head(2).itertuples()],
        "context": context, "definitions": C.DEFINITIONS,
    }


def ward_scorecard(wo: pd.DataFrame, flags: pd.DataFrame, wards: pd.DataFrame,
                   heavy_days: int | None = None, text_fn=None) -> tuple[pd.DataFrame, dict]:
    money = _money_by_wo(flags)
    rows, facts_by_ward = [], {}
    for w in wards.itertuples(index=False):
        w = pd.Series(w._asdict())
        g = wo[wo.ward_code == w.ward_code]
        billed = float(g.cost_inr.sum())
        budget = float(w.monsoon_repair_budget_inr_2025)
        flagged = float(money.reindex(g.work_order_id).fillna(0).sum())
        facts = ward_facts(g, w, heavy_days)
        facts_by_ward[w.ward_code] = facts
        rows.append({
            "ward_code": w.ward_code,
            "budget_inr": budget,
            "billed_inr": billed,
            "budget_used_pct": round(100 * billed / budget, 1) if budget else 0.0,
            "flagged_inr": flagged,
            "flagged_pct": round(100 * flagged / billed, 1) if billed else 0.0,
            "reopen_pct": _pct(g.reopened_within_30d == "Y"),
            "sla_pct": _pct(g.sla_met == "Y"),
            "top_contractor_id": (g.groupby("contractor_id").cost_inr.sum().idxmax() if len(g) else None),
            "summary_text": text_fn(facts) if text_fn else "",
        })
    return pd.DataFrame(rows), {"facts": facts_by_ward}
