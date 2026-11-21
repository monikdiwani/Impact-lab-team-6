import { FLAG_LABEL, inr, short } from "../../lib/format";

/* Client-side CSV export of the currently filtered flag rows (for ward officers). */

/**
 * Evidence strings from the pipeline group digits the Western way (₹331,958).
 * Every amount in them is a plain integer after a rupee sign, so regroup them
 * Indian style (₹3,31,958) to match the Billed and At risk columns.
 */
export function evidenceText(s) {
  return (s || "").replace(/₹(\d[\d,]*\d|\d)/g, (_, d) => inr(Number(d.replace(/,/g, ""))));
}

const COLUMNS = [
  ["flag_id", (r) => r.flag_id],
  ["flag_type", (r) => r.flag_type],
  ["flag", (r) => FLAG_LABEL[r.flag_type] || r.flag_type],
  ["severity", (r) => r.severity],
  ["work_order_id", (r) => r.work_order_id],
  ["related_work_order_id", (r) => r.related_work_order_id],
  ["ward_code", (r) => r.ward_code],
  ["ward_name", (r, ctx) => ctx.wardName.get(r.ward_code)],
  ["road_id", (r) => r.road_id],
  ["contractor_id", (r) => r.contractor_id],
  ["contractor", (r, ctx) => short(ctx.names[r.contractor_id])],
  ["billed_inr", (r) => r.billed_inr],
  ["expected_inr", (r) => r.expected_inr],
  ["amount_at_risk_inr", (r) => r.amount_at_risk_inr],
  ["evidence", (r) => evidenceText(r.evidence)],
];

function cell(v) {
  if (v == null) return "";
  const s = String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(rows, ctx) {
  const head = COLUMNS.map(([h]) => h).join(",");
  const body = rows.map((r) => COLUMNS.map(([, get]) => cell(get(r, ctx))).join(","));
  return [head, ...body].join("\r\n");
}

/** file name that says what was filtered: flags_OVERBILL_ward-A.csv */
export function csvName(f) {
  const bits = ["flags"];
  if (f.type) bits.push(f.type);
  if (f.ward) bits.push(`ward-${f.ward.replace(/\//g, "-")}`);
  if (f.contractor) bits.push(f.contractor);
  if (f.severity) bits.push(f.severity);
  if (f.q) bits.push("search");
  return `${bits.join("_")}.csv`;
}

export function downloadCsv(text, filename) {
  // BOM so Excel reads the rupee sign in the evidence column correctly
  const blob = new Blob(["﻿", text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
