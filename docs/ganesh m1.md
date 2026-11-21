# M1: Connect (complaint data engineering): what was built

Owner: Ganesh. Scope is M1 from `docs/BLUEPRINT.md` only. All data is synthetic.

## Summary

M1 turns the raw complaints into clean, ward-tagged, de-duplicated issues. It links each complaint to its work order, and it produces the open-issue list that M3's planner needs.

Entry point: `pipeline.connect.run(data_dir, out_dir) -> dict[str, Path]`. A full run on the real data takes about 50 seconds.

All 7 tests in `tests/test_connect.py` pass.

## Files

| File | Purpose |
|---|---|
| `pipeline/common/io.py` | Typed UTF-8 loaders: complaints, work orders (with `linked_complaint_ids` split into lists), localities, wards, roads, contractors, ward GeoJSON |
| `pipeline/common/geo.py` | numpy haversine and a shapely point-in-polygon `WardLocator` (no geopandas) |
| `pipeline/common/llm.py` | `ask()`: cached Claude wrapper (`claude-opus-5-5`, structured output). Never raises. Returns the cached response, or the fallback if there is no key or the call fails. `cached()` is a cache-only lookup |
| `pipeline/connect/ward.py` | Ward recovery |
| `pipeline/connect/extract.py` | Category, severity and English summary. Also `extract_complaint(record)`, the function the evals call |
| `pipeline/connect/dedup.py` | Issue clustering: pair model + average-linkage (rule-based fallback), and its precision/recall check |
| `pipeline/connect/__init__.py` | `run()`, plus the work-order trail and the open-issue builder |

## Outputs (columns match `contracts/schemas.py`)

| Output | Rows | Notes |
|---|---:|---|
| `complaints_clean.parquet` | 6,501 | Every complaint kept, none lost. `linked_work_order_id` is filled for every complaint a work order links |
| `wo_trail.parquet` | 2,499 | One row per work order: complaint count, first complaint time, channels, total upvotes, hours to complete |
| `open_issues.parquet` | 687 | Open and In Progress complaints grouped into issues, each with a `road_id` |
| `dedup_metrics.json` | | Precision, recall and F1, plus the counts of how each ward and each extraction was produced |
| `csv/*.csv` | same | Readable CSV copies of the three tables (UTF-8 with BOM, opens in Excel). The Parquet files are the contract; the CSVs are for inspection only |

Saved in `outputs/`. They are the latest run (dedup F1 0.698). `complaints_clean` has 3,529 distinct issues.

## How each step works

**1. Ward recovery.** Order: given, then GPS, then locality.
- `given`: the ward already on the complaint (6,044 rows).
- `gps`: point-in-polygon on `wards.geojson` (271 rows).
- `locality`: a match on `locality_text` against `localities.csv` names and aliases (Devanagari included). For partial names such as "Malad" it takes the first gazetteer entry that starts with it. If that fails it scans the description for the longest known place name (186 rows).
- Result: 100% of complaints have a ward.
- I did not use the linked work order's ward to fill gaps. That would make the accuracy test circular.

**2. Extraction.**
- Rows that are non-English or have a vague reported category ("Road related", "Other") are sent to Claude, with a JSON schema that limits the category to the six known values.
- Everything else, and everything when Claude is unavailable, uses a multilingual keyword fallback.
- Severity from the fallback is a simple rule: base 3, +1 for danger words (school, hospital, accident and similar), +1 for 30 or more upvotes.
- Every row records whether it came from `claude` or `rules`. This is reported in `dedup_metrics.json`.

**3. De-duplication (model-based).** Per ward:
- Candidate pairs are complaints received within 144 hours of each other.
- Each pair gets features: time gap, GPS distance, same locality, same category (cleaned and as reported), road names mentioned agree or disagree, character n-gram text similarity, same language and channel.
- A gradient-boosting classifier scores each pair. It is trained on pairs where both complaints are linked to a work order (same work order = duplicate).
- Scoring is out-of-fold by ward: each ward is scored by a model that never saw that ward, so the precision and recall reported are held-out numbers.
- Average-linkage clustering on the scores (cut at probability 0.30) forms the issues. Average linkage stops a single weak link from chaining unrelated complaints together, which was the main problem with the first version.
- If scikit-learn is not installed, it falls back to the earlier rule-based clusterer (F1 about 0.606).
- The threshold (0.30) and settings were chosen by looking at the same data's scores, so the held-out number is slightly optimistic.

**4. Work-order trail.** Per work order, first complaint time is the earliest linked complaint. Hours to complete are measured from that to `completed_at`.

**5. Open issues.**
- An issue is a cluster that contains at least one Open or In Progress complaint.
- `n_complaints` counts every complaint in the cluster, because it is the demand signal for M3.
- Each issue gets a road: the nearest road-segment midpoint in the same ward.
- The reference point is the complaint's GPS, or the locality centre if there is no GPS, or the ward centre as a last resort.

## Results on the real data

| Check | Result | Target |
|---|---|---|
| Ward coverage | 100% | at least 98% |
| Recovered-ward accuracy vs work-order ward | passes the test | at least 90% |
| Dedup pairwise precision | 0.713 | |
| Dedup pairwise recall | 0.684 | |
| Dedup F1 | 0.698 | at least 0.60 (was 0.606 with the first rule-based version) |
| Open issues with a road | 100% | at least 90% |

Eval harness self-checks (free, no API): the oracle target scores 100%, the null target 0%, and the citizen baseline 88% valid, 0% on `cat_wrong` cases.

## Known limits (please read)

- **Claude extraction has not run.**
  - No `ANTHROPIC_API_KEY` was available, and the cache is empty, so all 6,501 rows are tagged `rules`.
  - To fill it, set the key and run `python -m pipeline.run_all` or `pipeline.connect.run`. About 2,900 rows go to Claude, and the responses are cached to `outputs/llm_cache/`.
  - Commit that cache so the demo works offline.
  - Rerun the dedup metrics afterwards.
- **Dedup trained on the data's own links.** The model learns from complaints linked to work orders. Open complaints are mostly unlinked, so how well it does on them cannot be measured. Citizens picked the wrong category on about 19% of linked complaints, which still caps recall. **`scikit-learn` is needed** (not in `requirements.txt`, which M4 owns); ask M4 to add it. Without it the fallback is used.
- **Severity is not validated.** The ground truth is the work order's `sla_hours` (24 h is 5 up to 168 h is 1). I have not scored the fallback rule against it.
- **`python -m evals.run_eval --target app`** was not run. It needs a human to run `--approve-harness` first.
- Nothing is committed, and `outputs/` has not been generated into the repo yet.

## Hand-off to the team

- **M3:** read `open_issues.parquet`. Every row has a `road_id`, so it can feed `open_issues` in the road-risk score.
- **M2 and M4:** use `wo_trail.parquet` for the complaint to work order link. `complaints_clean.linked_work_order_id` gives the same link from the complaint side.
- **M4:** show the dedup precision/recall from `dedup_metrics.json` on the dashboard.
