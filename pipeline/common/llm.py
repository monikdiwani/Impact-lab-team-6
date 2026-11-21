"""Cached Claude wrapper (owner: M1). Never raises; returns `fallback` on any failure.

Every response is cached to outputs/llm_cache/<sha256>.json so the demo needs no
network. With no ANTHROPIC_API_KEY, only cache hits or the fallback are returned.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

MODEL = "claude-opus-5-5"
CACHE_DIR = Path(os.environ.get("LLM_CACHE_DIR",
                                Path(__file__).resolve().parents[2] / "outputs" / "llm_cache"))
_client = None


def _key(prompt, system, effort, schema) -> str:
    blob = json.dumps([MODEL, system, prompt, effort, schema], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cached(prompt: str, *, system: str, effort: str = "medium", schema: dict | None = None):
    """Return the cached response or None (no network)."""
    p = CACHE_DIR / f"{_key(prompt, system, effort, schema)}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))["response"]
        except Exception:
            return None
    return None


def ask(prompt: str, *, system: str, effort: str = "medium", schema: dict | None = None,
        fallback: str | dict = "") -> str | dict:
    global _client
    hit = cached(prompt, system=system, effort=effort, schema=schema)
    if hit is not None:
        return hit
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback
    try:
        if _client is None:
            import anthropic
            _client = anthropic.Anthropic()
        cfg: dict = {"effort": effort}
        if schema:
            cfg["format"] = {"type": "json_schema", "schema": schema}
        msg = _client.messages.create(
            model=MODEL, max_tokens=4096, system=system,
            messages=[{"role": "user", "content": prompt}], output_config=cfg)
        if getattr(msg, "stop_reason", None) == "refusal":
            return fallback
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        resp = json.loads(text) if schema else text
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{_key(prompt, system, effort, schema)}.json").write_text(
            json.dumps({"response": resp}, ensure_ascii=False), encoding="utf-8")
        return resp
    except Exception:
        return fallback
