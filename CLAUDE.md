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

The team plan (stack, module ownership, output schemas, audit rules with expected counts) is in [docs/BLUEPRINT.md](docs/BLUEPRINT.md). Follow its ownership and schema contracts when adding code. Output schemas are in `contracts/schemas.py`.

## Tests and evals

- `pytest -q`: Layer-1 regression suite. Module tests skip until `pipeline.<module>.run(data_dir, out_dir)` exists. Run one file with `pytest tests/test_audit.py -q`, or one test with `pytest tests/test_audit.py -k planted -q`.
- `tests/test_audit.py` pins the expected flag counts (114 / 45 / 493 / 1259 / 611) and plants anomalies via `tests/planted.py`. Change thresholds there in the same PR as any audit rule change.
- `python -m evals.run_eval --suite extraction|narrative --target app|oracle|null|citizen|template`: Claude evals; see [evals/README.md](evals/README.md). Non-`app` targets are free harness self-checks. `--approve-harness` is a human step; don't pass it on the user's behalf.
- `python -m evals.backtest_risk`: checks whether the road risk ranking predicts August–September trouble from June–July data, compared with a naive baseline.
- `python -m evals.build_cases` regenerates `evals/cases/` deterministically.
- [sanjay command.md](sanjay%20command.md) has copy-paste test and eval commands per module (M1 Connect, M2 Audit, M3 Risk).
- `--target app` evals call `pipeline.connect.extract.extract_complaint` (M1) and `pipeline.audit.explain.{contractor_scorecard_text,ward_summary_text,flag_explanation}` (M2). The contract is in `evals/targets.py`; keep those signatures stable.
- No pipeline code exists yet (only tests, evals and contracts), so module tests currently skip and `--target app` exits with a message.
- City-wide spend is about ₹13 crore. Ward budgets are sized against it, so budget-vs-spend comparisons are meaningful.
