"""Export pipeline outputs to compact JSON for the web app (app/public/data/).

Run from the repo root after `python -m pipeline.run_all` (or the module runs):
    python app/export_data.py

The app only reads these JSON files. Every number shown in the UI comes from here,
which comes from the pandas pipeline. Nothing is computed by an LLM.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.audit.scorecards import _money_by_wo  # noqa: E402  same "count each bill once" rule as the scorecards
OUT_DIR, DATA_DIR = ROOT / "outputs", ROOT / "data"
DEST = ROOT / "app" / "public" / "data"


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else round(float(v), 4)
    if isinstance(v, (pd.Timestamp,)):
        return None if pd.isna(v) else v.strftime("%Y-%m-%d %H:%M")
    if v is pd.NA or v is pd.NaT:
        return None
    return v


def records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in r.items()} for r in df.to_dict("records")]


def write(name: str, obj) -> None:
    path = DEST / f"{name}.json"
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {path.relative_to(ROOT)}  {path.stat().st_size / 1024:,.0f} KB")


def pq(name: str) -> pd.DataFrame:
    return pd.read_parquet(OUT_DIR / f"{name}.parquet")


def csv(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / f"{name}.csv", encoding="utf-8")


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    print("writing", DEST.relative_to(ROOT))

    wards = csv("wards")
    wo = csv("work_orders")
    roads = csv("roads")
    flags = pq("audit_flags")
    cs = pq("contractor_scorecard")
    ws = pq("ward_scorecard")
    wr = pq("ward_risk")
    rr = pq("road_risk")
    plan = pq("budget_plan")
    md = pq("method_durability")
    text = json.loads((OUT_DIR / "scorecard_text.json").read_text(encoding="utf-8"))
    memos = json.loads((OUT_DIR / "ward_memos.json").read_text(encoding="utf-8"))
    risk_report = json.loads((OUT_DIR / "risk_report.json").read_text(encoding="utf-8"))
    dedup = json.loads((OUT_DIR / "dedup_metrics.json").read_text(encoding="utf-8"))

    # ---- summary: everything the Overview needs in one small file ------------------
    money = _money_by_wo(flags)
    by_type = flags.groupby("flag_type").agg(n=("flag_id", "size"), amount=("amount_at_risk_inr", "sum"))
    write("summary", {
        "as_of": risk_report.get("as_of"),
        "n_work_orders": int(len(wo)),
        "n_complaints": int(len(csv("complaints"))),
        "n_wards": int(len(wards)),
        "n_contractors": int(len(cs)),
        "n_roads": int(len(roads)),
        "billed_inr": float(wo.cost_inr.sum()),
        "budget_inr": float(wards.monsoon_repair_budget_inr_2025.sum()),
        "flagged_inr": float(money.sum()),
        "dlp_inr": float(by_type.loc["DLP_PAID", "amount"]),
        "reopen_pct": round(100 * (wo.reopened_within_30d == "Y").mean(), 1),
        "sla_pct": round(100 * (wo.sla_met == "Y").mean(), 1),
        "flags_by_type": {t: {"n": int(r.n), "amount": float(r.amount)} for t, r in by_type.iterrows()},
        "thresholds": text["thresholds"],
        "score_weights": text["score_weights"],
        "fairness_notes": text["fairness_notes"],
        "risk_weights": risk_report.get("weights"),
        "risk_notes": risk_report.get("data_notes"),
        "plan_repair_inr": risk_report.get("plan_repair_inr"),
        "over_budget_wards": risk_report.get("over_budget_wards"),
        "dedup": {k: dedup[k] for k in ("precision", "recall", "f1", "n_truth_pairs", "n_pred_pairs") if k in dedup},
        "dedup_sources": {k: dedup.get(k) for k in ("extraction_source_counts", "ward_source_counts")},
    })

    # ---- wards: scorecard + risk + memo + names, one row per ward ----------------
    w = (wards[["ward_code", "ward_name", "zone", "low_lying_index", "population_est", "engineering_crews"]]
         .merge(ws, on="ward_code", how="left")
         .merge(wr[["ward_code", "risk_score", "flood_days", "open_issues", "remaining_budget_inr",
                    "open_complaints", "mean_road_risk", "max_road_risk"]], on="ward_code", how="left"))
    w["memo"] = w.ward_code.map(lambda c: (memos.get(c) or {}).get("memo"))
    # spend by contractor and by method per ward, for the money-trail charts
    def spend_by(col):
        out = {}
        for (ward, key), v in wo.groupby(["ward_code", col]).cost_inr.sum().round(0).items():
            out.setdefault(ward, {})[key] = float(v)
        return w.ward_code.map(lambda c: out.get(c, {}))
    w["spend_by_contractor"] = spend_by("contractor_id")
    w["spend_by_method"] = spend_by("repair_method")
    failed = wo[wo.reopened_within_30d == "Y"].groupby("ward_code").cost_inr.sum()
    w["failed_repair_inr"] = w.ward_code.map(failed).fillna(0.0)
    w["n_jobs"] = w.ward_code.map(wo.groupby("ward_code").size()).fillna(0).astype(int)
    write("wards", records(w))

    # ---- contractors ----------------------------------------------------------------
    c = cs.copy()
    c["n_flags_by_type"] = c.n_flags_by_type.map(json.loads)
    c["components"] = c.contractor_id.map(text["score_components"])
    c["facts"] = c.contractor_id.map(text["facts"]["contractors"])
    method_mix = wo.groupby(["contractor_id", "repair_method"]).size()
    c["method_mix"] = c.contractor_id.map(lambda k: {m: int(n) for m, n in method_mix.loc[k].items()})
    write("contractors", records(c))

    # ---- flags (all), work orders (all), roads (risk + geometry) ------------------------
    write("flags", records(flags))

    trail = pq("wo_trail").set_index("work_order_id")
    w2 = wo.merge(roads[["road_id", "road_name", "under_dlp"]], on="road_id", how="left")
    w2["n_complaints"] = w2.work_order_id.map(trail.n_complaints).fillna(0).astype(int)
    w2["first_complaint_at"] = w2.work_order_id.map(trail.first_complaint_at)
    w2["hours_to_complete"] = w2.work_order_id.map(trail.hours_to_complete)
    w2["total_upvotes"] = w2.work_order_id.map(trail.total_upvotes)
    w2["flag_types"] = w2.work_order_id.map(flags.groupby("work_order_id").flag_type.apply(list))
    w2["linked_complaint_ids"] = w2.linked_complaint_ids.fillna("").map(lambda s: [x for x in s.split("|") if x])
    write("work_orders", records(w2.drop(columns=["contractor_name"])))

    geo = json.loads((DATA_DIR / "roads.geojson").read_text(encoding="utf-8"))
    coords = {f["properties"]["road_id"]: [[round(x, 5), round(y, 5)] for x, y in f["geometry"]["coordinates"]]
              for f in geo["features"]}
    r = rr.copy()
    r["coords"] = r.road_id.map(coords)
    write("roads", records(r))

    write("plan", records(plan))
    write("methods", records(md))

    # ---- complaints: cleaned + original text (tracker page, lazy loaded) ---------------
    cc = pq("complaints_clean")
    raw = csv("complaints").set_index("complaint_id")
    cc["description"] = cc.complaint_id.map(raw.description)
    cc["locality_text"] = cc.complaint_id.map(raw.locality_text)
    cc["upvotes"] = cc.complaint_id.map(raw.upvotes)
    cc["photo_description"] = cc.complaint_id.map(raw.photo_description)
    cc["category_reported"] = cc.complaint_id.map(raw.category_reported)
    cc["resolved_at"] = cc.complaint_id.map(raw.resolved_at)
    write("complaints", records(cc))

    # ---- geography + context -------------------------------------------------------------
    wg = json.loads((DATA_DIR / "wards.geojson").read_text(encoding="utf-8"))
    for f in wg["features"]:
        f["geometry"]["coordinates"] = [[[round(x, 5), round(y, 5)] for x, y in ring]
                                        for ring in f["geometry"]["coordinates"]]
    write("wards_geo", wg)
    write("hotspots", records(csv("flood_hotspots")))
    write("facilities", records(csv("facilities")))
    write("contractor_names", dict(zip(cs.contractor_id, cs.contractor_name)))


if __name__ == "__main__":
    main()
