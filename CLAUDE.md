# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Team 6's workspace for the **Claude Impact Lab Mumbai** hackathon (21 Nov 2026), challenge "Follow the Rupee: Mumbai Monsoon Roads". The goal: build a Claude-powered tool showing **where each ward's road repair money went, whether the work held up, and where the next rupee should go**.

So far the repo holds only the provided dataset (`data/`) and docs. There's no application code, build system or tests yet. Update this file once a stack is chosen.

- [README.md](README.md): challenge brief and the four steps (Connect → Audit → Hold to account → Budget smarter)
- [DATA_DICTIONARY.md](DATA_DICTIONARY.md): meaning of every column. Check it before you interpret a field.
- [STARTER_IDEAS.md](STARTER_IDEAS.md): candidate tools, starter prompts and the **judging rubric**. Audit accuracy (25%) and the budget ranking (20%) are scored against a hidden answer key.

## Data constraints

- **All data is synthetic and all contractors are fictional.** Real Mumbai names (wards, localities, roads, hospitals) appear only for realism. Output must not present findings as claims about real BMC departments or real people.
- Scorecards and flags must be **fair and evidence-based**. Cite the `work_order_id`s behind every flag or score. Account for context such as `low_lying_index`, heavy-rain weeks and big tides before blaming a contractor. Don't penalise a contractor just for doing more work.
- For quick prompt iteration, use `data/complaints_sample_200.csv` (a 7–8 Jul heavy-rain spell) instead of the full 6,501-row `complaints.csv`.

## How the data joins

```
complaints.complaint_id <──(pipe-separated linked_complaint_ids)── work_orders
work_orders.road_id ──> roads (under_dlp, last_resurfaced) ──> traffic (road_id)
work_orders.repair_method ──> rate_card
work_orders.contractor_id ──> contractors
work_orders.ward_code ──> wards (monsoon_repair_budget_inr_2025, low_lying_index)
facilities.ambulance_entry_road, accidents.road_id ──> roads
flood_hotspots / localities ──(ward_code, lat/lon)──> wards
rainfall_daily, tides ──(date)──> any timestamped table
```

Things that trip people up:
- `linked_complaint_ids` is **pipe-separated** (`BMC25-000013|BMC25-000012`). A blank value means no complaint was linked, which is itself an audit signal (for example, a double-billing pattern).
- `rate_card.unit` is either `per sqm` (expected cost = `area_sqm` × `standard_rate_inr`) or `per job` (flat). Normal variation is about ±20–30%, so don't flag inside that band. One `repair_method` value contains commas and is quoted in the CSV.
- `under_dlp = Y` on a road means repairs should be done free by the original contractor. A BMC-paid work order on such a road is a flag.
- `sla_hours` is measured **from the first complaint to completion**, not from `assigned_at`.
- `contractors.active_wards` is `"; "`-separated, and so is `wards.localities`.
- `rainfall_daily` has 2 stations per date (Santacruz, Colaba), and `tides` has 2 high tides per date. Aggregate before joining on date.
- `complaints.ward_code` is blank for about 7% of rows and `category_reported` is wrong or vague for about 18%. Recover ward from lat/lon (point-in-polygon on `wards.geojson` matches the dataset's `ward_code`) or from `locality_text` via `localities.csv` aliases, which include Devanagari.
- Complaint `description` and `social_posts.text` mix English, Hinglish, Marathi and Hindi. `photo_description` stands in for image content.
- Timestamps are `YYYY-MM-DD HH:MM` IST. Files are UTF-8, so read with an explicit `encoding="utf-8"` on Windows. Printing Devanagari text to the Windows console crashes unless `PYTHONIOENCODING=utf-8` is set.
- City-wide spend is about ₹13 crore. Ward budgets are sized against it, so budget-vs-spend comparisons are meaningful.

The team plan (stack, module ownership, output schemas, audit rules with expected counts) is in [docs/BLUEPRINT.md](docs/BLUEPRINT.md). Follow its ownership and schema contracts when adding code. Output schemas are in `contracts/schemas.py`.

## CI / CD

- `.github/workflows/`: **CI** (`ci.yml`) runs lint, a DB freshness check, `pytest` on Python 3.12 and 3.14, and `python -m evals.ci_check` (the free eval gates) on every push and PR to main/dev. It never calls Claude. **CD:** `cd-data-release.yml` publishes the `data-latest` release after CI passes on main. `regenerate-outputs.yml` (manual) re-runs the pipeline and opens a PR. `paid-evals.yml` (manual) runs paid evals with the `ANTHROPIC_API_KEY` secret. The `claude-smoke` job in `ci.yml` makes 3 real Claude calls (`python -m evals.claude_smoke`) on pushes to main only; it's non-blocking (`continue-on-error`). Setup and branch protection are in [docs/CI_CD.md](docs/CI_CD.md).
- Before pushing, run the same checks locally: `python -m ruff check --select E9,F63,F7,F82 .`, `python -m pipeline.db --check`, `python -m pytest -q`, `python -m evals.ci_check`. Code must stay Python 3.12-compatible.
- New dependencies go in `requirements.txt` (CI installs only that). M1's de-dup needs `scikit-learn` and `scipy`; without them it silently falls back to weaker rules.

## Database (what the app reads)

- `outputs/follow_the_rupee.db` (SQLite, about 7 MB, committed) holds the reference data, every cleaned pipeline output and the Claude texts, with primary and foreign keys enforced at build time. The app should read it through `pipeline.db` (`db.query(sql, params)` or `db.connect()`, read-only), not the parquet or CSV files.
- Start from the views: `v_complaint_trail`, `v_work_orders`, `v_ward_money`, `v_contractor_cards`, `v_next_rupee`, `v_work_order_flags`. The schema reference, with an example query per question, is [docs/DATABASE.md](docs/DATABASE.md), which is generated, so don't hand-edit it.
- **Kept in step automatically.** Every M1, M2 or M3 `run()` that writes into `outputs/` ends with `pipeline.db.sync.after_run()`, which rebuilds the DB (about 10 s). Runs into other folders (tests, backtest, scratch) never touch it, so `pytest` doesn't change the committed DB. A new module that writes to `outputs/` must call `after_run` too.
- **Full run:** `python -m pipeline` runs M1, then M3, then M2, then builds the DB once (auto-sync is paused between steps). `--no-llm` makes no new Claude calls and reuses cached answers (`LLM_OFFLINE=1`), so an offline re-run reproduces the committed outputs exactly. `--only m3` runs one step.
- **Manual:** `python -m pipeline.db` to rebuild, or `python -m pipeline.db --check` to check freshness. `tests/test_db.py` fails if the committed DB is older than its inputs.
- `LLM_CACHE_READ=0` skips cache reads (eval `--fresh`). `LLM_DISABLE=1` (tests, eval `rules` target) skips Claude and the cache. `LLM_OFFLINE=1` uses the cache but never calls the API. Don't use `LLM_DISABLE` for pipeline runs into `outputs/`, because it replaces the cached Claude texts with templates.
- **Everything downstream is exported from the DB on every rebuild** (`pipeline.db.sync.export_all`): the web app's `app/public/data/*.json` (via `app/export_data.py`, which reads only the DB) and `outputs/csv/*.csv` (including `audit_flags`, `billing_anomalies`, `budget_plan` and `road_risk` for judges). `tests/test_db.py` fails if either is older than the DB. Never hand-edit them.
- SQLite divides an INTEGER by an INTEGER as integers, so `CAST(... AS REAL)` before dividing money columns (`cost_inr` and `standard_rate_inr` are both integers).

## Tests and evals

- `pytest -q`: Layer-1 suite, about 2.5 min, free. `tests/conftest.py` sets `LLM_DISABLE=1`, so no Claude calls even with a key in `.env`. Run one file with `pytest tests/test_audit.py -q`, or one test with `pytest tests/test_audit.py -k planted -q`. The fast unit tests are `tests/test_extract.py`, `tests/test_llm.py` and `tests/test_eval_harness.py`.
- `tests/test_audit.py` pins the expected flag counts (114 / 45 / 493 / 1259 / 611) and plants anomalies via `tests/planted.py`. Change thresholds there in the same PR as any audit rule change.
- `python -m evals.run_eval --suite extraction|narrative --target app|claude|rules|oracle|null|citizen|template`: see [evals/README.md](evals/README.md). `rules` runs the real app code with Claude off (free). `app` and `claude` are paid and gated. `--approve-harness` is a human step; don't pass it on the user's behalf.
- `python -m evals.backtest_risk`: checks whether the road risk ranking predicts August–September trouble from June–July data, compared with a naive baseline.
- `python -m evals.build_cases` regenerates `evals/cases/` deterministically: `extraction` (150 answerable, a regression check), `extraction_routed` (the 21 complaints the evidence can't decide) and `narrative`. Each suite has its own harness approval.
- [sanjay command.md](sanjay%20command.md) has copy-paste test and eval commands per module. [docs/sanjay fixes.md](docs/sanjay%20fixes.md) records what was fixed on 21 Nov and why.
- Eval contract (keep signatures stable, see `evals/targets.py`): `pipeline.connect.extract.extract_complaint(record, force_claude=False)` (M1), `pipeline.audit.explain.{contractor_scorecard_text,ward_summary_text,flag_explanation}` (M2), and `pipeline.common.llm.{reset_last_meta,get_last_meta}`.

## Claude calls

- All Claude calls go through `pipeline/common/llm.py` `ask()`, which never raises. Responses are cached in `outputs/llm_cache/` (or `LLM_CACHE_DIR`). `LLM_DISABLE=1` returns the fallback with no network. Failures are recorded in `get_last_meta()["error"]`, not swallowed.
- M1 extraction calls Claude only for the 120 complaints whose reliable text has no road keyword. Claude labels them `Not road-related`, and they stay in `complaints_clean` with no issue, no severity and no path to M3. Category comes from the photo template, then English or helpline text, then the citizen's category. Rows with no reliable evidence (non-English app text, vague category, no photo) get the most common category as `no_evidence`, with no Claude call: on those, Claude scored 19% against 28.6%. Severity is a per-category lookup. Run `python -m evals.measure_routing` for the current figures.
