"""Facts about the dataset that the whole team's design relies on.

These pass today, with no pipeline code. If one fails, the data changed under us
and the blueprint's expected counts need rechecking before anything else.
"""
import numpy as np
import pandas as pd

from tests.conftest import read_csv


def test_every_repair_method_is_on_the_rate_card(work_orders):
    rc = read_csv("rate_card")
    assert set(work_orders.repair_method) <= set(rc.repair_method)
    assert set(rc.unit) == {"per sqm", "per job"}


def test_linked_complaints_all_exist_and_are_unique(work_orders, complaints):
    ids = work_orders.linked_complaint_ids.dropna().str.split("|").explode()
    assert ids.is_unique
    assert ids.isin(complaints.complaint_id).all()


def test_unlinked_work_order_count(work_orders):
    assert work_orders.linked_complaint_ids.isna().sum() == 45


def test_dlp_roads(work_orders):
    roads = read_csv("roads")
    assert (roads.under_dlp == "Y").sum() == 61
    on_dlp = work_orders.road_id.isin(roads.loc[roads.under_dlp == "Y", "road_id"])
    assert on_dlp.sum() == 493


def test_cost_ratio_band(work_orders):
    rc = read_csv("rate_card")
    m = work_orders.merge(rc, on="repair_method")
    expected = np.where(m.unit == "per sqm", m.area_sqm * m.standard_rate_inr, m.standard_rate_inr)
    ratio = m.cost_inr / expected
    assert ratio.min() >= 0.70, "normal jobs are documented as ±20-30% around the rate"
    assert (ratio > 1.30).sum() == 114


def test_sla_hours_map_to_severity(work_orders):
    # evals/ uses this mapping as ground-truth severity
    assert set(work_orders.sla_hours) == {24, 48, 72, 120, 168}


def test_complaint_ward_matches_linked_work_order(work_orders, complaints):
    links = (work_orders.dropna(subset=["linked_complaint_ids"])
             .assign(cid=lambda d: d.linked_complaint_ids.str.split("|")).explode("cid"))
    m = links.merge(complaints, left_on="cid", right_on="complaint_id", suffixes=("_wo", "_c"))
    has = m.ward_code_c.notna()
    assert (m.ward_code_c[has] == m.ward_code_wo[has]).all()


def test_every_contractor_works_in_every_ward(work_orders):
    # the fairness argument in the scorecards depends on this
    per = work_orders.groupby("contractor_id").ward_code.nunique()
    assert (per == 24).all()


def test_timestamps_parse(work_orders, complaints):
    for col in ("assigned_at", "work_started_at", "completed_at"):
        pd.to_datetime(work_orders[col])
    pd.to_datetime(complaints.received_at)
