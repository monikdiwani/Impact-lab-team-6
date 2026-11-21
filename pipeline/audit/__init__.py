"""M2: financial audit and contractor accountability.

    run(data_dir, out_dir) -> {name: path}
writes audit_flags.parquet, contractor_scorecard.parquet, ward_scorecard.parquet and
scorecard_text.json (schemas in contracts/schemas.py).

Flag explanations use the template by default (about 2,500 flags). Set
AUDIT_LLM_FLAGS=1 to have Claude reword them too (cached by M1's wrapper).
Scorecard summaries use Claude when pipeline.common.llm exists, else the template.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from pipeline.audit import config as C
from pipeline.audit import explain, rules, scorecards
from pipeline.audit.load import enrich_work_orders, load_frames


def _flag_facts(r, wo_by_id: pd.DataFrame) -> dict:
    w = wo_by_id.loc[r.work_order_id]
    f = {"flag_type": r.flag_type, "work_order_id": r.work_order_id, "contractor_name": w.contractor_name,
         "ward_code": r.ward_code, "road_name": w.road_name, "repair_method": w.repair_method,
         "billed_inr": int(r.billed_inr), "rate_card_inr": int(round(w.expected_inr)),
         "ratio": round(float(w.cost_ratio), 2), "definitions": C.DEFINITIONS}
    if r.flag_type == "DOUBLE_BILL":
        f["earlier_work_order_id"] = r.related_work_order_id
    elif r.flag_type == "REPEAT_REPAIR":
        f["followup_work_order_id"] = r.related_work_order_id
        f["followup_cost_inr"] = int(r.amount_at_risk_inr)
    elif r.flag_type == "SLA_MISS" and pd.notna(w.hours_to_complete):
        f["hours_late"] = round(float(w.hours_to_complete - w.sla_hours), 1)
    return f


def _heavy_rain_days(data_dir: Path) -> int | None:
    try:
        rain = pd.read_csv(Path(data_dir) / "rainfall_daily.csv", encoding="utf-8")
        return int(rain[rain.imd_category.isin(["Heavy", "Very heavy", "Extremely heavy"])].date.nunique())
    except Exception:
        return None


def run(data_dir: Path, out_dir: Path) -> dict[str, Path]:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    frames = load_frames(data_dir)
    wo = enrich_work_orders(frames)

    flags = rules.all_flags(wo)
    use_llm = os.environ.get("AUDIT_LLM_FLAGS") == "1"
    wo_by_id = wo.set_index("work_order_id")
    flags["explanation"] = [explain.flag_explanation(_flag_facts(r, wo_by_id), use_llm=use_llm)
                            for r in flags.itertuples()]

    cs, cs_meta = scorecards.contractor_scorecard(wo, flags, frames["contractors"],
                                                  text_fn=explain.contractor_scorecard_text)
    ws, ws_meta = scorecards.ward_scorecard(wo, flags, frames["wards"], heavy_days=_heavy_rain_days(data_dir),
                                            text_fn=explain.ward_summary_text)

    text = {
        "contractors": dict(zip(cs.contractor_id, cs.summary_text)),
        "wards": dict(zip(ws.ward_code, ws.summary_text)),
        "fairness_notes": scorecards.FAIRNESS_NOTES,
        "score_weights": C.SCORE_WEIGHTS,
        "score_components": cs_meta["components"],
        "thresholds": {"overbill_ratio": C.OVERBILL_RATIO, "overbill_high_ratio": C.OVERBILL_HIGH_RATIO,
                       "double_bill_days": C.DOUBLE_BILL_DAYS, "repeat_window_days": C.REPEAT_WINDOW_DAYS},
        "facts": {"contractors": cs_meta["facts"], "wards": ws_meta["facts"]},
    }

    # write only after everything computed, so a failure leaves the previous outputs in place
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {name: out_dir / f"{name}.parquet" for name in ("audit_flags", "contractor_scorecard", "ward_scorecard")}
    flags.to_parquet(paths["audit_flags"], index=False)
    cs.to_parquet(paths["contractor_scorecard"], index=False)
    ws.to_parquet(paths["ward_scorecard"], index=False)
    paths["scorecard_text"] = out_dir / "scorecard_text.json"
    paths["scorecard_text"].write_text(json.dumps(text, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return paths


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parents[2]
    out = run(root / "data", Path(sys.argv[1]) if len(sys.argv) > 1 else root / "outputs")
    print({k: str(v) for k, v in out.items()})
