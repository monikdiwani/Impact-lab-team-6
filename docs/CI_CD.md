# CI / CD (GitHub Actions)

Four workflows live in `.github/workflows/`. CI is free and automatic. CD publishes the data automatically and runs the pipeline or paid evals when you ask.

| Workflow | When it runs | What it does | Cost |
|---|---|---|---|
| **CI** (`ci.yml`) | Every push and PR to `main` / `dev`, or manually | 4 parallel jobs: **lint** (syntax errors, undefined names); **database** (`outputs/follow_the_rupee.db` matches the committed outputs); **tests** (`pytest` on Python 3.12 and 3.14); **eval gates** (`python -m evals.ci_check`) | Free. No secrets, never calls Claude (`LLM_OFFLINE=1`), except the smoke job below |
| **CI: Real Claude calls (smoke)** (job in `ci.yml`) | Pushes to `main` and manual runs only, after tests and eval gates pass | `python -m evals.claude_smoke`: 3 live calls through the app's own code (M1 flags a non-road complaint, M1 reads a photo with the rules bypassed, M2 writes contractor text that must pass the eval checks), no cache. Results go in a table on the run summary. **Non-blocking:** if the key or credit fails it shows red, but CI and the data release still pass | About 2 US cents per push to `main` |
| **CD - publish data** (`cd-data-release.yml`) | After CI passes on a push to `main`, or manually | Re-checks the database is fresh, then replaces the **`data-latest`** GitHub Release with the database, the schema doc, `outputs.zip`, `llm_cache.zip` and checksums | Free |
| **CD - regenerate outputs** (`regenerate-outputs.yml`) | Manually (Actions tab → Run workflow) | Runs `python -m pipeline` on a clean machine, runs the tests, and opens a **pull request** if any output changed. Offline by default (cached Claude answers); tick *claude* to call Claude for new prompts | Free offline; paid with *claude* ticked |
| **Paid evals** (`paid-evals.yml`) | Manually | Runs `python -m evals.run_eval` for the suite and target you pick, as a new variant `v<run number>`, and uploads the results | Paid (about $1 for the full extraction suite) |

## The free eval gates (CI)

`python -m evals.ci_check` fails the build if any of these slip. It's the same command locally.

| Check | Gate |
|---|---|
| Harness sanity | extraction oracle 100%, null 0%; narrative template 100%, null 0% |
| M1 extraction, real code with Claude off (`rules`) | category ≥ 99%, severity best ≥ 99%, ward ≥ 99%, severity exact at the data's ceiling |
| M2 narrative text with Claude off (`rules`) | passes every programmatic check (numbers grounded, IDs valid, word limits, no accusations, required context) |
| M3 risk backtest | Spearman and P@20 at least as good as the naive "past work orders" baseline |

The results appear as a table on the run's summary page and as an artifact.

## One-time setup in GitHub (repo admin)

1. **Settings → Actions → General → Workflow permissions:** choose *Read and write permissions*, and tick *Allow GitHub Actions to create and approve pull requests*. The release and regenerate workflows need this.
2. **Settings → Branches → Add rule for `main`:** require a pull request, and require the status checks *Lint*, *Database matches committed outputs*, *Tests (Python 3.12)*, *Tests (Python 3.14)* and *Free eval gates*. Then nothing reaches `main` without passing CI.
3. **Settings → Secrets and variables → Actions:** add `ANTHROPIC_API_KEY`. The paid workflows and the CI smoke job use it; no other job reads it. The account needs credit, otherwise every call returns HTTP 400 "credit balance is too low".
   - If you add *Required reviewers* to the `paid-evals` environment, the smoke job waits for approval on every push to `main`. Leave the reviewers off if you want it to run unattended.
4. Optional: **Settings → Environments → `paid-evals`**, then add *Required reviewers* so every paid eval run waits for approval. The environment is created the first time the workflow runs.

## Rules the workflows enforce

- **Paid evals respect the harness approval.** If the eval files changed since the hash committed in `.claude/hillclimb/<suite>/_state.json`, the run stops. A human approves locally (`--approve-harness`) and commits `_state.json`.
- **Committed results are never overwritten.** Paid evals always write a new variant (`v<run number>`) and upload it as an artifact.
- **No stale data is published.** The data release refuses to publish if the database is older than its inputs.
- **The database's build time always changes,** so regenerate only opens a PR when real content changed.

## App deployment

There is no app yet (M4). When `app/` exists, the simplest deployment is Streamlit Community Cloud pointed at `main` and `app/Home.py`, with `ANTHROPIC_API_KEY` in its secrets. It redeploys on every push to `main`, and with the branch rule above, only code that passed CI gets there. The app should read `outputs/follow_the_rupee.db` through `pipeline.db`, or download it from the `data-latest` release.
