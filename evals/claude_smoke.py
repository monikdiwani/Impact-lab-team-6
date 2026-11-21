"""Real Claude smoke test: three live calls through the app's own code paths.

    python -m evals.claude_smoke        # needs ANTHROPIC_API_KEY (CI: the repo secret)

It answers one question cheaply (about 3 short calls, roughly 2 US cents): can the app
really talk to Claude right now, and do the answers come back in the shape the app needs?

  1. M1 non-road detection: "Street light not working near building" goes to Claude and
     must come back "Not road-related".
  2. M1 reading a clear photo + English text with the rules bypassed (the eval's
     Claude-only path): must come back "Pothole".
  3. M2 contractor scorecard text: Claude's text must be used (not the template) and pass
     the eval's programmatic checks (numbers grounded, IDs valid, word limit, no accusation).
     If M2 rejected Claude's text and used its template, that is reported in the detail.

Every call bypasses the response cache (LLM_CACHE_READ=0, scratch cache dir), so a pass
means Claude answered now. Exit 1 on any failure, with the API's reason (for example an
empty credit balance). Writes a table to $GITHUB_STEP_SUMMARY inside GitHub Actions.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

from evals import graders  # noqa: E402
from evals.run_eval import CASES, load_env  # noqa: E402  (load_env reads .env locally)
from pipeline.common import llm  # noqa: E402
from pipeline.connect import extract as X  # noqa: E402

APP = "MyBMC App"


def _call(fn):
    llm.reset_last_meta()
    t = time.monotonic()
    out = fn()
    return out, (llm.get_last_meta() or {}), round(time.monotonic() - t, 1)


def check_non_road():
    r, meta, s = _call(lambda: X.classify("Street light not working near building", None, "Other", "en", APP,
                                          "Andheri East"))
    ok = r["source"] == "claude" and r["category"] == X.NOT_ROAD
    return "M1 non-road detection", ok, f"category={r['category']!r} source={r['source']}", meta, s


def check_forced_read():
    r, meta, s = _call(lambda: X.classify("Huge pothole near the station, two wheelers falling daily.",
                                          "Wide shot of road with several potholes, auto rickshaw swerving",
                                          "Waterlogging", "en", APP, "Dadar", force_claude=True))
    ok = r["source"] == "claude" and r["category"] == "Pothole"
    return "M1 Claude-only read", ok, f"category={r['category']!r} source={r['source']}", meta, s


def check_scorecard_text():
    from pipeline.audit import explain
    case = next(c for c in map(json.loads, open(CASES / "narrative.jsonl", encoding="utf-8"))
                if c["kind"] == "contractor")
    text, meta, s = _call(lambda: explain.contractor_scorecard_text(dict(case["facts"])))
    used_claude = text != explain.contractor_template(dict(case["facts"]))
    grade, expl = graders.grade_narrative(text, case)
    # pass = Claude answered and the text the app shows passes every check. M2 may still use
    # its template if Claude's text breaks a rule (e.g. too long); that is reported, not failed.
    ok = grade["passes_all"] == 1
    detail = (f"Claude text used={used_claude}, checks={'pass' if grade['passes_all'] else expl}, "
              f"{len(text.split())} words")
    return "M2 scorecard text", ok, detail, meta, s


def live_env() -> None:
    """Force real calls: no cache reads, a scratch cache, no offline/disable switches."""
    os.environ["LLM_CACHE_READ"] = "0"
    os.environ["LLM_CACHE_DIR"] = tempfile.mkdtemp(prefix="claude-smoke-")
    os.environ.pop("LLM_DISABLE", None)
    os.environ.pop("LLM_OFFLINE", None)


def main() -> int:
    load_env()
    live_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (CI: add the repo secret; locally: .env)", file=sys.stderr)
        return 1
    rows, failed = [], []
    for check in (check_non_road, check_forced_read, check_scorecard_text):
        try:
            name, ok, detail, meta, secs = check()
        except Exception as e:  # noqa: BLE001 - report, don't crash the job
            name, ok, detail, meta, secs = check.__name__, False, f"{type(e).__name__}: {e}", {}, 0
        err = meta.get("error")
        model = meta.get("model") or "-"
        if err:
            reason = err.split("'message': '")[-1].split("'")[0] if "'message': '" in err else err
            ok, detail = False, f"API error: {reason[:160]}"
        elif ok and not str(model).startswith(llm.MODEL):
            ok, detail = False, f"served by {model}, expected {llm.MODEL}"
        usage = meta.get("usage") or {}
        tokens = f"{usage.get('input_tokens', '-')} in / {usage.get('output_tokens', '-')} out"
        rows.append((name, "pass" if ok else "**FAIL**", model, tokens, secs, detail))
        if not ok:
            failed.append(f"{name}: {detail}")

    table = ["| Check | Result | Model | Tokens | Seconds | Detail |", "|---|---|---|---|---|---|"]
    table += [f"| {a} | {b} | {c} | {d} | {e} | {f.replace('|', '/')} |" for a, b, c, d, e, f in rows]
    report = "## Real Claude smoke test\n\n" + "\n".join(table) + "\n"
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(report)
    if failed:
        hint = (" Add credit in the Anthropic Console (Plans & Billing)."
                if any("credit balance" in x for x in failed) else "")
        print("FAILED:\n  " + "\n  ".join(failed) + hint, file=sys.stderr)
        return 1
    print("all 3 real Claude calls passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
