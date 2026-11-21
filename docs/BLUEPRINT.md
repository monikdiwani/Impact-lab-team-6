# Team 6 Blueprint: "Follow the Rupee" Accountability Platform

> All data is synthetic and every contractor is fictional. The numbers below come from running the analysis on `data/` and were checked by hand. They are not estimates.

---

## 1. Problem analysis

The judges score a **tool**, not a platform. The rubric in `STARTER_IDEAS.md` decides what we build:

| Criterion | Weight | What it means for us |
|---|---|---|
| Audit accuracy | 25% | Scored against a hidden answer key, so precise rules beat clever ML |
| Fair accountability | 20% | Every score has to be explainable, adjusted for context, and backed by work-order IDs |
| Budget recommendation | 20% | Also scored against the answer key. Needs a ranked list plus a repair method |
| Connects the trail | 15% | Complaint → work order → road → contractor, visible end to end |
| Usable by a real person | 10% | A ward officer or citizen can act on what they see |
| Demo and clarity | 10% | A working demo that tells a story |

So **65% of the score is audit, scorecards and budget.** Complaint clean-up only supports those.

## 2. What's in the dataset (checked)

Coverage: 2,499 work orders, 6,501 complaints, 8 contractors, 24 wards and 291 road segments, Jun to early Oct 2025. Total spend is ₹13.43 Cr against ₹14.91 Cr budgeted.

### How the tables join
```
complaints.complaint_id ◄── work_orders.linked_complaint_ids  (pipe "|" separated)
work_orders.road_id ──► roads (under_dlp, last_resurfaced, bus_route) ──► traffic
work_orders.repair_method ──► rate_card (per sqm | per job)
work_orders.contractor_id ──► contractors      (every contractor works in all 24 wards)
work_orders.ward_code ──► wards (budget, low_lying_index, crews)
facilities.ambulance_entry_road, accidents.road_id ──► roads
flood_hotspots (lat/lon, ward) · rainfall_daily (2 stations/day) · tides (2 rows/day)
```

### Anomalies found in the data

| # | Signal | Rule we tested | Hits | ₹ involved | Notes |
|---|---|---|---:|---:|---|
| A1 | **Over-billing** | cost ÷ (rate × area, or flat rate) > 1.30 | 114 (109 above 1.5×) | ₹44.8 L above the 1.3× tolerance | Normal jobs fall between 0.75 and 1.30. Concentrated in Mahalaxmi (42) and Arabian Sea (37) |
| A2 | **Double billing** | no linked complaint AND an earlier WO on the same road and work type within 7 days | **45** | ₹25.9 L | All 45 unlinked WOs match this rule exactly (IDs around WO25-0245x to 02500). Very likely a planted pattern |
| A3 | **DLP violation** | `roads.under_dlp = Y` and BMC paid | 493 WOs on 61 roads | ₹2.62 Cr | Should have been repaired free by the original contractor. The original contractor isn't in the data, so we flag the road, not who did the repair |
| A4 | **SLA breach** | `sla_met = N` | 1,259 (50%) | | Recomputed from the first linked complaint to completion, it matches 99.96% (1 boundary case). We trust the column |
| A5 | **Failed repair** | `reopened_within_30d = Y` | 611 (24%) | ₹3.07 Cr | 82% have a follow-up WO on the same road within 30 days. That's money spent twice |
| A6 | Contractor pattern | re-open / SLA / over-billing by contractor | | | Re-open rate ranges from **9% (Deccan) to 39% (Western Coast)**. Mahalaxmi is worst on SLA (39%) **and** over-billing |

Things we checked so that our fairness story holds up:
- Every contractor works in all 24 wards, so geography doesn't explain the gaps between them. Ward `low_lying_index` actually correlates *negatively* with re-open rate (−0.21).
- Repair **method** does matter: cold mix re-opens 32% of the time, dewatering 14%. Contractor durability scores must be **adjusted for method mix** (see M2).
- 284 WOs were assigned *before* their first linked complaint. That's ambiguous (complaints may have been linked later), so we show it as context, not as a flag.

### Complaints
- Status: 3,934 Resolved, **1,014 Closed-Duplicate**, **896 Open/In Progress**, and 657 rejected or forwarded.
- **All 4,948 linked complaint IDs exist, and duplicates are linked to WOs too.** The data has ground truth for de-duplication, so we can *measure* how accurate our de-dup is.
- Gaps: `ward_code` is missing in 457 rows and lat/lon in 2,724. About 18% of categories are wrong or vague ("Road related", "Other").
- Languages: en 3,626 · hi-en 1,538 · mr 805 · hi 532. `localities.csv` aliases include Devanagari.
- **The 896 open complaints are the demand side for the budget planner.**

### What each requirement can be built from

| Requirement | Supported by | Possible? |
|---|---|---|
| Clean, de-dup and geocode complaints | complaints, localities, wards.geojson | ✅ |
| Link complaints → WOs | `linked_complaint_ids` (given) | ✅ already linked. We validate it and expose it |
| Rate-card, double-billing, DLP and SLA checks | work_orders, rate_card, roads | ✅ |
| "Did it last?" | reopened_within_30d + follow-up WOs | ✅ |
| Payments | ❌ no payments table. `cost_inr` is the billed amount, so we call it "billed", never "paid out" |
| Risk: rain, tides, flooding, traffic, accidents, facilities | all present | ✅ (rain and tides are city-level only, 2 stations) |
| Photo analysis | `photo_description` text only | ⚠️ text stand-in only |

## 3. Solution and what makes it different

**"Follow the Rupee": one app that traces each rupee from complaint to repair to outcome and then to the next rupee.**

What sets it apart:
1. **Traceability:** click any ward, contractor or flag and drill down to the actual work orders and the citizen complaints behind them.
2. **A rupee-denominated audit:** "₹2.62 Cr billed on roads still under warranty" lands harder than a count.
3. **Fair scorecards:** method-mix-adjusted durability, context notes (low-lying ward, heavy-rain week), and neutral wording ("needs review", never "fraud").
4. **A next-rupee planner:** a ranked road list per ward, sized to the *remaining* budget, with a durable repair method and a one-line reason for each. DLP roads get routed to "make the contractor fix it, ₹0".
5. **Claude where it adds value:** multilingual complaint parsing, plain-language scorecards and ward reports, and a citizen "what happened to my complaint?" lookup. **Every number is computed by pandas. Claude only explains numbers it is given.**

## 4. Technology stack (recommended)

| Layer | Choice | Why |
|---|---|---|
| Language | **Python only** | One language for 4 people with no context switching. Pandas is what the data needs |
| Data processing | pandas + numpy | Data is small (about 12k rows), runs in seconds |
| Storage | **Parquet/JSON files in `outputs/`** | No DB to set up. Each member owns their own output files, so there are no merge conflicts |
| Frontend + backend | **Streamlit (multipage)** | UI and server in one, 4 people can work on separate pages, deploys free |
| Charts | Plotly | Interactive, works natively in Streamlit |
| Maps | pydeck (`GeoJsonLayer` for wards, `PathLayer` for roads) | Ships with Streamlit. No geopandas needed |
| Geo maths | numpy haversine + shapely (point-in-polygon only) | Avoids the geopandas install on Python 3.14 |
| LLM | `anthropic` Python SDK, model `claude-opus-5-5` | Structured outputs for extraction, plain text for narratives |
| Deploy | Streamlit Community Cloud from `main` (backup: run locally) | Takes 5 minutes |

**No FastAPI and no React.** A separate API layer would double the integration work with no gain for judges. Our "API" is a set of **Python function signatures plus frozen output schemas** (section 10).

**Claude usage rules** (one shared wrapper, `pipeline/common/llm.py`):
- Model `claude-opus-5-5`. Thinking is always on, so control depth with `output_config={"effort": "low"}` for bulk extraction and `"medium"` for narratives.
- Use structured outputs (`output_config.format`) for complaint extraction. Don't use forced `tool_choice` or assistant prefill (both return a 400 on this model).
- **Cache every response to `outputs/llm_cache/*.json`, keyed by a prompt hash, and commit the cache.** The demo must not depend on live API calls or on the venue Wi-Fi.
- If there's no API key, fall back to a template string so the app never crashes.
- Handle `stop_reason == "refusal"` and enable server-side `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`).

## 5. System architecture

```
                 ┌──────────────── data/*.csv, *.geojson (read-only) ───────────────┐
                 ▼                          ▼                          ▼
   ┌─────────────────────────┐ ┌─────────────────────────┐ ┌─────────────────────────┐
   │ M1  pipeline/connect    │ │ M2  pipeline/audit      │ │ M3  pipeline/risk       │
   │ clean · dedup · geocode │ │ rate · dup · DLP · SLA  │ │ road/ward risk · plan   │
   │ multilingual · links    │ │ scorecards (adjusted)   │ │ method choice · budget  │
   └──────────┬──────────────┘ └──────────┬──────────────┘ └──────────┬──────────────┘
              │ complaints_clean.parquet  │ audit_flags.parquet       │ road_risk.parquet
              │ open_issues.parquet ──────┼──────────────────────────►│ budget_plan.parquet
              │ wo_trail.parquet          │ contractor_scorecard      │ ward_risk.parquet
              ▼                           ▼ ward_scorecard            ▼
   ┌────────────────────────────── outputs/  (schemas: contracts/schemas.py) ────────┐
   └──────────────────────────────────────┬─────────────────────────────────────────┘
                                          ▼
   ┌────────────────────────── M4  app/  (Streamlit) ───────────────────────────────┐
   │ Overview map · Ward money trail · Audit flags · Contractors · Next-rupee ·      │
   │ Complaint tracker   ── calls pipeline/common/llm.py (cached) for narratives ──  │
   └────────────────────────────────────────────────────────────────────────────────┘
```

**Data flow:** `python -m pipeline.run_all` runs M1 → M2 → M3 (M3 also reads M1's `open_issues`) and writes `outputs/`. The app only **reads** `outputs/`. Until the real outputs exist, the app reads `outputs_mock/` (same schemas). The switch is `DATA_DIR` in `app/config.py`.

## 6. Who does what

| | M1: Connect | M2: Audit and accountability | M3: Risk and budget | M4: Product and integration |
|---|---|---|---|---|
| Core | Cleaning, ward recovery, geocoding, de-dup, multilingual extraction, complaint→WO trail, open-issue list | 5 audit rules, ₹ impact, contractor and ward scorecards with fairness adjustment | Road and ward risk scores, method durability, budget allocation per ward | Repo setup, contracts, mocks, Streamlit app, maps and charts, deployment, demo |
| Claude | Extraction from multilingual text (category, severity, locality) | One-line flag explanations, citizen scorecards | "Why this road" reasons, ward budget memo | Citizen complaint tracker, ward one-pager |
| Owns | `pipeline/connect/`, `pipeline/common/` | `pipeline/audit/` | `pipeline/risk/` | `app/`, `contracts/`, `outputs_mock/`, `pipeline/run_all.py`, `requirements.txt` |
| Load | Medium-high (plus shared utilities) | High | High | High |

## 7. Responsibilities in detail

### M1: Data engineering and complaint intelligence
**Files:** `pipeline/common/io.py` (typed loaders for every CSV, UTF-8, date parsing), `pipeline/common/llm.py` (the cached Claude wrapper), `pipeline/connect/*.py`.

Build:
1. **Loaders** (do these first, everyone imports them): `load_work_orders()`, `load_complaints()` and so on, with parsed datetimes and `linked_complaint_ids` split into lists. **Push to `dev` by T+0:45.**
2. **Ward recovery** for the 457 blank wards: point-in-polygon on `wards.geojson` when there's lat/lon, otherwise an alias match on `localities.csv` (normalise case and match Devanagari aliases).
3. **De-dup:** cluster by (ward, category, 200 m radius or same locality, 72 h window) plus text similarity. **Measure it against ground truth:** complaints linked to the same WO are true duplicates. Report precision and recall on the dashboard, which earns points for "connects the trail".
4. **Multilingual extraction:** run Claude structured output on the **non-English plus "Road related"/"Other"** complaints (about 2,900 rows). That costs money, so do it in batches and cache the results. Develop on `complaints_sample_200.csv`. Output: `category_clean`, `severity_1_5`, `locality_norm`, `english_summary`.
5. **Trail:** a `wo_trail` table with one row per WO: complaint count, first complaint time, channels, total upvotes, and hours from complaint to completion.
6. **Open issues:** the 896 Open/In Progress complaints, de-duplicated into issues and attached to a `road_id` (nearest road segment midpoint inside the same ward). **This is M3's demand input.**

**Outputs:** `complaints_clean.parquet`, `wo_trail.parquet`, `open_issues.parquet`, `dedup_metrics.json`.
**Tests:** every complaint has a ward after recovery (target >98%), and the ward recovered from lat/lon matches the given ward on rows that have both (>95%).

### M2: Financial audit and contractor accountability
**Files:** `pipeline/audit/rules.py`, `pipeline/audit/scorecards.py`, `pipeline/audit/explain.py`.

Build:
1. **Rules**, each returning rows that match the `AuditFlag` schema:
   - `OVERBILL`: ratio > 1.30. Severity high above 1.5. Evidence: expected vs billed.
   - `DOUBLE_BILL`: no complaint linked + an earlier WO on the same `road_id` and `work_type` within 7 days. Evidence: the earlier WO ID.
   - `DLP_PAID`: road under DLP and cost > 0. The ₹ figure is "recoverable".
   - `SLA_MISS`: use `sla_met`. Show hours late (computed from the first complaint).
   - `REPEAT_REPAIR`: re-opened + follow-up WO ID and its cost (the "paid twice" amount).
2. **₹ impact per flag** (`amount_at_risk_inr`): the excess over 1.3× for over-billing, the full cost for double-billing and DLP, and the follow-up cost for repeat repairs.
3. **Contractor scorecard:** SLA %, re-open %, **method-adjusted re-open** (actual ÷ expected given their method mix), median cost ratio, flag counts, volume, and ₹ spent. Combine into a 0–100 score from documented weights. Grade A–E.
4. **Ward scorecard:** budget vs billed, % of spend flagged, re-open %, SLA %, and the top contractor in the ward.
5. **Claude:** a ≤120-word citizen scorecard per contractor and a one-line reason per flag. Neutral tone, cite WO IDs, and no word like "fraud" or "corrupt".

**Outputs:** `audit_flags.parquet`, `contractor_scorecard.parquet`, `ward_scorecard.parquet`, `scorecard_text.json`.
**Tests:** 45 DOUBLE_BILL, 493 DLP_PAID, and 114 OVERBILL flags. If those counts move, something broke.

### M3: Risk analysis and budget recommendation
**Files:** `pipeline/risk/road_risk.py`, `pipeline/risk/planner.py`, `pipeline/risk/explain.py`.

Build:
1. **Road risk (0–100), one row per segment**, each component normalised 0–1 with documented weights:
   - exposure: `peak_hour_vehicles`, `congestion_index`, `bus_route`/`bus_routes_count`
   - safety: accidents on the road (weight Pothole, Waterlogged and Uneven-road causes higher, Fatal > Grievous > Minor)
   - criticality: is it the `ambulance_entry_road` for a hospital (emergency = Y) or a school
   - flood: distance to the nearest `flood_hotspot` × `years_flagged_last_5`, plus a tide-sensitivity boost
   - condition: years since `last_resurfaced`, re-open history (from the WOs), and **open issues from M1**
2. **Ward risk:** `low_lying_index`, mean and max road risk, the number of hotspot flood days (rain at the nearest station > threshold), and open issues.
3. **Method choice:** per `work_type`, choose the method with the lowest re-open rate whose cost fits. Show the cost per *lasting* repair (cost ÷ (1 − re-open rate)).
4. **Planner:** remaining = budget − billed (if below 0, the ward is over budget and the plan is "reallocate / no new spend"). Fill the ward's remaining budget greedily in order of risk per rupee. **DLP roads → action "Invoke DLP, ₹0 to BMC".**
5. **Claude:** a one-line "why this road" from the component values, plus a 150-word ward budget memo.

**Outputs:** `road_risk.parquet`, `ward_risk.parquet`, `budget_plan.parquet`, `method_durability.parquet`.
**Tests:** the risk components sum to the score, the plan never exceeds the remaining budget, and DLP roads cost ₹0.

### M4: Frontend, integration and product
**Files:** `contracts/schemas.py`, `outputs_mock/`, `app/Home.py`, `app/pages/*.py`, `app/components/*.py`, `app/config.py`, `pipeline/run_all.py`, `requirements.txt`, `.streamlit/`.

Build:
1. **In the first 45 min:** the repo skeleton, `contracts/schemas.py`, and `outputs_mock/` generated by `contracts/make_mocks.py` (fake rows with the correct columns), so the other three members can code against them right away.
2. **Pages:**
   1. **Overview:** a city KPI strip (₹ billed, ₹ flagged, ₹ under DLP, re-open %) and a ward choropleth (toggle: % spend flagged, risk, budget used).
   2. **Ward money trail:** budget vs billed, spend by contractor and method (bar), ₹ on failed repairs, the Claude one-pager.
   3. **Audit flags:** a filterable table (type, ward, contractor), ₹ at risk, and a drill-down into one WO showing its complaints, road, contractor, and **evidence**.
   4. **Contractors:** a leaderboard, a per-contractor card with Claude text, and a "fairness notes" expander.
   5. **Next rupee:** a ward picker, a ranked plan table, the road map coloured by risk, and the reason for each row.
   6. **Complaint tracker:** enter a complaint ID (or a question in any language) and get the WO, contractor, cost, SLA, and whether the fix held up.
3. **Integration:** the `run_all.py` orchestrator, the switch from mocks to real data, and deployment.

**Tests:** every page loads with mocks and with the real outputs, and nothing crashes with no API key.

## 8. Repository structure

```
Impact-lab-team-6/
├── CLAUDE.md  README.md  DATA_DICTIONARY.md  STARTER_IDEAS.md
├── docs/BLUEPRINT.md
├── requirements.txt              # M4 owns; others ask in chat
├── data/                         # read-only, never edit
├── contracts/
│   ├── schemas.py                # M4 owns; changes need all 4 to agree
│   └── make_mocks.py
├── outputs_mock/                 # M4: fake files that follow the schemas
├── outputs/                      # generated; each file owned by its producer
│   └── llm_cache/                # committed Claude responses
├── pipeline/
│   ├── run_all.py                # M4
│   ├── common/{io.py,llm.py,geo.py}   # M1
│   ├── connect/                  # M1
│   ├── audit/                    # M2
│   └── risk/                     # M3
├── app/
│   ├── Home.py  config.py        # M4
│   ├── components/               # M4
│   └── pages/                    # M4 (M2/M3 may add a page after asking M4)
└── tests/{test_connect.py,test_audit.py,test_risk.py,test_app_smoke.py}
```

## 9. Git workflow

**Branches:** `main` (protected, always demoable) ← `dev` (integration) ← one feature branch per member:
`feat/m1-connect`, `feat/m2-audit`, `feat/m3-risk`, `feat/m4-app`. For short follow-ups, use `fix/m2-overbill-threshold`.

**Commits:** `<type>(<module>): <summary>`, for example `feat(audit): add DLP_PAID rule`, `fix(risk): cap plan at remaining budget`. Types: feat, fix, data, ui, docs, test, chore.

**Rules**
1. **Never edit another member's folder.** Ask in the team chat, and the owner makes the change.
2. Shared files (`contracts/schemas.py`, `requirements.txt`, `pipeline/common/io.py`) change only through a small PR that the owner merges after announcing it.
3. Each member writes **only their own output files**, so binary parquet files never conflict.
4. Pull `dev` into your branch at least every hour: `git pull origin dev`.
5. PRs go into `dev` and need one review: M1↔M2 review each other, M3↔M4 review each other. M4 merges `dev` → `main` at each milestone.
6. Before opening a PR, run `python -m pipeline.run_all && pytest -q`.

**M4: one-time setup (T+0:00)**
```bash
git add CLAUDE.md docs/ && git commit -m "docs: add CLAUDE.md and blueprint"
# create skeleton + contracts + mocks, then:
git add . && git commit -m "chore: project skeleton, contracts, mocks"
git push -u origin main
git checkout -b dev && git push -u origin dev
# GitHub → Settings → Branches: protect main (require PR)
```

**Every member**
```bash
git clone https://github.com/monikdiwani/Impact-lab-team-6.git
cd Impact-lab-team-6
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
git checkout dev && git pull
git checkout -b feat/m2-audit                         # your branch

# work loop
git add pipeline/audit tests/test_audit.py            # stage your own files, not "git add ."
git commit -m "feat(audit): add OVERBILL and DOUBLE_BILL rules"
git pull origin dev                                   # pick up teammates' work, resolve conflicts locally
git push -u origin feat/m2-audit
gh pr create --base dev --title "feat(audit): rules v1" --body "What/why, tests run"
```

**Merging (the reviewer)**
```bash
gh pr review <n> --approve
gh pr merge <n> --squash --delete-branch=false
```

**Release to `main` (M4, at each milestone)**
```bash
git checkout main && git pull && git merge --no-ff dev -m "release: milestone 2" && git push
```

`.gitignore`: `.venv/`, `__pycache__/`, `.env`, `.streamlit/secrets.toml`. **Don't** ignore `outputs/`. It gets committed so the deployed app works without running the pipeline.

## 10. Integration contracts (frozen at T+0:45)

### Function contracts. Each module exposes one entry point:
```python
# pipeline/connect/__init__.py  (M1)
def run(data_dir: Path, out_dir: Path) -> dict[str, Path]  # writes complaints_clean, wo_trail, open_issues
# pipeline/audit/__init__.py    (M2)
def run(data_dir: Path, out_dir: Path) -> dict[str, Path]  # writes audit_flags, contractor_scorecard, ward_scorecard
# pipeline/risk/__init__.py     (M3) reads out_dir/open_issues.parquet if present, else proceeds without
def run(data_dir: Path, out_dir: Path) -> dict[str, Path]
# pipeline/common/llm.py        (M1)
def ask(prompt: str, *, system: str, effort: str = "medium", schema: dict | None = None,
        fallback: str = "") -> str | dict          # cached; never raises; returns fallback on failure
```
**Error handling:** a module that fails logs the error and leaves the previous output files in place. `run_all` continues with the next module, and the app shows an "data unavailable" banner per section instead of crashing.

### Output schemas (`contracts/schemas.py`)

`audit_flags.parquet` (M2)
| column | type | example |
|---|---|---|
| flag_id | str | `F-DLP-0001` |
| flag_type | str enum | `OVERBILL` · `DOUBLE_BILL` · `DLP_PAID` · `SLA_MISS` · `REPEAT_REPAIR` |
| severity | str | `high` · `medium` · `low` |
| work_order_id | str | `WO25-02456` |
| related_work_order_id | str \| null | `WO25-02301` |
| ward_code, road_id, contractor_id | str | `F/S`, `RD0011`, `CT05` |
| billed_inr, expected_inr, amount_at_risk_inr | float | 61000, 25000, 28500 |
| evidence | str | `billed 2.44× rate card (₹61,000 vs ₹25,000)` |
| explanation | str | Claude or template, ≤25 words |

`contractor_scorecard.parquet` (M2): contractor_id, contractor_name, n_jobs, billed_inr, sla_pct, reopen_pct, reopen_expected_pct, durability_index, median_cost_ratio, n_flags_by_type (JSON str), amount_flagged_inr, score_0_100, grade, summary_text

`ward_scorecard.parquet` (M2): ward_code, budget_inr, billed_inr, budget_used_pct, flagged_inr, flagged_pct, reopen_pct, sla_pct, top_contractor_id, summary_text

`complaints_clean.parquet` (M1): complaint_id, received_at, channel, ward_code, ward_source (`given`/`gps`/`locality`), lat, lon, category_clean, severity_1_5, language, english_summary, issue_id, linked_work_order_id, status

`wo_trail.parquet` (M1): work_order_id, n_complaints, first_complaint_at, channels, total_upvotes, hours_to_complete

`open_issues.parquet` (M1): issue_id, ward_code, road_id, category_clean, severity_1_5, n_complaints, first_reported_at, total_upvotes

`road_risk.parquet` (M3): road_id, ward_code, road_name, risk_score, c_exposure, c_safety, c_critical, c_flood, c_condition (each 0–1), open_issues, under_dlp, reason

`budget_plan.parquet` (M3): ward_code, rank, road_id, action (`Repair`/`Invoke DLP`/`Monitor`), recommended_method, est_cost_inr, cumulative_inr, remaining_budget_inr, risk_score, reason

`ward_risk.parquet` (M3): ward_code, risk_score, low_lying_index, flood_days, open_issues, remaining_budget_inr

**Example row as JSON (budget_plan):**
```json
{"ward_code":"F/S","rank":1,"road_id":"RD0058","action":"Repair","recommended_method":"Mastic asphalt",
 "est_cost_inr":126000,"cumulative_inr":126000,"remaining_budget_inr":412000,"risk_score":91.4,
 "reason":"Ambulance route to KEM Hospital, 2 pothole accidents, 300 m from Hindmata hotspot"}
```

## 11. Timeline (assumes about 6.5 hours of build time; scale it if you have less)

| Time | Everyone | M1 | M2 | M3 | M4 |
|---|---|---|---|---|---|
| T+0:00–0:30 | Read this doc and agree on scope | | | | Repo, branches, skeleton |
| T+0:30–0:45 | **Freeze the contracts** | `io.py` loaders | Rules on paper | Weights on paper | schemas.py + mocks pushed |
| T+0:45–2:30 | Parallel build | Ward recovery, trail, open issues | 5 rules + ₹ impact | Road risk components | Overview + Audit pages on mocks |
| **T+2:30** | **M1: real outputs on `dev`** | Start Claude extraction | Scorecards | Planner | Contractors + Next-rupee pages |
| T+2:30–3:30 | | De-dup + metrics | Claude text | Uses M1's open_issues | Ward + Tracker pages |
| **T+3:30** | **Integration 1:** run_all on `dev`, app on real data, merge to main | | | | |
| T+3:30–4:45 | Fix integration bugs, polish | LLM cache filled | Fairness notes | Claude reasons | Map polish, deploy |
| **T+4:45** | **Feature freeze.** Only bug fixes after this point | | | | |
| T+4:45–5:30 | Test, deploy, record a backup video | | | | |
| T+5:30–6:30 | Slides and rehearsal ×2 | | | | |

**Critical path:** M4's contracts and mocks at T+0:45, then M1's loaders, then M1's `open_issues` before the M3 planner. If M1 slips, M3 plans from existing WO and accident history and leaves open issues out.

## 12. MVP vs advanced

**MVP (must have by T+3:30):** 5 audit rules with ₹ figures; contractor and ward scorecards; road risk plus ward budget plan; 4 pages (Overview, Audit, Contractors, Next rupee); WO drill-down showing the linked complaints.

**Advanced, in priority order:** (1) Claude narratives (cached); (2) ward choropleth map; (3) complaint tracker; (4) de-dup metrics vs ground truth; (5) multilingual extraction on the full set; (6) a "what if" budget slider; (7) a downloadable PDF ward report.

**Don't build:** real photo analysis (we only have text), payment reconciliation (no payments data), predictive ML models (rules score better against an answer key and are easier to explain), a live social-media feed. `social_posts.csv` is only good for an optional "citizen sentiment" tile.

## 13. Testing and deployment

- `tests/` has one file per module. The audit counts in §7 act as regression checks.
- `test_app_smoke.py` imports every page module against both `outputs_mock/` and `outputs/`.
- Before every PR: `python -m pipeline.run_all && pytest -q && streamlit run app/Home.py`.
- Deploy: Streamlit Community Cloud → repo `main` → `app/Home.py`. Put `ANTHROPIC_API_KEY` in the app secrets (never in git). Committed `outputs/` and `llm_cache/` mean the deployed app makes no live LLM calls during the demo.
- Backup: run it locally on M4's laptop plus a recorded 2-minute screen capture.

## 14. Demo flow (5 minutes)

1. **Hook (20 s):** "Mumbai billed ₹13.4 Cr for monsoon road repairs. ₹2.6 Cr of that was on roads still under warranty."
2. **Overview map (40 s):** KPIs, then click a ward.
3. **Follow one rupee (90 s):** a Marathi complaint, then its work order, the contractor, billed at 2.4× the rate card, re-opened in 3 weeks, re-billed. Show the evidence panel.
4. **Accountability (60 s):** the contractor leaderboard with fairness notes ("every contractor works in all 24 wards; adjusted for repair method"). Read one Claude scorecard aloud.
5. **Next rupee (60 s):** pick a ward and show the ranked plan: "Ambulance route to KEM, mastic, ₹1.26 L. This road is under DLP, so invoke the warranty at ₹0."
6. **Close (30 s):** how a corporator or citizen would use it, what Claude did and what pandas did, and that all data is synthetic.

## 15. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Integration breaks late | Contracts frozen at T+0:45, mocks from minute one, integration at T+3:30 rather than at the end |
| Claude API slow, rate-limited or no Wi-Fi | Committed response cache, template fallbacks, extraction run in bulk once |
| LLM invents numbers | Claude only receives computed numbers and must cite WO IDs. Every number shown in the UI comes from pandas |
| Unfair or defamatory wording | Fixed tone rules in the system prompt ("needs review", no "fraud"), a fairness-notes panel, and "synthetic data" in the footer |
| Python 3.14 wheel problems | Avoid geopandas. Pin versions in `requirements.txt`. If a wheel breaks, use a Python 3.12 venv |
| Overbuilding | Feature freeze at T+4:45. MVP list first |
| Windows console encoding (Devanagari crashes `print`) | `set PYTHONIOENCODING=utf-8`, and always pass `encoding="utf-8"` |
| Thresholds differ from the answer key | Keep thresholds in one config dict (`pipeline/audit/config.py`) so they're easy to tune and show them in the UI |
