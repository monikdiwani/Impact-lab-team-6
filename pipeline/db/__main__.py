"""python -m pipeline.db [--data data] [--out outputs] [--db PATH] [--no-docs] [--check]"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from pipeline.db import db_path
from pipeline.db.build import DATA, DOC, OUT, build, stale_inputs

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build or check the SQLite database.")
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--db", default=None, help="database path (default: outputs/follow_the_rupee.db or $RUPEE_DB)")
    ap.add_argument("--no-docs", action="store_true", help="don't rewrite docs/DATABASE.md")
    ap.add_argument("--check", action="store_true", help="exit 1 if the database is older than its inputs")
    a = ap.parse_args()
    target = Path(a.db) if a.db else db_path()
    if a.check:
        stale = stale_inputs(target, Path(a.data), Path(a.out))
        if stale:
            print(f"{target} is out of date; changed inputs: {', '.join(stale)}\nRebuild: python -m pipeline.db")
            sys.exit(1)
        print(f"{target} is up to date with its inputs")
        sys.exit(0)
    p = build(Path(a.data), Path(a.out), target, None if a.no_docs else DOC)
    from pipeline.db.sync import export_all
    export_all(p)              # app data + CSV copies follow the database (real DB only)
    con = sqlite3.connect(p)
    counts = json.loads(con.execute("SELECT value_json FROM meta WHERE key='row_counts'").fetchone()[0])
    con.close()
    print(f"built {p} ({p.stat().st_size / 1e6:.1f} MB): " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
