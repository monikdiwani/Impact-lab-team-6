import { Fragment, useMemo } from "react";
import { ArrowRight, CaretRight, Quotes, MapTrifold, Receipt } from "@phosphor-icons/react";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, LabelList } from "recharts";
import { inr, inrShort, num, pct, FLAG_LABEL, FLAG_HELP, GRADE_CLASS } from "../../lib/format";
import { href } from "../../lib/router";
import { useWorkOrder } from "../../components/WorkOrderPanel";

/* the three score parts, in the order the formula reads */
const PARTS = [
  { key: "durability", label: "Repairs lasted", swatch: "bg-primary" },
  { key: "sla", label: "Deadlines met", swatch: "bg-primary/55" },
  { key: "billing", label: "Clean billing", swatch: "bg-primary/30" },
];

/* flag types, grouped by which part of the score they relate to */
const FLAG_ROWS = [
  { type: "OVERBILL", role: "Lowers the clean billing part." },
  { type: "DOUBLE_BILL", role: "Lowers the clean billing part." },
  { type: "REPEAT_REPAIR", role: "Re-opened jobs feed the repairs lasted part." },
  { type: "SLA_MISS", role: "Late jobs feed the deadlines met part." },
  { type: "DLP_PAID", role: "Not in the score. DLP means the road is still under the original contractor's warranty, so the city should pay nothing. The flag stays on the road." },
];

const ISSUE_TITLE = {
  "billed above rate card": "Billed above rate card",
  "possible double bill": "Possible double bill",
  "re-opened within 30 days": "Re-opened within 30 days",
};

export default function Detail({ c, total, weights }) {
  const { openWorkOrder } = useWorkOrder();
  const f = c.facts || {};
  return (
    <section className="enter enter-d2 rounded-box border border-base-300 bg-base-100" aria-labelledby="ct-name">
      {/* header */}
      <div className="flex flex-col gap-4 border-b border-base-300 px-5 py-5 sm:flex-row sm:items-center sm:justify-between md:px-6">
        <div className="min-w-0">
          <p className="text-sm text-base-content/60">
            Rank <span className="num">{c.rank}</span> of <span className="num">{total}</span>
          </p>
          <h2 id="ct-name" className="mt-0.5 text-xl font-semibold tracking-tight md:text-2xl">
            {c.contractor_name}
          </h2>
          <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-base-content/70">
            <span className="inline-flex items-center gap-1.5">
              <Receipt size={16} aria-hidden /> <span className="num">{num(c.n_jobs)}</span> jobs, <span className="num">{inrShort(c.billed_inr)}</span> billed
            </span>
            {f.wards_active != null && (
              <span className="inline-flex items-center gap-1.5">
                <MapTrifold size={16} aria-hidden /> Worked in <span className="num">{f.wards_active}</span> wards
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-4 sm:flex-row-reverse sm:text-right">
          <div className={`text-6xl leading-none font-semibold tracking-tight ${GRADE_CLASS[c.grade] || ""}`} aria-label={`Grade ${c.grade}`}>
            {c.grade}
          </div>
          <div>
            <div className="text-sm text-base-content/60">Score</div>
            <div className="num text-2xl font-semibold tracking-tight">
              {num(c.score_0_100, 1)}
              <span className="text-base font-normal text-base-content/60"> / 100</span>
            </div>
          </div>
        </div>
      </div>

      {/* citizen scorecard */}
      {c.summary_text && (
        <div className="border-b border-base-300 px-5 py-5 md:px-6">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="font-semibold">Citizen scorecard</h3>
            <span className="text-xs text-base-content/60">Written from the numbers on this page</span>
          </div>
          <div className="mt-3 flex gap-3">
            <Quotes size={20} weight="fill" className="mt-0.5 shrink-0 text-primary/60" aria-hidden />
            <p className="max-w-4xl leading-relaxed text-base-content/85">
              <Scorecard text={c.summary_text} onOpen={openWorkOrder} />
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-x-10 gap-y-8 px-5 py-6 md:px-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-8">
          <ScoreBreakdown c={c} weights={weights} />
          <MethodMix mix={c.method_mix} nJobs={c.n_jobs} />
        </div>
        <div className="flex min-w-0 flex-col gap-8 lg:border-l lg:border-base-300 lg:ps-10">
          <FlagsByType c={c} />
          <Examples rows={f.example_work_orders || []} days={f.definitions?.double_bill_window_days} onOpen={openWorkOrder} />
        </div>
      </div>
    </section>
  );
}

/* The generated text uses Western digit grouping and plain WO ids: re-format rupees the
   Indian way and turn each work order id into a button that opens its drill-down. */
function Scorecard({ text, onOpen }) {
  const parts = text.split(/(WO\d{2}-\d{5})/);
  return parts.map((p, i) =>
    /^WO\d{2}-\d{5}$/.test(p) ? (
      <button
        key={i}
        type="button"
        onClick={() => onOpen(p)}
        className="link link-primary font-mono text-[0.95em] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary rounded-field"
        aria-label={`Open work order ${p}`}
      >
        {p}
      </button>
    ) : (
      <Fragment key={i}>{p}</Fragment>
    ),
  );
}

function ScoreBreakdown({ c, weights = {} }) {
  const comp = c.components || {};
  const nBill = (c.n_flags_by_type?.OVERBILL || 0) + (c.n_flags_by_type?.DOUBLE_BILL || 0);
  const evidence = {
    durability: `${pct(c.reopen_pct)} re-opened vs ${pct(c.reopen_expected_pct)} expected for its repair methods`,
    sla: `${pct(c.sla_pct)} of jobs finished by the deadline`,
    billing: `${num(nBill)} billing flags (over-billing or a possible double bill) across ${num(c.n_jobs)} jobs`,
  };
  const rows = PARTS.map((p) => {
    const w = weights[p.key] ?? 0;
    const v = comp[p.key] ?? 0;
    return { ...p, weight: 100 * w, value: v, points: 100 * w * v };
  });
  const w = Object.fromEntries(rows.map((r) => [r.key, Math.round(r.weight)]));

  return (
    <div>
      <h3 className="font-semibold">How the score is built</h3>
      <p className="mt-1 text-sm leading-relaxed text-base-content/70">
        {w.durability}% repairs lasted (re-open rate adjusted for the repair methods used), {w.sla}% deadlines met, {w.billing}% clean billing. Each part is rated
        from 0 to 1, then weighted, so the points add up to the score.
      </p>

      {/* segmented bar out of 100 */}
      <div className="mt-4" role="img" aria-label={`Score ${num(c.score_0_100, 1)} out of 100: ${rows.map((r) => `${r.label} ${num(r.points, 1)} of ${num(r.weight)}`).join(", ")}`}>
        <div className="flex h-3 w-full overflow-hidden rounded-full bg-base-300/70">
          {rows.filter((r) => r.points > 0).map((r) => (
            <span key={r.key} className={`h-full ${r.swatch} border-r-2 border-base-100 last:border-r-0`} style={{ width: `${r.points}%` }} />
          ))}
        </div>
        <div className="num mt-1.5 flex justify-between text-xs text-base-content/50" aria-hidden>
          <span>0</span>
          <span>100</span>
        </div>
      </div>

      <ul className="mt-3 divide-y divide-base-300">
        {rows.map((r) => (
          <li key={r.key} className="grid grid-cols-[auto_1fr_auto] items-start gap-x-3 py-3">
            <span className={`mt-1.5 size-2.5 rounded-full ${r.swatch}`} aria-hidden />
            <div className="min-w-0">
              <div className="font-medium">{r.label}</div>
              <div className="text-sm text-base-content/60">{evidence[r.key]}</div>
              <div className="mt-2 flex items-center gap-2">
                <span className="h-1.5 w-full max-w-48 overflow-hidden rounded-full bg-base-200">
                  <span className={`block h-full rounded-full ${r.swatch}`} style={{ width: `${100 * r.value}%` }} />
                </span>
                <span className="num text-xs text-base-content/60">rated {num(r.value, 2)}</span>
              </div>
            </div>
            <div className="num text-right">
              <span className="font-semibold">{num(r.points, 1)}</span>
              <span className="text-sm text-base-content/60"> / {num(r.weight)}</span>
            </div>
          </li>
        ))}
        <li className="flex items-baseline justify-between py-3">
          <span className="font-medium">Score</span>
          <span className="num">
            <span className="text-lg font-semibold">{num(c.score_0_100, 1)}</span>
            <span className="text-sm text-base-content/60"> / 100</span>
          </span>
        </li>
      </ul>
    </div>
  );
}

function FlagsByType({ c }) {
  const counts = c.n_flags_by_type || {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-semibold">Flags by type</h3>
          <p className="mt-1 text-sm text-base-content/60">
            <span className="num">{num(total)}</span> flags on this contractor's jobs. A flag means "needs review", not wrongdoing.
          </p>
        </div>
        {c.amount_flagged_inr != null && (
          <div className="text-right" title="Rupees at risk on flagged jobs, taking the largest flag per job so no job is counted twice. Missed deadlines carry no rupee amount.">
            <div className="num text-lg font-semibold">{inrShort(c.amount_flagged_inr)}</div>
            <div className="text-xs text-base-content/60">at risk on flagged jobs</div>
          </div>
        )}
      </div>
      <ul className="mt-3 divide-y divide-base-300 border-y border-base-300">
        {FLAG_ROWS.map(({ type, role }) => (
          <li key={type}>
            <a
              href={href("flags", null, { contractor: c.contractor_id, type })}
              title={FLAG_HELP[type]}
              className="group grid grid-cols-[1fr_auto_auto] items-center gap-3 rounded-field py-3 hover:bg-base-200/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              <span className="min-w-0">
                <span className="block font-medium group-hover:underline">{FLAG_LABEL[type]}</span>
                <span className="block text-sm leading-snug text-base-content/60">{role}</span>
              </span>
              <span className="num text-right text-lg font-semibold">{num(counts[type] || 0)}</span>
              <CaretRight size={16} className="text-base-content/40" aria-hidden />
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Examples({ rows, days, onOpen }) {
  if (!rows.length) return null;
  const line = (e) => {
    if (e.rate_card_inr != null)
      return (
        <>
          Billed <span className="num">{inr(e.billed_inr)}</span> against a rate card price of <span className="num">{inr(e.rate_card_inr)}</span>
          {e.ratio != null && <span className="num"> ({num(e.ratio, 2)}x)</span>}
        </>
      );
    if (e.earlier_work_order_id)
      return (
        <>
          Same kind of job on the same road as {e.earlier_work_order_id}
          {days ? `, within ${days} days` : ""}. Billed <span className="num">{inr(e.billed_inr)}</span>
        </>
      );
    return (
      <>
        Billed <span className="num">{inr(e.billed_inr)}</span>
      </>
    );
  };
  return (
    <div>
      <h3 className="font-semibold">Jobs to check first</h3>
      <p className="mt-1 text-sm text-base-content/60">Open a job to follow its rupees from complaint to bill.</p>
      <ul className="mt-3 flex flex-col gap-2">
        {rows.map((e) => (
          <li key={e.work_order_id}>
            <button
              type="button"
              onClick={() => onOpen(e.work_order_id)}
              className="group flex w-full items-center gap-3 rounded-field border border-base-300 px-3.5 py-3 text-left transition-colors hover:border-primary/50 hover:bg-base-200/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              aria-label={`Open work order ${e.work_order_id}: ${e.issue}`}
            >
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="font-mono text-sm font-medium">{e.work_order_id}</span>
                  <span className="badge badge-sm badge-outline whitespace-nowrap">{ISSUE_TITLE[e.issue] || e.issue}</span>
                </span>
                <span className="mt-1 block text-sm text-base-content/70">{line(e)}</span>
              </span>
              <ArrowRight size={16} className="shrink-0 text-base-content/40 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" aria-hidden />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* wraps long method names onto two lines inside the y axis */
function wrap(text, max = 22) {
  const out = [""];
  for (const w of text.split(" ")) {
    const cur = out[out.length - 1];
    if (cur && (cur + " " + w).length > max) out.push(w);
    else out[out.length - 1] = cur ? `${cur} ${w}` : w;
  }
  return out.slice(0, 2);
}

function MethodTick({ x, y, payload }) {
  const lines = wrap(payload.value);
  return (
    <text x={x - 8} y={y} textAnchor="end" fill="var(--color-base-content)" fillOpacity={0.75} fontSize={12}>
      {lines.map((l, i) => (
        <tspan key={i} x={x - 8} dy={i === 0 ? (lines.length > 1 ? -4 : 4) : 14}>
          {l}
        </tspan>
      ))}
    </text>
  );
}

function MixTip({ active, payload, nJobs }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-box border border-base-300 bg-base-100 px-3 py-2 text-sm shadow-sm">
      <div className="font-medium">{d.method}</div>
      <div className="num text-base-content/70">
        {num(d.n)} jobs, {pct((100 * d.n) / nJobs)} of this contractor's work
      </div>
    </div>
  );
}

function MethodMix({ mix, nJobs }) {
  const data = useMemo(
    () =>
      Object.entries(mix || {})
        .map(([method, n]) => ({ method, n }))
        .sort((a, b) => b.n - a.n),
    [mix],
  );
  if (!data.length) return null;
  return (
    <div>
      <h3 className="font-semibold">Repair methods used</h3>
      <p className="mt-1 text-sm text-base-content/60">
        Jobs by method. Some methods re-open more often than others, which is why the expected re-open rate depends on this mix.
      </p>
      <div className="mt-3" style={{ height: data.length * 34 + 16 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 0, right: 36, bottom: 0, left: 0 }} barCategoryGap={8}>
            <XAxis type="number" hide domain={[0, "dataMax"]} />
            <YAxis type="category" dataKey="method" width={172} tickLine={false} axisLine={false} tick={<MethodTick />} interval={0} />
            <Tooltip cursor={{ fill: "var(--color-base-200)" }} content={<MixTip nJobs={nJobs} />} isAnimationActive={false} />
            <Bar dataKey="n" fill="var(--color-primary)" radius={[0, 4, 4, 0]} maxBarSize={18} isAnimationActive={false}>
              <LabelList dataKey="n" position="right" fill="var(--color-base-content)" fillOpacity={0.7} fontSize={12} className="num" />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
