"""Run the whole pipeline into outputs/ and update the database once at the end.

    python -m pipeline                    # M1 -> M3 -> M2 -> database (Claude on if a key is set)
    python -m pipeline --no-llm           # free: no new Claude calls (cached answers are reused)
    python -m pipeline --only m3          # one module (then the database)
    python -m pipeline --only m1,m3       # M3 reads M1's open issues, so re-run it after M1

Order: M1 connect (complaints, issues, open issues) -> M3 risk (reads M1's open issues)
-> M2 audit (independent of M1/M3) -> database. Each module's own run() would also
update the database (pipeline/db/sync.py); here that is paused so it is built once.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from pipeline.db import sync
from pipeline.db.build import DATA, DOC, OUT, build, stale_inputs

STEPS = {
    "m1": ("M1 connect", lambda d, o: __import__("pipeline.connect", fromlist=["run"]).run(d, o)),
    "m3": ("M3 risk", lambda d, o: __import__("pipeline.risk", fromlist=["run"]).run(d, o)),
    "m2": ("M2 audit", lambda d, o: __import__("pipeline.audit", fromlist=["run"]).run(d, o)),
}
ORDER = ["m1", "m3", "m2"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default=",".join(ORDER), help="comma-separated subset of m1,m3,m2")
    ap.add_argument("--no-llm", action="store_true",
                    help="no new Claude calls: cached answers are reused, misses fall back to rules/templates")
    ap.add_argument("--data", default=str(DATA))
    a = ap.parse_args(argv)
    chosen = [s.strip().lower() for s in a.only.split(",") if s.strip()]
    unknown = sorted(set(chosen) - set(STEPS))
    if unknown:
        ap.error(f"unknown step(s) {unknown}; choose from {ORDER}")
    if a.no_llm:
        os.environ["LLM_OFFLINE"] = "1"   # not LLM_DISABLE: keep the cached Claude texts in outputs/
    else:
        try:
            import evals.run_eval  # noqa: F401  - loads ANTHROPIC_API_KEY from .env, never prints it
        except ImportError:
            pass
    data, out = Path(a.data), OUT
    with sync.paused():
        for key in [k for k in ORDER if k in chosen]:
            label, fn = STEPS[key]
            t = time.time()
            print(f"[pipeline] {label} ...", flush=True)
            fn(data, out)
            print(f"[pipeline] {label} done in {time.time() - t:.0f}s", flush=True)
    t = time.time()
    p = build(data, out, None, DOC)
    print(f"[pipeline] database updated -> {p} ({time.time() - t:.0f}s)")
    stale = stale_inputs(p, data, out)
    if stale:
        print(f"[pipeline] WARNING: database differs from inputs: {stale}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
