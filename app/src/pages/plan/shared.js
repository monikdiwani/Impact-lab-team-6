/* Plan page constants shared by its sections (local to the page, not app-wide). */

export const ACTIONS = {
  Repair: {
    badge: "badge-primary badge-soft",
    line: "Paid fix from this ward's remaining budget, using the method that re-opens least.",
  },
  "Invoke DLP": {
    badge: "badge-warning badge-soft",
    line: "Still under the original contractor's warranty (DLP, defect liability period). They fix it and BMC pays ₹0.",
  },
  Monitor: {
    badge: "badge-ghost",
    line: "No paid work now: lower risk, or the ward has no money left. Keep it under watch.",
  },
};

/* The five parts of a road's risk score. risk_score = 100 x sum(weight x component), components are 0 to 1. */
export const FACTORS = [
  { key: "c_condition", label: "Road condition", help: "Past and recent repairs, repairs that re-opened, open complaints, plus wear across the ward." },
  { key: "c_flood", label: "Flood", help: "How close the road is to a known flood hotspot, and how low-lying the ward is." },
  { key: "c_safety", label: "Safety", help: "Recent accidents, weighted by severity and by whether the road surface played a part." },
  { key: "c_critical", label: "Critical facilities", help: "Hospitals and schools that use this road as their ambulance or entry road." },
  { key: "c_exposure", label: "Traffic exposure", help: "Peak-hour vehicles, congestion and bus routes." },
];

/* one shade of the accent per factor, strongest first (single accent, no extra hues) */
export const FACTOR_SHADE = [88, 66, 48, 32, 20].map(
  (p) => `color-mix(in oklch, var(--color-primary) ${p}%, var(--color-base-100))`,
);

export function factorsWithWeights(weights) {
  return FACTORS.map((f, i) => ({ ...f, weight: weights?.[f.key] ?? 0, shade: FACTOR_SHADE[i] })).sort((a, b) => b.weight - a.weight);
}

/*
  Road colour for this page. The shared riskRamp starts at a near-background tint, so low-risk
  wards (scores 11 to 45) vanished on the map, worst in dark mode. Rescale to the city range
  (scores run about 11 to 78) and keep a visible floor. Used by the map, its legend and the table dot.
*/
const CITY_MIN = 10;
const CITY_MAX = 80;
export function roadT(score) {
  const t = Math.max(0, Math.min(1, (score - CITY_MIN) / (CITY_MAX - CITY_MIN)));
  return 0.45 + 0.55 * t;
}
/* thin outline under each road so even the palest line separates from the ward fill */
export const ROAD_CASING = "color-mix(in oklch, var(--color-base-content) 40%, transparent)";
