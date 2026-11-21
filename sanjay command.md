# Sanjay's commands: test + eval for M1, M2, M3

Run everything from the repo root. Details: [evals/README.md](evals/README.md).

## One-time setup

```powershell
pip install -r requirements.txt
$env:PYTHONIOENCODING = "utf-8"          # Devanagari in the cases crashes the console without this
$env:ANTHROPIC_API_KEY = "sk-ant-..."    # only needed for the paid evals (M1, M2)
```

Git Bash equivalent: `export PYTHONIOENCODING=utf-8`

## All three at once

```powershell
pytest -q                # free. Module tests SKIP until that module exists
pytest -q -rs            # same, and lists why each test was skipped
```

A skipped test means the module isn't written yet. A failed test means it's written and wrong.

---

## M1: Connect (complaints)

**Needs:** `pipeline/connect/__init__.py` with `run(data_dir, out_dir)` (tests) and
`pipeline/connect/extract.py` with `extract_complaint(record: dict) -> dict` (eval).

### Test (free)

```powershell
pytest tests/test_connect.py -q -s       # -s prints dedup precision / recall / F1
```

What it checks: no complaints lost, ward coverage ≥ 98%, recovered wards correct (≥ 90% on blank-ward rows), work-order links preserved, de-dup F1 ≥ 0.60 against the real linked groups, open issues have a `road_id`.

### Eval (extraction suite, 150 cases)

```powershell
# 1. free harness self-checks: must give 100% / 0% / 56.7% category
python -m evals.run_eval --suite extraction --target oracle
python -m evals.run_eval --suite extraction --target null
python -m evals.run_eval --suite extraction --target citizen    # the bar Claude must beat

# 2. first paid run: pilot on 10 cases. --approve-harness is YOUR step: review evals/cases/REVIEW.md first
python -m evals.run_eval --suite extraction --target app --approve-harness --limit 10

# 3. full run
python -m evals.run_eval --suite extraction --target app

# 4. after changing the prompt: run it as a new variant, then compare summaries
python -m evals.run_eval --suite extraction --target app --variant v1
```

Numbers to report: **category** (beat 56.7%), **category on `cat_wrong`** (Claude fixing the citizen's mistakes), **ward recovery on blank-ward cases**, severity ±1, and the per-language rows (en / hi-en / mr / hi).

---

## M2: Audit (flags, scorecards, text)

**Needs:** `pipeline/audit/__init__.py` with `run(data_dir, out_dir)` (tests) and
`pipeline/audit/explain.py` with `contractor_scorecard_text`, `ward_summary_text`, `flag_explanation`, each taking a `facts: dict` and returning a `str` (eval). The eval needs all three.

### Test (free)

```powershell
pytest tests/test_audit.py -q                      # counts + planted anomalies
pytest tests/test_audit.py -k planted -q           # only the planted anomaly tests
pytest tests/test_eval_graders.py -q               # the text graders reject bad text (already passing)
```

What it checks: flag counts 114 OVERBILL / 45 DOUBLE_BILL / 493 DLP_PAID / 1259 SLA_MISS / 611 REPEAT_REPAIR; all 10 planted over-bills, double-bills and the planted warranty road are caught; the near-miss controls are **not** flagged; every flag has evidence; no accusing words; 8 contractors and 24 wards scored; Deccan outranks Western Coast.

### Eval (narrative suite, 29 cases)

```powershell
# 1. free harness self-checks
python -m evals.run_eval --suite narrative --target template    # 100% on the programmatic checks
python -m evals.run_eval --suite narrative --target null        # 0%

# 2. first paid run: pilot, then approve
python -m evals.run_eval --suite narrative --target app --approve-harness --limit 5

# 3. full run, free checks only (invented numbers, fake IDs, word limits, banned words, required context)
python -m evals.run_eval --suite narrative --target app

# 4. add the claude-sonnet-5-5 judge (fair / evidence / actionable / plain): paid
python -m evals.run_eval --suite narrative --target app --judge
```

Numbers to report: **passes all**, **numbers OK** (no invented figures), **IDs valid**, **no accusation**, **context** (low-lying and over-budget cases), plus the judge's four columns.

---

## M3: Risk and budget

**Needs:** `pipeline/risk/__init__.py` with `run(data_dir, out_dir)` that writes `road_risk.parquet` (and `budget_plan.parquet`, `ward_risk.parquet` for the tests). Reads `open_issues.parquet` from `out_dir` if M1 has written it.

### Test (free)

```powershell
pytest tests/test_risk.py -q
```

What it checks: every road scored 0–100 with components in 0–1, DLP flag carried through, plan never exceeds a ward's remaining budget, the 6 over-budget wards get no new repairs, warranty roads are "Invoke DLP" at ₹0, ranks are contiguous, methods exist on the rate card.

### Eval (backtest: does the ranking predict later trouble?)

```powershell
# baseline the model must beat (works now, no M3 code needed)
python -m evals.backtest_risk --target naive

# the real thing: rank roads using data before 1 Aug, score against Aug-Oct outcomes
python -m evals.backtest_risk

# different split date
python -m evals.backtest_risk --cutoff 2025-07-15
```

Compare the `model` row with `baseline_past_work_orders` (spearman 0.586, P@20 0.30, captured@20 0.137). **Beating those is the pass mark.** If the model is lower, it's adding noise and the weights need rethinking. Results are saved to `.claude/hillclimb/risk_backtest/`.

---

## Reading results (M1 and M2 evals)

```
.claude/hillclimb/<suite>/<variant>/
  results.jsonl   one row per case: grade, explanation, model, tokens
  traces/         the exact input and output per case: read a few before trusting a number
  errors.jsonl    timeouts and API errors (never counted as failures of the model)
  summary.json    the headline numbers
```

Runs resume where they stopped, so re-running the same command only does missing cases.
