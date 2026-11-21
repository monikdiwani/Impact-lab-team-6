# Fixes after the extraction pilot (Sanjay, 21 Nov)

**Starting point:** the 10-case extraction pilot scored category 70%, severity 30% exact, ward 100% and language 0%. This file lists every problem behind those numbers, what was changed, and the measured result. Everything is reproducible with the commands in [sanjay command.md](../sanjay%20command.md).

**Scope:**
- **M1's files:** `pipeline/connect/extract.py`, `pipeline/connect/dedup.py` and `pipeline/common/llm.py`, changed with Sanjay's go-ahead.
- **Shared tooling:** the eval harness (`evals/`), the tests (`tests/`) and the docs.
- **Not changed:** M2's and M3's code.

## Results at a glance

| What | Before | After |
|---|---|---|
| Category accuracy, rules only, 4,798 linked complaints outside the eval set | 84.3% (trusting the citizen) | **98.3%** |
| Same, on rows where the citizen picked the wrong category | 26.2% (old M1 code, Ganesh's measurement) | **89.1%** |
| Category on the new 166-case eval set, `rules` target | | **100%** (citizen bar: 54.8%) |
| Severity exact / within one (eval set) | 26.7% / 74.7% (old M1 code) | **46.4% / 95.2%** (ceiling about 47% exact) |
| Claude calls in one full pipeline run | about 3,000, one at a time (hours) | **151, 8 at a time** (minutes), cached |
| De-dup precision / recall / F1 | 0.713 / 0.684 / 0.698 | **0.730 / 0.782 / 0.755** |
| Test suite | 54 tests, 5 min 35 s | **86 tests, 51 s** |
| Claude calls made by one test run, if a key is set | about 360 (paid) | **0** |

The 98.3% figure includes complaints that no system could get right. The 100% on the eval set excludes them; that's explained in section 3.

## 1. What the data showed (the root causes)

These were measured on the linked complaints, where the truth is the category of the work order that fixed them.

1. **Photo descriptions are decisive.** The data has 12 fixed photo templates, and each maps to exactly one category, 100% of the time. The old keyword rule misread two of them: "crater filled with muddy water" became Waterlogging, and "manhole cover sunk" became Road cave-in.
2. **English text and 1916-helpline operator notes are reliable.** Keywords get them right 90–98% of the time, even when the citizen picked the wrong category.
3. **Hindi, Marathi and Hinglish text from the app or portal is unrelated to the real problem.** For example, "मैनहोल खुला है" (manhole open) appears on a pothole job where both the citizen and the photo say pothole. Every keyword row in that text has the same category mix (44% pothole, 25% waterlogging, …). That's an artefact of how the synthetic data was generated, so reading this text is right only about 26% of the time, while the citizen's category is right 84–86%.
4. **Severity depends only on the category.** Within a category it's noise: urgency words, upvotes, photo, road type and repair area all show no signal (upvote correlation 0.01). A per-category lookup is the best any method can do: about 47% exact and 89% within one.
5. **Language can't be read from the text.** Helpline rows are English operator notes even when the caller spoke Marathi or Hindi (740 linked rows), so `language` is an input, not something to predict.

## 2. M1 extraction and the Claude wrapper

| # | Problem | Evidence | Fix |
|---|---|---|---|
| 1 | Claude reached only 3 of the 10 pilot cases. Hindi and Marathi cases never reached it. | Pilot timings: about 6 s for 3 cases, under 0.15 s for the rest. `extract_complaint` defaulted the missing language to `"en"`. | Routing is now based on evidence, not on the language label. If language is missing, it's detected from the text as a fallback. |
| 2 | The citizen's category was trusted whenever it was specific. | 16.5% of citizen categories are wrong. Case 000131, "loose paver blocks" filed as Waterlogging, stayed Waterlogging. | `extract.py` routes by evidence: photo template, then English or helpline text with exactly one keyword match, then the citizen's category, then Claude. Measured accuracies are in the module docstring. |
| 3 | Unreliable non-English text would have driven decisions. | Finding 3 above. | For Hindi, Marathi and Hinglish app/portal text with no photo, the specific citizen category is used (87%). Claude is used only when the category is vague. |
| 4 | Keyword false positives. | "Mahakali **Caves** Road" counted as a cave-in, and "**block**ed drain" as paver blocks. | Tighter patterns, with unit tests for both. |
| 5 | The severity rule (urgency words and upvotes) carried no signal. | Rules got 1 of 7 exact in the pilot, no better than always guessing 3. | Severity is now a per-category lookup, and Claude no longer guesses it. |
| 6 | The Claude prompt anchored on the citizen's category and left out the photo. | The prompt contained "Reported category: …" and no photo description. | New system prompt: category definitions and an evidence order (photo, then operator or English text, then citizen category, which is wrong about 1 in 6 times). It now gets the photo, channel and locality, and returns category, English summary and which evidence decided it. |
| 7 | A full pipeline run with a key would have taken hours. | About 3,000 Claude calls in a plain loop, about 6 s each. | Only 151 of 6,501 complaints go to Claude, and `extract()` runs them 8 at a time. |
| 8 | `llm.ask()` swallowed every error and returned the fallback. A rate limit or bad key would have been scored as if Claude had answered. | `except Exception: return fallback`. | Errors are recorded in `get_last_meta()["error"]`. `ask()` still never raises, so the demo can't crash. |
| 9 | The eval couldn't see the model, tokens or stop reason. | `model=None` on every pilot row. | New `get_last_meta()` and `reset_last_meta()`, per thread. Cache entries now store the model too. |
| 10 | No retry setting and no refusal fallback. | | `max_retries=4` (the SDK backs off on 429, 5xx and overload), plus server-side `fallbacks="default"`. Refused or truncated answers aren't cached. |
| 11 | There was no way to switch Claude off, and the cache folder was fixed when the module loaded. | | `LLM_DISABLE=1` gives a clean rules-only run. `LLM_CACHE_DIR` is now read on every call. |
| 12 | De-dup was slow. | 74 s per clustering, mostly the gradient-boosting scorer. | Histogram gradient boosting with the same depth and rounds: 27 s, F1 0.755 vs 0.753. |

**Smoke test with the real API:** one call through the new wrapper ("Road has caved in … knee deep", which matches two categories). Claude answered Road cave-in, the model and token usage (806 in / 77 out) were recorded, and the second call was a cache hit. Cost: about half a US cent.

## 3. Eval harness

| # | Problem | Fix |
|---|---|---|
| 13 | The language metric was meaningless. The input left language out, and it can't be read from helpline text anyway. | `language` is now an input, and the metric is removed. |
| 14 | **The label guard biased the set.** It dropped 521 cases whose text contradicted the truth, which were exactly the realistic cases where non-English text is wrong and the citizen is right. That made text-reading look better than it is. | New answerability guard: a case is dropped only if no reliable input points to the truth (87 of 4,787). Contradictory cases are kept. Each case records its supporting evidence. |
| 15 | One mislabelled case in the old set (000423). | Gone, because the new guard only counts photo, English or helpline text, and the citizen's category as evidence. |
| 16 | No case in the set reached Claude, so the eval couldn't measure what Claude adds. | New `ambiguous` slice (24 cases) and a paid `claude` target that sends every case to Claude, bypassing the rules. |
| 17 | There was no free way to measure M1's or M2's real code. | New `rules` target: the real app code with Claude off. |
| 18 | The approval fingerprint changed with line endings, so a teammate on another OS would have had to re-approve. | The fingerprint now normalises line endings, with a test. |
| 19 | A run folder could mix rows graded under different eval versions. | Each run folder records `run_info.json` and refuses to resume under different eval files. Your old pilot is archived in `.claude/hillclimb/extraction/_archive/pilot-before-fixes/`. |
| 20 | Failed Claude calls would have been scored as model answers. | They now go to `errors.jsonl` as `serving_error`. |
| 21 | Eval runs wrote into the demo cache, and reps were identical replays. | Eval runs use their own cache (`.claude/hillclimb/<suite>/_llm_cache/`, git-ignored). `--fresh` bypasses it. |
| 22 | Results didn't say where the answer came from. | The summary shows accuracy by evidence source, the number of Claude calls, and for M2 how often the final text was the template rather than Claude's. |

**Honest limit:** on answerable complaints M1's rules already score 100% on the eval set, so Claude's measurable job on category is the small ambiguous slice. Its other job, English summaries, isn't scored by these graders. Most complaints that actually reach Claude in the pipeline are open ones with no work order yet, so they have no ground truth to score against.

## 4. Tests

| # | Problem | Fix |
|---|---|---|
| 23 | With a key in the shell, one test run would have made about 360 paid Claude calls. | `tests/conftest.py` sets `LLM_DISABLE=1` for the session. |
| 24 | M1's connect step ran twice per session. | The risk fixture reuses the connect run's `open_issues.parquet`. |
| 25 | The new logic had no tests. | New `tests/test_extract.py` (routing, photo templates on the real data, keyword traps, severity lookup, language fallback, contract), `tests/test_llm.py` (disable switch, cache, per-thread meta, error, refusal and truncation handling, using a fake client) and `tests/test_eval_harness.py` (line-ending-proof fingerprint, run-folder guard, failed calls kept out of scores, case integrity). |

## 5. Other checks run (free)

- **M2 narrative, `rules` target:** M2's real templates pass every programmatic check (29/29): no invented numbers, valid IDs, word limits, no accusing words, required context.
- **M3 backtest:** correlation 0.650, P@20 0.40, captured@20 0.164, against the naive baseline's 0.586 / 0.30 / 0.137, so M3 beats it on all three. M3 tuned its weights on this backtest, so treat these as in-sample numbers.
- **Self-checks:** oracle 100%, null 0%, citizen 54.8% (extraction); template 100% (narrative).

## 6. Not done yet / your steps

1. **Paid evals.** `--approve-harness` is your step. The cases and runner changed, so review [evals/cases/REVIEW.md](../evals/cases/REVIEW.md), then run the pilot, the full `app` run and the `claude` ablation (commands in [sanjay command.md](../sanjay%20command.md)). Your `.env` key is picked up automatically.
2. **Committed outputs: regenerated (done, see section 7).**
3. **Independent review in progress.** A multi-agent review of these changes, with every finding checked by a separate skeptic, was still running at commit time. Confirmed findings will be fixed and added here in a follow-up commit.
4. **Teammates' notes:** `docs/ganesh m1 result.md` still has the old numbers.

## 7. Regenerated outputs (Claude on)

All of `outputs/` was rebuilt from the current code, with Claude enabled, in this order: M1 (`pipeline.connect.run`), M3 (`pipeline.risk.run`), M2 (`pipeline.audit.run`). The CSV copies in `outputs/csv/` were rewritten from the new parquet files. All 9 contract files pass `contracts.schemas.validate`.

| Output | Before (committed) | After |
|---|---|---|
| Extraction sources (6,501 complaints) | rules 6,501 (no key) | text 2,862 · photo 2,838 · citizen 650 · **Claude 151** (0 fallbacks, so every call succeeded) |
| Complaints whose category differs from the citizen's pick | 0 | 1,055 |
| De-dup precision / recall / F1 | 0.713 / 0.684 / 0.698 | 0.732 / 0.782 / 0.756 |
| Open issues (M1) | 687 | 658 |
| M3 open-issue source | `M3-fallback` (455, its own stand-in) | **`M1`** (658) |
| M3 plan | 124 repairs, ₹82.5 L | 119 repairs, ₹85.7 L (61 "Invoke DLP" unchanged) |
| M3 ward memos | 24 templates | 24 Claude-written |
| M2 audit flags | 114 / 45 / 493 / 1259 / 611 | **identical** (M2 doesn't depend on M1) |
| M2 contractor and ward summaries | 32 templates | 30 Claude-written, 2 templates |

- **Why 2 M2 summaries are templates:** Claude's text ran over the 120 or 150-word limit, so M2's own guard kept its template. That's working as designed.
- **Number formatting:** Claude writes amounts like "Rs 17209448", without Indian digit grouping. M2's prompt could ask for ₹ with commas.
- **Cache:** `outputs/llm_cache/` now holds 206 cached answers (151 M1, 32 M2, 24 M3, one prompt shared), so the demo runs with no network. The 3 stale entries from the pre-fix pilot were set aside, not committed.
- **Cost:** about 207 Claude calls in total.

## 8. Paid eval results and the severity question

Sanjay ran the paid evals after re-approving the harness. All runs had 166 cases scored and 0 failed attempts.

| Run | Category | Severity exact | Severity within one | Ward | Claude calls |
|---|---|---|---|---|---|
| `app` baseline (and a `v1` re-run, identical) | **100%** | 46.4% | 95.2% | 100% | 5 (the ambiguous cases, all correct) |
| `claude` ablation (every case through Claude, rules bypassed) | 93.4% | 45.8% | 91.6% | 100% | 166 (median 812 tokens in, 73 out) |

**Claude on its own makes the mistake the router is built to avoid.** All 11 of its misses are Hindi, Marathi or Hinglish complaints from the app or portal (11 of 67 such cases, 0 of 99 elsewhere). In 9 it believed text like "मैनहोल खुला है" (manhole open) over a correct citizen category. In 2 it even overrode a decisive photo, although the prompt puts the photo first. In the real app those cases never reach Claude, so the router scores 100%. The photo weakness only affects photo text Claude hasn't seen before, because all 12 known templates are handled by rules. Fixing it in the prompt would invalidate the 151 cached pipeline answers, so that's left for later.

### Is severity failing?

No. **There is no pass mark for severity, and 46.4% exact is the best any method can score.**

- **The correct answer comes from the work order, not the complaint.** It's the work order's deadline (24 h = 5 … 168 h = 1), and in this synthetic data it depends only on the category. Within a category it's random.
- **Nothing beats the category lookup.** A cross-validated model (grouped by work order) using 30 features scored worse than the lookup on 4,798 linked complaints. The features covered channel, language, upvotes, hour, weekday, rainfall, tides, ward, low-lying index, flood-hotspot distance, GPS, photo and text length, plus work-order fields the extractor never sees (method, cost, area, road traffic).

  | Method | Exact | Within one |
  |---|---|---|
  | **Category lookup (what M1 does)** | **46.6%** | **88.9%** |
  | Model, category only | 46.5% | 87.1% |
  | Model, everything the complaint offers | 42.7% | 82.5% |
  | Model, plus work-order fields | 45.9% | 84.0% |
- **On these 166 cases**, within one (95.2%) is already the maximum. Exact (77/166) could reach 84 only by switching pothole to 2, waterlogging to 5 and drain to 4. Those values suit this sample but are wrong across all complaints (pothole: 776 at 3 vs 672 at 2; waterlogging: 474 at 4 vs 304 at 5), so changing them would be tuning to the test set.
- **Category is 100% correct**, so no extraction change can raise severity.

**What was actually wrong was the report.** Nothing showed that 46.4% is the ceiling, so it read as a failure. Fixed:

| # | Change |
|---|---|
| 26 | New metric **`severity best`**. A case passes if the severity is the exact truth or the best possible answer for the true category. That's the part extraction controls. The best values come from linked complaints outside the eval set (`evals/build_cases.py`, `severity_best_table`): paver 1, drain 3 (4 is a near-tie, also accepted), manhole 5, pothole 3, cave-in 5, waterlogging 4. They match M1's lookup, and a test checks this. |
| 27 | The runner now prints the ceiling next to the raw numbers: *"severity ceiling on this set: exact 46.4%, within one 95.2%"*. |
| 28 | Free self-checks with the new metric: `rules` scores severity best **100%**, exact 46.4% and within one 95.2%, both at the ceiling. Oracle 100%, null 0%, citizen (always 3) 54.8%. |

**How to read severity from now on:**
- `severity best` should be 100%.
- `severity =` and `severity ±1` should equal the printed ceiling.
- Anything below the ceiling means the category was wrong.

**Official re-run with the new metric** (Sanjay re-approved the harness, 166 scored, 0 failed attempts each):

| Run | Category | `severity best` | Severity exact | Severity within one | Ceiling (exact / within one) |
|---|---|---|---|---|---|
| `app` | **100%** | **100%** | 46.4% | 95.2% | 46.4% / 95.2% |
| `claude` ablation | 93.4% | 95.2% | 45.8% | 91.6% | 46.4% / 95.2% |

The app is at the severity ceiling. The Claude-only run loses severity only where it got the category wrong. Earlier runs from before the metric are kept in the `_archive/` folders, with the suffix `-before-severity-metric`.

## 9. SQLite database (what the app connects to)

All cleaned data now lives in one SQLite database, `outputs/follow_the_rupee.db`. The app connects to it through `pipeline.db` instead of reading loose parquet, CSV and JSON files.

| What | Detail |
|---|---|
| Build | `python -m pipeline.db` (about 10 s) builds from `data/` and `outputs/` and writes [docs/DATABASE.md](DATABASE.md) |
| Contents | 28 tables. Reference data (wards, roads, traffic, contractors and their wards, rate card, work orders, facilities, hotspots, accidents, rainfall, tides, social posts, map GeoJSON); `complaints` (raw text merged with M1's cleaned fields); `issues` (all 3,302 duplicate clusters linked to their work order); every M1/M2/M3 output; `narratives` (56 Claude or template texts); `meta` (build time, row counts, input hashes, de-dup metrics, risk report, scoring weights, fairness notes) |
| Integrity | STRICT column types, primary keys and foreign keys on every table. The build fails on any foreign-key violation, failed integrity check or row-count mismatch |
| App API | 6 views: `v_complaint_trail` (complaint → issue → work order → contractor, cost, SLA, re-opened, flags), `v_work_orders`, `v_ward_money`, `v_contractor_cards`, `v_next_rupee`, `v_work_order_flags`. `db.query(sql, params)` returns a DataFrame. `db.connect()` is read-only, with foreign keys on |
| Safety | Built into a temp file and swapped in at the end. The app's connection rejects writes |
| Freshness | `meta` stores the sha256 of every input. `python -m pipeline.db --check` and `tests/test_db.py` fail if the committed DB is older than its inputs |

**A bug the tests caught while building it:** SQLite divides an integer by an integer as integers. For per-job repair methods the cost and the rate are both whole numbers, so the first version of `v_work_orders` showed a 1.4× bill as ratio 1 and lost 23 of the 114 over-bills. Fixed with `CAST(... AS REAL)`, and a test now checks the view agrees with M2 on all 114.

**Example:** `SELECT * FROM v_complaint_trail WHERE complaint_id = 'BMC25-000005'` returns:
- the Hinglish complaint, cleaned to "Open or broken manhole";
- its issue ISS-00001, which groups 5 complaints across the app, the helpline and English text;
- the work order that fixed it, with the contractor, the cost against the rate card, whether it met the SLA and whether it re-opened;
- the audit flags on that job.

17 new tests in `tests/test_db.py`.

## 10. The database stays connected to every run

**The problem:** the database was a separate manual step (`python -m pipeline.db`). Re-running M1, M2 or M3 without it left the app reading old data.

| Run type | What happens to the database now |
|---|---|
| `python -m pipeline` (new) | Runs M1, then M3, then M2, then builds the database once at the end (auto-sync paused in between). `--only m3` runs one step. |
| `python -m pipeline --no-llm` | Same, with no new Claude calls: cached answers are reused (`LLM_OFFLINE=1`). Verified: an offline full run reproduces every committed output exactly (151 Claude extractions and 24 Claude memos from cache). |
| A single module into `outputs/` (`python -m pipeline.risk`, `pipeline.audit.run(...)`, `pipeline.connect.run(...)`) | Its `run()` ends with `pipeline.db.sync.after_run()` and rebuilds the database. Verified for M3 and M2 standalone (`[db] M3: database updated`). |
| Tests, risk backtest, scratch folders | Never touch it: they write to temp folders. Verified that `pytest` leaves the committed database's build time unchanged. |
| Paid evals | Don't involve the database. They grade Claude through the app functions on fixed cases. |

**Safety details**
- **A failed rebuild doesn't crash the module run.** The module's outputs are already written, and the previous database stays as it was, because the build is atomic. The error is printed and `tests/test_db.py` fails until it's fixed.
- **Parallel runs don't collide:** each process builds into its own temp file.
- **Locked files are handled:** on Windows, if the app holds the file open, the swap retries and then explains.
- **Stale-plan reminder:** running M1 alone warns when M3's plan is older than M1's open issues.

**Why a second offline switch exists:** `LLM_DISABLE` (used by tests and the eval `rules` target) skips the cache entirely. For a pipeline run into `outputs/` that would replace the cached Claude texts with templates, so `--no-llm` uses `LLM_OFFLINE` instead.

8 new tests: auto-sync builds for `outputs/` and only `outputs/`; pause and env switch; a failed rebuild doesn't crash; every module's `run()` has the hook; the full run keeps dependency order and builds once; offline mode uses the cache and never calls the API. Full suite: 113 pass.

## 11. CI / CD with GitHub Actions

Details and one-time GitHub setup are in [docs/CI_CD.md](CI_CD.md).

| Workflow | Trigger | Does |
|---|---|---|
| CI | every push / PR to main, dev | lint, DB freshness, pytest on Python 3.12 + 3.14, free eval gates (`python -m evals.ci_check`: 17 gates, all passing locally) |
| CD - publish data | CI passed on a push to main | replaces the `data-latest` release: database, schema doc, outputs zip, Claude cache zip, checksums |
| CD - regenerate outputs | manual | re-runs the pipeline on a clean runner (offline by default), runs the tests, opens a PR if outputs changed |
| Paid evals | manual | runs a paid eval as a new variant with the `ANTHROPIC_API_KEY` secret. Respects the committed harness approval. Optional reviewer gate through the `paid-evals` environment |

**Found while building it:** `requirements.txt` was missing `scikit-learn` and `scipy`. M1's de-duplication needs them, and on a clean machine it would have silently fallen back to the weaker rules-based de-dup. Both are added. Also added: `.gitattributes` (database and parquet files are binary), Dependabot (weekly update PRs), and a CI badge in the README. 3 unused imports and variables in Sanjay's files were cleaned up.

## 12. Independent code review: 23 confirmed findings fixed

A multi-agent review checked the M1 rewrite, the Claude wrapper and the eval harness. Five reviewers each took a different angle, and every finding was then re-checked by a separate skeptic who tried to disprove it. **23 findings were confirmed and 8 rejected.** All 23 are fixed.

### What changed in the product

| # | Finding | Fix | Effect |
|---|---|---|---|
| 0 | **120 junk or non-road complaints** ("Test", "asdfgh", "Street light not working", "Garbage not collected") became Pothole, severity 3, and **37 open issues made only of junk** (plus 7 mixed ones) fed M3's budget ranking | New category **"Not road-related"**. Reliable text with no road keyword and no photo goes to Claude, which may answer it. Without Claude it falls back to "Not road-related" (`noise_fallback`). These rows get no severity, stay in `complaints_clean` for the trail, and are kept out of de-dup and open issues | Claude labelled **all 120** as non-road, with no false positives. Open issues went from 658 to **617**. The M3 plan is now 123 repairs worth ₹80.4 L |
| 1 | `extract_complaint` start-up wasn't thread-safe and could crash with `KeyError` | Built once under a lock, both objects published together | Test runs 80 calls on 8 threads |
| 7 | Summaries mislabelled helpline English notes as "original text in mr", and stated the inferred category as if the citizen reported it | Reliable text is kept verbatim. Other text says "not translated; classified as X from <source>" | |
| 8 | "knee deep" triggered Waterlogging on pothole and cave-in texts; "Pot-hole" matched nothing | Keyword patterns fixed | 7 complaints now decided by text instead of Claude. English text matching two categories went from 6 to 0 |
| 9 | Fallback used keywords from non-English text that is close to random | Fallback reads keywords only from reliable text, otherwise uses "Pothole" | Fallback on Claude's real traffic: **28.6%** (was about 19%) |
| 10, 18 | Docstring and README numbers were stale (old 150/166-case sets, "87%", "~26%", "90–98%", "150 complaints") | New `python -m evals.measure_routing` recomputes every figure. Docs now quote its output | |
| 12 | A malformed cache file could still raise into the app; a cache file with a byte-order mark was ignored | Cache entries are validated, a BOM is tolerated, and M1 also guards the call | |
| 15 | Answers from the server-side fallback model were cached as the main model's answers | Not cached any more | |

### What changed in the eval harness

| # | Finding | Fix |
|---|---|---|
| 2, 6 | The free `rules` target replayed old results after the app code changed | Free targets always run from scratch. A test changes the app between two runs |
| 3 | `--judge` and plain runs shared one folder, so judge metrics showed 0% or their columns disappeared | Judge setting is part of the run identity. Metrics are computed only over rows that have them (`n/a` otherwise). Judge columns are never dropped |
| 4 | "Policy-neutral" and "constant error" claims about the answerability guard were false: rules score 100% on the kept cases **by construction** | The claims are corrected in the code and README. The main suite is described as a regression check. The rows without reliable evidence are measured separately (next row) |
| 5 | The "ambiguous" slice barely reached Claude (5 cases, all already solved by the fallback) | Removed. New suite **`extraction_routed`** holds exactly the 21 linked complaints M1 sends to Claude (none with reliable evidence). Free baselines: rules fallback 28.6%, citizen 0%. This is where Claude's category value can be checked |
| 11 | `--fresh` didn't make reps independent | `LLM_CACHE_READ=0`: no cache reads, so every call is a new sample |
| 13 | `--judge` on a free target made paid judge calls without the approval gate | Gated |
| 14 | Claude refusals in the ablation were scored using the rules answer | Refusals go to `errors.jsonl`. In `app` runs they're counted and printed |
| 16 | A `.env` saved as UTF-8 with BOM lost the key silently; a UTF-16 `.env` crashed every eval and test collection | Both encodings load. An unreadable file prints a warning instead of crashing |
| 17 | `--suite narrative --target claude` sent you to approve the harness first | Rejected before any setup |
| 21 | The test suite and `rules` target could in principle reach the committed Claude cache | Both use an empty scratch cache. A test checks `LLM_DISABLE` ignores a filled cache |
| — | Paid runs could resume after an M1 code change and mix two app versions | Run identity includes an app-code fingerprint, and the message says what changed |

### Tests (findings 19 to 22 plus the fixes above)

**150 tests now (was 113).** New ones cover:
- pipeline category accuracy at least 97% on linked complaints (the DataFrame path, not just `route()`), and a sane source mix;
- junk complaints: all 120 caught, and nothing else;
- `extract()` agreeing row by row with `classify()`;
- the Claude-only flag reaching the app;
- the thread-safety stress test;
- cache robustness and `LLM_CACHE_READ`;
- a failed Claude call going to the errors file through the **real** per-thread path (the old test mocked it);
- free re-runs after a code change, judge identity, refusals, `.env` encodings and the gate order.

All **17 free eval gates** pass; risk backtest Spearman is 0.646 against 0.586 for the baseline.

### Outputs regenerated (Claude on)

**M1:**
- **Sources:** text 2,869, photo 2,838, citizen 650, Claude 144 (0 fallbacks).
- **Linked accuracy with Claude:** 98.3%.
- **De-dup F1:** 0.758.

**M3:** builds from M1's 617 real open issues, and all 24 memos are written by Claude.

**M2:** unchanged.

The database rebuilt itself.

**Your step:** the eval cases, runner and M1 code changed, so approve each paid suite again after reading [evals/cases/REVIEW.md](../evals/cases/REVIEW.md):
- `--suite extraction --target app --approve-harness`
- `--suite extraction_routed --target app --approve-harness`

The earlier 166-case runs are archived with the suffix `-166-cases-before-review-fixes`.

## 13. The app reads the database, and Claude stops guessing where there's no evidence

### The web app now reads the database

**The problem:** Devansh's React app (`app/`) read JSON built by `app/export_data.py` straight from the parquet and CSV files, bypassing the database. `outputs/csv/` wasn't refreshed by any run either.

**The fix:**
- `app/export_data.py` now reads only the SQLite database through `pipeline.db`: tables, `meta`, `narratives` and `geo_layers`.
- **Verified identical output:** a deep comparison of all 13 JSON files from the old file-based export and the new database-based one found no differences.
- **Every database rebuild re-exports everything downstream** (`pipeline/db/sync.py` `export_all`, called after a module run, `python -m pipeline` and `python -m pipeline.db`):
  - the app's `app/public/data/*.json`;
  - `outputs/csv/*.csv`, now including the judge-checkable `audit_flags.csv`, `billing_anomalies.csv` (493 warranty jobs, 114 over-bills, 45 double bills), `budget_plan.csv` and `road_risk.csv`. The rubric assessment ranked this as its highest-value action.
- **Freshness checks:** `app/public/data/manifest.json` and `outputs/csv/README.txt` record which database build they came from, and `tests/test_db.py` fails if either is stale.
- **Proof the files aren't read:** a test disables the parquet and CSV readers and confirms the export still works from the database alone.

### Claude no longer guesses on complaints with no evidence

**The problem:** Sanjay's paid `extraction_routed` run found that, on the 21 linked complaints with no reliable evidence (non-English app text, vague citizen category, no photo), **Claude was right 19.0% of the time against 28.6% for simply answering the most common category**. The text in these complaints doesn't describe the real problem in this data.

**The fix:**
- These complaints now get the most common category, with source `no_evidence`, a summary that says "needs a field check", and **no Claude call**.
- The free re-run (`v1`) confirms it: **28.6%** category, and severity within one **71.4% against 57.1%**.
- Claude is now used for category only on the 120 junk complaints, where it labelled all 120 correctly.
- The case files didn't change, so the existing harness approval is still valid.

### Outputs regenerated

- **M1:** text 2,869, photo 2,838, citizen 650, Claude 120, no_evidence 24.
- **M3:** builds from 614 open issues; 122 repairs, ₹82.6 L.

### API credit ran out

**10 of the 24 ward memos are templates.** The Anthropic account's credit ran out partway through: the API now answers *"Your credit balance is too low"*, which is an HTTP 400 error. M3 fell back to its template as designed and nothing crashed. The other 14 memos came from the cache.

**To restore them:** add credit (Anthropic Console, Plans & Billing), then run `python -m pipeline`. Only the 10 missing memos will be requested; everything else is cached.

Until then, paid evals will record each call as a `serving_error` instead of scoring it.

**Tests:** 150 → **157**, all passing; all 17 eval gates pass.
