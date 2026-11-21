"""python -m pipeline.risk [--data data] [--out outputs] [--no-llm]"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from . import run

ROOT = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "outputs"))
    ap.add_argument("--no-llm", action="store_true", help="template memos only")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    paths = run(Path(a.data), Path(a.out), use_llm=not a.no_llm)
    print(json.dumps(json.loads(paths["risk_report"].read_text(encoding="utf-8")), indent=1, ensure_ascii=False))
