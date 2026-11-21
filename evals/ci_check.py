"""Free eval gates for CI: no API key, no cost. Fails (exit 1) if any gate is missed.

    python -m evals.ci_check

1. Harness sanity: oracle must score 100%, null 0% (a broken grader or runner shows up here).
2. The real app code with Claude off (`rules` target): M1 extraction and M2 narrative text
   must hold their measured level, and severity must sit at the data's ceiling.
3. M3 risk backtest: the ranking must beat the naive "past work orders" baseline.

Writes a markdown table to $GITHUB_STEP_SUMMARY when run inside GitHub Actions.
"""
from __future__ import annotations

import json
import os
import sys

from evals import backtest_risk, run_eval

HC = run_eval.HC / "_selfcheck"

# (suite, target, {metric: (op, value)})
GATES = [
    ("extraction", "oracle", {"category": ("==", 1.0), "severity_exact": ("==", 1.0), "severity_best": ("==", 1.0),
                              "ward": ("==", 1.0), "valid_output": ("==", 1.0)}),
    ("extraction", "null", {"category": ("==", 0.0), "valid_output": ("==", 0.0)}),
    ("extraction", "rules", {"category": (">=", 0.99), "severity_best": (">=", 0.99), "ward": (">=", 0.99),
                             "valid_output": ("==", 1.0)}),
    ("narrative", "template", {"passes_all": ("==", 1.0)}),
    ("narrative", "null", {"passes_all": ("==", 0.0)}),
    ("narrative", "rules", {"passes_all": (">=", 1.0)}),
]
OPS = {"==": lambda a, b: abs(a - b) < 1e-9, ">=": lambda a, b: a >= b - 1e-9}


def main() -> int:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    rows, failed = [], []

    def record(name, metric, got, op, want):
        ok = OPS[op](got, want)
        rows.append((name, metric, f"{got:.3f}", f"{op} {want}", "pass" if ok else "**FAIL**"))
        if not ok:
            failed.append(f"{name} {metric}: {got:.3f} (needs {op} {want})")

    for suite, target, gates in GATES:
        run_eval.main(["--suite", suite, "--target", target])
        s = json.loads((HC / f"{suite}-{target}" / "summary.json").read_text(encoding="utf-8"))
        if s["n_errors"]:
            failed.append(f"{suite}/{target}: {s['n_errors']} failed attempts")
        for metric, (op, want) in gates.items():
            record(f"{suite}/{target}", metric, s["metrics"][metric]["mean"], op, want)
        if suite == "extraction" and target == "rules":      # severity must reach the data's ceiling
            ceiling = s["severity_ceiling"]
            record("extraction/rules", "severity_exact vs ceiling",
                   s["metrics"]["severity_exact"]["mean"], ">=", round(ceiling["exact"] - 0.005, 3))

    backtest_risk.main([])
    b = json.loads((backtest_risk.OUT / "app.json").read_text(encoding="utf-8"))
    for metric in ("spearman", "precision_at_20"):
        record("risk backtest", f"{metric} vs naive", b["model"][metric], ">=",
               b["baseline_past_work_orders"][metric])

    table = ["| Check | Metric | Got | Gate | Result |", "|---|---|---|---|---|"]
    table += [f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in rows]
    report = "## Free eval gates\n\n" + "\n".join(table) + "\n"
    print("\n" + report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(report)
    if failed:
        print("FAILED gates:\n  " + "\n  ".join(failed), file=sys.stderr)
        return 1
    print(f"all {len(rows)} gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
