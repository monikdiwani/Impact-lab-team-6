"""Recompute the routing figures quoted in pipeline/connect/extract.py and the docs, so
they never go stale. Free: Claude is switched off (the 'claude' rows use the fallback).

    python -m evals.measure_routing

Held-out pool = linked complaints (truth = the fixing work order's work_type) that are not
in the main extraction eval set.
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

os.environ["LLM_DISABLE"] = "1"

from evals.build_cases import CASES, DATA, _linked, _support  # noqa: E402
from pipeline.connect import extract as X  # noqa: E402

SEV = {24: 5, 48: 4, 72: 3, 120: 2, 168: 1}


def pct(x) -> str:
    return f"{100 * x:.1f}%"


def main() -> int:
    eval_ids = {json.loads(line)["id"] for line in open(CASES / "extraction.jsonl", encoding="utf-8")}
    m = _linked()
    m = m[~m.complaint_id.isin(eval_ids)].reset_index(drop=True)
    out = X.extract(m)
    ok = out.category_clean == out.work_type
    wrong = out.category_reported != out.work_type
    support = m.apply(_support, axis=1).map(bool)
    sev = out.sla_hours.map(SEV)
    noisy = (out.language != "en") & (out.channel != X.HELPLINE)
    kw = out.description.map(lambda t: (X.keyword_hits(t) or [None])[0])

    print(f"held-out linked complaints: {len(out):,} (linked {len(m) + len(eval_ids):,} minus {len(eval_ids)} eval cases)")
    print(f"  category, rules (Claude rows on fallback): {pct(ok.mean())}   trusting the citizen: "
          f"{pct((out.category_reported == out.work_type).mean())}")
    print(f"  on rows where the citizen was wrong: {pct(ok[wrong].mean())} (n={int(wrong.sum())})")
    print(f"  on rows with reliable evidence: {pct(ok[support].mean())} (n={int(support.sum())}); "
          f"without: {pct(ok[~support].mean())} (n={int((~support).sum())}, "
          f"base rate 'Pothole' {pct((out.work_type[~support] == X.DEFAULT_CATEGORY).mean())})")
    print("  by source: " + ", ".join(f"{s} {pct(ok[out.extraction_source == s].mean())} (n={int((out.extraction_source == s).sum())})"
                                      for s in out.extraction_source.value_counts().index))
    print(f"  noisy (non-English app/portal) text, first keyword vs truth: {pct((kw[noisy] == out.work_type[noisy]).mean())} "
          "overall; " + ", ".join(f"{lang} {pct((kw[noisy & (out.language == lang)] == out.work_type[noisy & (out.language == lang)]).mean())}"
                                  for lang in ("hi", "hi-en", "mr")))
    s = out.severity_1_5.astype("float")
    print(f"  severity with extracted category: exact {pct((s == sev).mean())}, within one {pct(((s - sev).abs() <= 1).mean())}")
    allc = X.extract(pd.read_csv(DATA / "complaints.csv", encoding="utf-8"))
    counts = allc.extraction_source.value_counts().to_dict()
    to_claude = counts.get("claude", 0) + counts.get("claude_fallback", 0) + counts.get("noise_fallback", 0)
    print(f"all {len(allc):,} complaints by source: {counts}")
    print(f"  routed to Claude: {to_claude} ({pct(to_claude / len(allc))}), of which non-road (no road keyword): "
          f"{counts.get('noise_fallback', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
