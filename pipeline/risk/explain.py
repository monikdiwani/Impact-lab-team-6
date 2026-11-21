"""Plain-language reasons for M3 outputs.

Every number comes from pandas. The template text is always produced, so the app works
with no API key. If M1's cached Claude wrapper (pipeline.common.llm.ask) exists, the
ward memo is rewritten by Claude from the same facts; otherwise the template is used.
Tone: neutral, no blame words, synthetic data.
"""
from __future__ import annotations

import json

import pandas as pd


def inr(x: float) -> str:
    x = float(x)
    if abs(x) >= 1e7:
        return f"₹{x / 1e7:.2f} Cr"
    if abs(x) >= 1e5:
        return f"₹{x / 1e5:.2f} L"
    return f"₹{x:,.0f}"


def road_facts(r) -> list[str]:
    """Short facts about a road, strongest first. r is a row of the road_risk table."""
    facts: list[tuple[float, str]] = []
    if getattr(r, "c_critical", 0) > 0 and isinstance(getattr(r, "top_facility", None), str):
        kind = "Ambulance route to" if r.top_type == "Hospital" else "Entry road for"
        facts.append((r.c_critical, f"{kind} {r.top_facility}"))
    n_road = int(getattr(r, "n_road_acc", 0) or 0)
    n_acc = int(getattr(r, "n_acc", 0) or 0)
    if n_road:
        facts.append((r.c_safety + 0.1, f"{n_road} road-condition accident{'s' * (n_road > 1)}"
                                        f" ({n_acc} in all)"))
    elif n_acc:
        facts.append((r.c_safety, f"{n_acc} accident{'s' * (n_acc > 1)} on record"))
    if isinstance(getattr(r, "hotspot", None), str) and r.hotspot_dist_m < 1500:
        facts.append((r.c_flood, f"{r.hotspot_dist_m:,.0f} m from {r.hotspot} flood hotspot"))
    if r.open_issues:
        facts.append((0.9, f"{int(r.open_complaints)} open complaint{'s' * (r.open_complaints > 1)}"))
    if r.n_reopened:
        facts.append((r.c_condition, f"{int(r.n_reopened)} of {int(r.n_wo)} past repairs re-opened"))
    elif r.n_wo >= 10:
        facts.append((r.c_condition * 0.8, f"{int(r.n_wo)} repairs this monsoon"))
    if r.c_exposure >= 0.6:
        facts.append((r.c_exposure * 0.7, f"{int(r.peak_hour_vehicles):,} vehicles/peak hour"
                                          + (f", {int(r.bus_routes_count)} bus routes" if r.bus_routes_count else "")))
    if r.years_since_resurfaced >= 5:
        facts.append((0.3, f"last resurfaced {r.years_since_resurfaced:.0f} years ago"))
    facts.sort(key=lambda t: -t[0])
    return [f for _, f in facts]


def road_reason(r, max_facts: int = 3) -> str:
    f = road_facts(r)
    return "; ".join(f[:max_facts]) if f else "Low traffic, no accidents or open complaints on record"


def plan_reason(r, action: str, note: str, method_row, remaining: float) -> str:
    base = road_reason(r, 2)
    if action == "Invoke DLP":
        return f"Under defect liability: original contractor repairs free, ₹0 to BMC. {base}"
    if note == "over_budget":
        return f"Ward already {inr(-remaining)} over budget: reallocate, no new spend. {base}"
    if note == "low_need":
        return f"Lower risk and no open complaints: keep under watch. {base}"
    if note == "no_room":
        return f"Not enough budget left this cycle. {base}"
    m = method_row
    durable = (f"{m.name}: {m.reopen_rate:.0%} re-open rate" if m is not None else "")
    extra = " (cheaper method that fits the money left)" if note == "cheaper_fit" else ""
    return f"{base}. {durable}{extra}"


def ward_memo_facts(ward: pd.Series, plan: pd.DataFrame) -> dict:
    rep = plan[plan.action == "Repair"]
    dlp = plan[plan.action == "Invoke DLP"]
    return {
        "ward_code": ward.ward_code,
        "budget_inr": float(ward.monsoon_repair_budget_inr_2025),
        "billed_inr": float(ward.billed_inr),
        "remaining_budget_inr": float(ward.remaining_budget_inr),
        "low_lying_index": float(ward.low_lying_index),
        "flood_days": int(ward.flood_days),
        "open_complaints": int(ward.open_complaints),
        "n_repairs": int(len(rep)),
        "repair_cost_inr": float(rep.est_cost_inr.sum()),
        "n_dlp_roads": int(len(dlp)),
        "top_roads": [{"road_id": r.road_id, "action": r.action, "method": r.recommended_method,
                       "est_cost_inr": float(r.est_cost_inr), "reason": r.reason}
                      for r in plan.sort_values("rank").head(3).itertuples()],
    }


def ward_memo_template(f: dict) -> str:
    head = (f"Ward {f['ward_code']} has billed {inr(f['billed_inr'])} of its {inr(f['budget_inr'])} "
            f"monsoon budget. ")
    if f["remaining_budget_inr"] <= 0:
        head += (f"It is {inr(-f['remaining_budget_inr'])} over budget, so the plan adds no new paid "
                 f"repairs and recommends reallocating from wards with money left. ")
    else:
        head += (f"The plan uses {inr(f['repair_cost_inr'])} of the {inr(f['remaining_budget_inr'])} left "
                 f"on {f['n_repairs']} road{'s' * (f['n_repairs'] != 1)}, highest risk first. ")
    if f["n_dlp_roads"]:
        head += (f"{f['n_dlp_roads']} road{'s are' if f['n_dlp_roads'] > 1 else ' is'} still under defect "
                 f"liability: ask the original contractor to repair at no cost. ")
    ctx = f"Context: low-lying index {f['low_lying_index']:.2f}, {f['flood_days']} likely flood days, "
    ctx += f"{f['open_complaints']} open complaints. "
    tops = "; ".join(f"{t['road_id']} ({t['action']}{', ' + inr(t['est_cost_inr']) if t['est_cost_inr'] else ''})"
                     for t in f["top_roads"])
    return head + ctx + f"Top priorities: {tops}."


MEMO_SYSTEM = (
    "You write short budget memos for a municipal ward officer. Use ONLY the numbers and road IDs "
    "given in the JSON facts; never invent figures. Neutral tone: no blame words such as fraud, "
    "scam or corrupt. Max 150 words, plain English. Data is synthetic."
)


def ward_memo(f: dict, use_llm: bool = True) -> tuple[str, str]:
    """Return (memo, source) where source is 'claude' or 'template'."""
    fallback = ward_memo_template(f)
    if use_llm:
        try:
            from pipeline.common.llm import ask  # M1's cached wrapper
        except ImportError:
            return fallback, "template"
        try:
            text = ask("Write the ward budget memo from these facts:\n" + json.dumps(f, ensure_ascii=False),
                       system=MEMO_SYSTEM, effort="medium", fallback=fallback)
            if isinstance(text, str) and text.strip() and text != fallback:
                return text.strip(), "claude"
        except Exception:  # noqa: BLE001 - narration must never break the pipeline
            pass
    return fallback, "template"
