"""Every M2 threshold and weight in one place (blueprint §15: easy to tune, shown in the UI).

If you change a rule threshold here, change tests/planted.py and the expected counts in
tests/test_audit.py in the same PR.
"""
from __future__ import annotations

# ---- audit rules ---------------------------------------------------------------
OVERBILL_RATIO = 1.30          # billed / rate-card expected above this is flagged
OVERBILL_HIGH_RATIO = 1.50     # ... and above this the severity is "high"
DOUBLE_BILL_DAYS = 7           # unlinked WO within this many days of an earlier same road + work type WO
REPEAT_WINDOW_DAYS = 30        # follow-up WO on the same road within this many days of completion
SLA_HIGH_LATE_FACTOR = 1.0     # hours late > sla_hours * factor  -> severity high
SLA_MEDIUM_LATE_HOURS = 24     # hours late > this                -> severity medium, else low

# ---- contractor score (0-100) ----------------------------------------------------
# Rates only, never raw counts, so a contractor is not penalised for doing more work.
# DLP_PAID is left out: the original (warranty) contractor is not in the data, so we
# flag the road, not whoever did the repair.
SCORE_WEIGHTS = {
    "durability": 0.40,   # method-adjusted re-open rate (actual vs expected for their method mix)
    "sla": 0.30,          # share of jobs that met the deadline
    "billing": 0.30,      # share of jobs with no OVERBILL / DOUBLE_BILL flag
}
# billing component = 1 - BILLING_PENALTY * (overbill + double_bill flags) / n_jobs, clipped to 0-1
BILLING_PENALTY = 4.0
# durability component = 1.5 - (actual re-open / expected re-open), clipped to 0-1
#   0.5x expected -> 1.0, as expected -> 0.5, 1.5x expected -> 0.0
GRADE_CUTOFFS = [(80, "A"), (65, "B"), (50, "C"), (35, "D"), (0, "E")]

# Flags that carry money for "flagged_inr". SLA_MISS has no ₹ impact.
MONEY_FLAGS = ("OVERBILL", "DOUBLE_BILL", "DLP_PAID", "REPEAT_REPAIR")

# Words the explanations must never use (tests + evals police the same list).
BANNED_WORDS = (
    r"\b(?:fraud\w*|corrupt\w*|scam\w*|theft|thief|thieves|stole|steal\w*|loot\w*|"
    r"embezzl\w*|kickback\w*|cheat\w*|swindl\w*|ghotala|bhrashtachar)\b"
)

WORD_LIMITS = {"contractor": 120, "ward": 150, "flag": 25}

DEFINITIONS = {
    "reopen_window_days": REPEAT_WINDOW_DAYS,
    "rate_card_tolerance_pct": round((OVERBILL_RATIO - 1) * 100),
    "double_bill_window_days": DOUBLE_BILL_DAYS,
}


def inr(x: float) -> str:
    """Indian digit grouping: 195064 -> '₹1,95,064', 13432818 -> '₹1,34,32,818'."""
    n = int(round(abs(x)))
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = f"{head},{tail}"
    return f"{'-' if x < 0 else ''}₹{s}"
