"""M3 tuning knobs in one place. Every weight here is documented in docs/monikdiwani.md.

risk_score = 100 * sum(WEIGHTS[k] * c_k) over the five components, so the weights
must sum to 1 and each component is already scaled to 0-1.
"""
from __future__ import annotations

# ---- road risk: component weights (sum to 1) -------------------------------------
# Tuned on the backtest (evals/backtest_risk.py) across 4 cutoffs, see docs/monikdiwani.md.
# Exposure and criticality barely predict *where* trouble happens, but they measure how
# bad it is when it does (buses, ambulances), so they keep a small share on purpose.
WEIGHTS = {
    "c_exposure": 0.05,
    "c_safety": 0.10,
    "c_critical": 0.10,
    "c_flood": 0.30,
    "c_condition": 0.45,
}

# exposure sub-weights
EXPOSURE = {"vehicles": 0.45, "congestion": 0.25, "bus": 0.30}
BUS_ROUTES_CAP = 30               # bus_routes_count at or above this scores 1.0

# safety: accident severity x cause weights, decayed by age
SEVERITY_W = {"Fatal": 5.0, "Grievous": 3.0, "Minor": 1.0}
CAUSE_W = {                       # road-condition causes are what a repair can fix
    "Pothole": 1.0,
    "Waterlogged road": 1.0,
    "Uneven road / open chamber": 1.0,
    "Skid on wet road": 0.6,
    "Poor visibility (rain)": 0.3,
}
CAUSE_W_OTHER = 0.15              # driver-behaviour causes (overspeeding, signal jump, ...)
ACCIDENT_HALF_LIFE_DAYS = 365

# criticality: facilities whose ambulance_entry_road is this road
FACILITY_W = {"hospital_emergency": 1.0, "hospital": 0.7, "school": 0.35}

# flood: proximity to hotspots
HOTSPOT_DECAY_M = 350             # exp(-distance / decay)
TIDE_BOOST = 0.25                 # tide-sensitive hotspots count 25% more
FLOOD_WARD_SHARE = 0.5            # c_flood = (1-share) * hotspot proximity + share * ward low_lying_index
STATIONS = {                      # approx. IMD observatory positions
    "Santacruz": (19.0896, 72.8656),
    "Colaba": (18.9067, 72.8147),
}
WARD_FLOOD_THRESHOLD_MM = 100     # used for wards with no hotspot

# condition sub-weights
CONDITION = {                     # road-level part (sums to 1)
    "past_work_orders": 0.45,
    "recent_work_orders": 0.20,   # last RECENT_DAYS before the as-of date
    "reopens": 0.15,
    "open_issues": 0.20,
    "age": 0.00,                  # years since last_resurfaced: no predictive signal in backtest
}
CONDITION_WARD_SHARE = 0.30       # blend in the ward's mean work orders per road (ward-wide wear)
RECENT_DAYS = 45
AGE_CAP_YEARS = 7

# ---- planner ----------------------------------------------------------------------
MIN_METHOD_JOBS = 30              # below this, a method's re-open rate is too noisy to trust
REOPEN_PRIOR_STRENGTH = 20        # Bayesian shrink of each method's re-open rate to the work-type mean
MAX_JOBS_PER_ROAD = 3             # cost a road for at most 3 jobs (one per open issue)
SURFACE_DEFAULT_WORK = {          # work type assumed when a road has no history and no open issue
    "Paver blocks": "Broken paver blocks",
}
DEFAULT_WORK = "Pothole"

# open complaints that count as unmet demand
OPEN_STATUSES = ("Open", "In Progress")
