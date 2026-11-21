# M1 test and eval results (Ganesh)

Run on 2025-11-21 against the commands in `sanjay command.md`. Results are unedited. Where something is weak or not run, it says so.

**Setup:** `ANTHROPIC_API_KEY` is not set and `outputs/llm_cache/` is empty. Every extraction in this run came from the keyword fallback, not from Claude.

## 1. Free regression test: `pytest tests/test_connect.py -q -s`

Result: **7 passed**, no failures (about 60 s). Rerun after the dedup improvement; the first run scored F1 0.606 and took 9.5 s.

| Check | Required | Result | Verdict |
|---|---|---|---|
| Output files match the contract | no schema problems | passed | Correct |
| No complaints lost | all 6,501 ids present and unique | passed | Correct |
| Ward coverage | at least 98% | passed (100%: 6,044 given, 271 from GPS, 186 from locality) | Correct |
| Recovered wards correct | at least 90% on blank-ward rows | passed | Correct |
| Work-order links preserved | 100% | passed | Correct |
| De-dup F1 vs real linked groups | at least 0.60 | **precision 0.713, recall 0.684, F1 0.698** | Correct (after improvement; the first version scored 0.620 / 0.592 / 0.606) |
| Open issues | `road_id` on at least 90%, severity 1 to 5, unique ids | passed (687 issues) | Correct |

## 2. Eval harness self-checks (free)

These confirm the harness itself works. They say nothing about my code.

| Target | Expected | Got | Verdict |
|---|---|---|---|
| oracle | 100% | 100% on every metric | Correct |
| null | 0% | 0% on every metric | Correct |
| citizen | category 56.7% | category **56.7%**, severity ±1 68.7%, ward 80.0% | Correct (matches the bar) |

## 3. Eval on M1's code (`--target app`): **not run**

The harness refuses with "no approved harness". Approval needs `--approve-harness`, a human step that `CLAUDE.md` says not to do on your behalf, and it comes after reviewing `evals/cases/REVIEW.md`. So the official steps 2, 3 and 4 (the 10-case pilot, the full run, a prompt variant) were **not run**. There are no official scores for M1.

Also, the paid runs would need an API key, which isn't set here, and the harness would not use Claude without one.

### Unofficial measurement (not the harness)

I called `pipeline.connect.extract.extract_complaint` directly on the same 150 cases and compared with the expected answers. This is the **keyword fallback only, with no Claude**. It is a rough guide, not a harness result.

| Metric | Result | Citizen bar | Verdict |
|---|---|---|---|
| Category | **102/150 = 68.0%** | 56.7% | Above the bar |
| Category on `cat_right` | 85/85 = 100% | | Correct |
| Category on `cat_wrong` (fixing the citizen's mistakes) | **17/65 = 26.2%** | 0% | Weak. This is the number Claude is meant to improve |
| Category on `blank_ward` | 27/30 = 90.0% | | |
| Category by language | en 70.8%, hi-en 79.4%, mr 62.2%, hi 58.1% | | Hindi and Marathi are weakest |
| Severity exact | 40/150 = 26.7% | 23.3% | Barely above the bar |
| Severity within ±1 | 112/150 = 74.7% | 68.7% | Slightly above the bar |
| Ward overall | 150/150 = 100% | 80.0% | Correct |
| Ward on blank-ward cases | 30/30 = 100% | 0% | Correct |

Notes on these numbers:
- Ward recovery is strong, but this test set only has 30 blank-ward cases.
- I did not score language. `extract_complaint` returns the `language` it is given, so scoring it would be meaningless.
- Category accuracy comes almost entirely from trusting the citizen's category when it is specific. The fallback fixes only a quarter of wrong categories.
- Severity from the fallback is a crude keyword rule, and it is mostly wrong on exact match.

## 4. Summary

- **Correct and passing:** all 7 pipeline tests, including ward recovery, link preservation and open issues. The three harness self-checks also match.
- **Improved:** de-dup F1 went from 0.606 to 0.698 using a pair model with average-linkage clustering, scored out-of-fold by ward.
- **Weak:** category on wrong citizen categories (26.2%) and exact severity (26.7%).
- **Not done:** the official Claude extraction eval, because the harness is not approved and no API key is set. The real "Claude fixed the citizen's mistakes" number does not exist yet.

## To finish the eval

1. Review `evals/cases/REVIEW.md`.
2. Set `ANTHROPIC_API_KEY`.
3. Run the 10-case pilot with `--approve-harness`, then the full `--target app` run.
4. Replace section 3 of this file with the official numbers.
