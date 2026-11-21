"""Cached Claude wrapper (owner: M1). `ask()` never raises; returns `fallback` on failure.

Every response is cached to outputs/llm_cache/<sha256>.json (override with LLM_CACHE_DIR)
so the demo needs no network.
  LLM_OFFLINE=1   cached answers only, never a new API call (misses get the fallback). Used by
                  `python -m pipeline --no-llm`, so an offline re-run keeps the cached Claude texts.
  LLM_DISABLE=1   no Claude at all, cache included: a clean rules-only run (tests, eval `rules`).
  no API key      behaves like LLM_OFFLINE.

Failures are not silent: get_last_meta() returns what happened on this thread's last
call (model, usage, stop_reason, cache hit, error), so the eval runner can tell a real
Claude answer from a fallback and record tokens. Call reset_last_meta() before a unit of
work if you need to know whether it called Claude at all.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

MODEL = "claude-opus-5-5"
MAX_TOKENS = 4096
FALLBACK_BETA = "server-side-fallback-2026-07-01"   # re-runs a refused request on a fallback model
_client = None
_client_lock = threading.Lock()
_local = threading.local()


def _cache_dir() -> Path:
    # read per call so a caller (e.g. the eval runner) can redirect it after import
    return Path(os.environ.get("LLM_CACHE_DIR")
                or Path(__file__).resolve().parents[2] / "outputs" / "llm_cache")


def _key(prompt, system, effort, schema) -> str:
    blob = json.dumps([MODEL, system, prompt, effort, schema], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _set_meta(**meta) -> None:
    _local.meta = meta


def get_last_meta() -> dict | None:
    """Meta for this thread's most recent ask() call, or None if none since reset."""
    return getattr(_local, "meta", None)


def reset_last_meta() -> None:
    _local.meta = None


def cached(prompt: str, *, system: str, effort: str = "medium", schema: dict | None = None):
    """Return the cached response or None (no network)."""
    p = _cache_dir() / f"{_key(prompt, system, effort, schema)}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))["response"]
        except (OSError, ValueError, KeyError):
            return None
    return None


def _get_client():
    global _client
    with _client_lock:
        if _client is None:
            import anthropic
            _client = anthropic.Anthropic(max_retries=4)   # SDK backs off on 429 / 5xx / overloaded
        return _client


def ask(prompt: str, *, system: str, effort: str = "medium", schema: dict | None = None,
        fallback: str | dict | None = "") -> str | dict | None:
    if os.environ.get("LLM_DISABLE") == "1":
        _set_meta(disabled=True)
        return fallback
    key = _key(prompt, system, effort, schema)
    path = _cache_dir() / f"{key}.json"
    if path.exists():
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            _set_meta(cache=True, model=entry.get("model", MODEL), usage=None,
                      stop_reason=entry.get("stop_reason", "end_turn"))
            return entry["response"]
        except (OSError, ValueError, KeyError):
            pass   # unreadable cache entry: fall through and call the API
    if os.environ.get("LLM_OFFLINE") == "1":
        _set_meta(error="offline_cache_miss")
        return fallback
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _set_meta(error="no_api_key")
        return fallback
    try:
        cfg: dict = {"effort": effort}
        if schema:
            cfg["format"] = {"type": "json_schema", "schema": schema}
        msg = _get_client().beta.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": prompt}], output_config=cfg,
            betas=[FALLBACK_BETA], fallbacks="default")
    except Exception as e:  # noqa: BLE001 - never raise into the app; record it instead
        _set_meta(error=f"{type(e).__name__}: {e}"[:300])
        return fallback
    usage = msg.usage.model_dump() if getattr(msg, "usage", None) is not None else None
    meta = {"cache": False, "model": msg.model, "usage": usage, "stop_reason": msg.stop_reason}
    if msg.stop_reason != "end_turn":   # refusal or max_tokens: don't trust or cache it
        _set_meta(**meta, error=f"stop_reason={msg.stop_reason}")
        return fallback
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    try:
        resp = json.loads(text) if schema else text
    except ValueError as e:
        _set_meta(**meta, error=f"bad JSON: {e}"[:300])
        return fallback
    _set_meta(**meta)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"response": resp, "model": msg.model, "stop_reason": msg.stop_reason},
                                   ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass   # a read-only cache must not break the app
    return resp
