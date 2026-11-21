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


def test_issues_cover_every_road_complaint(built):
    """Every road complaint belongs to an issue; non-road complaints ('Not road-related')
    stay in complaints for the trail but have no issue."""
    with_issue = q(built, "SELECT COUNT(*) n FROM complaints WHERE issue_id IS NOT NULL").n[0]
    assert q(built, "SELECT SUM(n_complaints) n FROM issues").n[0] == with_issue
    no_issue = q(built, "SELECT DISTINCT category_clean FROM complaints WHERE issue_id IS NULL")
    assert set(no_issue.category_clean) <= {"Not road-related"}
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


# ---- auto-sync: every run into outputs/ updates the DB; other folders never touch it ------

@pytest.fixture
def fake_project(tmp_path, monkeypatch):
    """A copy of outputs/ standing in for the app's folder, with its own DB and doc path."""
    from pipeline.db import build as B
    out = tmp_path / "outputs"
    shutil.copytree(OUT, out, ignore=shutil.ignore_patterns("llm_cache", "csv", "*.db*"))
    monkeypatch.setattr(B, "OUT", out)
    monkeypatch.setattr(B, "DOC", tmp_path / "DATABASE.md")
    monkeypatch.setenv("RUPEE_DB", str(tmp_path / "app.db"))
    monkeypatch.delenv("RUPEE_DB_AUTOSYNC", raising=False)
    return out


def test_run_into_app_outputs_updates_the_db(fake_project, tmp_path):
    from pipeline.db.sync import after_run
    p = after_run(DATA, fake_project, "M2")
    assert p == tmp_path / "app.db" and p.exists() and stale_inputs(p, DATA, fake_project) == []


def test_run_into_other_folders_never_touches_the_db(fake_project, tmp_path):
    from pipeline.db.sync import after_run
    assert after_run(DATA, tmp_path / "scratch", "M1") is None
    assert not (tmp_path / "app.db").exists()


def test_committed_db_untouched_by_test_runs():
    """conftest/backtest runs write to temp folders, so they must not rebuild outputs/'s DB."""
    from pipeline.db.sync import _same
    from pipeline.db.build import OUT as REAL_OUT
    import tempfile
    assert not _same(tempfile.gettempdir(), REAL_OUT)


def test_paused_and_env_switch(fake_project, tmp_path, monkeypatch):
    from pipeline.db import sync
    with sync.paused():
        assert sync.after_run(DATA, fake_project, "M1") is None
    assert sync.enabled()
    monkeypatch.setenv("RUPEE_DB_AUTOSYNC", "0")
    assert sync.after_run(DATA, fake_project, "M1") is None
    assert not (tmp_path / "app.db").exists()


def test_failed_rebuild_does_not_crash_the_run(fake_project, monkeypatch, capsys):
    from pipeline.db import build as B
    from pipeline.db.sync import after_run

    def boom(*a, **k):
        raise ValueError("foreign key violations: {...}")
    monkeypatch.setattr(B, "build", boom)
    assert after_run(DATA, fake_project, "M3") is None
    assert "updating the database failed" in capsys.readouterr().err


def test_each_module_run_ends_with_the_db_hook():
    import inspect
    from pipeline import audit, connect, risk
    for mod, tag in ((connect, "M1"), (audit, "M2"), (risk, "M3")):
        assert f'after_run(data_dir, out_dir, "{tag}")' in inspect.getsource(mod.run), tag


def test_full_run_order_and_single_build(monkeypatch, tmp_path):
    from pipeline import run_all
    from pipeline.db import sync
    monkeypatch.delenv("LLM_OFFLINE", raising=False)   # main(--no-llm) sets it; restore after the test
    calls = []

    def step(name):
        def fn(d, o):
            assert not sync.enabled(), "auto-sync must be paused inside python -m pipeline"
            calls.append(name)
        return fn
    monkeypatch.setattr(run_all, "STEPS", {k: (k, step(k)) for k in run_all.ORDER})
    monkeypatch.setattr(run_all, "build", lambda *a, **k: calls.append("db") or tmp_path / "x.db")
    monkeypatch.setattr(run_all, "stale_inputs", lambda *a, **k: [])
    assert run_all.main(["--no-llm"]) == 0
    assert calls == ["m1", "m3", "m2", "db"]
    calls.clear()
    assert run_all.main(["--no-llm", "--only", "m2,m1"]) == 0
    assert calls == ["m1", "m2", "db"]          # always dependency order, whatever was typed



# ---- the web app's data comes from the database --------------------------------------------

def _export_module():
    import importlib.util
    from pipeline.db import ROOT
    spec = importlib.util.spec_from_file_location("app_export_data", ROOT / "app" / "export_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_app_export_reads_only_the_database(built, tmp_path, monkeypatch):
    """With parquet/CSV reads disabled, the export still works: it reads the DB alone."""
    exp = _export_module()

    def no_files(*a, **k):
        raise AssertionError("the app export must read the database, not files")
    monkeypatch.setattr(pd, "read_parquet", no_files)
    monkeypatch.setattr(pd, "read_csv", no_files)
    dest = exp.main(built, tmp_path / "app_data")
    names = {p.name for p in dest.glob("*.json")}
    assert {"summary.json", "flags.json", "complaints.json", "plan.json", "manifest.json"} <= names
    import json
    flags = json.loads((dest / "flags.json").read_text(encoding="utf-8"))
    assert len(flags) == q(built, "SELECT COUNT(*) n FROM audit_flags").n[0]


def test_committed_app_data_matches_the_committed_database():
    """app/public/data/manifest.json must name the build of outputs/follow_the_rupee.db.
    It refreshes on every pipeline run; by hand: python app/export_data.py"""
    import json
    from pipeline.db import ROOT
    manifest = ROOT / "app" / "public" / "data" / "manifest.json"
    if not manifest.exists() or not DEFAULT_DB.exists():
        pytest.skip("no committed app data / database")
    exp = _export_module()
    got = json.loads(manifest.read_text(encoding="utf-8"))["db_build_id"]
    assert got == exp.Source(DEFAULT_DB).build_id(), \
        "app data is older than the database; run: python app/export_data.py"


def test_app_export_only_follows_the_real_database(tmp_path):
    from pipeline.db.sync import export_app_data
    assert export_app_data(tmp_path / "scratch.db") is None      # tests and scratch DBs never touch the app


def test_csv_copies_come_from_the_database(built, tmp_path):
    from pipeline.db.sync import CSV_EXPORTS, export_csv
    dest = export_csv(built, tmp_path / "csv")
    for name in CSV_EXPORTS:
        assert (dest / f"{name}.csv").exists(), name
    flags = pd.read_csv(dest / "billing_anomalies.csv", encoding="utf-8-sig")
    assert flags.flag_type.value_counts().to_dict() == {"DLP_PAID": 493, "OVERBILL": 114, "DOUBLE_BILL": 45}
    assert len(pd.read_csv(dest / "audit_flags.csv", encoding="utf-8-sig")) == \
        q(built, "SELECT COUNT(*) n FROM audit_flags").n[0]


def test_committed_csv_copies_match_the_committed_database():
    from pipeline.db import ROOT
    readme = ROOT / "outputs" / "csv" / "README.txt"
    if not readme.exists() or not DEFAULT_DB.exists():
        pytest.skip("no committed CSV copies / database")
    built_at = db.query("SELECT value_json FROM meta WHERE key = 'built_at_utc'").value_json[0].strip('"')
    assert built_at in readme.read_text(encoding="utf-8"), \
        "outputs/csv is older than the database; run: python -m pipeline.db"
