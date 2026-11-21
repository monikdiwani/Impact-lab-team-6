"""Eval harness safeguards: approval survives line-ending changes, a run directory can't
silently mix eval versions / app versions / judge settings, free targets always re-run,
failed or refused Claude calls never reach the scores, .env loads in any Windows encoding,
and the case sets are well formed."""
from __future__ import annotations

import json
from types import SimpleNamespace

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
    ident = {"harness_sha": "h1", "app_sha": "a1", "judge": False}
    R.check_run_dir(out, ident, "app", wipe_stale=False)
    (out / "results.jsonl").write_text("{}\n", encoding="utf-8")
    R.check_run_dir(out, ident, "app", wipe_stale=False)                       # same: resume OK
    for change in ({"harness_sha": "h2"}, {"app_sha": "a2"}, {"judge": True}):
        with pytest.raises(SystemExit) as e:
            R.check_run_dir(out, {**ident, **change}, "app", wipe_stale=False)
        assert next(iter(change)) in str(e.value)                              # says what changed
    R.check_run_dir(out, {**ident, "harness_sha": "h2"}, "rules", wipe_stale=True)
    assert not (out / "results.jsonl").exists()


@pytest.fixture
def scratch_hc(tmp_path, monkeypatch):
    """Point the runner's results folder at a temp dir (state, approvals and runs)."""
    monkeypatch.setattr(R, "HC", tmp_path / "hc")
    monkeypatch.delenv("LLM_CACHE_READ", raising=False)
    return tmp_path / "hc"


def test_free_targets_rerun_after_app_code_changes(scratch_hc, monkeypatch):
    from pipeline.connect import extract as X
    args = ["--suite", "extraction", "--target", "rules", "--limit", "6"]
    R.main(args)
    first = json.loads((scratch_hc / "_selfcheck" / "extraction-rules" / "summary.json").read_text())
    assert first["metrics"]["category"]["mean"] == 1.0
    real = X.extract_complaint
    monkeypatch.setattr(X, "extract_complaint", lambda rec, **k: {**real(rec, **k), "category_clean": "Pothole"})
    R.main(args)
    second = json.loads((scratch_hc / "_selfcheck" / "extraction-rules" / "summary.json").read_text())
    assert second["n_scored"] == 6 and second["metrics"]["category"]["mean"] < 1.0, "old results were replayed"


def test_failed_claude_call_goes_to_errors_through_the_real_meta_path(tmp_path, monkeypatch):
    """No mocking of the per-thread meta: the app really calls llm.ask, the API really fails."""
    from pipeline.common import llm

    class RateLimitError(Exception):
        pass

    def boom(**kw):
        raise RateLimitError("slow down")
    monkeypatch.delenv("LLM_DISABLE", raising=False)
    monkeypatch.delenv("LLM_OFFLINE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(llm, "_client", SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=boom))))
    llm.ask("stale", system="s")   # leaves error meta on THIS thread; the worker must not see it

    case = {"id": "C1", "tags": ["en"], "input": {"x": 1},
            "expected": {"category": "Pothole", "severity": 3, "severity_best": [3], "ward_code": "A"}}
    args = SimpleNamespace(timeout_s=10, expect_model="claude-opus-5-5")
    good = {"category_clean": "Pothole", "severity_1_5": 3, "ward_code": "A"}

    sink = R.Sink(tmp_path / "a")
    R.run_attempt(case, 0, "extraction", "app", lambda c: (llm.ask("p", system="s", fallback=None), good)[1],
                  args, sink, None)
    assert not (tmp_path / "a" / "results.jsonl").exists()
    assert json.loads((tmp_path / "a" / "errors.jsonl").read_text())["failure_class"] == "serving_error"

    sink = R.Sink(tmp_path / "b")                 # no Claude call in the case: it must be scored
    R.run_attempt(case, 0, "extraction", "app", lambda c: good, args, sink, None)
    assert json.loads((tmp_path / "b" / "results.jsonl").read_text())["grade"]["category"] == 1


def test_claude_only_refusal_is_not_scored(tmp_path, monkeypatch):
    monkeypatch.setattr(R.targets, "reset_app_meta", lambda: None)
    monkeypatch.setattr(R.targets, "app_meta", lambda: {"stop_reason": "refusal", "error": "stop_reason=refusal",
                                                         "model": "claude-opus-5-5"})
    case = {"id": "C1", "tags": ["en"], "input": {"x": 1},
            "expected": {"category": "Pothole", "severity": 3, "severity_best": [3], "ward_code": "A"}}
    args = SimpleNamespace(timeout_s=10, expect_model="claude-opus-5-5")
    fallback = {"category_clean": "Pothole", "severity_1_5": 3, "ward_code": "A", "extraction_source": "claude_fallback"}
    R.run_attempt(case, 0, "extraction", "claude", lambda c: fallback, args, R.Sink(tmp_path), None)
    assert not (tmp_path / "results.jsonl").exists()
    assert json.loads((tmp_path / "errors.jsonl").read_text())["failure_class"] == "refusal"


@pytest.mark.parametrize("encoding,prefix", [("utf-8", b""), ("utf-8", b"\xef\xbb\xbf"), ("utf-16", b"")])
def test_env_file_loads_in_windows_encodings(tmp_path, monkeypatch, encoding, prefix):
    monkeypatch.delenv("RUPEE_TEST_KEY", raising=False)
    f = tmp_path / ".env"
    f.write_bytes(prefix + "# comment\nRUPEE_TEST_KEY=abc123\n".encode(encoding))
    R.load_env(f)
    import os
    assert os.environ.get("RUPEE_TEST_KEY") == "abc123"


def test_unreadable_env_file_warns_instead_of_crashing(tmp_path, capsys):
    f = tmp_path / ".env"
    f.write_bytes(b"\x80\x81\xfe not text")
    R.load_env(f)
    assert "could not read" in capsys.readouterr().err


def test_judge_needs_the_approved_harness(scratch_hc):
    with pytest.raises(SystemExit) as e:
        R.main(["--suite", "narrative", "--target", "template", "--judge"])
    assert "approve" in str(e.value)


def test_narrative_claude_is_rejected_before_any_setup(scratch_hc):
    with pytest.raises(SystemExit) as e:
        R.main(["--suite", "narrative", "--target", "claude"])
    assert "extraction" in str(e.value)
    assert not scratch_hc.exists() or not any(scratch_hc.iterdir())


def test_extraction_cases_are_well_formed():
    cases = R.load_cases("extraction")
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert set(c["input"]) == set(INPUT_FIELDS)
        assert c["meta"]["support"], f"{c['id']} has no reliable evidence for its label"
        assert "status" not in c["input"] and "resolved_at" not in c["input"]


def test_routed_suite_is_exactly_what_the_evidence_cannot_decide():
    from pipeline.connect.extract import route
    routed = R.load_cases("extraction_routed")
    assert routed
    main_ids = {c["id"] for c in R.load_cases("extraction")}
    for c in routed:
        i = c["input"]
        assert route(i["description"], i["photo_description"], i["category_reported"],
                     i["language"], i["channel"])[1] in ("claude", "no_evidence"), c["id"]
        assert c["meta"]["support"] == [], c["id"]
        assert c["id"] not in main_ids


def test_severity_best_matches_m1_lookup_and_is_independent():
    """build_cases derives the best-possible severity from complaints OUTSIDE the eval
    set; M1's lookup must be one of those values for every category."""
    from pipeline.connect.extract import severity_for
    for suite in ("extraction", "extraction_routed"):
        for c in R.load_cases(suite):
            best = c["expected"]["severity_best"]
            assert best and all(1 <= v <= 5 for v in best), c["id"]
            assert severity_for(c["expected"]["category"]) in best, c["id"]


def test_summary_never_counts_missing_metrics_as_zero(tmp_path):
    out = tmp_path / "v1"
    out.mkdir()
    rows = [{"prompt_id": f"c{i}", "rep": 0, "status": "ok", "tags": ["x"], "meta": {},
             "grade": {"passes_all": 1, **({"judge_fair": 1} if i == 0 else {})}} for i in range(3)]
    (out / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    s = R.summarize(out, [{"id": "passes_all", "label": "passes all"}, {"id": "judge_fair", "label": "judge"}])
    assert s["metrics"]["judge_fair"] == {"mean": 1.0, "ci95": list(R.wilson(1, 1)), "n": 1}
