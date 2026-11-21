"""Export the database to compact JSON for the web app (app/public/data/).

Reads ONLY the SQLite database (outputs/follow_the_rupee.db, via pipeline.db), never the
parquet/CSV files, so the app shows exactly what the database holds. It runs on its own
after every database rebuild (pipeline/db/sync.py and `python -m pipeline`); by hand:

    python app/export_data.py

The app only reads these JSON files. Every number shown in the UI comes from here,
which comes from the pandas pipeline. Nothing is computed by an LLM.
manifest.json records which database build the files came from; tests/test_db.py fails
if the committed app data is older than the database.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import db  # noqa: E402
from pipeline.audit.scorecards import _money_by_wo  # noqa: E402  same "count each bill once" rule as the scorecards

DEST = ROOT / "app" / "public" / "data"
# columns stored as ISO text in SQLite that the app expects as "YYYY-MM-DD HH:MM"
TIMESTAMPS = {"work_orders": ["assigned_at", "work_started_at", "completed_at"],
              "complaints": ["received_at", "resolved_at"], "wo_trail": ["first_complaint_at"]}
BOOLEANS = {"method_durability": ["trusted", "recommended"]}   # SQLite stores 0/1


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (np.bool_,)):
        return bool(v)
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


class Source:
    """Read-only view of one database file."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else db.db_path()
        self.meta = {k: json.loads(v) for k, v in
                     db.query("SELECT key, value_json FROM meta", path=self.path).itertuples(index=False)}

    def table(self, name: str) -> pd.DataFrame:
        df = db.query(f'SELECT * FROM "{name}"', path=self.path)
        for col in TIMESTAMPS.get(name, []):
            df[col] = pd.to_datetime(df[col])
        for col in BOOLEANS.get(name, []):
            df[col] = df[col].astype("boolean")
        return df

    def narratives(self, kind: str) -> dict[str, str]:
        n = db.query("SELECT subject_id, text FROM narratives WHERE kind = ?", [kind], path=self.path)
        return dict(zip(n.subject_id, n.text))

    def geo(self, name: str) -> dict:
        g = db.query("SELECT geojson FROM geo_layers WHERE name = ?", [name], path=self.path)
        return json.loads(g.geojson[0])

    def build_id(self) -> str:
        """Identity of the inputs this database was built from (stable across rebuilds)."""
        return hashlib.sha256(json.dumps(self.meta["input_sha256"], sort_keys=True).encode()).hexdigest()


def main(db_path: Path | None = None, dest: Path | None = None) -> Path:
    dest = Path(dest) if dest else DEST
    src = Source(db_path)
    dest.mkdir(parents=True, exist_ok=True)
    print(f"writing {dest} from {src.path.name}")

    def write(name: str, obj) -> None:
        path = dest / f"{name}.json"
        path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  {path.name}  {path.stat().st_size / 1024:,.0f} KB")

    wards = src.table("wards")
    wo = src.table("work_orders")
    roads = src.table("roads")
    flags = src.table("audit_flags")
    cs = src.table("contractor_scorecard")
    ws = src.table("ward_scorecard")
    wr = src.table("ward_risk")
    rr = src.table("road_risk")
    plan = src.table("budget_plan")
    md = src.table("method_durability")
    text = src.meta                                   # thresholds, weights, notes, components, facts
    memos = src.narratives("ward_budget_memo")
    risk_report = src.meta["risk_report"]
    dedup = src.meta["dedup_metrics"]
    n_complaints = int(db.query("SELECT COUNT(*) n FROM complaints", path=src.path).n[0])

    # ---- summary: everything the Overview needs in one small file ------------------
    money = _money_by_wo(flags)
    by_type = flags.groupby("flag_type").agg(n=("flag_id", "size"), amount=("amount_at_risk_inr", "sum"))
    write("summary", {
        "as_of": risk_report.get("as_of"),
        "n_work_orders": int(len(wo)),
        "n_complaints": n_complaints,
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
    w["memo"] = w.ward_code.map(memos)

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

    trail = src.table("wo_trail").set_index("work_order_id")
    w2 = wo.merge(roads[["road_id", "road_name", "under_dlp"]], on="road_id", how="left")
    w2["n_complaints"] = w2.work_order_id.map(trail.n_complaints).fillna(0).astype(int)
    w2["first_complaint_at"] = w2.work_order_id.map(trail.first_complaint_at)
    w2["hours_to_complete"] = w2.work_order_id.map(trail.hours_to_complete)
    w2["total_upvotes"] = w2.work_order_id.map(trail.total_upvotes)
    w2["flag_types"] = w2.work_order_id.map(flags.groupby("work_order_id").flag_type.apply(list))
    w2["linked_complaint_ids"] = w2.linked_complaint_ids.fillna("").map(lambda s: [x for x in s.split("|") if x])
    write("work_orders", records(w2.drop(columns=["contractor_name"])))

    geo = src.geo("roads")
    coords = {f["properties"]["road_id"]: [[round(x, 5), round(y, 5)] for x, y in f["geometry"]["coordinates"]]
              for f in geo["features"]}
    r = rr.copy()
    r["coords"] = r.road_id.map(coords)
    write("roads", records(r))

    write("plan", records(plan))
    write("methods", records(md))

    # ---- complaints: cleaned + original text (tracker page, lazy loaded) ---------------
    cc = src.table("complaints")[["complaint_id", "received_at", "channel", "ward_code", "ward_source", "lat",
                                  "lon", "category_clean", "severity_1_5", "language", "english_summary",
                                  "issue_id", "linked_work_order_id", "status", "description", "locality_text",
                                  "upvotes", "photo_description", "category_reported", "resolved_at"]]
    write("complaints", records(cc))

    # ---- geography + context -------------------------------------------------------------
    wg = src.geo("wards")
    for f in wg["features"]:
        f["geometry"]["coordinates"] = [[[round(x, 5), round(y, 5)] for x, y in ring]
                                        for ring in f["geometry"]["coordinates"]]
    write("wards_geo", wg)
    write("hotspots", records(src.table("flood_hotspots")))
    write("facilities", records(src.table("facilities")))
    write("contractor_names", dict(zip(cs.contractor_id, cs.contractor_name)))

    write("manifest", {"source": "outputs/follow_the_rupee.db", "db_build_id": src.build_id(),
                       "db_built_at_utc": src.meta.get("built_at_utc"),
                       "note": "Exported from the SQLite database by app/export_data.py; do not edit."})
    return dest


if __name__ == "__main__":
    main()
