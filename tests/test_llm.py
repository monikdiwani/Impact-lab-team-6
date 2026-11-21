"""pipeline.common.llm: disable switch, cache, per-thread meta, error recording.
Uses a fake client, so no network and no cost."""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from pipeline.common import llm


class _Usage:
    def model_dump(self):
        return {"input_tokens": 10, "output_tokens": 5}


def _msg(text, stop="end_turn", model="claude-opus-5-5"):
    return SimpleNamespace(model=model, stop_reason=stop, usage=_Usage(),
                           content=[SimpleNamespace(type="text", text=text)])


class FakeClient:
    def __init__(self, result):
        self.result, self.calls = result, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_DISABLE", raising=False)
    monkeypatch.delenv("LLM_OFFLINE", raising=False)
    monkeypatch.delenv("LLM_CACHE_READ", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))

    def use(result):
        fake = FakeClient(result)
        monkeypatch.setattr(llm, "_client", fake)
        return fake
    return use


def test_disable_switch_returns_fallback_without_calling(env, monkeypatch):
    fake = env(_msg("hi"))
    monkeypatch.setenv("LLM_DISABLE", "1")
    llm.reset_last_meta()
    assert llm.ask("p", system="s", fallback="FB") == "FB"
    assert fake.calls == [] and llm.get_last_meta() == {"disabled": True}


def test_success_records_meta_and_caches(env, tmp_path):
    fake = env(_msg('{"a": 1}'))
    llm.reset_last_meta()
    assert llm.ask("p", system="s", schema={"type": "object"}, fallback=None) == {"a": 1}
    m = llm.get_last_meta()
    assert m["model"] == "claude-opus-5-5" and m["usage"]["output_tokens"] == 5 and m["cache"] is False
    assert fake.calls[0]["fallbacks"] == "default" and fake.calls[0]["betas"] == [llm.FALLBACK_BETA]
    # second call: cache hit, no API call, no usage billed
    llm.reset_last_meta()
    assert llm.ask("p", system="s", schema={"type": "object"}, fallback=None) == {"a": 1}
    assert len(fake.calls) == 1 and llm.get_last_meta()["cache"] is True
    entry = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert entry["model"] == "claude-opus-5-5"


def test_api_error_is_recorded_not_silent(env):
    env(RuntimeError("boom"))
    llm.reset_last_meta()
    assert llm.ask("p", system="s", fallback="FB") == "FB"
    assert "RuntimeError: boom" in llm.get_last_meta()["error"]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_bad_stop_reason_falls_back_and_is_not_cached(env, tmp_path, stop):
    env(_msg("partial", stop=stop))
    llm.reset_last_meta()
    assert llm.ask("p", system="s", fallback="FB") == "FB"
    assert llm.get_last_meta()["stop_reason"] == stop
    assert not list(tmp_path.glob("*.json"))


def test_bad_json_is_recorded(env):
    env(_msg("not json"))
    llm.reset_last_meta()
    assert llm.ask("p", system="s", schema={"type": "object"}, fallback=None) is None
    assert "bad JSON" in llm.get_last_meta()["error"]


def test_no_key_is_recorded(env, monkeypatch):
    env(_msg("x"))
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    llm.reset_last_meta()
    assert llm.ask("p", system="s", fallback="FB") == "FB"
    assert llm.get_last_meta() == {"error": "no_api_key"}


def test_meta_is_per_thread(env):
    env(_msg("x"))
    llm.reset_last_meta()
    llm.ask("p", system="s")
    seen = {}
    t = threading.Thread(target=lambda: seen.setdefault("other", llm.get_last_meta()))
    t.start()
    t.join()
    assert seen["other"] is None and llm.get_last_meta() is not None


def test_offline_uses_cache_but_never_calls(env, monkeypatch):
    fake = env(_msg('"cached text"'))
    assert llm.ask("p", system="s", fallback="FB") == '"cached text"'      # warm the cache (1 call)
    monkeypatch.setenv("LLM_OFFLINE", "1")
    assert llm.ask("p", system="s", fallback="FB") == '"cached text"'      # cache hit, no call
    assert llm.ask("other", system="s", fallback="FB") == "FB"             # miss: fallback, no call
    assert len(fake.calls) == 1 and llm.get_last_meta()["error"] == "offline_cache_miss"


# ---- review fixes ------------------------------------------------------------------------

def _write_entry(tmp_path, prompt, response, model="claude-opus-5-5", system="s", effort="medium", schema=None,
                 raw=None, bom=False):
    p = tmp_path / f"{llm._key(prompt, system, effort, schema)}.json"
    text = raw if raw is not None else json.dumps({"response": response, "model": model, "stop_reason": "end_turn"})
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return p


def test_disable_skips_a_filled_cache(env, tmp_path, monkeypatch):
    fake = env(_msg("x"))
    _write_entry(tmp_path, "p", "CACHED")
    monkeypatch.setenv("LLM_DISABLE", "1")
    llm.reset_last_meta()
    assert llm.ask("p", system="s", fallback="FB") == "FB"
    assert fake.calls == [] and llm.get_last_meta() == {"disabled": True}


@pytest.mark.parametrize("raw", ["[1, 2]", "\"just a string\"", "null", "{\"no_response\": 1}", "not json"])
def test_bad_cache_entry_never_raises(env, tmp_path, raw):
    fake = env(_msg("fresh answer"))
    _write_entry(tmp_path, "p", None, raw=raw)
    llm.reset_last_meta()
    assert llm.ask("p", system="s", fallback="FB") == "fresh answer"      # treated as a miss
    assert len(fake.calls) == 1 and llm.cached("q", system="s") is None


def test_cache_entry_with_bom_is_read(env, tmp_path):
    fake = env(_msg("x"))
    _write_entry(tmp_path, "p", "CACHED", bom=True)
    assert llm.ask("p", system="s", fallback="FB") == "CACHED" and fake.calls == []


def test_answer_from_fallback_model_is_used_but_not_cached(env, tmp_path):
    env(_msg("from fallback", model="claude-opus-4-8"))
    assert llm.ask("p", system="s", fallback="FB") == "from fallback"
    assert not list(tmp_path.glob("*.json"))


def test_cache_read_switch_forces_a_fresh_call(env, tmp_path, monkeypatch):
    fake = env(_msg("new sample"))
    _write_entry(tmp_path, "p", "OLD")
    monkeypatch.setenv("LLM_CACHE_READ", "0")
    assert llm.ask("p", system="s", fallback="FB") == "new sample" and len(fake.calls) == 1
