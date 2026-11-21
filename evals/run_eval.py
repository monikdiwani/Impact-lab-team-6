"""Eval runner.

  python -m evals.run_eval --suite extraction --target citizen      # free: the bar to beat
  python -m evals.run_eval --suite extraction --target oracle       # free: harness check, ~100%
  python -m evals.run_eval --suite extraction --target rules        # free: app code, Claude off
  python -m evals.run_eval --suite extraction --target app --limit 10   # paid pilot
  python -m evals.run_eval --suite narrative --target app --judge   # paid, adds LLM judge

Results for --target app go to .claude/hillclimb/<suite>/<variant>/ (results.jsonl,
traces/, errors.jsonl) in the layout the hillclimb report builder reads. Other targets
write to .claude/hillclimb/_selfcheck/ instead so they never mix with real variants.

Properties: rows written as each case finishes; resume keyed on (case, rep), and a run
directory refuses to resume under different eval files (run_info.json); hard per-case
wall-clock ceiling; jittered backoff on rate limits with retry counts recorded; failed
attempts (timeouts, harness errors, failed Claude calls the app fell back from) go to
errors.jsonl with a failure class, never into results.jsonl; served-model check;
harness-integrity gate for --target app, hashed with line endings normalised so the
approval survives a checkout on another OS. App Claude responses are cached under
.claude/hillclimb/<suite>/_llm_cache (not the demo cache); --fresh bypasses it.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import math
import os
import random
import re
import shutil
import sys
import tempfile
import threading
import time
from collections import defaultdict
from pathlib import Path

from evals import graders, targets

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).resolve().parent / "cases"
HC = ROOT / ".claude" / "hillclimb"
RETRYABLE = ("RateLimit", "Overloaded", "InternalServer", "APIConnection", "APITimeout", "ServiceUnavailable")
MAX_RETRIES = 4


# ---- env -----------------------------------------------------------------------------

def load_env(path: Path = ROOT / ".env") -> None:
    """Load KEY=VALUE lines from .env into os.environ without overriding variables
    already set in the shell, and without needing python-dotenv. Empty values skipped."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip().removeprefix("export ").strip(), val.strip().strip("\"'")
        if key and val:
            os.environ.setdefault(key, val)


load_env()


# ---- io ------------------------------------------------------------------------------

def load_cases(suite: str) -> list[dict]:
    with open(CASES / f"{suite}.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def safe_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)


class Sink:
    def __init__(self, out: Path):
        self.out = out
        (out / "traces").mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def done(self) -> set[tuple[str, int]]:
        p = self.out / "results.jsonl"
        if not p.exists():
            return set()
        with open(p, encoding="utf-8") as f:
            return {(r["prompt_id"], r["rep"]) for r in map(json.loads, f) if r}

    def _append(self, name, obj):
        with self.lock, open(self.out / name, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")

    def result(self, row, trace):
        (self.out / "traces" / f"{safe_id(row['prompt_id'])}_rep{row['rep']}.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        self._append("results.jsonl", row)

    def error(self, obj):
        self._append("errors.jsonl", obj)


# ---- harness gate ----------------------------------------------------------------------

def file_digest(p: Path) -> bytes:
    """File bytes with CRLF normalised to LF: git's autocrlf rewrites line endings per OS,
    and an approval must not break just because a teammate checked out on Windows."""
    return p.read_bytes().replace(b"\r\n", b"\n") if p.exists() else b"<missing>"


def harness_sha(paths: list[str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(set(paths)):
        h.update(rel.encode())
        h.update(file_digest(ROOT / rel))
    return h.hexdigest()


def check_run_dir(out: Path, sha: str, target: str, wipe_stale: bool) -> None:
    """A run directory belongs to one version of the eval files. Resuming into it with a
    different version would mix rows graded under different rules."""
    info_p = out / "run_info.json"
    info = json.loads(info_p.read_text(encoding="utf-8")) if info_p.exists() else None
    has_rows = (out / "results.jsonl").exists() or (out / "errors.jsonl").exists()
    if info and info.get("harness_sha") == sha:
        return
    if has_rows:
        if not wipe_stale:
            why = "was made with different eval files" if info else "has no run_info.json (made before it existed)"
            sys.exit(f"{out.relative_to(ROOT)} {why}.\nUse a new --variant (v1, v2, ...) or move that folder "
                     f"away (e.g. into .claude/hillclimb/<suite>/_archive/) before running.")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    info_p.write_text(json.dumps({"harness_sha": sha, "target": target}, indent=1), encoding="utf-8")


def gate(state_path: Path, state: dict, approve: bool):
    sha = harness_sha(state["harness_paths"])
    if state.get("harness_sha") == sha:
        return
    if approve:
        state["harness_sha"] = sha
        state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
        print(f"harness approved: sha256 {sha[:12]} over {len(state['harness_paths'])} files", file=sys.stderr)
        return
    what = "no approved harness" if not state.get("harness_sha") else "harness changed since approval"
    sys.exit(f"{what} (sha {sha[:12]} over {', '.join(state['harness_paths'])}).\n"
             "A human should review the eval files, then re-run once with --approve-harness.")


def ensure_state(suite: str, judge: bool) -> tuple[Path, dict]:
    d = HC / suite
    d.mkdir(parents=True, exist_ok=True)
    p = d / "_state.json"
    state = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    metrics = graders.EXTRACTION_METRICS if suite == "extraction" else graders.NARRATIVE_METRICS
    if judge:
        metrics = metrics + graders.JUDGE_METRICS
    state["metrics"] = metrics
    state.setdefault("perf_fields", [{"id": "latency_s", "label": "latency", "unit": "s"},
                                     {"id": "cost_usd", "label": "cost", "unit": "$"}])
    state.setdefault("harness_paths", ["evals/run_eval.py", "evals/graders.py", "evals/targets.py",
                                       f"evals/cases/{suite}.jsonl"])
    p.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return p, state


# ---- one attempt ---------------------------------------------------------------------------

def call_with_retries(fn, timeout_s):
    """Run fn() under a hard wall-clock ceiling; retry retryable errors with jitter.
    Returns (value, retries). Raises TimeoutError or the last exception."""
    retries = 0
    deadline = time.monotonic() + timeout_s if timeout_s else None
    while True:
        ex = cf.ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(fn)
        try:
            left = None if deadline is None else max(0.1, deadline - time.monotonic())
            return fut.result(timeout=left), retries
        except cf.TimeoutError:
            raise TimeoutError(f"case exceeded {timeout_s}s wall clock") from None
        except Exception as e:  # noqa: BLE001 - classified below
            if retries < MAX_RETRIES and any(k in type(e).__name__ for k in RETRYABLE):
                retries += 1
                sleep = min(30, 2 ** retries) * (0.5 + random.random())
                if deadline and time.monotonic() + sleep > deadline:
                    raise TimeoutError(f"case exceeded {timeout_s}s wall clock during backoff") from e
                time.sleep(sleep)
                continue
            raise
        finally:
            ex.shutdown(wait=False)


def run_attempt(case, rep, suite, target, fn, args, sink, judge_client):
    paid = target in ("app", "claude")
    prompt = case["input"] if suite == "extraction" else case["facts"]
    base = {"prompt_id": case["id"], "rep": rep, "target": target}
    t0 = time.monotonic()

    def invoke():
        if paid:
            targets.reset_app_meta()       # meta is per-thread; this runs in the worker thread
        out = fn(case)
        return out, (targets.app_meta() if paid else None)

    try:
        (output, meta), retries = call_with_retries(invoke, args.timeout_s)
    except TimeoutError as e:
        sink.error({**base, "failure_class": "timeout", "detail": str(e)})
        return
    except Exception as e:  # noqa: BLE001
        cls = "serving_error" if any(k in type(e).__name__ for k in RETRYABLE) else "harness_error"
        sink.error({**base, "failure_class": cls, "detail": f"{type(e).__name__}: {e}"[:500]})
        return
    latency = round(time.monotonic() - t0, 3)
    meta = meta or {}
    served = meta.get("model")
    err = meta.get("error")
    stop = meta.get("stop_reason")
    if err and stop not in ("refusal", "max_tokens"):
        # the app called Claude, the call failed, and the app returned its fallback: that is
        # an infrastructure failure, not the model's answer, so it must not be scored
        sink.error({**base, "failure_class": "serving_error", "detail": f"app fell back: {err}"[:500],
                    "model": served, "usage": meta.get("usage")})
        return
    if paid and served and args.expect_model and not str(served).startswith(args.expect_model):
        sink.error({**base, "failure_class": "model_mismatch", "detail": f"served {served}, expected {args.expect_model}",
                    "model": served, "usage": meta.get("usage")})
        return

    if suite == "extraction":
        grade, expl = graders.grade_extraction(output, case["expected"])
    else:
        grade, expl = graders.grade_narrative(output, case)
    extra = {}
    if judge_client is not None:
        try:
            (jg, je, jm), jr = call_with_retries(lambda: graders.judge_narrative(output or "", case, judge_client),
                                                 args.timeout_s)
            grade.update(jg)
            expl.update(je)
            extra = {**jm, "judge_retries": jr}
        except Exception as e:  # noqa: BLE001
            sink.error({**base, "failure_class": "grader_error", "detail": f"{type(e).__name__}: {e}"[:500]})
            return

    row = {
        "prompt_id": case["id"], "rep": rep, "prompt": json.dumps(prompt, ensure_ascii=False),
        "tags": case["tags"], "stop_reason": stop,
        "status": "truncated" if stop == "max_tokens" else "ok",
        "grade": grade, "explanation": expl, "latency_s": latency,
        "model": served, "usage": meta.get("usage"),
        "meta": {"target": target, "retries": retries, "output": output,
                 "expected": case.get("expected"), "failure_class": "refusal" if stop == "refusal" else None,
                 "llm_called": bool(meta) and not meta.get("disabled"), "llm_cache_hit": meta.get("cache"),
                 "used_template": (output == targets.template_for(case))
                 if paid and suite == "narrative" else None,
                 **extra},
    }
    if extra.get("judge_model"):
        row["judge_model"], row["judge_usage"] = extra["judge_model"], extra.get("judge_usage")
    trace = [{"role": "system", "content": f"target={target} suite={suite}"},
             {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, indent=1)},
             {"role": "assistant", "content": output if isinstance(output, str)
              else json.dumps(output, ensure_ascii=False, indent=1)}]
    sink.result(row, trace)


# ---- summary -----------------------------------------------------------------------------

def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def summarize(out: Path, metrics: list[dict]) -> dict:
    p = out / "results.jsonl"
    rows = [json.loads(line) for line in open(p, encoding="utf-8")] if p.exists() else []
    ok = [r for r in rows if r["status"] == "ok"]
    errs = sum(1 for _ in open(out / "errors.jsonl", encoding="utf-8")) if (out / "errors.jsonl").exists() else 0
    trunc = len(rows) - len(ok)
    print(f"\n{out.relative_to(ROOT)}  —  {len(ok)} scored, {trunc} truncated, {errs} failed attempts")
    summary = {"n_scored": len(ok), "n_truncated": trunc, "n_errors": errs, "metrics": {}, "by_tag": {}}
    for m in metrics:
        vals = [r["grade"].get(m["id"], 0) for r in ok]
        k, n = sum(vals), len(vals)
        lo, hi = wilson(k, n)
        summary["metrics"][m["id"]] = {"mean": k / n if n else None, "ci95": [lo, hi], "n": n}
        if n:
            print(f"  {m['label']:<15} {100 * k / n:6.1f}%   (95% CI {100 * lo:.0f}–{100 * hi:.0f}, n={n})")
    head = metrics[0]["id"]
    by = defaultdict(list)
    for r in ok:
        for t in r["tags"]:
            by[t].append(r["grade"].get(head, 0))
    if by:
        print(f"  {head} by tag: " + "  ".join(f"{t} {100 * sum(v) / len(v):.0f}% (n={len(v)})"
                                               for t, v in sorted(by.items())))
    summary["by_tag"] = {t: sum(v) / len(v) for t, v in by.items()}
    by_src = defaultdict(list)
    for r in ok:
        out_ = r["meta"].get("output")
        if isinstance(out_, dict) and out_.get("extraction_source"):
            by_src[out_["extraction_source"]].append(r["grade"].get(head, 0))
    if by_src:
        print(f"  {head} by evidence source: " + "  ".join(
            f"{s} {100 * sum(v) / len(v):.0f}% (n={len(v)})" for s, v in sorted(by_src.items())))
        summary["by_source"] = {s: {"mean": sum(v) / len(v), "n": len(v)} for s, v in by_src.items()}
    tmpl = [r for r in ok if r["meta"].get("used_template") is not None]
    if tmpl:
        n_t = sum(1 for r in tmpl if r["meta"]["used_template"])
        print(f"  final text was M2's template (Claude's text rejected or unavailable): {n_t} of {len(tmpl)}")
        summary["used_template"] = n_t
    calls = [r for r in ok if r["meta"].get("llm_called")]
    if calls:
        hits = sum(1 for r in calls if r["meta"].get("llm_cache_hit"))
        print(f"  Claude calls: {len(calls)} of {len(ok)} cases ({hits} served from the eval cache)")
    if any("ward" == m["id"] for m in metrics):
        bw = [r["grade"]["ward"] for r in ok if "blank_ward" in r["tags"]]
        if bw:
            print(f"  ward recovery on blank-ward cases: {100 * sum(bw) / len(bw):.0f}% (n={len(bw)})")
            summary["ward_recovery_blank"] = sum(bw) / len(bw)
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


# ---- main ----------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", required=True, choices=["extraction", "narrative"])
    ap.add_argument("--target", default="app",
                    choices=["app", "claude", "rules", "oracle", "null", "citizen", "template"])
    ap.add_argument("--variant", default="baseline", help="baseline | v1 | v2 … (only for --target app)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--timeout-s", type=float, default=180, help="per-case wall clock ceiling; 0 = none")
    ap.add_argument("--limit", type=int, default=0, help="first N cases only (pilot)")
    ap.add_argument("--judge", action="store_true", help="narrative only: add the LLM judge (paid)")
    ap.add_argument("--expect-model", default="claude-opus-5-5")
    ap.add_argument("--fresh", action="store_true",
                    help="app only: bypass the eval's Claude response cache (needed for --reps > 1 to mean anything)")
    ap.add_argument("--approve-harness", action="store_true", help="human-only: record the reviewed harness sha")
    args = ap.parse_args(argv)

    paid = args.target in ("app", "claude")
    if not paid and args.variant != "baseline":
        sys.exit("--variant only applies to --target app / claude")
    if not re.fullmatch(r"baseline|v\d+", args.variant):
        sys.exit("--variant must be 'baseline' or v<N> (the report builder ignores other names)")
    if args.judge and args.suite != "narrative":
        sys.exit("--judge only applies to --suite narrative")

    state_path, state = ensure_state(args.suite, args.judge)
    if paid:
        gate(state_path, state, args.approve_harness)
        flow = HC / (args.suite if args.target == "app" else f"{args.suite}-claude-only")
        if flow != HC / args.suite:   # the report builder needs metrics next to the variants
            flow.mkdir(parents=True, exist_ok=True)
            (flow / "_state.json").write_text(json.dumps({"metrics": state["metrics"],
                                                          "perf_fields": state["perf_fields"]}, indent=1),
                                              encoding="utf-8")
        out = flow / args.variant
    else:
        out = HC / "_selfcheck" / f"{args.suite}-{args.target}"
    check_run_dir(out, harness_sha(state["harness_paths"]), args.target, wipe_stale=not paid)

    # The app reads these when it first calls Claude, so set them before resolving it.
    if args.target == "rules":
        os.environ["LLM_DISABLE"] = "1"
    elif paid:
        os.environ.pop("LLM_DISABLE", None)
        os.environ["LLM_CACHE_DIR"] = (tempfile.mkdtemp(prefix="eval-llm-") if args.fresh
                                       else str(HC / args.suite / "_llm_cache"))
        if args.reps > 1 and not args.fresh:
            print("note: --reps > 1 without --fresh replays cached answers, so reps will be identical")

    cases = load_cases(args.suite)
    if args.limit:
        cases = cases[: args.limit]
    try:
        fn = targets.resolve(args.suite, args.target)
    except (ImportError, AttributeError) as e:
        sys.exit(f"target '{args.target}' needs app code that is not implemented yet: {e}\n"
                 "See evals/targets.py for the contract.")

    if (paid or args.judge) and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Put it in .env (copy .env.example) or export it in your shell.")
    judge_client = None
    if args.judge:
        import anthropic
        judge_client = anthropic.Anthropic()

    sink = Sink(out)
    done = sink.done()
    todo = [(c, r) for c in cases for r in range(args.reps) if (c["id"], r) not in done]
    print(f"{args.suite}/{args.target}: {len(todo)} attempts to run ({len(done)} already done) -> {out.relative_to(ROOT)}")
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(run_attempt, c, r, args.suite, args.target, fn, args, sink, judge_client) for c, r in todo]
        for i, f in enumerate(cf.as_completed(futs), 1):
            f.result()
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}")
    summarize(out, state["metrics"])


if __name__ == "__main__":
    main()
