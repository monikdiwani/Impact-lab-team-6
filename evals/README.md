# Evals

Four layers, cheapest first. Layer 1 lives in `tests/`; the rest live here.

| Layer | What | Cost | Command |
|---|---|---|---|
| 1 | Pipeline regression + planted anomalies + grader sanity | free | `pytest -q` |
| 2 | Complaint extraction (M1's Claude call) vs ground truth | paid | `python -m evals.run_eval --suite extraction` |
| 3 | Claude-written text (scorecards, ward summaries, flag reasons) | free checks, paid judge | `python -m evals.run_eval --suite narrative [--judge]` |
| 4 | Does the road risk ranking predict later trouble? | free | `python -m evals.backtest_risk` |

On Windows, set `PYTHONIOENCODING=utf-8` first (the cases contain Devanagari).

## Where the ground truth comes from

All of it is derived from `data/` by `python -m evals.build_cases`, which is deterministic:

- **category**: `work_type` of the work order the complaint is linked to. Citizens picked a different category for 16.5% of linked complaints.
- **severity 1–5**: the work order's `sla_hours` (24 → 5, 48 → 4, 72 → 3, 120 → 2, 168 → 1).
- **ward**: the work order's ward. It matches 100% of complaints that have a ward, and 30 test cases have a blank ward.
- **language**: the `language` column.
- **Label guard**: candidates whose description *and* photo text contradict the work order (521 of 4,787) are left out, so the model isn't marked wrong for reading the text correctly.
- `complaints_sample_200.csv` is kept **out** of the test set. Use it for prompt development.

The extraction set is deliberately enriched with the hard cases: 65 of 150 have a wrong citizen category, and 30 have a blank ward. Report `cat_wrong` and blank-ward scores separately. They're the "Claude fixed what the citizen got wrong" number for the demo.

## What the app must expose (contract)

See [targets.py](targets.py). Until these exist, `--target app` exits with a clear message.

```python
pipeline.connect.extract.extract_complaint(record: dict) -> dict      # M1
pipeline.audit.explain.contractor_scorecard_text(facts: dict) -> str  # M2
pipeline.audit.explain.ward_summary_text(facts: dict) -> str          # M2
pipeline.audit.explain.flag_explanation(facts: dict) -> str           # M2
pipeline.risk.run(data_dir, out_dir)  -> writes road_risk.parquet     # M3 (backtest)
```

Optional but recommended: give `pipeline/common/llm.py` a `get_last_meta()` that returns `{"model", "usage", "stop_reason"}` for the current thread's last call. The runner then records tokens, truncation and the model that actually answered for every case.

## Self-checks (free, no Claude)

```bash
python -m evals.run_eval --suite extraction --target oracle    # must be 100%
python -m evals.run_eval --suite extraction --target null      # must be 0%
python -m evals.run_eval --suite extraction --target citizen   # the bar: 56.7% category on this set
python -m evals.run_eval --suite narrative  --target template  # 100% on programmatic checks
python -m evals.backtest_risk --target naive                    # baseline the risk model must beat
```

If any of these move, the harness is broken. Fix that before trusting a real run.

## Running against the real app

1. **Review the cases once** in [cases/REVIEW.md](cases/REVIEW.md), then approve the harness. Approval is a human step: it records a hash of the runner, graders and cases, and the runner refuses to score the app if any of them change afterwards.
   ```bash
   python -m evals.run_eval --suite extraction --target app --approve-harness --limit 10
   ```
2. **Pilot on 10 cases**, read a few files in `.claude/hillclimb/extraction/baseline/traces/`, then run the full set.
3. **To compare a prompt change**, run it as a new variant, then compare the summaries:
   ```bash
   python -m evals.run_eval --suite extraction --target app --variant v1
   ```

Output per run: `results.jsonl` (one row per case with grade, explanation, model, usage), `traces/`, `errors.jsonl` (timeouts, API errors, model mismatches, kept out of the scores) and `summary.json`. Runs resume where they stopped.

The `--judge` flag (narrative only) adds a `claude-sonnet-5-5` grader for fair / evidence / actionable / plain. The app runs on `claude-opus-5-5`, so it never grades its own output.

## Thresholds to keep in sync

`tests/planted.py` and `tests/test_audit.py` mirror the blueprint: OVERBILL above 1.30× the rate card, DOUBLE_BILL within 7 days with no linked complaint, and the expected counts 114 / 45 / 493 / 1259 / 611. If M2 changes a rule on purpose, update these in the same PR.
