"""Keep the database in step with every pipeline run.

Each module's run() (M1 connect, M2 audit, M3 risk) calls after_run() as its last step.
When the run wrote into the project's outputs/ folder - the one the app reads - the
database is rebuilt from data/ + outputs/ (about 10 s). Runs into any other folder (tests,
the risk backtest, scratch dirs) never touch it, so running the test suite doesn't change
the committed database.

  RUPEE_DB_AUTOSYNC=0   turn it off; `python -m pipeline` uses this to build once at the
                        end instead of after every module (see pipeline/run_all.py).

After a successful rebuild of the app's database, everything derived from it is re-exported:
the web app's data (app/public/data/*.json, via app/export_data.py) and the CSV copies for
people and judges (outputs/csv/*.csv), so nothing downstream can drift from the database.

If the rebuild fails (e.g. a new output breaks a foreign key), the module's outputs are
already written and the previous database is left untouched (the build is atomic); the
error is printed loudly, and tests/test_db.py will fail until it is fixed.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)
ENV = "RUPEE_DB_AUTOSYNC"

# outputs written by an upstream module that a downstream module reads
DOWNSTREAM = {"M1": [("open_issues.parquet", "budget_plan.parquet", "M3 (python -m pipeline --only m3)")]}


def _same(a, b) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def enabled() -> bool:
    return os.environ.get(ENV, "1") != "0"


def after_run(data_dir, out_dir, module: str) -> Path | None:
    """Rebuild the database if this run wrote the app's outputs/. Never raises."""
    from pipeline.db import build as B
    from pipeline.db import db_path
    if not enabled() or not _same(out_dir, B.OUT):
        return None
    for upstream, downstream, who in DOWNSTREAM.get(module, []):
        up, down = Path(out_dir) / upstream, Path(out_dir) / downstream
        if down.exists() and up.stat().st_mtime > down.stat().st_mtime:
            print(f"[db] note: {module} rewrote {upstream}; {downstream} is now older. Re-run {who} so the "
                  f"plan uses the new data.", file=sys.stderr)
    try:
        p = B.build(Path(data_dir), Path(out_dir), db_path(), B.DOC)
    except Exception as e:  # noqa: BLE001 - outputs are written; the DB must not crash the run
        msg = (f"[db] {module} finished, but updating the database failed: {type(e).__name__}: {e}\n"
               f"[db] The previous database is unchanged (and now out of date). Fix the cause, then run: "
               f"python -m pipeline.db")
        log.error(msg)
        print(msg, file=sys.stderr)
        return None
    print(f"[db] {module}: database updated -> {p}")
    export_all(p)
    return p


# CSV copies for people and judges, all read from the database. name -> SQL
CSV_EXPORTS = {
    "complaints_clean": 'SELECT complaint_id, received_at, channel, ward_code, ward_source, lat, lon, category_clean, '
                        'severity_1_5, language, english_summary, issue_id, linked_work_order_id, status FROM complaints',
    "open_issues": "SELECT * FROM open_issues",
    "wo_trail": "SELECT * FROM wo_trail",
    "audit_flags": "SELECT * FROM audit_flags ORDER BY flag_type, work_order_id",
    "billing_anomalies": "SELECT * FROM audit_flags WHERE flag_type IN ('OVERBILL', 'DOUBLE_BILL', 'DLP_PAID') "
                         "ORDER BY flag_type, amount_at_risk_inr DESC",
    "budget_plan": "SELECT * FROM v_next_rupee ORDER BY ward_code, rank",
    "road_risk": "SELECT * FROM road_risk ORDER BY risk_score DESC",
}


def export_all(db_file: Path) -> None:
    export_app_data(db_file)
    export_csv(db_file)


def export_csv(db_file: Path, dest: Path | None = None) -> Path | None:
    """Write outputs/csv/*.csv from the app's database (UTF-8 with BOM, opens cleanly in
    Excel). Only for the real database unless dest is given; never raises."""
    import json
    from pipeline import db
    from pipeline.db import DEFAULT_DB, ROOT
    if dest is None:
        if not _same(db_file, DEFAULT_DB):
            return None
        dest = ROOT / "outputs" / "csv"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for name, sql in CSV_EXPORTS.items():
            db.query(sql, path=db_file).to_csv(dest / f"{name}.csv", index=False, encoding="utf-8-sig")
        meta = json.loads(db.query("SELECT value_json FROM meta WHERE key = 'built_at_utc'", path=db_file).value_json[0])
        lines = ["Exported from outputs/follow_the_rupee.db on every pipeline run; do not edit by hand.",
                 f"Database built {meta} UTC. All data is synthetic.", ""]
        (dest / "README.txt").write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - exports must never crash the run
        print(f"[db] database updated, but exporting the CSV copies failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    print(f"[db] CSV copies exported -> {dest}")
    return dest


def export_app_data(db_file: Path) -> Path | None:
    """Re-export the web app's JSON from the app's database. Only for the real database
    (never a test or scratch DB); never raises."""
    from pipeline.db import DEFAULT_DB, ROOT
    script = ROOT / "app" / "export_data.py"
    if not script.exists() or not _same(db_file, DEFAULT_DB):
        return None
    try:
        spec = importlib.util.spec_from_file_location("app_export_data", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        dest = mod.main(Path(db_file))
    except Exception as e:  # noqa: BLE001 - the database is fine; the app export must not crash the run
        print(f"[db] database updated, but exporting the app data failed: {type(e).__name__}: {e}",
              file=sys.stderr)
        print("[db] Fix the cause, then run: python app/export_data.py", file=sys.stderr)
        return None
    print(f"[db] app data exported -> {dest}")
    return dest


@contextmanager
def paused():
    """Suspend auto-sync (used to run several modules, then build once)."""
    old = os.environ.get(ENV)
    os.environ[ENV] = "0"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = old
