"""Eval harness safeguards: approval survives line-ending changes, a run directory can't
silently mix eval versions, failed Claude calls never reach the scores, case integrity."""
from __future__ import annotations

import json

import pytest

from evals import run_eval as R
from evals.build_cases import INPUT_FIELDS


def test_harness_sha_ignores_line_endings(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    (tmp_path / "a.py").write_bytes(b"x = 1\ny = 2\n")
    lf = R.harness_sha(["a.py"])
    (tmp_path / "a.py").write_bytes(b"x = 1\r\ny = 2\r\n")
    assert R.harness_sha(["a.py"]) == lf
    (tmp_path / "a.py").write_bytes(b"x = 1\ny = 3\n")
    assert R.harness_sha(["a.py"]) != lf


def test_run_dir_refuses_to_mix_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    out = tmp_path / "baseline"
    R.check_run_dir(out, "sha1", "app", wipe_stale=False)
    (out / "results.jsonl").write_text("{}\n", encoding="utf-8")
    R.check_run_dir(out, "sha1", "app", wipe_stale=False)            # same version: resume OK
    with pytest.raises(SystemExit):
        R.check_run_dir(out, "sha2", "app", wipe_stale=False)        # changed eval: refuse
    R.check_run_dir(out, "sha2", "rules", wipe_stale=True)           # free targets: start over
    assert not (out / "results.jsonl").exists()


def test_failed_claude_call_goes_to_errors_not_scores(tmp_path, monkeypatch):
    sink = R.Sink(tmp_path)
    case = {"id": "C1", "tags": ["en"], "input": {"x": 1},
            "expected": {"category": "Pothole", "severity": 3, "ward_code": "A"}}
    monkeypatch.setattr(R.targets, "reset_app_meta", lambda: None)
    monkeypatch.setattr(R.targets, "app_meta", lambda: {"error": "RateLimitError: slow down", "model": None})
    args = type("A", (), {"timeout_s": 10, "expect_model": "claude-opus-5-5"})()
    fn = lambda c: {"category_clean": "Pothole", "severity_1_5": 3, "ward_code": "A"}  # noqa: E731
    R.run_attempt(case, 0, "extraction", "app", fn, args, sink, None)
    assert not (tmp_path / "results.jsonl").exists()
    err = json.loads((tmp_path / "errors.jsonl").read_text(encoding="utf-8"))
    assert err["failure_class"] == "serving_error"


def test_extraction_cases_are_well_formed():
    cases = R.load_cases("extraction")
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert set(c["input"]) == set(INPUT_FIELDS)
        assert c["meta"]["support"], f"{c['id']} has no reliable evidence for its label"
        assert "status" not in c["input"] and "resolved_at" not in c["input"]
    assert sum("ambiguous" in c["tags"] for c in cases) >= 10


def test_severity_best_matches_m1_lookup_and_is_independent():
    """build_cases derives the best-possible severity from complaints OUTSIDE the eval
    set; M1's lookup must be one of those values for every category."""
    from pipeline.connect.extract import severity_for
    cases = R.load_cases("extraction")
    for c in cases:
        best = c["expected"]["severity_best"]
        assert best and all(1 <= v <= 5 for v in best), c["id"]
        assert severity_for(c["expected"]["category"]) in best, c["id"]
