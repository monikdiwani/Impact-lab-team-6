"""Keep the database in step with every pipeline run.

Each module's run() (M1 connect, M2 audit, M3 risk) calls after_run() as its last step.
When the run wrote into the project's outputs/ folder - the one the app reads - the
database is rebuilt from data/ + outputs/ (about 10 s). Runs into any other folder (tests,
the risk backtest, scratch dirs) never touch it, so running the test suite doesn't change
the committed database.

  RUPEE_DB_AUTOSYNC=0   turn it off; `python -m pipeline` uses this to build once at the
                        end instead of after every module (see pipeline/run_all.py).

If the rebuild fails (e.g. a new output breaks a foreign key), the module's outputs are
already written and the previous database is left untouched (the build is atomic); the
error is printed loudly, and tests/test_db.py will fail until it is fixed.
"""
from __future__ import annotations

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
    return p


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
