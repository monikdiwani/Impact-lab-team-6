/*
  Indian number formatting. Use these everywhere so money reads the same on every page.
    inr(9597)          -> "₹9,597"
    inr(13432818)      -> "₹1,34,32,818"
    inrShort(13432818) -> "₹1.34 Cr"
    inrShort(4476584)  -> "₹44.8 L"
    inrShort(86755)    -> "₹86,755"
*/
const grp = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function inr(x) {
  if (x == null || Number.isNaN(x)) return "-";
  return `₹${grp.format(Math.round(x))}`;
}

export function inrShort(x) {
  if (x == null || Number.isNaN(x)) return "-";
  const a = Math.abs(x);
  const sign = x < 0 ? "-" : "";
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(1)} L`;
  return `${sign}₹${grp.format(Math.round(a))}`;
}

export function num(x, digits = 0) {
  if (x == null || Number.isNaN(x)) return "-";
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(x);
}

export function pct(x, digits = 1) {
  if (x == null || Number.isNaN(x)) return "-";
  return `${Number(x).toFixed(digits)}%`;
}

/** "2025-07-08 14:30" -> "8 Jul 2025, 14:30" */
export function when(s) {
  if (!s) return "-";
  const [d, t] = s.split(" ");
  const [y, m, day] = d.split("-").map(Number);
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1];
  return `${day} ${mon} ${y}${t ? `, ${t}` : ""}`;
}

/** strip the " (synthetic)" suffix for compact labels; full names stay in tooltips and cards */
export function short(name) {
  return (name || "").replace(/\s*\(synthetic\)\s*$/i, "");
}

/* Human labels for audit flag types. Neutral wording: a flag means "needs review". */
export const FLAG_LABEL = {
  OVERBILL: "Over-billing",
  DOUBLE_BILL: "Possible double bill",
  DLP_PAID: "Paid during warranty",
  SLA_MISS: "Missed deadline",
  REPEAT_REPAIR: "Repair did not last",
};

export const FLAG_HELP = {
  OVERBILL: "Billed more than 1.3 times the rate card price for this repair method.",
  DOUBLE_BILL: "No complaint linked, and the same road got the same kind of job within 7 days.",
  DLP_PAID: "The road is still under the original contractor's warranty (defect liability period), so the city should not pay.",
  SLA_MISS: "Finished later than the deadline, counted from the first citizen complaint.",
  REPEAT_REPAIR: "The repair re-opened within 30 days. The rupee amount is the follow-up job that redid it.",
};

/* daisyUI badge class per severity */
export const SEV_BADGE = { high: "badge-error", medium: "badge-warning", low: "badge-ghost" };

/* grade -> daisyUI colour */
export const GRADE_CLASS = { A: "text-success", B: "text-success", C: "text-warning", D: "text-error", E: "text-error" };
