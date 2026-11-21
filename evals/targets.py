"""What gets evaluated.

`app` targets call the real pipeline code (the contract below). The other targets
are free, deterministic stand-ins used to validate the harness itself:
  oracle   returns the truth / a known-good text  -> should score ~100%
  null     returns nothing                         -> should score ~0%
  citizen  (extraction) trusts what the citizen typed -> the bar Claude must beat
  template (narrative) a fixed fill-in-the-blanks text, no LLM

App contracts (owners implement these; signatures are the integration point):
  pipeline.connect.extract.extract_complaint(record: dict) -> dict          [M1]
      keys: category_clean, severity_1_5, ward_code, language, (english_summary)
  pipeline.audit.explain.contractor_scorecard_text(facts: dict) -> str      [M2]
  pipeline.audit.explain.ward_summary_text(facts: dict) -> str              [M2]
  pipeline.audit.explain.flag_explanation(facts: dict) -> str               [M2]

Optional: if pipeline.common.llm exposes get_last_meta() -> {"model", "usage",
"stop_reason"} for the current thread's last call, the runner records it per case
so cost and truncation show up in the results.
"""
from __future__ import annotations

import importlib

APP = {
    "extraction": {"*": "pipeline.connect.extract:extract_complaint"},
    "narrative": {
        "contractor": "pipeline.audit.explain:contractor_scorecard_text",
        "ward": "pipeline.audit.explain:ward_summary_text",
        "flag": "pipeline.audit.explain:flag_explanation",
    },
}


def _load(spec: str):
    mod, fn = spec.split(":")
    return getattr(importlib.import_module(mod), fn)


def app_meta():
    try:
        return importlib.import_module("pipeline.common.llm").get_last_meta()
    except (ImportError, AttributeError):
        return None


def resolve(suite: str, target: str):
    """Return fn(case) -> output."""
    if target == "app":
        table = APP[suite]
        fns = {k: _load(v) for k, v in table.items()}   # raises early if not implemented
        if suite == "extraction":
            return lambda case: fns["*"](dict(case["input"]))
        return lambda case: fns[case["kind"]](dict(case["facts"]))

    if suite == "extraction":
        if target == "oracle":
            return lambda c: {"category_clean": c["expected"]["category"], "severity_1_5": c["expected"]["severity"],
                              "ward_code": c["expected"]["ward_code"], "language": c["expected"]["language"]}
        if target == "null":
            return lambda c: {}
        if target == "citizen":
            return lambda c: {"category_clean": c["input"]["category_reported"], "severity_1_5": 3,
                              "ward_code": c["input"]["ward_code"], "language": "en"}

    if suite == "narrative":
        if target == "null":
            return lambda c: ""
        if target in ("template", "oracle"):
            return _template
    raise SystemExit(f"unknown target {target!r} for suite {suite!r}")


def _inr(x):
    return f"₹{x:,}"


def _template(case) -> str:
    f, k = case["facts"], case["kind"]
    if k == "contractor":
        ex = f["example_work_orders"]
        cite = f" See {ex[0]['work_order_id']}." if ex else ""
        small = " This is based on only one job, so it is too early to judge." if f["n_jobs"] == 1 else ""
        speed_vs = (f" It is fast (on time {f['sla_met_pct']}%) but repairs often re-open ({f['reopened_pct']}%)."
                    if f["sla_met_pct"] > f["city_average"]["sla_met_pct"] and f["reopened_pct"] > f["city_average"]["reopened_pct"]
                    else "")
        return (f"{f['contractor_name']} did {f['n_jobs']} jobs worth {_inr(f['billed_inr'])}. "
                f"{f['sla_met_pct']}% were finished on time (city average {f['city_average']['sla_met_pct']}%) and "
                f"{f['reopened_pct']}% re-opened within {f['definitions']['reopen_window_days']} days "
                f"(city average {f['city_average']['reopened_pct']}%).{speed_vs}{small} "
                f"{f['n_above_rate_card_tolerance']} bills were above the rate card and need review.{cite} "
                f"To improve: use longer-lasting repair methods.")
    if k == "ward":
        over = (" The ward is over budget." if f["budget_used_pct"] > 100 else "")
        low = (" It is a low-lying ward where flooding is common." if f["low_lying_index"] >= 0.6 else "")
        return (f"Ward {f['ward_code']} billed {_inr(f['billed_inr'])} of its {_inr(f['budget_inr'])} budget "
                f"({f['budget_used_pct']}%).{over}{low} {f['reopened_pct']}% of repairs re-opened within "
                f"{f['definitions']['reopen_window_days']} days and {f['sla_met_pct']}% met the deadline. "
                f"{_inr(f['billed_on_dlp_roads_inr'])} was billed on roads still under the contractor's warranty (DLP); "
                f"the ward office should ask those contractors to fix them at no cost.")
    reasons = {"OVERBILL": f"billed {f['ratio']}x the rate card", "DOUBLE_BILL":
               f"same road and job as {f.get('earlier_work_order_id')} within 7 days, no complaint linked",
               "DLP_PAID": "road still under warranty (DLP), should be free",
               "REPEAT_REPAIR": "repair re-opened within 30 days"}
    return f"{f['work_order_id']}: {reasons[f['flag_type']]}. Needs review."
