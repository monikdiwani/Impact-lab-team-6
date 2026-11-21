import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowRight, ArrowSquareOut, Info } from "@phosphor-icons/react";
import { useData, load, byKey } from "../lib/data";
import { inr, inrShort, num, pct, short } from "../lib/format";
import { href, go } from "../lib/router";
import { PageHeader, Panel, Kpi, Loaded, EmptyState, FlagBadge, SevBadge, WardSelect, ContractorName } from "../components/ui";
import MumbaiMap from "../components/MumbaiMap";
import { useWorkOrder } from "../components/WorkOrderPanel";

/*
  Ward money trail: one ward at a time. Where its monsoon repair money went and whether the work held up.
  Route: #/wards (defaults to the ward with the highest share of spend flagged) or #/wards/<code>.
*/

export default function Wards({ id }) {
  const state = useData(["wards", "flags", "contractor_names", "summary"]);
  return (
    <Loaded state={state} what="ward data">
      {([wards, flags, names, summary]) => <WardPage id={id} wards={wards} flags={flags} names={names} summary={summary} />}
    </Loaded>
  );
}

/**
  work_orders.json (1.5 MB, cached by load()) is needed twice on this page:
  - the spend split, because the current export leaves wards.spend_by_contractor / spend_by_method null;
  - the flags table, to name the contractor who billed a follow-up (redo) job.
  A failed fetch is retried whenever the ward changes (load() drops failed promises from its cache).
*/
function useWorkOrders(wardCode) {
  const [wo, setWo] = useState({ rows: null, error: null });
  useEffect(() => {
    if (!wardCode) return;
    let alive = true;
    setWo((s) => (s.error ? { rows: null, error: null } : s));
    load("work_orders")
      .then((rows) => alive && setWo((s) => (s.rows === rows ? s : { rows, error: null })))
      .catch((error) => alive && setWo({ rows: null, error }));
    return () => {
      alive = false;
    };
  }, [wardCode]);
  return wo;
}

/* Spend split for one ward: from wards.json when the export has it, else summed from work_orders.json. */
function useWardSpend(ward, wo) {
  const ready = ward?.spend_by_contractor && ward?.spend_by_method;
  return useMemo(() => {
    if (!ward) return { loading: false };
    if (ready) return { byContractor: ward.spend_by_contractor, byMethod: ward.spend_by_method, loading: false };
    if (wo.error) return { error: wo.error, loading: false };
    if (!wo.rows) return { loading: true };
    const byContractor = {};
    const byMethod = {};
    for (const r of wo.rows) {
      if (r.ward_code !== ward.ward_code) continue;
      byContractor[r.contractor_id] = (byContractor[r.contractor_id] || 0) + (r.cost_inr || 0);
      byMethod[r.repair_method] = (byMethod[r.repair_method] || 0) + (r.cost_inr || 0);
    }
    return { byContractor, byMethod, loading: false };
  }, [ward, ready, wo]);
}

function WardPage({ id, wards, flags, names, summary }) {
  const sorted = useMemo(() => [...wards].sort((a, b) => a.ward_code.localeCompare(b.ward_code, "en", { numeric: true })), [wards]);
  const topFlagged = useMemo(() => [...wards].sort((a, b) => (b.flagged_pct ?? 0) - (a.flagged_pct ?? 0))[0], [wards]);
  const ward = id ? wards.find((w) => w.ward_code === id) : topFlagged;

  const wardFlags = useMemo(() => (ward ? flags.filter((f) => f.ward_code === ward.ward_code) : []), [flags, ward]);
  const wo = useWorkOrders(ward?.ward_code);
  const spend = useWardSpend(ward, wo);
  const woById = useMemo(() => (wo.rows ? byKey(wo.rows, "work_order_id") : null), [wo.rows]);
  const rowsHint = Math.max(Object.keys(spend.byContractor || {}).length, Object.keys(spend.byMethod || {}).length);

  if (!ward) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Ward money trail" />
        <div className="rounded-box border border-base-300 bg-base-100">
          <EmptyState
            title={`No ward called "${id}"`}
            hint="Ward codes look like A, F/S or K/E. Choose a ward below, or open the ward with the most spend flagged."
            action={
              <div className="mt-2 flex flex-col items-center gap-3">
                <label className="flex flex-col gap-1.5 text-left" htmlFor="ward-missing-select">
                  <span className="text-sm text-base-content/70">Choose a ward</span>
                  <select
                    id="ward-missing-select"
                    className="select select-sm w-60"
                    defaultValue=""
                    onChange={(e) => e.target.value && go("wards", e.target.value)}
                  >
                    <option value="" disabled>
                      Select a ward
                    </option>
                    {sorted.map((w) => (
                      <option key={w.ward_code} value={w.ward_code}>
                        {w.ward_code}: {w.ward_name}
                      </option>
                    ))}
                  </select>
                </label>
                <a className="btn btn-sm btn-primary" href={href("wards")}>
                  Open the ward with the most spend flagged
                </a>
              </div>
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={
          <>
            <span className="font-mono">{ward.ward_code}</span>
            <span className="text-base-content/40"> </span>
            {ward.ward_name}
          </>
        }
        lede="Where this ward's 2025 monsoon road repair money went, and whether the work held up."
        actions={<WardSelect wards={sorted} value={ward.ward_code} onChange={(c) => c && go("wards", c)} label="Choose a ward" />}
      />

      <div className="enter -mt-2 flex flex-col gap-2">
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <Fact label="Zone" value={ward.zone} />
          <Fact label="Low-lying index" value={num(ward.low_lying_index, 2)} hint="0 to 1. Higher means the ward floods more easily." />
          <Fact label="Population" value={num(ward.population_est)} />
          <Fact label="Engineering crews" value={num(ward.engineering_crews)} />
        </dl>
        {!id && (
          <p className="flex items-center gap-1.5 text-sm text-base-content/60">
            <Info size={16} aria-hidden />
            Showing {ward.ward_code}, the ward with the highest share of spend flagged for review. Choose another ward above or on the map.
          </p>
        )}
      </div>

      <KpiStrip ward={ward} summary={summary} />

      <div className="enter enter-d1 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-6">
          <BudgetBlock ward={ward} />
          <Conditions ward={ward} />
        </div>
        <MapPanel wards={wards} ward={ward} />
      </div>

      <div className="enter enter-d2 grid gap-6 md:grid-cols-2">
        <SpendChart
          title="Spend by contractor"
          subtitle="Click a name to open the contractor."
          spend={spend}
          pick="byContractor"
          billed={ward.billed_inr}
          label={(k) => short(names[k] || k)}
          link={(k) => href("contractors", k)}
          rowsHint={rowsHint}
        />
        <SpendChart title="Spend by repair method" subtitle="What the money bought." spend={spend} pick="byMethod" billed={ward.billed_inr} label={(k) => k} rowsHint={rowsHint} />
      </div>

      <Narrative ward={ward} />

      <FlagsTable ward={ward} flags={wardFlags} names={names} woById={woById} woError={wo.error} />
    </div>
  );
}

function Fact({ label, value, hint }) {
  return (
    <div className="flex items-baseline gap-1.5" title={hint}>
      <dt className="text-base-content/60">{label}</dt>
      <dd className="num font-medium">{value}</dd>
    </div>
  );
}

/* ------------------------------------------------------------------ KPIs */

function KpiStrip({ ward, summary }) {
  return (
    <section aria-label="Key numbers" className="enter rounded-box border border-base-300 bg-base-100 p-5">
      <div className="grid grid-cols-2 gap-x-6 gap-y-6 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Billed" value={inrShort(ward.billed_inr)} note={`${pct(ward.budget_used_pct)} of budget`} />
        <Kpi label="Spend flagged" value={pct(ward.flagged_pct)} note={`${inrShort(ward.flagged_inr)} needs review`} />
        <Kpi label="Re-opened in 30 days" value={pct(ward.reopen_pct)} note={`City average ${pct(summary.reopen_pct)}`} />
        <Kpi label="Deadline (SLA) met" value={pct(ward.sla_pct)} note={`City average ${pct(summary.sla_pct)}`} />
        <Kpi label="Spent on failed repairs" value={inrShort(ward.failed_repair_inr)} note="Jobs that re-opened" />
        <Kpi label="Jobs" value={num(ward.n_jobs)} note="Work orders, Jun to Oct" />
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ Budget */

/*
  Budget drawn as an outlined box, billed as a solid fill inside it. If billed runs past the budget,
  the overspend continues beyond the outline in the error colour. Scale = max(budget, billed).
*/
function BudgetBlock({ ward }) {
  const budget = ward.budget_inr || 0;
  const billed = ward.billed_inr || 0;
  const over = billed > budget;
  const diff = Math.abs(billed - budget);
  const scale = Math.max(budget, billed) || 1;
  const budgetW = (100 * budget) / scale;
  const billedW = (100 * Math.min(billed, budget)) / scale;
  const overW = over ? (100 * (billed - budget)) / scale : 0;

  return (
    <Panel title="Budget against billed" subtitle="2025 monsoon road repair budget for this ward.">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <div className="text-sm text-base-content/60">Billed</div>
          <div className={`num text-2xl font-semibold tracking-tight ${over ? "text-error" : ""}`}>{inr(billed)}</div>
        </div>
        <div className="text-right">
          <div className="text-sm text-base-content/60">Budget</div>
          <div className="num text-2xl font-semibold tracking-tight">{inr(budget)}</div>
        </div>
      </div>

      <div
        className="relative mt-4 h-9"
        role="img"
        aria-label={`Billed ${inr(billed)} against a budget of ${inr(budget)}. ${over ? `${inr(diff)} over budget.` : `${inr(diff)} left.`}`}
      >
        {/* budget outline */}
        <div className="absolute inset-y-0 left-0 rounded-field border-2 border-dashed border-base-content/30" style={{ width: `${budgetW}%` }} />
        {/* billed within budget */}
        <div className="absolute inset-y-1 left-1 rounded-[calc(var(--radius-field)-2px)] bg-primary" style={{ width: `calc(${billedW}% - 0.5rem)` }} />
        {over && (
          <>
            <div className="absolute inset-y-1 rounded-r-[calc(var(--radius-field)-2px)] bg-error" style={{ left: `${budgetW}%`, width: `${overW}%` }} />
            <div className="absolute -inset-y-1.5 w-0.5 bg-base-content" style={{ left: `calc(${budgetW}% - 1px)` }} aria-hidden />
          </>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
        <div className="flex items-center gap-4 text-base-content/70">
          <span className="flex items-center gap-1.5">
            <span className="inline-block size-3 rounded-sm bg-primary" aria-hidden /> Billed
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block size-3 rounded-sm border-2 border-dashed border-base-content/40" aria-hidden /> Budget
          </span>
          {over && (
            <span className="flex items-center gap-1.5">
              <span className="inline-block size-3 rounded-sm bg-error" aria-hidden /> Over budget
            </span>
          )}
        </div>
        {over ? (
          <span className="num font-medium text-error">
            {inr(diff)} over budget ({pct(ward.budget_used_pct)} used)
          </span>
        ) : (
          <span className="num font-medium">
            {inr(diff)} left ({pct(100 - ward.budget_used_pct)} of budget)
          </span>
        )}
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------------ Charts */

function ChartTip({ active, payload, billed }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-field border border-base-300 bg-base-100 px-3 py-2 text-sm shadow-sm">
      <div className="font-medium">{d.full || d.name}</div>
      <div className="num">{inr(d.value)}</div>
      {billed > 0 && <div className="num text-base-content/60">{pct((100 * d.value) / billed)} of ward spend</div>}
    </div>
  );
}

/* split a long label into at most two lines of ~22 chars on word boundaries */
function wrap(text, max = 20) {
  if (text.length <= max) return [text];
  const words = text.split(" ");
  let a = "";
  let i = 0;
  while (i < words.length && (a + (a ? " " : "") + words[i]).length <= max) a += (a ? " " : "") + words[i++];
  if (!a) return [text.slice(0, max - 1) + "…"];
  let b = words.slice(i).join(" ");
  if (b.length > max) b = b.slice(0, max - 1).trimEnd() + "…";
  return [a, b];
}

function Tick({ x, y, payload, link }) {
  const lines = wrap(payload.value);
  const t = (
    <text x={x - 8} y={y} textAnchor="end" fontSize={12} fill="var(--color-base-content)" className={link ? "underline decoration-base-content/30 underline-offset-2" : ""}>
      <title>{payload.value}</title>
      {lines.map((l, i) => (
        <tspan key={i} x={x - 8} dy={i === 0 ? (lines.length > 1 ? "-0.35em" : "0.32em") : "1.2em"}>
          {l}
        </tspan>
      ))}
    </text>
  );
  const url = link?.(payload.value);
  return url ? (
    <a href={url} className="focus:outline-none [&:focus-visible_text]:fill-primary [&:hover_text]:fill-primary">
      {t}
    </a>
  ) : (
    t
  );
}

const SKELETON_H = 10 * 38 + 24;

function SpendChart({ title, subtitle, spend, pick, billed, label, link, rowsHint }) {
  const rows = useMemo(() => {
    const m = spend[pick];
    if (!m) return [];
    return Object.entries(m)
      .map(([k, v]) => ({ key: k, name: label(k), value: v }))
      .filter((r) => r.value > 0)
      .sort((a, b) => b.value - a.value);
  }, [spend, pick, label]);

  // the tick only knows the label; map it back to the key for links
  const byName = useMemo(() => Object.fromEntries(rows.map((r) => [r.name, r.key])), [rows]);
  const tickLink = link ? (name) => link(byName[name]) : null;
  const height = Math.max(200, (rowsHint || rows.length) * 38 + 24);

  return (
    <Panel title={title} subtitle={subtitle} className="min-w-0">
      {spend.loading ? (
        // most wards have 8 contractors and 10 repair methods; reserve the 10-row chart height so the page does not jump
        <div className="skeleton w-full" style={{ height: SKELETON_H }} />
      ) : spend.error ? (
        <p className="text-sm text-error">Could not load work orders for this chart.</p>
      ) : rows.length === 0 ? (
        <EmptyState title="No spend recorded" hint="This ward has no billed work orders in the season." />
      ) : (
        <div className="[contain:inline-size]" style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 0 }} barCategoryGap={8}>
              <CartesianGrid horizontal={false} stroke="var(--color-base-300)" />
              <XAxis
                type="number"
                tickFormatter={inrShort}
                tick={{ fontSize: 11, fill: "var(--color-base-content)", opacity: 0.6 }}
                axisLine={false}
                tickLine={false}
                tickCount={4}
              />
              <YAxis
                type="category"
                dataKey="name"
                width={158}
                axisLine={false}
                tickLine={false}
                interval={0}
                tick={(p) => <Tick {...p} link={tickLink} />}
              />
              <Tooltip
                cursor={{ fill: "var(--color-base-200)" }}
                content={<ChartTip billed={billed} />}
                isAnimationActive={false}
              />
              <Bar
                dataKey="value"
                fill="var(--color-primary)"
                radius={[0, 4, 4, 0]}
                maxBarSize={22}
                className={link ? "cursor-pointer" : ""}
                onClick={link ? (d) => (window.location.hash = link(d?.payload?.key ?? d?.key)) : undefined}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ Map + conditions */

function MapPanel({ wards, ward }) {
  const names = useMemo(() => Object.fromEntries(wards.map((w) => [w.ward_code, w])), [wards]);
  const values = useMemo(() => ({ [ward.ward_code]: 1 }), [ward.ward_code]);
  return (
    <Panel title="Where it is" subtitle="Click another ward to switch." bodyClass="pt-2">
      <MumbaiMap
        height={440}
        values={values}
        color={() => "color-mix(in oklch, var(--color-primary) 40%, var(--color-base-200))"}
        selected={ward.ward_code}
        onSelect={(c) => c !== ward.ward_code && go("wards", c)}
        label={(c) => (names[c] ? `${c}: ${names[c].ward_name}, ${pct(names[c].flagged_pct)} of spend flagged` : c)}
        ariaLabel={`Map of Mumbai wards with ${ward.ward_code} highlighted`}
      />
    </Panel>
  );
}

function Conditions({ ward }) {
  const rows = [
    ["Likely flood days", num(ward.flood_days), "Days this season the ward is expected to flood."],
    ["Open road issues", num(ward.open_issues), "Problems still waiting for a repair."],
    ["Open complaints", num(ward.open_complaints), "Citizen complaints not yet resolved."],
    ["Mean road risk", num(ward.mean_road_risk, 1), "Average risk score across the ward's roads, 0 to 100."],
    ["Highest road risk", num(ward.max_road_risk, 1), "Risk score of the ward's riskiest road, 0 to 100."],
  ];
  return (
    <Panel
      title="Ward conditions now"
      subtitle="What the next rupee has to deal with."
      actions={
        <a href={href("plan", ward.ward_code)} className="link link-primary hidden shrink-0 items-center gap-1 text-sm sm:inline-flex">
          Repair plan for {ward.ward_code} <ArrowRight size={16} aria-hidden />
        </a>
      }
    >
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 xl:grid-cols-5">
        {rows.map(([k, v, hint]) => (
          <div key={k} title={hint}>
            <dt className="text-sm text-base-content/60">{k}</dt>
            <dd className="num mt-0.5 text-xl font-semibold tracking-tight">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 text-xs leading-relaxed text-base-content/60">
        Road risk is a 0 to 100 score from road condition, flood exposure and safety. Higher means the road needs attention sooner.
      </p>
      <a href={href("plan", ward.ward_code)} className="link link-primary mt-3 inline-flex items-center gap-1 text-sm sm:hidden">
        Repair plan for {ward.ward_code} <ArrowRight size={16} aria-hidden />
      </a>
    </Panel>
  );
}

/* ------------------------------------------------------------------ Narrative */

function Narrative({ ward }) {
  const summary = ward.summary_text || null; // already Indian digit grouping from the pipeline
  return (
    <section className="enter enter-d3 rounded-box border border-base-300 bg-base-100">
      <div className="grid md:grid-cols-2 md:divide-x divide-y md:divide-y-0 divide-base-300">
        <div className="p-5">
          <h2 className="font-semibold">Audit summary</h2>
          <p className="mt-2 leading-relaxed text-base-content/80">{summary || "No summary for this ward."}</p>
        </div>
        <div className="p-5">
          <h2 className="font-semibold">Budget memo</h2>
          <p className="mt-2 leading-relaxed text-base-content/80">{ward.memo || "No memo for this ward."}</p>
        </div>
      </div>
      <p className="border-t border-base-300 px-5 py-3 text-xs text-base-content/60">
        Both texts are generated from the numbers on this page. DLP (defect liability period) means the road is still under the original
        contractor's warranty, so the city should pay nothing for repairs.
      </p>
    </section>
  );
}

/* ------------------------------------------------------------------ Flags */

/*
  One row per work order that was actually billed, so no rupee is listed twice.
  A REPEAT_REPAIR flag sits on the original job, but its amount is the cost of the follow-up job that redid it
  (related_work_order_id). So that money is keyed to the follow-up job, the same job a DLP_PAID or OVERBILL flag
  on it would point at. Each row keeps the largest amount among its flags (as export_data.py does per work
  order) and shows every flag type on it. The contractor is the one who billed that job.
*/
const SEV_RANK = { high: 3, medium: 2, low: 1 };

function billedWo(f) {
  return f.flag_type === "REPEAT_REPAIR" && f.related_work_order_id ? f.related_work_order_id : f.work_order_id;
}

function groupByBilledWo(flags, woById) {
  const groups = new Map();
  for (const f of flags) {
    const key = billedWo(f);
    let g = groups.get(key);
    if (!g) {
      g = { wo: key, amount: 0, types: [], severity: null, redoOf: [], contractorId: null };
      groups.set(key, g);
    }
    g.amount = Math.max(g.amount, f.amount_at_risk_inr || 0);
    if (!g.types.includes(f.flag_type)) g.types.push(f.flag_type);
    if ((SEV_RANK[f.severity] || 0) > (SEV_RANK[g.severity] || 0)) g.severity = f.severity;
    if (key !== f.work_order_id && !g.redoOf.includes(f.work_order_id)) g.redoOf.push(f.work_order_id);
    // a flag raised on this very job carries its contractor; a redo flag carries the original job's contractor
    if (key === f.work_order_id) g.contractorId = f.contractor_id;
  }
  for (const g of groups.values()) {
    const row = woById?.get(g.wo);
    if (row) g.contractorId = row.contractor_id;
  }
  return [...groups.values()];
}

function FlagsTable({ ward, flags, names, woById, woError }) {
  const { openWorkOrder } = useWorkOrder();
  const top = useMemo(
    () =>
      groupByBilledWo(flags, woById)
        .filter((g) => g.amount > 0)
        .sort((a, b) => b.amount - a.amount)
        .slice(0, 10),
    [flags, woById],
  );
  const allLink = href("flags", null, { ward: ward.ward_code });

  return (
    <Panel
      className="enter enter-d3"
      title="Largest flags in this ward"
      subtitle="Top 10 billed jobs by amount that needs review. Each job is listed once, even when it has more than one flag. Open a work order to see the evidence."
      actions={
        flags.length > 0 && (
          <a href={allLink} className="btn btn-sm btn-ghost hidden shrink-0 sm:inline-flex">
            See all {num(flags.length)} flags <ArrowRight size={16} aria-hidden />
          </a>
        )
      }
      bodyClass="px-0 pb-2"
    >
      {top.length === 0 ? (
        <EmptyState title="No flags with an amount in this ward" hint="Missed-deadline flags carry no rupee amount, so they are only listed on the flags page." />
      ) : (
        <div className="overflow-x-auto [contain:inline-size]">
          <table className="table">
            <thead>
              <tr className="text-base-content/60">
                <th className="pl-5">Work order billed</th>
                <th>Flags</th>
                <th className="hidden md:table-cell">Severity</th>
                <th className="hidden lg:table-cell">Billed by</th>
                <th className="pr-5 text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {top.map((g) => (
                <tr key={g.wo} className="align-top hover:bg-base-200/60">
                  <td className="pl-5">
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs gap-1 px-1.5 font-mono"
                      onClick={() => openWorkOrder(g.wo)}
                      aria-label={`Open work order ${g.wo}`}
                    >
                      {g.wo}
                      <ArrowSquareOut size={16} className="opacity-60" aria-hidden />
                    </button>
                  </td>
                  <td>
                    <div className="flex flex-wrap gap-1">
                      {g.types.map((t) => (
                        <FlagBadge key={t} type={t} />
                      ))}
                    </div>
                    {g.redoOf.length > 0 && (
                      <div className="mt-1 text-xs text-base-content/60">
                        Redo of{" "}
                        {g.redoOf.map((o, i) => (
                          <span key={o}>
                            {i > 0 && ", "}
                            <button
                              type="button"
                              className="link link-hover font-mono"
                              onClick={() => openWorkOrder(o)}
                              aria-label={`Open original work order ${o}, the repair that did not last`}
                            >
                              {o}
                            </button>
                          </span>
                        ))}
                        , the repair that did not last
                      </div>
                    )}
                  </td>
                  <td className="hidden md:table-cell">
                    <SevBadge severity={g.severity} />
                  </td>
                  <td className="hidden max-w-56 truncate lg:table-cell">
                    {g.contractorId ? (
                      <a className="link link-hover" href={href("contractors", g.contractorId)}>
                        <ContractorName name={names[g.contractorId] || g.contractorId} />
                      </a>
                    ) : woError ? (
                      <span className="text-base-content/60">Open the work order</span>
                    ) : (
                      <span className="skeleton inline-block h-4 w-28 align-middle" aria-label="Loading contractor" />
                    )}
                  </td>
                  <td className="num pr-5 text-right font-medium">{inr(g.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {flags.length > 0 && (
        <div className="px-5 pt-3">
          <a href={allLink} className="link link-primary inline-flex items-center gap-1 text-sm">
            See all {num(flags.length)} flags in this ward <ArrowRight size={16} aria-hidden />
          </a>
        </div>
      )}
    </Panel>
  );
}
