"""M2 regression + planted-anomaly tests. Skips until pipeline.audit.run exists."""
from __future__ import annotations

import pandas as pd
import pytest

from contracts.schemas import FLAG_TYPES, SEVERITIES, validate
from tests.conftest import copy_data, import_module_or_skip, read_output, run_module
from tests.planted import plant

# Counts on the real data (docs/BLUEPRINT.md §2). If a rule change moves one of
# these on purpose, update it here in the same PR and say why.
EXPECTED_COUNTS = {
    "OVERBILL": 114,
    "DOUBLE_BILL": 45,
    "DLP_PAID": 493,
    "SLA_MISS": 1259,
    "REPEAT_REPAIR": 611,
}


@pytest.fixture(scope="module")
def flags(audit_out):
    return read_output(audit_out, "audit_flags")


def test_outputs_match_contract(audit_out):
    for name in ("audit_flags", "contractor_scorecard", "ward_scorecard"):
        assert validate(read_output(audit_out, name), name) == []


@pytest.mark.parametrize("flag_type", FLAG_TYPES)
def test_flag_counts_on_real_data(flags, flag_type):
    got = (flags.flag_type == flag_type).sum()
    assert got == EXPECTED_COUNTS[flag_type], f"{flag_type}: {got} flags, expected {EXPECTED_COUNTS[flag_type]}"


def test_flag_values_are_sane(flags, work_orders):
    assert flags.flag_id.is_unique
    assert set(flags.flag_type) <= set(FLAG_TYPES)
    assert set(flags.severity) <= set(SEVERITIES)
    assert flags.work_order_id.isin(work_orders.work_order_id).all()
    rel = flags.related_work_order_id.dropna()
    assert rel.isin(work_orders.work_order_id).all()
    assert (flags.amount_at_risk_inr >= 0).all()
    assert flags.evidence.fillna("").str.len().gt(0).all(), "every flag needs evidence text"


def test_double_bills_point_at_the_earlier_job(flags):
    db = flags[flags.flag_type == "DOUBLE_BILL"]
    assert db.related_work_order_id.notna().all()


def test_explanations_avoid_accusations(flags):
    banned = r"\b(?:fraud\w*|corrupt\w*|scam\w*|theft|stole|loot\w*|embezzl\w*|kickback\w*)\b"
    bad = flags.explanation.fillna("").str.contains(banned, case=False, regex=True)
    assert not bad.any(), flags.loc[bad, ["flag_id", "explanation"]].head().to_string()


def test_scorecards_cover_everyone(audit_out):
    cs = read_output(audit_out, "contractor_scorecard")
    ws = read_output(audit_out, "ward_scorecard")
    assert len(cs) == 8 and cs.contractor_id.is_unique
    assert len(ws) == 24 and ws.ward_code.is_unique
    assert cs.score_0_100.between(0, 100).all()
    assert ws.billed_inr.sum() == pytest.approx(134_328_183, rel=1e-6)


def test_contractor_ranking_matches_reopen_extremes(audit_out):
    """Deccan (CT with 9% re-opens) must outrank Western Coast (39%)."""
    cs = read_output(audit_out, "contractor_scorecard").set_index("contractor_name")
    deccan = cs.filter(like="Deccan", axis=0).score_0_100.iloc[0]
    western = cs.filter(like="Western Coast", axis=0).score_0_100.iloc[0]
    assert deccan > western


# ---- planted anomalies -------------------------------------------------------

@pytest.fixture(scope="module")
def planted_run(tmp_path_factory):
    import_module_or_skip("pipeline.audit")
    data = copy_data(tmp_path_factory.mktemp("planted") / "data")
    truth = plant(data)
    out = run_module("pipeline.audit", data, data.parent / "out")
    return truth, read_output(out, "audit_flags")


def _ids(flags: pd.DataFrame, flag_type: str) -> set[str]:
    return set(flags.loc[flags.flag_type == flag_type, "work_order_id"])


@pytest.mark.parametrize("flag_type,attr", [
    ("OVERBILL", "overbill"), ("DOUBLE_BILL", "double_bill"), ("DLP_PAID", "dlp_paid"),
])
def test_planted_anomalies_are_caught(planted_run, flag_type, attr):
    truth, flags = planted_run
    planted = set(getattr(truth, attr))
    missed = planted - _ids(flags, flag_type)
    assert not missed, f"{flag_type} missed {len(missed)}/{len(planted)} planted: {sorted(missed)}"


@pytest.mark.parametrize("flag_type,attr", [
    ("OVERBILL", "overbill_controls"), ("DOUBLE_BILL", "double_bill_controls"),
    ("DLP_PAID", "dlp_controls"),
])
def test_near_miss_controls_are_not_flagged(planted_run, flag_type, attr):
    truth, flags = planted_run
    wrong = set(getattr(truth, attr)) & _ids(flags, flag_type)
    assert not wrong, f"{flag_type} false positives on controls: {sorted(wrong)}"
