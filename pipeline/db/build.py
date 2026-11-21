"""Build the SQLite database from data/ (reference tables) and outputs/ (pipeline results).

    python -m pipeline.db            # build outputs/follow_the_rupee.db + docs/DATABASE.md
    python -m pipeline.db --check    # is the committed database up to date with its inputs?

Design
- STRICT tables with primary keys and foreign keys; every foreign key is checked after
  loading (the build fails on any violation) and indexed for joins.
- Timestamps are ISO text 'YYYY-MM-DD HH:MM:SS', so SQLite's date functions work on them.
- `complaints` merges the raw complaint (text, photo, upvotes, citizen's category and ward)
  with M1's cleaned fields; `issues` holds every duplicate cluster M1 found, and links each
  to its work order, so complaint -> issue -> work order -> contractor/flags is plain SQL.
- Views (v_*) are the app's read API; see docs/DATABASE.md for each with an example.
- Built into a temp file and swapped in at the end, so a reader never sees a half-built DB.
- meta records the sha256 of every input file; `--check` compares them to the current files.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.db import DEFAULT_DB, ROOT

DATA = ROOT / "data"
OUT = ROOT / "outputs"
DOC = ROOT / "docs" / "DATABASE.md"
SCHEMA_VERSION = 1
OPEN_STATUSES = ("Open", "In Progress")
TS = "%Y-%m-%d %H:%M:%S"


@dataclass
class Table:
    name: str
    df: pd.DataFrame
    pk: list[str]
    doc: str
    fks: list[tuple[str, str, str]] = field(default_factory=list)   # (column, ref_table, ref_column)
    unique: list[list[str]] = field(default_factory=list)
    source: str = ""


# ---- loading -----------------------------------------------------------------------------

def _csv(data_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(data_dir / f"{name}.csv", encoding="utf-8")


def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def _mode(s: pd.Series):
    s = s.dropna()
    return s.mode().iloc[0] if len(s) else None


def load_tables(data_dir: Path = DATA, out_dir: Path = OUT) -> list[Table]:
    d, o = Path(data_dir), Path(out_dir)
    T: list[Table] = []

    # -- reference tables (data/) --
    wards = _csv(d, "wards")
    T.append(Table("wards", wards, ["ward_code"], "24 BMC wards: approximate boundaries, monsoon repair budget, low-lying index.",
                   source="data/wards.csv"))
    T.append(Table("localities", _csv(d, "localities"), ["locality"],
                   "Gazetteer of localities with lat/lon and aliases (incl. Devanagari).",
                   [("ward_code", "wards", "ward_code")], source="data/localities.csv"))
    roads = _csv(d, "roads")
    roads["last_resurfaced"] = _ts(roads.last_resurfaced)
    T.append(Table("roads", roads, ["road_id"], "Road segments with last resurfaced date and Defect Liability Period status (under_dlp Y/N).",
                   [("ward_code", "wards", "ward_code")], source="data/roads.csv"))
    T.append(Table("traffic", _csv(d, "traffic"), ["road_id"], "Peak-hour traffic per road segment.",
                   [("road_id", "roads", "road_id")], source="data/traffic.csv"))
    contractors = _csv(d, "contractors")
    T.append(Table("contractors", contractors, ["contractor_id"], "The 8 fictional contractors.", source="data/contractors.csv"))
    cw = (contractors.assign(ward_code=contractors.active_wards.str.split(";"))
          .explode("ward_code")[["contractor_id", "ward_code"]])
    cw["ward_code"] = cw.ward_code.str.strip()
    T.append(Table("contractor_wards", cw[cw.ward_code != ""].drop_duplicates(), ["contractor_id", "ward_code"],
                   "contractors.active_wards split into one row per (contractor, ward).",
                   [("contractor_id", "contractors", "contractor_id"), ("ward_code", "wards", "ward_code")],
                   source="data/contractors.csv"))
    T.append(Table("rate_card", _csv(d, "rate_card"), ["repair_method"], "Standard rate per repair method (per sqm or per job).",
                   source="data/rate_card.csv"))
    wo = _csv(d, "work_orders")
    for col in ("assigned_at", "work_started_at", "completed_at"):
        wo[col] = _ts(wo[col])
    T.append(Table("work_orders", wo, ["work_order_id"],
                   "Repair jobs: contractor, method, area, billed cost, SLA, re-opened. linked_complaint_ids is kept "
                   "as in the source; use complaint_work_orders for joins.",
                   [("ward_code", "wards", "ward_code"), ("road_id", "roads", "road_id"),
                    ("contractor_id", "contractors", "contractor_id"), ("repair_method", "rate_card", "repair_method")],
                   source="data/work_orders.csv"))
    links = (wo.dropna(subset=["linked_complaint_ids"])
             .assign(complaint_id=lambda x: x.linked_complaint_ids.str.split("|"))
             .explode("complaint_id")[["complaint_id", "work_order_id"]])
    T.append(Table("complaint_work_orders", links, ["complaint_id"],
                   "Which work order fixed each complaint (from work_orders.linked_complaint_ids).",
                   [("complaint_id", "complaints", "complaint_id"), ("work_order_id", "work_orders", "work_order_id")],
                   source="data/work_orders.csv"))
    fac = _csv(d, "facilities")
    T.append(Table("facilities", fac, ["facility_id"], "Hospitals and municipal schools with their ambulance entry road.",
                   [("ward_code", "wards", "ward_code"), ("ambulance_entry_road", "roads", "road_id")],
                   source="data/facilities.csv"))
    T.append(Table("flood_hotspots", _csv(d, "flood_hotspots"), ["hotspot_id"], "Chronic waterlogging spots.",
                   [("ward_code", "wards", "ward_code")], source="data/flood_hotspots.csv"))
    acc = _csv(d, "accidents")
    acc["occurred_at"] = _ts(acc.occurred_at)
    T.append(Table("accidents", acc, ["accident_id"], "Road accidents 2024-2025 with probable cause.",
                   [("ward_code", "wards", "ward_code"), ("road_id", "roads", "road_id")], source="data/accidents.csv"))
    T.append(Table("rainfall_daily", _csv(d, "rainfall_daily"), ["date", "station"], "Daily rainfall at Santacruz and Colaba.",
                   source="data/rainfall_daily.csv"))
    T.append(Table("tides", _csv(d, "tides"), ["date", "high_tide_time"], "Two high tides per day; big_tide_flag Y if >= 4.5 m.",
                   source="data/tides.csv"))
    sp = _csv(d, "social_posts")
    sp["posted_at"] = _ts(sp.posted_at)
    T.append(Table("social_posts", sp, ["post_id"], "X / WhatsApp / Instagram posts in mixed languages (not cleaned).",
                   source="data/social_posts.csv"))
    geo = pd.DataFrame({"name": ["wards", "roads"],
                        "geojson": [(d / "wards.geojson").read_text(encoding="utf-8"),
                                    (d / "roads.geojson").read_text(encoding="utf-8")]})
    T.append(Table("geo_layers", geo, ["name"], "GeoJSON for the ward polygons and road segments, for maps.",
                   source="data/wards.geojson, data/roads.geojson"))

    # -- complaints: raw + M1 cleaned --
    raw = _csv(d, "complaints")
    clean = pd.read_parquet(o / "complaints_clean.parquet")
    extra = raw[["complaint_id", "category_reported", "description", "locality_text", "ward_code", "gps_accuracy_m",
                 "photo_url", "photo_description", "complainant_id", "upvotes", "resolved_at"]].rename(
        columns={"ward_code": "ward_code_reported"})
    comp = clean.merge(extra, on="complaint_id", how="left", validate="one_to_one")
    comp["received_at"], comp["resolved_at"] = _ts(comp.received_at), _ts(comp.resolved_at)
    comp = comp[["complaint_id", "received_at", "channel", "language", "category_reported", "category_clean",
                 "severity_1_5", "description", "english_summary", "photo_description", "photo_url", "locality_text",
                 "ward_code_reported", "ward_code", "ward_source", "lat", "lon", "gps_accuracy_m", "upvotes",
                 "complainant_id", "status", "resolved_at", "issue_id", "linked_work_order_id"]]

    # -- issues: every duplicate cluster M1 found --
    oi = pd.read_parquet(o / "open_issues.parquet")
    g = comp.groupby("issue_id", sort=True)
    issues = pd.DataFrame({
        "ward_code": g.ward_code.agg(_mode), "category_clean": g.category_clean.agg(_mode),
        "severity_1_5": g.severity_1_5.max(), "n_complaints": g.size(),
        "first_reported_at": g.received_at.min(), "last_reported_at": g.received_at.max(),
        "total_upvotes": g.upvotes.sum(), "work_order_id": g.linked_work_order_id.agg(_mode),
        "is_open": g.status.agg(lambda s: int(s.isin(OPEN_STATUSES).any())),
    }).reset_index()
    road_by_wo = wo.set_index("work_order_id").road_id
    issues["road_id"] = issues.issue_id.map(oi.set_index("issue_id").road_id).fillna(
        issues.work_order_id.map(road_by_wo))
    T.append(Table("issues", issues, ["issue_id"],
                   "Every issue (duplicate cluster) from M1: complaints that describe the same problem. work_order_id "
                   "is the job that fixed it (if any); road_id comes from M1's open-issue matching or that job.",
                   [("ward_code", "wards", "ward_code"), ("work_order_id", "work_orders", "work_order_id"),
                    ("road_id", "roads", "road_id")], source="outputs/complaints_clean.parquet"))
    T.append(Table("complaints", comp, ["complaint_id"],
                   "All 6,501 complaints: raw fields (description, photo, citizen's category and ward) plus M1's cleaned "
                   "fields (category_clean, severity_1_5, english_summary, recovered ward_code, issue_id).",
                   [("ward_code", "wards", "ward_code"), ("issue_id", "issues", "issue_id"),
                    ("linked_work_order_id", "work_orders", "work_order_id")],
                   source="data/complaints.csv + outputs/complaints_clean.parquet"))

    # -- pipeline outputs --
    def out(name, pk, doc, fks=(), unique=()):
        T.append(Table(name, pd.read_parquet(o / f"{name}.parquet"), pk, doc, list(fks), list(unique),
                       source=f"outputs/{name}.parquet"))

    out("open_issues", ["issue_id"], "M1: open / in-progress issues matched to a road; demand for M3's planner.",
        [("issue_id", "issues", "issue_id"), ("ward_code", "wards", "ward_code"), ("road_id", "roads", "road_id")])
    out("wo_trail", ["work_order_id"], "M1: per work order - complaints linked, first complaint, channels, hours to complete.",
        [("work_order_id", "work_orders", "work_order_id")])
    out("audit_flags", ["flag_id"], "M2: audit flags (OVERBILL, DOUBLE_BILL, DLP_PAID, SLA_MISS, REPEAT_REPAIR) with evidence "
        "and amount at risk.",
        [("work_order_id", "work_orders", "work_order_id"), ("related_work_order_id", "work_orders", "work_order_id"),
         ("ward_code", "wards", "ward_code"), ("road_id", "roads", "road_id"),
         ("contractor_id", "contractors", "contractor_id")])
    out("contractor_scorecard", ["contractor_id"], "M2: contractor scorecard (SLA, durability, billing, grade, summary).",
        [("contractor_id", "contractors", "contractor_id")])
    out("ward_scorecard", ["ward_code"], "M2: ward accountability scorecard.",
        [("ward_code", "wards", "ward_code"), ("top_contractor_id", "contractors", "contractor_id")])
    out("road_risk", ["road_id"], "M3: road risk score 0-100 and its five components (0-1).",
        [("road_id", "roads", "road_id"), ("ward_code", "wards", "ward_code")])
    out("ward_risk", ["ward_code"], "M3: ward risk and remaining budget.", [("ward_code", "wards", "ward_code")])
    out("budget_plan", ["road_id"], "M3: next-rupee plan, one row per road, ranked within each ward.",
        [("ward_code", "wards", "ward_code"), ("road_id", "roads", "road_id"),
         ("recommended_method", "rate_card", "repair_method")], [["ward_code", "rank"]])
    out("method_durability", ["work_type", "repair_method"], "M3: re-open rate and cost per lasting repair by method.",
        [("repair_method", "rate_card", "repair_method")])

    # -- Claude-written texts --
    sc = json.loads((o / "scorecard_text.json").read_text(encoding="utf-8"))
    memos = json.loads((o / "ward_memos.json").read_text(encoding="utf-8"))
    rows = ([("contractor_summary", k, v, None, None) for k, v in sc.get("contractors", {}).items()]
            + [("ward_summary", k, v, None, None) for k, v in sc.get("wards", {}).items()]
            + [("ward_budget_memo", k, v.get("memo"), v.get("source"), json.dumps(v.get("facts"), ensure_ascii=False))
               for k, v in memos.items()])
    T.append(Table("narratives", pd.DataFrame(rows, columns=["kind", "subject_id", "text", "source", "facts_json"]),
                   ["kind", "subject_id"],
                   "Plain-language texts: M2 contractor/ward summaries and M3 ward budget memos (source: claude or "
                   "template where recorded; facts_json is what the memo was written from).",
                   source="outputs/scorecard_text.json, outputs/ward_memos.json"))
    return T


# ---- SQL ---------------------------------------------------------------------------------

def _sqltype(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s) or pd.api.types.is_integer_dtype(s):
        return "INTEGER"
    if pd.api.types.is_float_dtype(s):
        return "REAL"
    return "TEXT"


def _ddl(t: Table) -> str:
    cols = [f'  "{c}" {_sqltype(t.df[c])}{" NOT NULL" if c in t.pk else ""}' for c in t.df.columns]
    cons = [f'  PRIMARY KEY ({", ".join(chr(34) + c + chr(34) for c in t.pk)})']
    cons += [f'  UNIQUE ({", ".join(chr(34) + c + chr(34) for c in u)})' for u in t.unique]
    cons += [f'  FOREIGN KEY ("{c}") REFERENCES "{rt}"("{rc}")' for c, rt, rc in t.fks]
    return f'CREATE TABLE "{t.name}" (\n' + ",\n".join(cols + cons) + "\n) STRICT"


def _rows(df: pd.DataFrame):
    cols = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            vals = [None if pd.isna(v) else v.strftime(TS) for v in s]
        elif pd.api.types.is_bool_dtype(s):
            vals = [None if pd.isna(v) else int(v) for v in s]
        elif pd.api.types.is_integer_dtype(s):
            vals = [None if pd.isna(v) else int(v) for v in s]
        elif pd.api.types.is_float_dtype(s):
            vals = [None if pd.isna(v) else float(v) for v in s]
        else:
            vals = [None if (v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA) else str(v) for v in s]
        cols.append(vals)
    return list(zip(*cols))


VIEWS = {
    "v_work_order_flags": ("Audit flags rolled up per work order.", """
SELECT work_order_id,
       COUNT(*)                                   AS n_flags,
       GROUP_CONCAT(flag_type, ', ')              AS flag_types,
       SUM(amount_at_risk_inr)                    AS amount_at_risk_inr,
       MAX(CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END) AS max_severity_rank
FROM audit_flags GROUP BY work_order_id"""),
    "v_work_orders": ("Each work order with contractor, road, rate-card expected cost, cost ratio, warranty status, "
                      "complaint trail and flags.", """
SELECT wo.work_order_id, wo.ward_code, wo.road_id, r.road_name, r.under_dlp, r.last_resurfaced,
       wo.work_type, wo.repair_method, wo.contractor_id, wo.contractor_name,
       wo.assigned_at, wo.work_started_at, wo.completed_at, wo.area_sqm, wo.cost_inr,
       CASE rc.unit WHEN 'per sqm' THEN wo.area_sqm * rc.standard_rate_inr
                    ELSE CAST(rc.standard_rate_inr AS REAL) END AS expected_cost_inr,
       -- CAST: INTEGER / INTEGER truncates in SQLite (a 1.4x bill would read as 1)
       ROUND(CAST(wo.cost_inr AS REAL) / CASE rc.unit WHEN 'per sqm' THEN wo.area_sqm * rc.standard_rate_inr
                                                      ELSE rc.standard_rate_inr END, 4) AS cost_ratio,
       wo.sla_hours, wo.sla_met, wo.reopened_within_30d, wo.engineer_remark,
       t.n_complaints, t.first_complaint_at, t.hours_to_complete,
       COALESCE(f.n_flags, 0) AS n_flags, f.flag_types, COALESCE(f.amount_at_risk_inr, 0) AS amount_at_risk_inr
FROM work_orders wo
JOIN rate_card rc          ON rc.repair_method = wo.repair_method
JOIN roads r               ON r.road_id = wo.road_id
LEFT JOIN wo_trail t       ON t.work_order_id = wo.work_order_id
LEFT JOIN v_work_order_flags f ON f.work_order_id = wo.work_order_id"""),
    "v_complaint_trail": ("The money trail for every complaint: complaint -> issue -> work order -> contractor, cost, "
                          "SLA, whether the fix held, and audit flags.", """
SELECT c.complaint_id, c.received_at, c.channel, c.language, c.category_reported, c.category_clean,
       c.severity_1_5, c.description, c.english_summary, c.ward_code, w.ward_name, c.status,
       c.issue_id, i.n_complaints AS complaints_in_issue,
       c.linked_work_order_id AS work_order_id, v.contractor_id, v.contractor_name, v.road_id, v.road_name,
       v.repair_method, v.assigned_at, v.completed_at, v.cost_inr, v.expected_cost_inr, v.cost_ratio,
       v.sla_met, v.reopened_within_30d, v.under_dlp, v.n_flags, v.flag_types, v.amount_at_risk_inr
FROM complaints c
LEFT JOIN wards w          ON w.ward_code = c.ward_code
LEFT JOIN issues i         ON i.issue_id = c.issue_id
LEFT JOIN v_work_orders v  ON v.work_order_id = c.linked_work_order_id"""),
    "v_ward_money": ("Per ward: budget vs billed, flagged money, risk, the next-rupee plan totals and the texts.", """
SELECT w.ward_code, w.ward_name, w.zone, w.low_lying_index,
       w.monsoon_repair_budget_inr_2025 AS budget_inr,
       s.billed_inr, s.budget_used_pct, s.flagged_inr, s.flagged_pct, s.reopen_pct, s.sla_pct,
       s.top_contractor_id, k.contractor_name AS top_contractor_name,
       r.risk_score AS ward_risk_score, r.remaining_budget_inr, r.open_issues,
       (SELECT COUNT(*) FROM budget_plan p WHERE p.ward_code = w.ward_code AND p.action = 'Repair')  AS planned_repairs,
       (SELECT COALESCE(SUM(p.est_cost_inr), 0) FROM budget_plan p
         WHERE p.ward_code = w.ward_code AND p.action = 'Repair')                                    AS planned_repair_inr,
       (SELECT COUNT(*) FROM budget_plan p WHERE p.ward_code = w.ward_code AND p.action = 'Invoke DLP') AS invoke_dlp_roads,
       s.summary_text, n.text AS budget_memo
FROM wards w
LEFT JOIN ward_scorecard s ON s.ward_code = w.ward_code
LEFT JOIN contractors k    ON k.contractor_id = s.top_contractor_id
LEFT JOIN ward_risk r      ON r.ward_code = w.ward_code
LEFT JOIN narratives n     ON n.kind = 'ward_budget_memo' AND n.subject_id = w.ward_code"""),
    "v_contractor_cards": ("Contractor scorecard with empanelment details.", """
SELECT cs.*, c.empanelled_since, c.active_wards
FROM contractor_scorecard cs JOIN contractors c ON c.contractor_id = cs.contractor_id"""),
    "v_next_rupee": ("M3's ranked plan with road, ward and risk-component details.", """
SELECT p.ward_code, w.ward_name, p.rank, p.road_id, rd.road_name, p.action, p.recommended_method,
       p.est_cost_inr, p.cumulative_inr, p.remaining_budget_inr, p.risk_score,
       rr.c_exposure, rr.c_safety, rr.c_critical, rr.c_flood, rr.c_condition, rr.open_issues,
       rd.under_dlp, rd.bus_route, rd.road_type, p.reason
FROM budget_plan p
JOIN wards w      ON w.ward_code = p.ward_code
JOIN roads rd     ON rd.road_id = p.road_id
LEFT JOIN road_risk rr ON rr.road_id = p.road_id"""),
}

EXAMPLES = [
    ("Trace one complaint to the money", "SELECT * FROM v_complaint_trail WHERE complaint_id = 'BMC25-000005'"),
    ("Where did each ward's money go?",
     "SELECT ward_code, ward_name, budget_inr, billed_inr, flagged_inr, planned_repair_inr FROM v_ward_money ORDER BY flagged_inr DESC"),
    ("Biggest over-bills",
     "SELECT work_order_id, contractor_id, billed_inr, expected_inr, amount_at_risk_inr, evidence FROM audit_flags "
     "WHERE flag_type = 'OVERBILL' ORDER BY amount_at_risk_inr DESC LIMIT 10"),
    ("Money billed on roads still under warranty",
     "SELECT ward_code, COUNT(*) AS jobs, SUM(cost_inr) AS billed_inr FROM v_work_orders WHERE under_dlp = 'Y' "
     "GROUP BY ward_code ORDER BY billed_inr DESC"),
    ("Next rupee for one ward", "SELECT rank, road_name, action, recommended_method, est_cost_inr, reason FROM v_next_rupee "
                                "WHERE ward_code = 'F/S' ORDER BY rank LIMIT 10"),
    ("All complaints about one issue", "SELECT complaint_id, channel, language, description FROM complaints "
                                       "WHERE issue_id = (SELECT issue_id FROM complaints WHERE complaint_id = 'BMC25-000005')"),
]


# ---- build -------------------------------------------------------------------------------

def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def input_files(data_dir: Path = DATA, out_dir: Path = OUT) -> dict[str, Path]:
    """{stable key: path}. Keys are 'data/<file>' and 'outputs/<file>' wherever the
    folders actually live, so a copy elsewhere hashes to the same keys."""
    files = sorted(Path(data_dir).glob("*.csv")) + sorted(Path(data_dir).glob("*.geojson"))
    keyed = {f"data/{f.name}": f for f in files if f.name != "complaints_sample_200.csv"}
    outs = ["complaints_clean.parquet", "open_issues.parquet", "wo_trail.parquet", "audit_flags.parquet",
            "contractor_scorecard.parquet", "ward_scorecard.parquet", "road_risk.parquet", "ward_risk.parquet",
            "budget_plan.parquet", "method_durability.parquet", "scorecard_text.json", "ward_memos.json",
            "dedup_metrics.json", "risk_report.json"]
    keyed.update({f"outputs/{f}": Path(out_dir) / f for f in outs})
    return keyed


def build(data_dir: Path = DATA, out_dir: Path = OUT, db_path: Path | None = None,
          doc_path: Path | None = DOC) -> Path:
    db_path = Path(db_path or DEFAULT_DB)
    tables = load_tables(data_dir, out_dir)
    tmp = db_path.with_name(f"{db_path.name}.{os.getpid()}.building")   # per process: parallel runs don't collide
    tmp.unlink(missing_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.execute("PRAGMA foreign_keys = OFF")     # load in any order, then check everything
        for t in tables:
            con.execute(_ddl(t))
            cols = ", ".join(f'"{c}"' for c in t.df.columns)
            con.executemany(f'INSERT INTO "{t.name}" ({cols}) VALUES ({", ".join("?" * len(t.df.columns))})',
                            _rows(t.df))
            for c, _, _ in t.fks:
                if [c] != t.pk:
                    con.execute(f'CREATE INDEX "ix_{t.name}_{c}" ON "{t.name}"("{c}")')
        for name, (_, sql) in VIEWS.items():
            con.execute(f'CREATE VIEW "{name}" AS {sql.strip()}')

        meta = {
            "schema_version": SCHEMA_VERSION,
            "built_at_utc": datetime.now(timezone.utc).strftime(TS),
            "row_counts": {t.name: len(t.df) for t in tables},
            "input_sha256": {k: _sha(f) for k, f in input_files(data_dir, out_dir).items()},
            "dedup_metrics": json.loads((Path(out_dir) / "dedup_metrics.json").read_text(encoding="utf-8")),
            "risk_report": json.loads((Path(out_dir) / "risk_report.json").read_text(encoding="utf-8")),
        }
        sc = json.loads((Path(out_dir) / "scorecard_text.json").read_text(encoding="utf-8"))
        meta.update({k: v for k, v in sc.items() if k not in ("contractors", "wards")})
        con.execute('CREATE TABLE "meta" ("key" TEXT NOT NULL PRIMARY KEY, "value_json" TEXT NOT NULL) STRICT')
        con.executemany('INSERT INTO "meta" VALUES (?, ?)',
                        [(k, json.dumps(v, ensure_ascii=False, default=str)) for k, v in meta.items()])
        con.commit()

        bad = con.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            summary = pd.DataFrame(bad, columns=["table", "rowid", "parent", "fkid"]).groupby(
                ["table", "parent"]).size().to_dict()
            raise ValueError(f"foreign key violations: {summary}")
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise ValueError(f"integrity_check: {ok}")
        for t in tables:
            n = con.execute(f'SELECT COUNT(*) FROM "{t.name}"').fetchone()[0]
            if n != len(t.df):
                raise ValueError(f"{t.name}: {n} rows in DB, {len(t.df)} in source")
        for name in VIEWS:
            con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
        con.execute("ANALYZE")
        con.commit()
    finally:
        con.close()
    con = sqlite3.connect(tmp)
    con.execute("VACUUM")
    con.close()
    _swap(tmp, db_path)
    if doc_path:
        write_docs(db_path, tables, Path(doc_path))
    return db_path


def _swap(tmp: Path, db_path: Path, tries: int = 10) -> None:
    """Atomic replace. On Windows it fails while another process has the file open (e.g. the
    app mid-query), so retry briefly, then explain."""
    import time
    for i in range(tries):
        try:
            os.replace(tmp, db_path)
            return
        except PermissionError:
            if i == tries - 1:
                tmp.unlink(missing_ok=True)
                raise PermissionError(f"{db_path} is locked by another program (is the app or a DB viewer "
                                      f"holding it open?). Close it and run: python -m pipeline.db") from None
            time.sleep(0.5)


def stale_inputs(db_path: Path | None = None, data_dir: Path = DATA, out_dir: Path = OUT) -> list[str]:
    """Input files whose content changed since the database was built (empty = up to date)."""
    db_path = Path(db_path or DEFAULT_DB)
    if not db_path.exists():
        return ["<database missing>"]
    con = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        recorded = json.loads(con.execute("SELECT value_json FROM meta WHERE key = 'input_sha256'").fetchone()[0])
    finally:
        con.close()
    current = {k: _sha(f) for k, f in input_files(data_dir, out_dir).items()}
    return sorted(k for k in set(recorded) | set(current) if recorded.get(k) != current.get(k))


# ---- docs --------------------------------------------------------------------------------

def write_docs(db_path: Path, tables: list[Table], doc_path: Path) -> None:
    con = sqlite3.connect(db_path)
    size_mb = db_path.stat().st_size / 1e6
    out = ["# Database: `outputs/follow_the_rupee.db`", "",
           "_Generated by `python -m pipeline.db` — do not edit by hand._", "",
           "One SQLite file holds the reference data, every cleaned pipeline output and the Claude-written texts, "
           "with primary and foreign keys enforced at build time. The app should read from here, not from the "
           "parquet/CSV files.", "",
           "```python", "from pipeline import db",
           "df = db.query(\"SELECT * FROM v_complaint_trail WHERE complaint_id = ?\", [\"BMC25-000005\"])",
           "con = db.connect()          # read-only sqlite3 connection", "```", "",
           "**Kept in step automatically:** every M1 / M2 / M3 run that writes `outputs/` rebuilds this database "
           "(`pipeline/db/sync.py`); runs into other folders (tests, backtest) never touch it. Full run: "
           "`python -m pipeline` (add `--no-llm` for a free run). Manual rebuild: `python -m pipeline.db`; check "
           "freshness: `python -m pipeline.db --check` (exits 1 if an input changed since the build).", "",
           f"Size {size_mb:.1f} MB · {len(tables)} tables · {len(VIEWS)} views · timestamps are ISO text "
           "`YYYY-MM-DD HH:MM:SS` · all data synthetic.", "",
           "## Views (start here)", "", "| View | What it gives you | Rows |", "|---|---|---|"]
    for name, (doc, _) in VIEWS.items():
        n = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        out.append(f"| `{name}` | {doc} | {n:,} |")
    out += ["", "## Example queries", ""]
    for title, sql in EXAMPLES:
        out += [f"**{title}**", "```sql", sql, "```", ""]
    out += ["## Tables", "", "| Table | Rows | Primary key | Source | What it is |", "|---|---|---|---|---|"]
    for t in tables:
        out.append(f"| `{t.name}` | {len(t.df):,} | {', '.join(t.pk)} | {t.source} | {t.doc} |")
    out.append("| `meta` | | key | build | Build time, schema version, row counts, input file hashes, de-dup "
               "metrics, risk report, scoring weights and fairness notes (JSON values). |")
    out += ["", "## Columns and keys", ""]
    for t in tables:
        out += [f"### `{t.name}`", ""]
        fk = {c: f"→ `{rt}.{rc}`" for c, rt, rc in t.fks}
        out += ["| Column | Type | Key |", "|---|---|---|"]
        for cid, cname, ctype, notnull, dflt, pk in con.execute(f'PRAGMA table_info("{t.name}")'):
            key = " ".join(x for x in ("PK" if pk else "", fk.get(cname, "")) if x)
            out.append(f"| {cname} | {ctype} | {key} |")
        if t.unique:
            out.append(f"\nUnique: {', '.join('(' + ', '.join(u) + ')' for u in t.unique)}")
        out.append("")
    con.close()
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text("\n".join(out), encoding="utf-8")
