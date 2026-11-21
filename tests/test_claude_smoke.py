"""The real-Claude smoke test's logic, checked with a fake client (no network, no cost)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from evals import claude_smoke as S
from evals.run_eval import CASES
from pipeline.common import llm


class _Usage:
    def model_dump(self):
        return {"input_tokens": 100, "output_tokens": 20}


def _reply(text, model="claude-opus-5-5"):
    return SimpleNamespace(model=model, stop_reason="end_turn", usage=_Usage(),
                           content=[SimpleNamespace(type="text", text=text)])


def _fake_create(**kw):
    prompt = kw["messages"][0]["content"]
    if "Street light" in prompt:
        return _reply(json.dumps({"category": "Not road-related", "english_summary": "A street light is out.",
                                  "evidence": "text"}))
    if "pothole" in prompt.lower() and "Photo description" in prompt:
        return _reply(json.dumps({"category": "Pothole", "english_summary": "A large pothole.", "evidence": "photo"}))
    case = next(c for c in map(json.loads, open(CASES / "narrative.jsonl", encoding="utf-8"))
                if c["kind"] == "contractor")
    f = case["facts"]
    return _reply(f"{f['contractor_name']} did {f['n_jobs']} jobs. Start by checking "
                  f"{f['example_work_orders'][0]['work_order_id']}.")


@pytest.fixture
def live(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr(S, "load_env", lambda: None)
    for k in ("LLM_CACHE_READ", "LLM_CACHE_DIR", "LLM_DISABLE", "LLM_OFFLINE"):
        monkeypatch.setenv(k, "x")            # registers each so monkeypatch restores it afterwards
        monkeypatch.delenv(k)
    def use(create):
        monkeypatch.setattr(llm, "_client", SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create))))
    return use


def test_smoke_passes_when_claude_answers(live):
    live(_fake_create)
    assert S.main() == 0


def test_smoke_fails_with_the_api_reason(live, capsys):
    def no_credit(**kw):
        raise RuntimeError("Error code: 400 - Your credit balance is too low to access the Anthropic API.")
    live(no_credit)
    assert S.main() == 1
    assert "credit balance" in capsys.readouterr().err


def test_smoke_rejects_a_wrong_answer(live):
    def wrong(**kw):
        return _reply(json.dumps({"category": "Pothole", "english_summary": "x", "evidence": "text"}))
    live(wrong)
    assert S.main() == 1
