"""M3 invariants. Skips until pipeline.risk.run exists.

Whether the ranking is *good* is measured by evals/backtest_risk.py; these tests only
check it is internally consistent.
"""
from __future__ import annotations

import pytest

from contracts.schemas import PLAN_ACTIONS, validate
from tests.conftest import read_csv, read_output

COMPONENTS = ["c_exposure", "c_safety", "c_critical", "c_flood", "c_condition"]


@pytest.fixture(scope="module")
def road_risk(risk_out):
    return read_output(risk_out, "road_risk")


@pytest.fixture(scope="module")
def plan(risk_out):
    return read_output(risk_out, "budget_plan")


def test_outputs_match_contract(risk_out):
    for name in ("road_risk", "ward_risk", "budget_plan"):
        assert validate(read_output(risk_out, name), name) == []


def test_every_road_scored(road_risk):
    assert set(road_risk.road_id) == set(read_csv("roads").road_id)
    assert road_risk.risk_score.between(0, 100).all()
    for c in COMPONENTS:
        assert road_risk[c].between(0, 1).all(), c


def test_dlp_flag_carried_through(road_risk):
    roads = read_csv("roads").set_index("road_id").under_dlp
    assert (road_risk.set_index("road_id").under_dlp == roads.reindex(road_risk.road_id).values).all()


def test_plan_never_exceeds_remaining_budget(plan):
    spend = plan[plan.action == "Repair"].groupby("ward_code").est_cost_inr.sum()
    remaining = plan.groupby("ward_code").remaining_budget_inr.first().clip(lower=0)
    over = spend - remaining.reindex(spend.index)
    assert (over <= 1).all(), over[over > 1].to_string()


def test_overspent_wards_get_no_new_repairs(plan, work_orders):
    budget = read_csv("wards").set_index("ward_code").monsoon_repair_budget_inr_2025
    billed = work_orders.groupby("ward_code").cost_inr.sum()
    overspent = set(budget.index[billed.reindex(budget.index) > budget])   # E, R/C, L, M/W, A, R/S
    repairs = plan[(plan.action == "Repair") & plan.ward_code.isin(overspent)]
    assert repairs.est_cost_inr.sum() == 0


def test_dlp_roads_cost_bmc_nothing(plan):
    dlp = set(read_csv("roads").query("under_dlp == 'Y'").road_id)
    rows = plan[plan.road_id.isin(dlp)]
    assert (rows.action != "Repair").all(), "DLP roads should be 'Invoke DLP', not paid repairs"
    assert (rows.loc[rows.action == "Invoke DLP", "est_cost_inr"] == 0).all()


def test_plan_shape(plan):
    assert set(plan.action) <= set(PLAN_ACTIONS)
    for ward, g in plan.groupby("ward_code"):
        assert list(g.sort_values("rank")["rank"]) == list(range(1, len(g) + 1)), ward
        repairs = g[g.action == "Repair"].sort_values("rank")
        assert repairs.cumulative_inr.is_monotonic_increasing, ward
    assert plan.reason.fillna("").str.len().gt(0).all()


def test_score_is_weighted_sum_of_components(road_risk):
    from pipeline.risk.config import WEIGHTS
    assert abs(sum(WEIGHTS.values()) - 1) < 1e-9
    rebuilt = 100 * sum(WEIGHTS[c] * road_risk[c] for c in COMPONENTS)
    assert (rebuilt - road_risk.risk_score).abs().max() < 0.05


def test_ward_risk_covers_every_ward(risk_out):
    wr = read_output(risk_out, "ward_risk")
    assert set(wr.ward_code) == set(read_csv("wards").ward_code)
    assert wr.risk_score.between(0, 100).all()


def test_every_road_in_plan_once(plan):
    assert set(plan.road_id) == set(read_csv("roads").road_id)
    assert not plan.road_id.duplicated().any()


def test_methods_are_on_rate_card(plan):
    methods = set(read_csv("rate_card").repair_method)
    used = set(plan.loc[plan.action == "Repair", "recommended_method"])
    assert used <= methods
