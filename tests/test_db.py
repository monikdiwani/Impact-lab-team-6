"""SQLite data layer: built from data/ + outputs/, keys enforced, views correct, read-only
access for the app, and the committed database kept in sync with its inputs."""
from __future__ import annotations

import shutil
import sqlite3

import pandas as pd
import pytest

from pipeline import db
from pipeline.db.build import DATA, DEFAULT_DB, OUT, VIEWS, build, stale_inputs


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return build(DATA, OUT, tmp_path_factory.mktemp("db") / "t.db", doc_path=None)


def q(path, sql):
    return db.query(sql, path=path)


def test_keys_and_integrity(built):
    con = sqlite3.connect(built)
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()


@pytest.mark.parametrize("table,source", [
    ("complaints", "complaints_clean.parquet"), ("open_issues", "open_issues.parquet"),
    ("audit_flags", "audit_flags.parquet"), ("budget_plan", "budget_plan.parquet"),
    ("road_risk", "road_risk.parquet"), ("contractor_scorecard", "contractor_scorecard.parquet"),
])
def test_row_counts_match_outputs(built, table, source):
    assert q(built, f"SELECT COUNT(*) n FROM {table}").n[0] == len(pd.read_parquet(OUT / source))


def test_reference_tables_match_data(built):
    for table in ("work_orders", "roads", "wards", "facilities", "accidents", "social_posts"):
        assert q(built, f"SELECT COUNT(*) n FROM {table}").n[0] == len(pd.read_csv(DATA / f"{table}.csv"))


def test_primary_keys_are_enforced(built, tmp_path):
    copy = tmp_path / "w.db"
    shutil.copy(built, copy)
    con = db.connect(copy, read_only=False)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO wards (ward_code) SELECT ward_code FROM wards LIMIT 1")
    with pytest.raises(sqlite3.IntegrityError):   # foreign keys are on for app connections
        con.execute("INSERT INTO complaint_work_orders VALUES ('BMC25-000005', 'WO25-99999')")
    con.close()


def test_flag_counts_survive_the_load(built):
    got = q(built, "SELECT flag_type, COUNT(*) n FROM audit_flags GROUP BY flag_type").set_index("flag_type").n.to_dict()
    assert got == {"OVERBILL": 114, "DOUBLE_BILL": 45, "DLP_PAID": 493, "SLA_MISS": 1259, "REPEAT_REPAIR": 611}


def test_complaint_trail_view(built):
    t = q(built, "SELECT COUNT(*) n, SUM(work_order_id IS NOT NULL) linked FROM v_complaint_trail")
    assert t.n[0] == 6501 and t.linked[0] == 4948
    one = q(built, "SELECT * FROM v_complaint_trail WHERE complaint_id = 'BMC25-000005'").iloc[0]
    wo = pd.read_csv(DATA / "work_orders.csv")
    expect = wo[wo.linked_complaint_ids.fillna("").str.split("|").map(lambda ids: "BMC25-000005" in ids)].iloc[0]
    assert one.work_order_id == expect.work_order_id and one.contractor_id == expect.contractor_id
    assert one.cost_inr == expect.cost_inr


def test_issues_cover_every_complaint(built):
    assert q(built, "SELECT SUM(n_complaints) n FROM issues").n[0] == 6501
    assert q(built, "SELECT COUNT(*) n FROM open_issues WHERE issue_id NOT IN (SELECT issue_id FROM issues)").n[0] == 0
    assert q(built, "SELECT COUNT(*) n FROM open_issues o JOIN issues i USING (issue_id) WHERE i.is_open = 0").n[0] == 0


def test_expected_cost_matches_rate_card_rule(built):
    """Same 114 over-bills as M2 and test_data_integrity. Guards against SQLite's integer
    division (per-job cost / per-job rate are both INTEGER)."""
    v = q(built, "SELECT cost_inr, expected_cost_inr, cost_ratio FROM v_work_orders")
    assert len(v) == 2499 and (v.cost_ratio > 1.30).sum() == 114
    assert ((v.cost_inr / v.expected_cost_inr - v.cost_ratio).abs() < 1e-4).all()


def test_every_view_answers(built):
    for name in VIEWS:
        assert q(built, f"SELECT COUNT(*) n FROM {name}").n[0] > 0, name


def test_app_connection_is_read_only(built):
    con = db.connect(built)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM wards")
    con.close()


def test_staleness_is_detected(built, tmp_path):
    out = tmp_path / "outputs"
    shutil.copytree(OUT, out, ignore=shutil.ignore_patterns("llm_cache", "csv", "*.db*"))
    assert stale_inputs(built, DATA, out) == []
    (out / "risk_report.json").write_text("{}", encoding="utf-8")
    assert stale_inputs(built, DATA, out) == ["outputs/risk_report.json"] or \
        any(s.endswith("risk_report.json") for s in stale_inputs(built, DATA, out))


def test_committed_database_is_up_to_date():
    if not DEFAULT_DB.exists():
        pytest.skip("no committed database yet")
    stale = stale_inputs(DEFAULT_DB)
    assert not stale, f"outputs/follow_the_rupee.db is older than {stale}; rebuild with: python -m pipeline.db"
