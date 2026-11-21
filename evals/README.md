# Evals

Four layers, cheapest first. Layer 1 lives in `tests/`; the rest live here.

| Layer | What | Cost | Command |
|---|---|---|---|
| 1 | Pipeline regression, planted anomalies, extraction/LLM-wrapper/harness unit tests | free | `pytest -q` |
| 2 | Complaint extraction (M1) vs ground truth | free (`rules`) / paid (`app`, `claude`) | `python -m evals.run_eval --suite extraction --target rules` |
| 3 | Claude-written text (scorecards, ward summaries, flag reasons) | free (`rules`) / paid (`app`, `--judge`) | `python -m evals.run_eval --suite narrative --target rules` |
| 4 | Does the road risk ranking predict later trouble? | free | `python -m evals.backtest_risk` |

On Windows, set `PYTHONIOENCODING=utf-8` first (the cases contain Devanagari). `.env` is loaded automatically.

## Targets

| Target | What runs | Cost | Output |
|---|---|---|---|
| `oracle` | returns the truth / a known-good text | free | must be 100%. Harness check |
| `null` | returns nothing | free | must be 0%. Harness check |
| `citizen` | (extraction) trusts what the citizen typed | free | the bar to beat |
| `template` | (narrative) the eval's own fill-in-the-blanks text | free | 100% on programmatic checks |
| `rules` | **the real app code with Claude switched off** (`LLM_DISABLE=1`) | free | what the deterministic part achieves |
| `app` | the real app code with Claude on | paid, gated | `.claude/hillclimb/<suite>/<variant>/` |
| `claude` | (extraction) Claude forced for **every** case, rules bypassed | paid, gated | `.claude/hillclimb/extraction-claude-only/<variant>/` |

The gap between `rules` and `app` is what Claude adds. `claude` is an ablation: how good is Claude on its own, and does it over-trust unreliable text?

**Suites:**
- `extraction` has 150 answerable complaints. It's a regression check.
- `extraction_routed` has the 21 linked complaints the app actually sends to Claude. This is where Claude's category contribution shows.
- `narrative` has 29 facts packets for M2's text.

Each suite has its own approval (`.claude/hillclimb/<suite>/_state.json`). Free targets always run from scratch.

## Where the ground truth comes from

All of it is derived from `data/` by `python -m evals.build_cases`, which is deterministic:

- **category**: `work_type` of the work order the complaint is linked to. Citizens picked a different category for 16.5% of linked complaints.
- **severity 1–5**: the work order's `sla_hours` (24 → 5, 48 → 4, 72 → 3, 120 → 2, 168 → 1). Within a category this is noise. A cross-validated model on 30 features (time, rain, tides, ward, hotspot distance, road traffic, even work-order cost and method) scores worse than a per-category lookup. So even a perfect category scores at most about **47% exact / 89% within one** overall.
  - `severity =` and `severity ±1` are capped by the data. The runner prints the ceiling for the set next to them (150-case set: 44.7% / 94.7%).
  - **`severity best`** is what the extractor controls. It passes when the answer is the exact truth or the best possible guess for the true category (`expected.severity_best`, derived from linked complaints outside the eval set). It should be 100%.
- **ward**: the work order's ward. It matches 100% of complaints that have a ward, and 30 test cases have a blank ward.
- **language is an input, not scored.** 1916-helpline rows are English operator notes even when the caller spoke Marathi or Hindi (740 linked rows), so the label can't be recovered from the text.
- `complaints_sample_200.csv` is kept **out** of the test set. Use it for prompt development.

### What the data says about evidence (measured on the linked complaints)

- **Photo description:** 12 fixed templates, each maps to exactly one category (100% pure).
- **English text and helpline notes:** a single keyword match is right 100% of the time on linked complaints, even when the citizen picked the wrong category.
- **Hindi / Marathi / Hinglish text from the app or portal:** statistically independent of the true category. Every keyword row has the same base-rate mix (about 44% pothole, 25% waterlogging, …). This is an artefact of the synthetic data.
- **Citizen-selected category:** right 84% of the time.
- **Junk / non-road complaints:** 120 complaints ("Test", "asdfgh", "Street light not working", "Garbage not collected") have English text with no road keyword and no photo. M1 labels them "Not road-related" (Claude agreed on all 120) and keeps them out of issues and M3's demand.
- **Recompute all of these:** `python -m evals.measure_routing` (free). It prints the figures quoted in `pipeline/connect/extract.py`.

### Answerability guard

A case is kept in the main suite only if at least one **reliable** input points to its truth label: a photo template, English or helpline text, or the citizen category (87 of 4,787 candidates have none). Contradictory cases are **kept**. For example, Hindi text that says "manhole" when the citizen and the truth both say pothole catches a system that over-trusts unreliable text. Each case records its supporting evidence in `meta.support` and in the REVIEW table.

**What this guard means (from the independent review):**
- **The main suite is a regression check, not a headroom measure.** The guard uses the same three evidence sources as M1's router, and in this data those sources are never wrong when present. So M1's rules score 100% on the kept cases by construction. The suite answers "does extraction still get every answerable complaint right?"
- **The dropped rows aren't "constant error".** They're rows where every method is guessing. They're measured separately: the linked rows the app sends to Claude make up `extraction_routed`, and `measure_routing` reports rules against the base rate on all held-out rows.

The earlier guard dropped any case whose text contradicted the truth (521 candidates). That removed exactly those realistic contradictory cases, which made text-reading look better than it is.

### The case sets

- **`extraction` (150):**
  - 15 per language × (citizen right / citizen wrong) cell, plus 30 with a blank ward.
  - Chips: `photo` / `no_photo`, `helpline`, `noisy_text` (non-English app/portal text), `blank_ward`.
- **`extraction_routed` (21):** every linked complaint for which M1's `route()` returns `claude`.
  - All 21 are Hindi, Marathi or Hinglish app text, with a vague citizen category and no photo, so there's no reliable evidence.
  - Free baselines: rules fallback 28.6%, citizen 0%.
  - The paid `app` run here shows whether Claude beats the fallback on its real traffic.
  - Defined with M1's own router, so rebuild the cases if the routing rules change.

**Where Claude adds value:**
- **On category:** only `extraction_routed`, plus the 120 non-road complaints (which have no work order, so no category truth).
- **English summaries:** these graders don't score them.
- **Head to head:** the `claude` ablation compares Claude with the router on the main suite. Earlier result: Claude alone was 93.4%, and all of its misses were on unreliable non-English text.

## What the app must expose (contract)

See [targets.py](targets.py).

```python
pipeline.connect.extract.extract_complaint(record: dict, force_claude=False) -> dict  # M1
pipeline.audit.explain.contractor_scorecard_text(facts: dict) -> str                 # M2
pipeline.audit.explain.ward_summary_text(facts: dict) -> str                         # M2
pipeline.audit.explain.flag_explanation(facts: dict) -> str                          # M2
pipeline.risk.run(data_dir, out_dir)  -> writes road_risk.parquet                    # M3 (backtest)
pipeline.common.llm.reset_last_meta() / get_last_meta()                              # M1 wrapper
```

`get_last_meta()` returns `{model, usage, stop_reason, cache, error}` for the current thread's last Claude call. The runner resets it before each case and reads it after. So it records tokens and the model that actually answered. If the app fell back because the Claude call **failed**, the case goes to `errors.jsonl` as `serving_error` instead of being scored as a model answer. For narrative cases it also records whether the final text was M2's template (Claude's text rejected or unavailable).

## Self-checks (free, no Claude)

```bash
python -m evals.run_eval --suite extraction --target oracle    # must be 100%
python -m evals.run_eval --suite extraction --target null      # must be 0%
python -m evals.run_eval --suite extraction --target citizen   # the bar: 57.3% category on this set
python -m evals.run_eval --suite extraction_routed --target rules   # fallback on Claude's real traffic: 28.6%
python -m evals.run_eval --suite extraction --target rules     # M1 without Claude: category 100%, severity best 100%
python -m evals.run_eval --suite narrative  --target template  # 100% on programmatic checks
python -m evals.run_eval --suite narrative  --target rules     # M2's templates through the graders
python -m evals.backtest_risk --target naive                    # baseline the risk model must beat
```

If oracle, null or template move, the harness is broken. Fix that before trusting a real run.

## Running against the real app

1. **Review the cases** in [cases/REVIEW.md](cases/REVIEW.md), then approve the harness. Approval is a human step: it records a hash of the runner, graders, targets and cases, with line endings normalised so it survives a checkout on another OS. The runner refuses paid runs if any of them change afterwards. **The cases and runner changed on 21 Nov, so approve again.**
   ```bash
   python -m evals.run_eval --suite extraction --target app --approve-harness --limit 10
   ```
2. **Pilot on 10 cases**, read a few files in `.claude/hillclimb/extraction/baseline/traces/`, then run the full set and the Claude-only ablation:
   ```bash
   python -m evals.run_eval --suite extraction --target app
   python -m evals.run_eval --suite extraction --target claude
   ```
3. **To compare a prompt change**, run it as a new variant:
   ```bash
   python -m evals.run_eval --suite extraction --target app --variant v1
   ```

Output per run: `results.jsonl` (one row per case with grade, explanation, model, usage, evidence source), `traces/`, `errors.jsonl` (timeouts, failed Claude calls, model mismatches, all kept out of the scores), `summary.json` and `run_info.json`.

- **Resuming:** paid runs resume where they stopped. A run directory refuses to resume if the eval files, the app code (`pipeline/connect`, `pipeline/common`, M2's `explain.py` and `config.py`) or the `--judge` setting changed. It says which one changed. Use a new `--variant`, or move the old folder into `_archive/`. Free targets never resume; they always re-run, so an app-code change shows up immediately.
- **Response cache:** the app's Claude responses are cached in `.claude/hillclimb/<suite>/_llm_cache/` (git-ignored, separate from the demo cache in `outputs/llm_cache/`). Re-runs of unchanged prompts are free.
  - `--fresh` skips cache reads (`LLM_CACHE_READ=0`), so every call and every rep is a new sample.
  - Answers served by the fallback model are never cached.
- **Refusals:** in the `claude` ablation a refusal goes to `errors.jsonl` (`refusal`), because the app's fallback answer isn't Claude's. In `app` runs the end-to-end answer is scored, and the refusal count is printed.
- **The judge is gated:** `--judge` needs the approved harness, even on free targets, because the judge itself is paid.
- **Judge:** `--judge` (narrative only) adds a `claude-sonnet-5-5` grader for fair / evidence / actionable / plain. The app runs on `claude-opus-5-5`, so it never grades its own output.

## Thresholds to keep in sync

`tests/planted.py` and `tests/test_audit.py` mirror the blueprint: OVERBILL above 1.30× the rate card, DOUBLE_BILL within 7 days with no linked complaint, and the expected counts 114 / 45 / 493 / 1259 / 611. If M2 changes a rule on purpose, update these in the same PR.
