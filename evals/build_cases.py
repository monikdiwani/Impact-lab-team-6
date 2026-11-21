"""Build the fixed eval case sets from data/. Deterministic (seeded); re-running
produces the same files. Run:  python -m evals.build_cases

  evals/cases/extraction.jsonl   150 complaints with ground truth from the linked work order
  evals/cases/narrative.jsonl    facts packets for contractor / ward / flag text
  evals/cases/REVIEW.md          human-readable copy of both, for the sign-off read
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CASES = Path(__file__).resolve().parent / "cases"
SEED = 6

SEVERITY_FROM_SLA = {24: 5, 48: 4, 72: 3, 120: 2, 168: 1}
# fields the extractor may see; status/resolved_at/complainant_id would leak the answer
INPUT_FIELDS = ["complaint_id", "received_at", "channel", "category_reported", "description",
                "locality_text", "ward_code", "lat", "lon", "photo_description", "upvotes"]
WORD_LIMITS = {"contractor": 120, "ward": 150, "flag": 25}

# Label-noise guard: the synthetic text sometimes contradicts the linked work order
# (e.g. "paani bhar gaya" on a manhole job). A case is kept only if the description
# or photo text supports the truth label, or neither gives a clear signal.
KEYWORDS = {
    "Pothole": r"pothole|khadd|gadd|खड्ड|गड्ड",
    "Waterlogging": r"waterlog|flood|paani|pani|पाणी|पानी",
    "Open or broken manhole": r"manhole|ढक्कन|झाकण|chamber",
    "Choked drain / nullah overflow": r"drain|nullah|nala|नाला|नाले|gatar",
    "Road cave-in": r"cave|sinkhole|dhans|धस|खचला|collapsed",
    "Broken paver blocks": r"paver|ब्लॉक",
}


def _guess(text):
    t = str(text).lower()
    hits = [k for k, pat in KEYWORDS.items() if re.search(pat, t)]
    return hits[0] if len(hits) == 1 else None


def _label_supported(row) -> bool:
    g_desc, g_photo = _guess(row.description), _guess(row.photo_description)
    if g_desc is None and g_photo is None:
        return True
    return row.work_type in (g_desc, g_photo)


def _csv(name):
    return pd.read_csv(DATA / f"{name}.csv", encoding="utf-8")


def _clean(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else round(float(v), 6)
    return v


# ---- extraction -----------------------------------------------------------------

def build_extraction(per_cell: int = 15, n_blank_ward: int = 30) -> list[dict]:
    wo, c = _csv("work_orders"), _csv("complaints")
    sample200 = set(_csv("complaints_sample_200").complaint_id)   # prompt-dev set: keep out
    links = (wo.dropna(subset=["linked_complaint_ids"])
             .assign(complaint_id=lambda d: d.linked_complaint_ids.str.split("|"))
             .explode("complaint_id"))
    m = c.merge(links[["complaint_id", "work_order_id", "work_type", "sla_hours", "ward_code"]],
                on="complaint_id", suffixes=("", "_truth"))
    m = m[~m.complaint_id.isin(sample200)]
    supported = m.apply(_label_supported, axis=1)
    print(f"label guard: dropped {int((~supported).sum())} of {len(m)} candidates whose text contradicts the truth label")
    m = m[supported]
    m["cat_wrong"] = m.category_reported != m.work_type
    rng = np.random.default_rng(SEED)

    picked = []
    blank = m[m.ward_code.isna()]
    picked.append(blank.sample(n_blank_ward, random_state=SEED))
    rest = m[m.ward_code.notna()]
    for lang in ["en", "hi-en", "mr", "hi"]:
        for wrong in (True, False):
            cell = rest[(rest.language == lang) & (rest.cat_wrong == wrong)]
            picked.append(cell.sample(min(per_cell, len(cell)), random_state=int(rng.integers(1e9))))
    df = pd.concat(picked).drop_duplicates("complaint_id")

    cases = []
    for r in df.itertuples(index=False):
        row = r._asdict()
        tags = [row["language"], "cat_wrong" if row["cat_wrong"] else "cat_right"]
        if pd.isna(row["ward_code"]):
            tags.append("blank_ward")
        cases.append({
            "id": row["complaint_id"],
            "tags": tags,
            "input": {k: _clean(row[k]) for k in INPUT_FIELDS},
            "expected": {
                "category": row["work_type"],
                "severity": SEVERITY_FROM_SLA[int(row["sla_hours"])],
                "ward_code": row["ward_code_truth"],
                "language": row["language"],
            },
            "meta": {"work_order_id": row["work_order_id"]},
        })
    return sorted(cases, key=lambda x: x["id"])


# ---- narrative facts ----------------------------------------------------------------

def _frames():
    wo, rc, roads, wards = _csv("work_orders"), _csv("rate_card"), _csv("roads"), _csv("wards")
    m = wo.merge(rc, on="repair_method").merge(roads[["road_id", "under_dlp", "road_name"]], on="road_id")
    m["expected"] = np.where(m.unit == "per sqm", m.area_sqm * m.standard_rate_inr, m.standard_rate_inr)
    m["ratio"] = m.cost_inr / m.expected
    m["t"] = pd.to_datetime(m.assigned_at)
    m = m.sort_values("t")
    m["prev_same"] = None
    for (road, wt), g in m.groupby(["road_id", "work_type"]):
        prev = g.work_order_id.shift()
        gap = g.t.diff().dt.days
        m.loc[g.index, "prev_same"] = np.where((gap <= 7) & g.linked_complaint_ids.isna(), prev, None)
    rain = _csv("rainfall_daily")
    heavy_days = int(rain[rain.imd_category.isin(["Heavy", "Very heavy", "Extremely heavy"])].date.nunique())
    return m, wards, heavy_days


DEFINITIONS = {"reopen_window_days": 30, "rate_card_tolerance_pct": 30, "double_bill_window_days": 7}


def _contractor_facts(m, cid, city):
    g = m[m.contractor_id == cid]
    over = g[g.ratio > 1.3]
    dlp = g[g.under_dlp == "Y"]
    dbl = g[g.prev_same.notna()]
    examples = (
        [{"work_order_id": r.work_order_id, "issue": "billed above rate card",
          "billed_inr": int(r.cost_inr), "rate_card_inr": int(round(r.expected)), "ratio": round(r.ratio, 2)}
         for r in over.nlargest(2, "ratio").itertuples()]
        + [{"work_order_id": r.work_order_id, "issue": "possible double bill",
            "earlier_work_order_id": r.prev_same, "billed_inr": int(r.cost_inr)} for r in dbl.head(1).itertuples()]
        + [{"work_order_id": r.work_order_id, "issue": "re-opened within 30 days",
            "billed_inr": int(r.cost_inr)} for r in g[g.reopened_within_30d == "Y"].head(1).itertuples()]
    )
    return {
        "contractor_id": cid, "contractor_name": g.contractor_name.iloc[0],
        "n_jobs": int(len(g)), "wards_active": int(g.ward_code.nunique()),
        "billed_inr": int(g.cost_inr.sum()),
        "sla_met_pct": round(100 * (g.sla_met == "Y").mean(), 1),
        "reopened_pct": round(100 * (g.reopened_within_30d == "Y").mean(), 1),
        "median_cost_vs_rate_card": round(float(g.ratio.median()), 2),
        "n_above_rate_card_tolerance": int(len(over)),
        "n_possible_double_bills": int(len(dbl)),
        "n_jobs_on_roads_under_dlp": int(len(dlp)),
        "billed_on_dlp_roads_inr": int(dlp.cost_inr.sum()),
        "city_average": city, "example_work_orders": examples,
        "context": ["Every contractor works in all 24 wards, so geography is comparable."],
        "definitions": DEFINITIONS,
    }


def _ward_facts(m, wards, code, heavy_days):
    g = m[m.ward_code == code]
    w = wards.set_index("ward_code").loc[code]
    budget = int(w.monsoon_repair_budget_inr_2025)
    over = g[g.ratio > 1.3]
    context = [f"The city had {heavy_days} days of heavy or worse rain this season."]
    if w.low_lying_index >= 0.6:
        context.append(f"Low-lying ward (low_lying_index {w.low_lying_index}); flooding is common.")
    return {
        "ward_code": code, "ward_name": w.ward_name, "budget_inr": budget,
        "billed_inr": int(g.cost_inr.sum()),
        "budget_used_pct": round(100 * g.cost_inr.sum() / budget, 1),
        "n_jobs": int(len(g)),
        "reopened_pct": round(100 * (g.reopened_within_30d == "Y").mean(), 1),
        "sla_met_pct": round(100 * (g.sla_met == "Y").mean(), 1),
        "low_lying_index": float(w.low_lying_index),
        "billed_on_dlp_roads_inr": int(g[g.under_dlp == "Y"].cost_inr.sum()),
        "n_above_rate_card_tolerance": int(len(over)),
        "top_contractor_by_spend": g.groupby("contractor_name").cost_inr.sum().idxmax(),
        "example_work_orders": [r.work_order_id for r in over.head(2).itertuples()],
        "context": context, "definitions": DEFINITIONS,
    }


def _flag_facts(r, flag_type):
    f = {"flag_type": flag_type, "work_order_id": r.work_order_id, "contractor_name": r.contractor_name,
         "ward_code": r.ward_code, "road_name": r.road_name, "repair_method": r.repair_method,
         "billed_inr": int(r.cost_inr), "rate_card_inr": int(round(r.expected)),
         "ratio": round(r.ratio, 2), "definitions": DEFINITIONS}
    if flag_type == "DOUBLE_BILL":
        f["earlier_work_order_id"] = r.prev_same
    return f


def build_narrative() -> list[dict]:
    m, wards, heavy_days = _frames()
    city = {"sla_met_pct": round(100 * (m.sla_met == "Y").mean(), 1),
            "reopened_pct": round(100 * (m.reopened_within_30d == "Y").mean(), 1)}
    cases = []

    def add(kind, cid, facts, tags, must_mention=None):
        cases.append({"id": cid, "tags": [kind, *tags], "kind": kind, "facts": facts,
                      "checks": {"word_limit": WORD_LIMITS[kind], "must_mention": must_mention}})

    for cid in sorted(m.contractor_id.unique()):
        add("contractor", f"contractor-{cid}", _contractor_facts(m, cid, city), ["real"])

    budget = wards.set_index("ward_code").monsoon_repair_budget_inr_2025
    used = m.groupby("ward_code").cost_inr.sum() / budget
    low = wards.set_index("ward_code").low_lying_index
    picks = {used.idxmax(): ["overspent"], used.idxmin(): ["underspent"],
             low.idxmax(): ["low_lying"], "F/S": ["hotspots"], "A": ["real"], "K/W": ["real"],
             "M/E": ["real"], "R/N": ["real"]}
    for code, tags in picks.items():
        facts = _ward_facts(m, wards, code, heavy_days)
        must = None
        if "overspent" in tags:
            must = r"over[- ]?(spent|budget|ran)|exceed|more than (its|the) budget|above (its|the) budget"
        if "low_lying" in tags:
            must = r"low[- ]lying|flood"
        add("ward", f"ward-{code.replace('/', '_')}", facts, tags, must)

    rng = np.random.default_rng(SEED)
    for ft, rows in [("OVERBILL", m[m.ratio > 1.3]), ("DOUBLE_BILL", m[m.prev_same.notna()]),
                     ("DLP_PAID", m[m.under_dlp == "Y"]),
                     ("REPEAT_REPAIR", m[m.reopened_within_30d == "Y"])]:
        for i in rng.choice(len(rows), size=3, replace=False):
            r = rows.iloc[int(i)]
            add("flag", f"flag-{ft}-{r.work_order_id}", _flag_facts(r, ft), [ft])

    # edge cases: synthetic facts packets that test judgement, not data
    base = _contractor_facts(m, "CT08", city)
    small = {**base, "contractor_id": "CT99", "contractor_name": "Test Contractor (synthetic edge case)",
             "n_jobs": 1, "billed_inr": 18400, "sla_met_pct": 0.0, "reopened_pct": 100.0,
             "n_above_rate_card_tolerance": 0, "n_possible_double_bills": 0,
             "n_jobs_on_roads_under_dlp": 0, "billed_on_dlp_roads_inr": 0, "example_work_orders": [],
             "context": ["Only one job on record."]}
    add("contractor", "edge-single-job", small, ["edge"],
        r"(only|just) (one|1|a single)|single job|limited|small (number|sample)|too (few|early)")
    mixed = {**base, "contractor_id": "CT98", "contractor_name": "Mixed Record Co (synthetic edge case)",
             "sla_met_pct": 71.0, "reopened_pct": 41.0, "example_work_orders": []}
    add("contractor", "edge-fast-but-fragile", mixed, ["edge"],
        r"(fast|quick|on time|speed).{0,120}(re-?open|last|durab|fail)|(re-?open|last|durab|fail).{0,120}(fast|quick|on time|speed)")
    return cases


def write_review(extraction, narrative):
    def fence(s):
        return f"````\n{s}\n````"
    out = ["# Eval cases: review before sign-off", "",
           f"Extraction: {len(extraction)} cases · Narrative: {len(narrative)} cases", "",
           "## Extraction", "", "| id | tags | category (truth) | severity | ward | language |",
           "|---|---|---|---|---|---|"]
    for c in extraction:
        e = c["expected"]
        out.append(f"| {c['id']} | {' '.join(c['tags'])} | {e['category']} | {e['severity']} | "
                   f"{e['ward_code']} | {e['language']} |")
    out += ["", "### Inputs", ""]
    for c in extraction:
        i = c["input"]
        out += [f"**{c['id']}** ({' · '.join(c['tags'])}) — citizen picked *{i['category_reported']}*, "
                f"truth *{c['expected']['category']}*", fence(i["description"]), ""]
    out += ["## Narrative", ""]
    for c in narrative:
        out += [f"### {c['id']} ({' · '.join(c['tags'])})",
                f"word limit {c['checks']['word_limit']}; must mention: `{c['checks']['must_mention']}`",
                fence(json.dumps(c["facts"], indent=1, ensure_ascii=False)), ""]
    (CASES / "REVIEW.md").write_text("\n".join(out), encoding="utf-8")


def main():
    CASES.mkdir(exist_ok=True)
    ex, nar = build_extraction(), build_narrative()
    for name, rows in (("extraction", ex), ("narrative", nar)):
        with open(CASES / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_review(ex, nar)
    tags = pd.Series([t for c in ex for t in c["tags"]]).value_counts().to_dict()
    print(f"extraction: {len(ex)} cases {tags}")
    print(f"narrative: {len(nar)} cases {pd.Series([c['tags'][0] for c in nar]).value_counts().to_dict()}")


if __name__ == "__main__":
    main()
