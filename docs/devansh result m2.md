# Devansh: M2 test and eval results

Run on 2026-11-21, branch `feat/m2-audit`, Python 3.11.9 in `.venv`. Commands come from `sanjay command.md` (M2 section). The results below are exactly what the tools printed. No test, threshold or expected count was changed to make anything pass.

## Summary

| Step | Command | Result | Verdict |
|---|---|---|---|
| Test 1 | `pytest tests/test_audit.py -q` | 17 passed | PASS |
| Test 2 | `pytest tests/test_audit.py -k planted -q` | 3 passed, 14 deselected | PASS |
| Test 3 | `pytest tests/test_eval_graders.py -q` | 10 passed | PASS |
| Eval 1a | `run_eval --suite narrative --target template` | passes all 100% | PASS (harness self-check) |
| Eval 1b | `run_eval --suite narrative --target null` | passes all 0% | PASS (harness self-check, 0% is the expected result) |
| Eval 2 | `run_eval --suite narrative --target app --approve-harness --limit 5` | NOT RUN | Human approval step, and no API key set |
| Eval 3 | `run_eval --suite narrative --target app` | BLOCKED: "no approved harness" | Not scored officially (see the unofficial check below) |
| Eval 4 | `run_eval --suite narrative --target app --judge` | NOT RUN | Paid, needs `ANTHROPIC_API_KEY` and Eval 2 first |

## Tests (free)

### `pytest tests/test_audit.py -q`
```
17 passed in 3.68s
```
What this confirms:
- Flag counts on real data: OVERBILL 114, DOUBLE_BILL 45, DLP_PAID 493, SLA_MISS 1259, REPEAT_REPAIR 611. All match.
- All 3 output files match the contract in `contracts/schemas.py`.
- Flag IDs are unique, and every flag has evidence text.
- Every DOUBLE_BILL points at an earlier work order.
- No accusing words in the explanations.
- 8 contractors and 24 wards scored, and ward billed totals add up to ₹13,43,28,183.
- Deccan (score 84.1) outranks Western Coast (40.9).

### `pytest tests/test_audit.py -k planted -q`
```
3 passed, 14 deselected in 1.94s
```
All 10 planted over-bills, all 10 planted double bills and every work order on the planted warranty road are caught. Note: this filter selects only the 3 "caught" tests. The 3 near-miss control tests (`test_near_miss_controls_are_not_flagged`) do not contain the word "planted", so they ran in Test 1, where they passed, not here.

### `pytest tests/test_eval_graders.py -q`
```
10 passed in 0.05s
```
The graders still reject bad text. These tests don't touch M2 code. They check the eval harness itself.

## Eval (narrative suite, 29 cases)

### 1a. `--target template` (harness self-check)
```
passes all       100.0%   (95% CI 88–100, n=29)
numbers OK       100.0%
IDs valid        100.0%
word limit       100.0%
no accusation    100.0%
context          100.0%
non-empty        100.0%
```
Expected 100%. Got 100%. Harness OK.

### 1b. `--target null` (harness self-check)
```
passes all         0.0%   (95% CI 0–12, n=29)
numbers OK       100.0%
IDs valid        100.0%
word limit         0.0%
no accusation    100.0%
context           86.2%
non-empty          0.0%
```
Expected 0% passes all. Got 0%. Harness OK. Empty text trivially "passes" numbers, IDs, accusation and the cases with no required context, which is why those columns are not 0.

### 2. `--target app --approve-harness --limit 5`: NOT RUN
- Approving the harness is a human step (project CLAUDE.md), so it was not run on my behalf.
- `ANTHROPIC_API_KEY` is not set in this shell.

### 3. `--target app`: BLOCKED
Actual output:
```
no approved harness (sha e55dbfb98489 over evals/run_eval.py, evals/graders.py, evals/targets.py, evals/cases/narrative.jsonl).
A human should review the eval files, then re-run once with --approve-harness.
```
No official score yet.

**Unofficial check (not the official eval):** I called the same grader (`evals.graders.grade_narrative`) directly on the M2 functions resolved through `evals.targets.resolve("narrative", "app")`:

| Metric | Result |
|---|---|
| passes all | 29 / 29 |
| numbers OK | 29 / 29 |
| IDs valid | 29 / 29 |
| word limit | 29 / 29 |
| no accusation | 29 / 29 |
| context (low-lying and over-budget cases) | 29 / 29 |
| non-empty | 29 / 29 |

Important caveat: M1's Claude wrapper `pipeline/common/llm.py` does not exist yet, so the M2 functions returned their **template** text, not Claude text. This result shows that the templates (the offline fallback) are correct. It says nothing yet about Claude's own output.

### 4. `--target app --judge`: NOT RUN
This step is paid, needs `ANTHROPIC_API_KEY`, and needs Eval 2 done first. The judge's four columns (fair / evidence / actionable / plain) have no result yet.

## Correct vs not yet verified

**Verified correct**
- All 5 audit rules and their counts.
- Planted anomalies caught, and near-miss controls not flagged.
- Contract columns, evidence on every flag, neutral wording.
- Contractor and ward scorecards.
- Template text passes every programmatic narrative check.

**Not yet verified**
- The official narrative eval score (needs harness approval).
- Claude-written text (needs M1's `llm.py` and an API key).
- Judge scores for fair / evidence / actionable / plain (paid).

## To finish the remaining steps

1. Review `evals/cases/REVIEW.md`.
2. Set your API key for this terminal: `$env:ANTHROPIC_API_KEY = "sk-..."`
3. Wait until M1's `pipeline/common/llm.py` is on `dev`, then run `git pull origin dev`.
4. Run the pilot and approve the harness: `python -m evals.run_eval --suite narrative --target app --approve-harness --limit 5`
5. Run the full set: `python -m evals.run_eval --suite narrative --target app`
6. Run with the judge: `python -m evals.run_eval --suite narrative --target app --judge`

## Notebook check of the output files (`pipeline/audit/m2_output_checks.ipynb`)

Run on 2026-11-21. The notebook recomputes every column of `audit_flags.parquet`, `contractor_scorecard.parquet`, `ward_scorecard.parquet` and `scorecard_text.json` from the raw CSVs, independently of the pipeline.

**Result: 101 PASS, 1 FAIL out of 102 checks.**

| Section | Result |
|---|---|
| Files exist, contract columns and types | all pass |
| `audit_flags` integrity and counts (114 / 45 / 493 / 1259 / 611) | all pass |
| OVERBILL, DOUBLE_BILL, DLP_PAID recomputed from raw data | all pass |
| SLA_MISS | 1 FAIL (below) |
| REPEAT_REPAIR follow-up WO and ₹ | all pass |
| Evidence and explanation text | all pass |
| Contractor scorecard (every column recomputed) | all pass |
| Ward scorecard (every column recomputed) | all pass |
| `scorecard_text.json` | all pass |

**The 1 failure:** `WO25-00541` finished exactly at its 24 h deadline (0 h late by the recompute), but the source data marks it `sla_met = N`, so M2 flags it as SLA_MISS. This is the 1 boundary case the blueprint (§2, A4) mentions, and the blueprint decides to trust the `sla_met` column. M2 follows the blueprint. The check is left failing on purpose rather than loosened.

A first run showed a second failure (109 REPEAT_REPAIR mismatches). That was a bug in the notebook itself: it compared a missing value (`NaN`) with `None`. It was fixed in the notebook. No M2 code or output changed.
