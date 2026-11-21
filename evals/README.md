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

## Where the ground truth comes from

All of it is derived from `data/` by `python -m evals.build_cases`, which is deterministic:

- **category**: `work_type` of the work order the complaint is linked to. Citizens picked a different category for 16.5% of linked complaints.
- **severity 1–5**: the work order's `sla_hours` (24 → 5, 48 → 4, 72 → 3, 120 → 2, 168 → 1). Within a category this is noise: no word, photo, road type, area or upvote count predicts it. So even a perfect category scores at most about **47% exact / 89% within one**. Read severity numbers against that ceiling, not against 100%.
- **ward**: the work order's ward. It matches 100% of complaints that have a ward, and 30 test cases have a blank ward.
- **language is an input, not scored.** 1916-helpline rows are English operator notes even when the caller spoke Marathi or Hindi (740 linked rows), so the label can't be recovered from the text.
- `complaints_sample_200.csv` is kept **out** of the test set. Use it for prompt development.

### What the data says about evidence (measured on the linked complaints)

- **Photo description:** 12 fixed templates, each maps to exactly one category (100% pure).
- **English text and helpline notes:** the keywords are right 90–98% of the time, even when the citizen picked the wrong category.
- **Hindi / Marathi / Hinglish text from the app or portal:** statistically independent of the true category. Every keyword row has the same base-rate mix (about 44% pothole, 25% waterlogging, …). This is an artefact of the synthetic data.
- **Citizen-selected category:** right 84% of the time.

### Answerability guard

A case is kept only if at least one **reliable** input points to its truth label: a photo template, English or helpline text, or the citizen category. Cases with no such evidence (87 of 4,787 candidates) are unanswerable by any system, so they're dropped. Contradictory cases are **kept**. For example, Hindi text that says "manhole" when the citizen and the truth both say pothole: these separate good systems from ones that over-trust the text. Each case records its supporting evidence in `meta.support` and in the REVIEW table.

The earlier guard dropped any case whose text contradicted the truth (521 candidates). That removed exactly those realistic contradictory cases, which made text-reading look better than it is.

### The case set (166)

- **15 per language × (citizen right / citizen wrong) cell:** 120 cases.
- **30 with a blank ward.**
- **An `ambiguous` slice of 24:** no photo, plus a vague citizen category or reliable text naming zero or several categories. This is the only slice where a reader can add anything over fixed rules, and in `app` the cases that reach Claude come from here.
- **Chips on each case:** `photo` / `no_photo`, `helpline`, `noisy_text` (non-English app/portal text), `blank_ward`, `ambiguous`.

**Honest limit:** on answerable complaints, M1's rules already score 100% on this set (98.3% across all 4,798 linked complaints outside it). Claude's measurable job on category is the ambiguous slice. Its other job is English summaries, which these graders don't score. Most complaints that actually reach Claude in the pipeline are open ones with no work order yet, so they have no ground truth.

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
python -m evals.run_eval --suite extraction --target citizen   # the bar: 54.8% category on this set
python -m evals.run_eval --suite extraction --target rules     # M1 without Claude
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

- **Resuming:** runs resume where they stopped. A run directory refuses to resume under different eval files: use a new `--variant`, or move the old folder into `_archive/`.
- **Response cache:** the app's Claude responses are cached in `.claude/hillclimb/<suite>/_llm_cache/` (git-ignored, separate from the demo cache in `outputs/llm_cache/`). Re-runs of unchanged prompts are free. `--fresh` bypasses the cache, which `--reps > 1` needs to mean anything.
- **Judge:** `--judge` (narrative only) adds a `claude-sonnet-5-5` grader for fair / evidence / actionable / plain. The app runs on `claude-opus-5-5`, so it never grades its own output.

## Thresholds to keep in sync

`tests/planted.py` and `tests/test_audit.py` mirror the blueprint: OVERBILL above 1.30× the rate card, DOUBLE_BILL within 7 days with no linked complaint, and the expected counts 114 / 45 / 493 / 1259 / 611. If M2 changes a rule on purpose, update these in the same PR.
