import { WarningCircle } from "@phosphor-icons/react";
import { Kpi } from "../../components/ui";
import { inrShort, pct } from "../../lib/format";
import { href } from "../../lib/router";

/*
  Budget state for one ward: budget, billed, money left (or overspend), what the plan spends,
  a single proportional bar, the over-budget callout and the planner memo.
*/
export default function Budget({ ward, rows, donors }) {
  const budget = ward.budget_inr;
  const billed = ward.billed_inr;
  const left = ward.remaining_budget_inr;
  const over = left < 0;
  const repairs = rows.filter((r) => r.action === "Repair");
  const planInr = repairs.reduce((s, r) => s + r.est_cost_inr, 0);
  const nDlp = rows.filter((r) => r.action === "Invoke DLP").length;
  const after = left - planInr;

  // bar segments as a share of whichever is larger: the budget, or what has been committed
  const scale = Math.max(budget, billed + planInr) || 1;
  const w = (x) => `${(100 * Math.max(0, x)) / scale}%`;
  const segs = [
    { key: "billed", v: Math.min(billed, budget), cls: "bg-base-content/35", label: over ? "Billed within budget" : "Billed so far" },
    { key: "over", v: billed - budget, cls: "bg-error", label: "Over budget" },
    { key: "plan", v: planInr, cls: "bg-primary", label: "This plan" },
    { key: "left", v: budget - billed - planInr, cls: "bg-base-300", label: "Not yet allocated" },
  ].filter((s) => s.v > 0);

  return (
    <section className="enter enter-d1 rounded-box border border-base-300 bg-base-100" aria-labelledby="budget-h">
      <div className="px-5 pt-4">
        <h2 id="budget-h" className="font-semibold">
          Ward {ward.ward_code} budget
        </h2>
        <p className="mt-0.5 text-sm text-base-content/60">{ward.ward_name}. Monsoon repair budget for 2025.</p>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-5 p-5 md:grid-cols-4">
        <Kpi label="Monsoon budget" value={inrShort(budget)} />
        <Kpi label="Billed so far" value={inrShort(billed)} note={`${pct(ward.budget_used_pct)} of budget`} />
        {over ? (
          <Kpi label="Over budget by" value={inrShort(-left)} tone="text-error" note="No money left this cycle" />
        ) : (
          <Kpi label="Left to spend" value={inrShort(left)} note={`${pct((100 * left) / budget)} of budget`} />
        )}
        <Kpi
          label="This plan spends"
          value={inrShort(planInr)}
          note={
            over
              ? `No paid repairs${nDlp ? `, ${nDlp} free under warranty` : ""}`
              : `${repairs.length} paid ${repairs.length === 1 ? "repair" : "repairs"}, ${inrShort(after)} unallocated`
          }
        />
      </div>

      <div className="px-5 pb-5">
        <div className="relative flex h-3 w-full overflow-hidden rounded-full bg-base-200" role="img"
          aria-label={segs.map((s) => `${s.label} ${inrShort(s.v)}`).join(", ")}>
          {segs.map((s) => (
            <span key={s.key} className={`h-full ${s.cls}`} style={{ width: w(s.v) }} />
          ))}
          {over && (
            <span className="absolute inset-y-0 w-0.5 bg-base-100" style={{ left: w(budget) }} aria-hidden />
          )}
        </div>
        <ul className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-sm text-base-content/70">
          {segs.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span className={`size-2.5 rounded-full ${s.cls}`} aria-hidden />
              {s.label} <span className="num font-medium text-base-content">{inrShort(s.v)}</span>
            </li>
          ))}
        </ul>
      </div>

      {over && (
        <div className="px-5 pb-5">
          <div role="status" className="alert alert-error alert-soft items-start">
            <WarningCircle size={20} className="mt-0.5 shrink-0" aria-hidden />
            <div className="flex flex-col gap-1">
              <div className="font-medium">
                Over budget by <span className="num">{inrShort(-left)}</span>: the plan adds no new paid repairs.
              </div>
              <div className="text-sm">
                Reallocate from wards with money left.
                {donors.length > 0 && (
                  <>
                    {" "}Most left after their own plan:{" "}
                    {donors.map((d, i) => (
                      <span key={d.ward_code}>
                        {i > 0 && ", "}
                        <a className="link font-medium" href={href("plan", d.ward_code)}>
                          {d.ward_code}
                        </a>{" "}
                        <span className="num">{inrShort(d.after)}</span>
                      </span>
                    ))}
                    .
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {ward.memo && (
        <div className="border-t border-base-300 px-5 py-4">
          <h3 className="text-sm font-medium text-base-content/60">Planner memo</h3>
          <p className="mt-1.5 max-w-4xl leading-relaxed">{ward.memo}</p>
        </div>
      )}
    </section>
  );
}
