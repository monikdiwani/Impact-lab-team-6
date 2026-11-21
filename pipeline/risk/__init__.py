"""M3: risk analysis and budget recommendation.

Entry point (docs/BLUEPRINT.md §10):

    from pipeline.risk import run
    run(data_dir, out_dir)  ->  {name: path}

Writes to out_dir:
    road_risk.parquet         one row per road segment (contract: contracts/schemas.py)
    ward_risk.parquet         one row per ward (contract)
    budget_plan.parquet       ranked plan per ward (contract)
    method_durability.parquet re-open rate and cost per lasting repair per method (extra)
    ward_memos.json           150-word budget memo per ward (template, or Claude if available)
    risk_report.json          run metadata: weights, data notes, demand source, totals

Reads out_dir/open_issues.parquet from M1 if present, else builds a stand-in from complaints.
CLI: python -m pipeline.risk [--data data] [--out outputs] [--no-llm]
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from contracts.schemas import SCHEMAS, validate

from . import config as C
from .demand import load_open_issues
from .explain import plan_reason, road_reason, ward_memo, ward_memo_facts
from .load import load
from .planner import method_durability, needed_work, plan
from .road_risk import road_risk, ward_risk

log = logging.getLogger(__name__)


def _contract(df: pd.DataFrame, name: str, extra: bool = False) -> pd.DataFrame:
    """Order columns as the contract says; keep extra context columns after them if asked."""
    cols = list(SCHEMAS[name])
    rest = [c for c in df.columns if c not in cols] if extra else []
    out = df[cols + rest].copy()
    for c, kind in SCHEMAS[name].items():
        if kind == "int":
            out[c] = pd.to_numeric(out[c]).fillna(0).astype("int64")
        elif kind == "float":
            out[c] = pd.to_numeric(out[c]).astype("float64")
        elif kind == "str":
            out[c] = out[c].astype("string")
    problems = validate(out, name)
    if problems:
        raise ValueError("; ".join(problems))
    return out


def run(data_dir: Path, out_dir: Path, use_llm: bool = True) -> dict[str, Path]:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    inp = load(data_dir)
    issues, source, unplaced = load_open_issues(inp, data_dir, out_dir)

    roads, hotspots = road_risk(inp, issues)
    roads["reason"] = [road_reason(r) for r in roads.itertuples()]
    wards = ward_risk(inp, roads, hotspots, issues, unplaced)

    methods = method_durability(inp)
    need = needed_work(inp, issues, methods)
    bp = plan(inp, roads, wards, methods, need, plan_reason)

    paths = {
        "road_risk": out_dir / "road_risk.parquet",
        "ward_risk": out_dir / "ward_risk.parquet",
        "budget_plan": out_dir / "budget_plan.parquet",
        "method_durability": out_dir / "method_durability.parquet",
        "ward_memos": out_dir / "ward_memos.json",
        "risk_report": out_dir / "risk_report.json",
    }
    _contract(roads, "road_risk", extra=True).to_parquet(paths["road_risk"], index=False)
    _contract(wards, "ward_risk", extra=True).to_parquet(paths["ward_risk"], index=False)
    _contract(bp, "budget_plan", extra=True).to_parquet(paths["budget_plan"], index=False)
    methods.to_parquet(paths["method_durability"], index=False)

    memos = {}
    for w in wards.itertuples(index=False):
        ws = pd.Series(w._asdict())
        f = ward_memo_facts(ws, bp[bp.ward_code == w.ward_code])
        text, src = ward_memo(f, use_llm=use_llm)
        memos[w.ward_code] = {"memo": text, "source": src, "facts": f}
    paths["ward_memos"].write_text(json.dumps(memos, ensure_ascii=False, indent=1), encoding="utf-8")

    report = {
        "as_of": str(inp.as_of.date()),
        "weights": C.WEIGHTS,
        "open_issues_source": source,
        "n_open_issues": int(len(issues)),
        "data_notes": inp.issues,
        "n_roads": int(len(roads)),
        "plan_actions": bp.action.value_counts().to_dict(),
        "plan_repair_inr": float(bp.loc[bp.action == "Repair", "est_cost_inr"].sum()),
        "over_budget_wards": sorted(wards.loc[wards.remaining_budget_inr <= 0, "ward_code"]),
        "recommended_methods": methods[methods.recommended]
            .set_index("work_type").repair_method.to_dict(),
    }
    paths["risk_report"].write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("M3 wrote %s", ", ".join(p.name for p in paths.values()))
    return paths
