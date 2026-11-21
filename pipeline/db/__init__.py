"""SQLite data layer: the app reads everything from one database, not from loose files.

    from pipeline import db
    df = db.query("SELECT * FROM v_complaint_trail WHERE complaint_id = ?", ["BMC25-000005"])
    with db.connect() as con: ...

The database is built from data/ and outputs/ by `python -m pipeline.db` (see build.py)
and lives at outputs/follow_the_rupee.db (override with the RUPEE_DB env var).
Schema reference with every table, view and an example query: docs/DATABASE.md.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "outputs" / "follow_the_rupee.db"


def db_path() -> Path:
    return Path(os.environ.get("RUPEE_DB") or DEFAULT_DB)


def connect(path: str | Path | None = None, read_only: bool = True) -> sqlite3.Connection:
    """Open the database. Read-only by default (what the app needs); foreign keys on.
    check_same_thread=False so a web app (e.g. Streamlit) can share it across threads."""
    p = Path(path) if path else db_path()
    if read_only:
        if not p.exists():
            raise FileNotFoundError(f"{p} not found. Build it with: python -m pipeline.db")
        con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
    else:
        con = sqlite3.connect(p, check_same_thread=False)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def query(sql: str, params=(), path: str | Path | None = None):
    """Run a SELECT and return a pandas DataFrame."""
    import pandas as pd
    con = connect(path)
    try:
        return pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()


def tables(path: str | Path | None = None) -> list[str]:
    con = connect(path)
    try:
        return [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name")]
    finally:
        con.close()
