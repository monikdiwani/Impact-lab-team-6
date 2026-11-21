"""M1 regression tests. Skips until pipeline.connect.run exists."""
from __future__ import annotations

from itertools import combinations

import pandas as pd
import pytest

from contracts.schemas import validate
from tests.conftest import read_output

MIN_WARD_COVERAGE = 0.98
MIN_DEDUP_F1 = 0.60     # raise as M1 improves; report the actual number on the dashboard


@pytest.fixture(scope="module")
def clean(connect_out):
    return read_output(connect_out, "complaints_clean")


def test_outputs_match_contract(connect_out):
    for name in ("complaints_clean", "wo_trail", "open_issues"):
        assert validate(read_output(connect_out, name), name) == []


def test_no_complaints_lost(clean, complaints):
    assert set(clean.complaint_id) == set(complaints.complaint_id)
    assert clean.complaint_id.is_unique


def test_ward_recovery_coverage(clean):
    cov = clean.ward_code.notna().mean()
    assert cov >= MIN_WARD_COVERAGE, f"ward coverage {cov:.1%}"


def test_recovered_wards_are_correct(clean, work_orders):
    """On complaints whose ward was blank, the recovered ward must match the ward
    of the work order that fixed them (ground truth: 342 such complaints)."""
    links = (work_orders.dropna(subset=["linked_complaint_ids"])
             .assign(complaint_id=lambda d: d.linked_complaint_ids.str.split("|"))
             .explode("complaint_id")[["complaint_id", "ward_code"]])
    m = clean.merge(links, on="complaint_id", suffixes=("", "_truth"))
    recovered = m[m.ward_source != "given"]
    assert len(recovered) > 0
    acc = (recovered.ward_code == recovered.ward_code_truth).mean()
    assert acc >= 0.90, f"recovered-ward accuracy {acc:.1%} on {len(recovered)} rows"


def test_links_preserved(clean, work_orders):
    links = (work_orders.dropna(subset=["linked_complaint_ids"])
             .assign(complaint_id=lambda d: d.linked_complaint_ids.str.split("|"))
             .explode("complaint_id").set_index("complaint_id").work_order_id)
    got = clean.set_index("complaint_id").linked_work_order_id.reindex(links.index)
    assert (got == links).mean() == 1.0


def _pairs(groups: pd.Series) -> set[tuple[str, str]]:
    out = set()
    for _, ids in groups.groupby(groups):
        out.update(combinations(sorted(ids.index), 2))
    return out


def test_dedup_against_ground_truth(clean):
    """Complaints linked to the same work order are the same issue. Pairwise
    precision/recall of issue_id clustering against that truth."""
    linked = clean.dropna(subset=["linked_work_order_id"]).set_index("complaint_id")
    truth = _pairs(linked.linked_work_order_id)
    pred = _pairs(linked.issue_id.dropna())
    tp = len(truth & pred)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if tp else 0.0
    print(f"\ndedup pairwise precision={precision:.3f} recall={recall:.3f} f1={f1:.3f}")
    assert f1 >= MIN_DEDUP_F1


def test_open_issues(connect_out, complaints):
    oi = read_output(connect_out, "open_issues")
    n_open = complaints.status.isin(["Open", "In Progress"]).sum()   # 896
    assert 0 < len(oi) <= n_open
    assert oi.issue_id.is_unique
    assert oi.road_id.notna().mean() >= 0.9, "M3 needs a road_id on open issues"
    assert oi.severity_1_5.between(1, 5).all()
