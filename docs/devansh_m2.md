# M2: Audit and Accountability (work log)

Owner: M2. Scope: `pipeline/audit/` only (docs/BLUEPRINT.md §7 M2). No other member's folder, shared file or contract was changed.

Branch: `feat/m2-audit` (local, not yet committed or pushed).

## Status

| Check | Result |
|---|---|
| `pytest tests/test_audit.py -q` | 17 / 17 pass |
| `pytest -q` (whole suite) | 36 pass, 15 skip (M1 and M3 not written yet) |
| Narrative eval checks (`--target app`, programmatic graders, no Claude call) | 29 / 29 pass |
| Contract (`contracts/schemas.py`) | all 3 M2 outputs validate |

## Files

| File | What it does |
|---|---|
| `__init__.py` | `run(data_dir, out_dir)` entry point. Writes the 4 output files only after everything is computed, so a crash leaves the old outputs in place |
| `config.py` | Every threshold, score weight, grade cutoff, banned word and word limit in one place |
| `load.py` | Reads the CSVs, works out rate-card expected cost, cost ratio, DLP status and first-complaint time per work order |
| `rules.py` | The 5 audit rules |
| `scorecards.py` | Contractor and ward scorecards, plus the fairness notes |
| `explain.py` | Flag explanations and scorecard summaries (Claude when available, template otherwise) |

## Outputs

Written to `out_dir` (normally `outputs/`):

- `audit_flags.parquet`: one row per flag
- `contractor_scorecard.parquet`: 8 rows
- `ward_scorecard.parquet`: 24 rows
- `scorecard_text.json`: summaries, fairness notes, score weights, score components per contractor, thresholds and the facts packets the text was written from

## Audit rules

| Flag | Rule | Severity | ₹ at risk | Hits | ₹ total |
|---|---|---|---|---:|---:|
| `OVERBILL` | billed / rate-card expected > 1.30 | high above 1.50, else medium | billed minus 1.30x expected | 114 | ₹44.8 L |
| `DOUBLE_BILL` | no linked complaint AND an earlier WO on the same road and work type within 7 days | high | full cost | 45 | ₹25.9 L |
| `DLP_PAID` | road `under_dlp = Y` and cost > 0 | medium | full cost (recoverable) | 493 | ₹2.62 Cr |
| `SLA_MISS` | `sla_met = N`; hours late measured from the first linked complaint | high if late by more than the deadline itself, medium if more than 24 h, else low | none | 1,259 | none |
| `REPEAT_REPAIR` | `reopened_within_30d = Y`; follow-up = next WO on the same road within 30 days of completion | medium with a follow-up, low without | follow-up WO cost (paid twice) | 611 | ₹2.63 Cr |

Notes:
- Expected cost is `area_sqm x rate` for `per sqm` methods and the flat rate for `per job` methods.
- `related_work_order_id` holds the earlier job for `DOUBLE_BILL` and the follow-up job for `REPEAT_REPAIR`.
- 82% of re-opened jobs have a follow-up WO, which matches the blueprint.
- The blueprint quotes ₹3.07 Cr for repeat repairs. That is the cost of the re-opened jobs themselves. M2 step 2 asks for the follow-up cost, which is what this uses (₹2.63 Cr).
- Every flag carries an `evidence` string with the actual numbers, for example: `billed 2.24x the rate card (₹22,935 vs ₹10,260 for Cold mix patch); ₹9,597 above the 1.30x tolerance`.

## Contractor scorecard

Score (0 to 100) = 40% durability + 30% on time + 30% clean billing.

- **Durability:** actual re-open rate compared with the rate that contractor's own mix of repair methods would predict city-wide. Component = `1.5 - actual/expected`, clipped to 0..1.
- **On time:** share of jobs with `sla_met = Y`.
- **Clean billing:** `1 - 4 x (OVERBILL + DOUBLE_BILL flags) / jobs`, clipped to 0..1.
- **Grades:** A 80+, B 65+, C 50+, D 35+, E below 35.
- `durability_index` = expected / actual re-open rate. Above 1 means repairs last better than the method mix predicts.

| ID | Contractor | Jobs | On time % | Re-open % | Expected re-open % | Durability | Median cost ratio | Score | Grade |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| CT05 | Deccan Paving Solutions | 287 | 59.6 | 9.1 | 23.8 | 2.62 | 1.015 | 84.1 | A |
| CT01 | Sahyadri Infra Works | 337 | 62.3 | 13.6 | 24.6 | 1.80 | 1.062 | 82.6 | A |
| CT08 | Mithi Infra Projects | 319 | 51.7 | 11.6 | 24.8 | 2.13 | 1.043 | 80.3 | A |
| CT02 | Konkan Roadcon Pvt Ltd | 337 | 46.0 | 26.7 | 24.1 | 0.90 | 1.048 | 56.3 | C |
| CT06 | Shivneri Construction | 289 | 47.1 | 26.3 | 24.3 | 0.92 | 1.046 | 55.4 | C |
| CT04 | Western Coast Asphalt Co | 299 | 47.2 | 38.8 | 24.6 | 0.63 | 1.065 | 40.9 | D |
| CT07 | Arabian Sea Engineering | 328 | 43.6 | 32.3 | 24.7 | 0.77 | 1.080 | 35.8 | D |
| CT03 | Mahalaxmi Civil Contractors | 303 | 39.3 | 37.6 | 24.7 | 0.66 | 1.079 | 20.4 | E |

All contractors are fictional (synthetic data).

### Fairness choices

- Only rates are scored, never counts, so a contractor is not penalised for doing more work.
- Re-open rates are adjusted for repair-method mix (cold mix re-opens far more often than dewatering).
- `DLP_PAID` is shown but not scored against the repairing contractor, because the original warranty contractor is not in the data.
- Every contractor works in all 24 wards, so geography does not explain the gaps.
- These notes ship in `scorecard_text.json` (`fairness_notes`) for the app's "fairness notes" panel.

## Ward scorecard

One row per ward: budget, billed, % of budget used, ₹ flagged, % of spend flagged, re-open %, on-time %, top contractor by spend, summary text.

- `flagged_inr` takes the largest ₹ flag per work order, so one job is never counted twice.
- Ward billed totals add up to ₹13,43,28,183, matching the test.
- 6 wards are over budget. G/S has the highest share of spend flagged (63.7%).

## Text (explain.py)

Public functions, matching the eval contract in `evals/targets.py`:

```python
contractor_scorecard_text(facts) -> str   # max 120 words
ward_summary_text(facts) -> str           # max 150 words
flag_explanation(facts) -> str            # max 25 words
```

- Facts packets use the same shape as `evals/build_cases.py`, so the eval and the app see the same input.
- Claude is called through M1's cached wrapper `pipeline.common.llm.ask` when it exists.
- The template is used instead when the wrapper is missing, there is no API key, or Claude's reply is too long, uses a banned word ("fraud", "corrupt" and so on) or cites a work order ID not in the facts.
- Flag explanations (about 2,500) use the template unless `AUDIT_LLM_FLAGS=1` is set, to keep cost down.
- The system prompt enforces neutral wording ("needs review"), explains DLP in plain words, and allows only numbers given in the facts.

## How to run

```bash
.venv\Scripts\activate
set PYTHONIOENCODING=utf-8
python -m pipeline.audit                 # writes outputs/
pytest tests/test_audit.py -q            # M2 tests
```

## Open items

1. **Commit and push** `feat/m2-audit`, then open a PR into `dev` for M1 to review.
2. **Generate `outputs/`:** not done yet (only temp test runs).
3. **Shared loaders:** switch `load.py` to M1's `pipeline/common/io.py` once it lands.
4. **Claude text:** turns on automatically when M1's `pipeline/common/llm.py` lands. Then run `python -m evals.run_eval --suite narrative --target app` (the harness approval step is for a human to do).
5. **Thresholds:** if any rule threshold in `config.py` changes, update `tests/planted.py` and the expected counts in `tests/test_audit.py` in the same PR.
