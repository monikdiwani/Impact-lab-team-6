# Sanjay's commands: test + eval for M1, M2, M3

Run everything from the repo root. Details: [evals/README.md](evals/README.md).

## One-time setup

```powershell
pip install -r requirements.txt
copy .env.example .env                   # then open .env and paste your key after ANTHROPIC_API_KEY=
$env:PYTHONIOENCODING = "utf-8"          # Devanagari in the cases crashes the console without this
```

`.env` is git-ignored. `evals/run_eval.py` loads it automatically, and a key already set in your shell takes priority. Only the paid evals (M1, M2) need the key. Git Bash: `cp .env.example .env` and `export PYTHONIOENCODING=utf-8`.

## All three at once

```powershell
pytest -q                # free. Module tests SKIP until that module exists
pytest -q -rs            # same, and lists why each test was skipped
```

A skipped test means the module isn't written yet. A failed test means it's written and wrong.
The suite switches Claude off for itself (`LLM_DISABLE=1`), so it is free even with a key in `.env`. It takes about 2.5 minutes; most of that is M1's de-dup model.

---

## M1: Connect (complaints)

**Needs:** `pipeline/connect/__init__.py` with `run(data_dir, out_dir)` (tests) and
`pipeline/connect/extract.py` with `extract_complaint(record: dict, force_claude=False) -> dict` (eval).

### Test (free)

```powershell
pytest tests/test_connect.py -q -s       # -s prints dedup precision / recall / F1
pytest tests/test_extract.py tests/test_llm.py -q   # extraction routing + Claude wrapper (seconds, no network)
```

What it checks: no complaints lost, ward coverage ≥ 98%, recovered wards correct (≥ 90% on blank-ward rows), work-order links preserved, de-dup F1 ≥ 0.60 against the real linked groups, open issues have a `road_id`.

### Eval (extraction suite, 166 cases)

```powershell
# 1. free: harness self-checks (100% / 0% / 54.8% category) and M1 without Claude
python -m evals.run_eval --suite extraction --target oracle
python -m evals.run_eval --suite extraction --target null
python -m evals.run_eval --suite extraction --target citizen    # the bar to beat
python -m evals.run_eval --suite extraction --target rules      # M1's real code, Claude off

# 2. paid pilot. The cases and runner changed on 21 Nov, so approve again.
#    --approve-harness is YOUR step: review evals/cases/REVIEW.md first
python -m evals.run_eval --suite extraction --target app --approve-harness --limit 10

# 3. full run, plus the Claude-only ablation (every case through Claude, rules bypassed)
python -m evals.run_eval --suite extraction --target app
python -m evals.run_eval --suite extraction --target claude

# 4. after changing the prompt: run it as a new variant, then compare summaries
python -m evals.run_eval --suite extraction --target app --variant v1
```

Numbers to report:
- **category** (citizen bar 54.8%), **category on `cat_wrong`** (fixing the citizen's mistakes) and **category by evidence source** (photo / text / citizen / claude).
- **The `ambiguous` slice:** the only cases where Claude decides the category in `app`.
- **ward recovery on blank-ward cases.**
- **severity:** `severity best` should be 100%. `severity =` and `severity ±1` should equal the ceiling line the runner prints (46.4% / 95.2% on this set); they can't go higher, because within a category the true severity is random.
- Language is now an input, so it isn't scored.

Earlier runs are kept in `.claude/hillclimb/extraction/_archive/` (the pre-fix pilot, plus baseline and v1 from before the `severity best` metric) and `.claude/hillclimb/extraction-claude-only/_archive/`. The grader and cases changed again on 21 Nov, so approve once more. Re-runs are free because the Claude answers are cached.

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
# 1. free harness self-checks, and M2's real templates through the graders
python -m evals.run_eval --suite narrative --target template    # 100% on the programmatic checks
python -m evals.run_eval --suite narrative --target null        # 0%
python -m evals.run_eval --suite narrative --target rules       # M2's code with Claude off: 100% today

# 2. first paid run: pilot, then approve (approve again: the runner changed on 21 Nov)
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

Result on 21 Nov: **model spearman 0.650, P@20 0.40, captured@20 0.164**, so it beats the baseline on all three. M3 tuned its weights on this backtest (4 cutoffs), so treat it as an in-sample number.

---

## Database (what the app connects to)

```powershell
python -m pipeline.db            # rebuild outputs/follow_the_rupee.db + docs/DATABASE.md after any pipeline run (~10 s)
python -m pipeline.db --check    # is the database up to date with data/ and outputs/?
pytest tests/test_db.py -q       # keys, row counts, views, read-only access, freshness
```

```python
from pipeline import db
db.query("SELECT * FROM v_complaint_trail WHERE complaint_id = ?", ["BMC25-000005"])
db.query("SELECT * FROM v_next_rupee WHERE ward_code = ? ORDER BY rank", ["F/S"])
```

Full run order after code changes: M1 `python -c "from pipeline.connect import run; run('data','outputs')"`, then M3 `python -m pipeline.risk`, then M2 `python -c "from pipeline.audit import run; run('data','outputs')"`, then `python -m pipeline.db`.

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
