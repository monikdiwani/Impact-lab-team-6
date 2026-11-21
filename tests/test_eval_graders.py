"""The eval graders must reject known-bad outputs. If a grader passes garbage, every
eval number built on it is meaningless, so these run with the free Layer-1 suite."""
import pytest

from evals.graders import grade_extraction, grade_narrative

CASE = {
    "kind": "contractor",
    "facts": {"contractor_name": "Sahyadri Infra Works (synthetic)", "n_jobs": 337, "billed_inr": 17209448,
              "sla_met_pct": 62.3, "reopened_pct": 13.6,
              "example_work_orders": [{"work_order_id": "WO25-00611", "ratio": 2.28}],
              "definitions": {"reopen_window_days": 30}},
    "checks": {"word_limit": 40, "must_mention": None},
}
GOOD = ("Sahyadri did 337 jobs worth ₹1.72 crore. 62% were on time and 13.6% re-opened within "
        "30 days. One bill (WO25-00611) was 2.28x the rate card and needs review.")


def g(text, case=CASE):
    return grade_narrative(text, case)[0]


def test_good_text_passes():
    assert g(GOOD)["passes_all"] == 1, grade_narrative(GOOD, CASE)[1]


@pytest.mark.parametrize("bad,metric", [
    (GOOD.replace("₹1.72 crore", "₹17.2 lakh"), "numbers_grounded"),       # wrong unit conversion
    (GOOD.replace("13.6%", "31%"), "numbers_grounded"),                    # invented number
    (GOOD.replace("WO25-00611", "WO25-09999"), "ids_valid"),               # invented work order
    (GOOD + " This looks like fraud.", "no_accusation"),
    (GOOD + " Corruption is likely.", "no_accusation"),
    (GOOD + " word" * 40, "within_limit"),
    ("", "nonempty"),
])
def test_bad_text_fails(bad, metric):
    grade = g(bad)
    assert grade[metric] == 0
    assert grade["passes_all"] == 0


def test_required_context_enforced():
    case = {**CASE, "checks": {"word_limit": 60, "must_mention": r"low[- ]lying|flood"}}
    assert g(GOOD, case)["context"] == 0
    assert g(GOOD + " The ward is low-lying.", case)["context"] == 1


def test_extraction_grader():
    exp = {"category": "Pothole", "severity": 4, "ward_code": "F/S", "language": "mr"}
    perfect = {"category_clean": "Pothole", "severity_1_5": 4, "ward_code": "F/S", "language": "mr"}
    assert all(grade_extraction(perfect, exp)[0].values())
    off_by_one = {**perfect, "severity_1_5": 5}
    gr = grade_extraction(off_by_one, exp)[0]
    assert gr["severity_within1"] == 1 and gr["severity_exact"] == 0
    assert grade_extraction({**perfect, "category_clean": "Potholes"}, exp)[0]["valid_output"] == 0
    assert not any(grade_extraction("I don't know", exp)[0].values())


def test_severity_best_credits_the_best_possible_guess():
    """Severity truth is noise within a category, so the grader also credits the best
    possible answer for the true category (expected['severity_best'])."""
    exp = {"category": "Pothole", "severity": 2, "severity_best": [3], "ward_code": "A"}
    base = {"category_clean": "Pothole", "ward_code": "A"}
    g = grade_extraction({**base, "severity_1_5": 3}, exp)[0]       # best guess, not exact
    assert g["severity_best"] == 1 and g["severity_exact"] == 0
    g = grade_extraction({**base, "severity_1_5": 2}, exp)[0]       # exact truth
    assert g["severity_best"] == 1 and g["severity_exact"] == 1
    g = grade_extraction({**base, "severity_1_5": 5}, exp)[0]       # neither
    assert g["severity_best"] == 0
    tie = {**exp, "category": "Choked drain / nullah overflow", "severity": 2, "severity_best": [3, 4]}
    assert grade_extraction({**base, "severity_1_5": 4}, tie)[0]["severity_best"] == 1
    assert grade_extraction({**base, "severity_1_5": None}, exp)[0]["severity_best"] == 0
