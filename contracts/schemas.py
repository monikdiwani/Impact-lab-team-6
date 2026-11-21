"""Frozen output contracts (docs/BLUEPRINT.md §10). Owner: M4.

Every pipeline module writes parquet files to outputs/ with exactly these columns.
Changing this file needs agreement from all four members because the app, the
tests (tests/) and the evals (evals/) all read it.
"""
from __future__ import annotations

FLAG_TYPES = ("OVERBILL", "DOUBLE_BILL", "DLP_PAID", "SLA_MISS", "REPEAT_REPAIR")
SEVERITIES = ("high", "medium", "low")
PLAN_ACTIONS = ("Repair", "Invoke DLP", "Monitor")

# column -> kind ("str", "float", "int", "datetime", "bool")
SCHEMAS: dict[str, dict[str, str]] = {
    # ---- M1 -------------------------------------------------------------
    "complaints_clean": {
        "complaint_id": "str", "received_at": "datetime", "channel": "str",
        "ward_code": "str", "ward_source": "str", "lat": "float", "lon": "float",
        "category_clean": "str", "severity_1_5": "int", "language": "str",
        "english_summary": "str", "issue_id": "str", "linked_work_order_id": "str",
        "status": "str",
    },
    "wo_trail": {
        "work_order_id": "str", "n_complaints": "int", "first_complaint_at": "datetime",
        "channels": "str", "total_upvotes": "int", "hours_to_complete": "float",
    },
    "open_issues": {
        "issue_id": "str", "ward_code": "str", "road_id": "str", "category_clean": "str",
        "severity_1_5": "int", "n_complaints": "int", "first_reported_at": "datetime",
        "total_upvotes": "int",
    },
    # ---- M2 -------------------------------------------------------------
    "audit_flags": {
        "flag_id": "str", "flag_type": "str", "severity": "str", "work_order_id": "str",
        "related_work_order_id": "str", "ward_code": "str", "road_id": "str",
        "contractor_id": "str", "billed_inr": "float", "expected_inr": "float",
        "amount_at_risk_inr": "float", "evidence": "str", "explanation": "str",
    },
    "contractor_scorecard": {
        "contractor_id": "str", "contractor_name": "str", "n_jobs": "int",
        "billed_inr": "float", "sla_pct": "float", "reopen_pct": "float",
        "reopen_expected_pct": "float", "durability_index": "float",
        "median_cost_ratio": "float", "n_flags_by_type": "str",
        "amount_flagged_inr": "float", "score_0_100": "float", "grade": "str",
        "summary_text": "str",
    },
    "ward_scorecard": {
        "ward_code": "str", "budget_inr": "float", "billed_inr": "float",
        "budget_used_pct": "float", "flagged_inr": "float", "flagged_pct": "float",
        "reopen_pct": "float", "sla_pct": "float", "top_contractor_id": "str",
        "summary_text": "str",
    },
    # ---- M3 -------------------------------------------------------------
    "road_risk": {
        "road_id": "str", "ward_code": "str", "road_name": "str", "risk_score": "float",
        "c_exposure": "float", "c_safety": "float", "c_critical": "float",
        "c_flood": "float", "c_condition": "float", "open_issues": "int",
        "under_dlp": "str", "reason": "str",
    },
    "ward_risk": {
        "ward_code": "str", "risk_score": "float", "low_lying_index": "float",
        "flood_days": "int", "open_issues": "int", "remaining_budget_inr": "float",
    },
    "budget_plan": {
        "ward_code": "str", "rank": "int", "road_id": "str", "action": "str",
        "recommended_method": "str", "est_cost_inr": "float", "cumulative_inr": "float",
        "remaining_budget_inr": "float", "risk_score": "float", "reason": "str",
    },
}

OWNERS = {
    "complaints_clean": "M1", "wo_trail": "M1", "open_issues": "M1",
    "audit_flags": "M2", "contractor_scorecard": "M2", "ward_scorecard": "M2",
    "road_risk": "M3", "ward_risk": "M3", "budget_plan": "M3",
}


def validate(df, name: str) -> list[str]:
    """Return a list of contract problems (empty list = OK)."""
    import pandas as pd

    problems = []
    schema = SCHEMAS[name]
    missing = [c for c in schema if c not in df.columns]
    if missing:
        problems.append(f"{name}: missing columns {missing}")
    for col, kind in schema.items():
        if col not in df.columns or df[col].dropna().empty:
            continue
        s = df[col].dropna()
        if kind in ("float", "int") and not pd.api.types.is_numeric_dtype(s):
            problems.append(f"{name}.{col}: expected numeric, got {s.dtype}")
        if kind == "datetime" and not pd.api.types.is_datetime64_any_dtype(s):
            try:
                pd.to_datetime(s)
            except (ValueError, TypeError):
                problems.append(f"{name}.{col}: not parseable as datetime")
    return problems
