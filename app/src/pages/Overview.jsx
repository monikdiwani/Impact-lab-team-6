import { useMemo } from "react";
import { Wallet, ShieldWarning, Certificate, ArrowCounterClockwise, Timer, ArrowRight, CaretRight, Info } from "@phosphor-icons/react";
import { useData, byKey } from "../lib/data";
import { inr, inrShort, pct, num, short, FLAG_LABEL, FLAG_HELP } from "../lib/format";
import { href, go, setQuery } from "../lib/router";
import { PageHeader, Panel, Kpi, Loaded, ErrorState, EmptyState, InlineBar } from "../components/ui";
import MumbaiMap, { ramp } from "../components/MumbaiMap";
import { useWorkOrder } from "../components/WorkOrderPanel";

/*
  Overview (#/). The 10-second story: what was billed, how much needs review,
  where in the city it sits, which flag types drive it, and the biggest single items.
  Map metric lives in the URL (?metric=flagged|risk|budget) so it survives reloads and can be shared.
*/

/*
  Local warm ramp. The shared riskRamp mixes in oklch, which rotates the hue from the cool neutral
  through purple on its way to red. Mixing in oklab keeps a straight neutral-to-red line.
*/
function riskRamp(t) {
  const p = Math.max(0, Math.min(1, t));
  return `color-mix(in oklab, var(--color-error) ${Math.round(8 + p * 82)}%, var(--color-base-200))`;
}

const METRICS = {
  flagged: {
    label: "% of spend flagged",
    key: "flagged_pct",
    fmt: (v) => pct(v),
    color: riskRamp,
    desc: "Share of each ward's billed money that has at least one review flag.",
  },
  risk: {
    label: "Risk score",
    key: "risk_score",
    fmt: (v) => num(v, 1),
    color: riskRamp,
    desc: "Next monsoon risk on a 0 to 100 scale, built from road condition, flooding, safety and critical routes.",
  },
  budget: {
    label: "Budget used",
    key: "budget_used_pct",
    fmt: (v) => pct(v),
    color: ramp,
    desc: "Money billed as a share of the ward's monsoon repair budget. Above 100% means over budget.",
  },
};

// notes picked from summary.fairness_notes, in this order, by their opening words (falls back to the first four)
const NOTE_PICKS = ["Wording is neutral", "Every contractor works", "Scores use rates", "Bills on roads under warranty"];

export default function Overview({ query }) {
  const state = useData(["summary", "wards"]);
  const metric = Object.hasOwn(METRICS, query?.metric ?? "") ? query.metric : "flagged";

  return (
    <Loaded state={state} what="the city summary">
      {([summary, wards]) => <Story summary={summary} wards={wards} metric={metric} />}
    </Loaded>
  );
}

function Story({ summary: s, wards, metric }) {
  const usedPct = s.budget_inr > 0 ? (100 * s.billed_inr) / s.budget_inr : null;
  const flaggedShare = s.billed_inr > 0 ? (100 * s.flagged_inr) / s.billed_inr : null;
  const dlpJobs = s.flags_by_type?.DLP_PAID?.n;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={`Mumbai billed ${inrShort(s.billed_inr)} of its ${inrShort(s.budget_inr)} road budget`}
        lede={`${inrShort(s.dlp_inr)} went to roads still under the original contractor's warranty, where the city should pay nothing.`}
      />

      <Panel className="enter enter-d1" bodyClass="py-5">
        <h2 className="sr-only">Key numbers, monsoon 2025</h2>
        <div className="grid grid-cols-2 gap-x-6 gap-y-6 md:grid-cols-3 xl:grid-cols-5 xl:divide-x xl:divide-base-300 [&>*]:xl:pl-6 [&>*:first-child]:xl:pl-0">
          <div className="col-span-2 md:col-span-1">
            <Kpi icon={Wallet} label="Billed vs budget" value={inrShort(s.billed_inr)}
              note={`of ${inrShort(s.budget_inr)}, ${pct(usedPct)} used`} />
          </div>
          <Kpi icon={ShieldWarning} label="Flagged for review" value={inrShort(s.flagged_inr)} tone="text-error"
            note={`${pct(flaggedShare)} of billed, multi-flag jobs counted once`} />
          <Kpi icon={Certificate} label="Billed under warranty" value={inrShort(s.dlp_inr)}
            note={dlpJobs != null ? `${num(dlpJobs)} jobs under DLP` : "roads under DLP"} />
          <Kpi icon={ArrowCounterClockwise} label="Re-opened in 30 days" value={pct(s.reopen_pct)}
            note="repairs that did not hold" />
          <Kpi icon={Timer} label="Deadline met" value={pct(s.sla_pct)}
            note="SLA counted from first complaint" />
        </div>
        <p className="mt-5 border-t border-base-300 pt-4 text-sm text-base-content/60">
          DLP (defect liability period) means the road is still under the original contractor's warranty, so repairs should cost the
          city nothing. SLA is the repair deadline. Figures cover {num(s.n_work_orders)} work orders and {num(s.n_complaints)} citizen
          complaints across {num(s.n_wards)} wards.
        </p>
      </Panel>

      <WardsAtAGlance wards={wards} metric={metric} />

      <div className="grid gap-6 lg:grid-cols-12">
        <FlagTypes summary={s} className="enter enter-d3 lg:col-span-7" />
        <LargestItems wards={wards} className="enter enter-d3 lg:col-span-5" />
      </div>

      <HowToRead summary={s} />
    </div>
  );
}

/* ---------------- map + ranked wards ---------------- */

function WardsAtAGlance({ wards, metric }) {
  const m = METRICS[metric];
  const byCode = useMemo(() => byKey(wards, "ward_code"), [wards]);

  const { values, min, max, top } = useMemo(() => {
    const vals = wards.map((w) => w[m.key]).filter((v) => v != null);
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const span = hi - lo || 1;
    const values = {};
    for (const w of wards) if (w[m.key] != null) values[w.ward_code] = (w[m.key] - lo) / span;
    const top = [...wards].filter((w) => w[m.key] != null).sort((a, b) => b[m.key] - a[m.key]).slice(0, 8);
    return { values, min: lo, max: hi, top };
  }, [wards, m]);

  const label = (code) => {
    const w = byCode.get(code);
    return w ? `${code}: ${w.ward_name}, ${m.fmt(w[m.key])}` : `Ward ${code}`;
  };

  const toggle = (
    <div className="join" role="group" aria-label="Map metric">
      {Object.entries(METRICS).map(([k, v]) => (
        <button key={k} type="button" aria-pressed={k === metric}
          className={`btn btn-sm join-item ${k === metric ? "btn-primary" : "btn-ghost border-base-300"}`}
          onClick={() => setQuery(k === "flagged" ? {} : { metric: k })}>
          {v.label}
        </button>
      ))}
    </div>
  );

  return (
    <section className="enter enter-d2 rounded-box border border-base-300 bg-base-100">
      <div className="flex flex-col gap-3 px-5 pt-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 className="font-semibold">Wards at a glance</h2>
          <p className="mt-0.5 text-sm text-base-content/60">{m.desc} Select a ward to open its money trail.</p>
        </div>
        <div className="max-w-full shrink-0 overflow-x-auto">{toggle}</div>
      </div>

      {top.length === 0 ? (
        <EmptyState title="No ward values for this metric" hint="Try another metric above." />
      ) : (
        <div className="grid gap-6 p-5 md:grid-cols-12">
          <div className="md:col-span-5">
            <MumbaiMap values={values} color={m.color} label={label} onSelect={(code) => go("wards", code)} height={540}
              ariaLabel={`Map of Mumbai wards coloured by ${m.label.toLowerCase()}`} />
          </div>

          <div className="flex flex-col md:col-span-7 md:border-l md:border-base-300 md:pl-6">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-sm font-medium">Top 8 wards by {m.label.toLowerCase()}</h3>
              <span className="text-xs text-base-content/60">of {wards.length}</span>
            </div>
            <ol className="mt-2 divide-y divide-base-300">
              {top.map((w, i) => {
                const v = w[m.key];
                const over = metric === "budget" && v > 100;
                return (
                  <li key={w.ward_code}>
                    <a href={href("wards", w.ward_code)}
                      className="group grid grid-cols-[1.5rem_3rem_1fr_auto] items-center gap-x-3 gap-y-1.5 rounded-field px-1 py-2.5 outline-offset-2 hover:bg-base-200 focus-visible:outline-2 focus-visible:outline-primary xl:grid-cols-[1.5rem_3rem_minmax(0,1fr)_minmax(6rem,10rem)_4.5rem]">
                      <span className="num text-sm text-base-content/50">{i + 1}</span>
                      <span className="font-mono text-sm font-medium">{w.ward_code}</span>
                      <span className="truncate text-sm" title={w.ward_name}>{w.ward_name}</span>
                      <span className="col-span-2 col-start-3 row-start-2 xl:col-span-1 xl:col-start-auto xl:row-start-auto">
                        <span className="block w-full">
                          <span className="block h-1.5 rounded-full" aria-hidden
                            style={{ width: `${Math.max(4, Math.round((100 * v) / max))}%`, background: m.color(values[w.ward_code]) }} />
                        </span>
                      </span>
                      <span className={`num text-right text-sm font-medium ${over ? "text-error" : ""}`}>
                        {m.fmt(v)}
                        {over && <span className="sr-only"> (over budget)</span>}
                      </span>
                    </a>
                  </li>
                );
              })}
            </ol>

            <div className="mt-auto pt-5">
              <div className="text-sm text-base-content/70">Map colour</div>
              <div className="mt-1.5 h-2.5 w-full max-w-sm rounded-full border border-base-300" aria-hidden
                style={{ background: `linear-gradient(to right, ${m.color(0)}, ${m.color(0.5)}, ${m.color(1)})` }} />
              <div className="mt-1 flex w-full max-w-sm justify-between text-xs text-base-content/60">
                <span className="num">Lowest {m.fmt(min)}</span>
                <span className="num">Highest {m.fmt(max)}</span>
              </div>
              <p className="mt-2 text-xs text-base-content/60">
                Stronger colour means a higher value, relative to the other wards.
                {metric === "budget" && " Over budget values are shown in red in the list."}
              </p>
              <a href={href("wards")} className="link link-hover mt-3 inline-flex items-center gap-1 text-sm text-primary">
                All {num(wards.length)} wards <ArrowRight size={16} aria-hidden />
              </a>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

/* ---------------- flag types ---------------- */

function FlagTypes({ summary: s, className }) {
  const rows = useMemo(
    () =>
      Object.entries(s.flags_by_type || {})
        .map(([type, v]) => ({ type, ...v }))
        .sort((a, b) => b.amount - a.amount || b.n - a.n),
    [s],
  );
  const maxAmt = Math.max(0, ...rows.map((r) => r.amount));

  return (
    <Panel className={className} title="Where the flagged money is"
      subtitle="Some jobs carry more than one flag, so these amounts add up to more than the flagged total.">
      {rows.length === 0 ? (
        <EmptyState title="No flags in this data" hint="Re-run the audit pipeline and export again." />
      ) : (
        <ul className="-my-1 divide-y divide-base-300">
          {rows.map((r) => (
            <li key={r.type}>
              <a href={href("flags", null, { type: r.type })}
                className="group -mx-2 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 rounded-field px-2 py-3 hover:bg-base-200 focus-visible:outline-2 focus-visible:outline-primary">
                <span className="flex items-center gap-1.5 font-medium">
                  {FLAG_LABEL[r.type] || r.type}
                  <CaretRight size={16} className="text-base-content/40 transition-transform group-hover:translate-x-0.5" aria-hidden />
                </span>
                <span className="num text-right font-semibold">{r.amount > 0 ? inrShort(r.amount) : "No ₹ amount"}</span>
                <span className="text-sm text-base-content/60">{FLAG_HELP[r.type]}</span>
                <span className="num text-right text-sm text-base-content/60">{num(r.n)} jobs</span>
                <span className="col-span-2 mt-1 block">
                  {r.amount > 0 ? (
                    <InlineBar value={r.amount} max={maxAmt} />
                  ) : (
                    <span className="text-xs text-base-content/50">Time only: a late job has no rupee amount at risk.</span>
                  )}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/* ---------------- largest single items (flags.json loaded only here) ---------------- */

// The work order whose bill a flag's amount_at_risk_inr belongs to.
const moneyWo = (f) => (f.flag_type === "REPEAT_REPAIR" && f.related_work_order_id) || f.work_order_id;

function LargestItems({ wards, className }) {
  const st = useData(["flags", "contractor_names"]);
  const { openWorkOrder } = useWorkOrder();
  const wardName = useMemo(() => byKey(wards, "ward_code"), [wards]);

  const top = useMemo(() => {
    if (!st.data) return [];
    const seen = new Set();
    const out = [];
    const sorted = [...st.data[0]].filter((f) => (f.amount_at_risk_inr || 0) > 0).sort((a, b) => b.amount_at_risk_inr - a.amount_at_risk_inr);
    for (const f of sorted) {
      // Dedup on the bill the amount belongs to. A REPEAT_REPAIR flag sits on the original job, but its
      // amount is the cost of the follow-up job (related_work_order_id), which may carry its own flag too.
      const k = moneyWo(f);
      if (seen.has(k)) continue;
      seen.add(k);
      out.push(f);
      if (out.length === 6) break;
    }
    return out;
  }, [st.data]);

  return (
    <Panel className={className} title="Largest single items to review" subtitle="Open a work order to see the bill, the complaints and the evidence. For a repair that was redone, the amount is the redo bill.">
      {st.loading ? (
        <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading flags">
          {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="skeleton h-12" />)}
        </div>
      ) : st.error ? (
        <ErrorState error={st.error} what="audit flags" />
      ) : top.length === 0 ? (
        <EmptyState title="No flagged amounts" hint="No flag in this export carries a rupee amount." />
      ) : (
        <>
          <ol className="-my-1 divide-y divide-base-300">
            {top.map((f) => {
              const cname = st.data[1]?.[f.contractor_id];
              const redo = moneyWo(f) !== f.work_order_id ? moneyWo(f) : null;
              return (
                <li key={f.flag_id} className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-0.5 py-2.5">
                  <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                    <button type="button" onClick={() => openWorkOrder(f.work_order_id)}
                      className="btn btn-link btn-sm h-auto min-h-0 p-0 font-mono text-sm font-medium text-primary no-underline hover:underline"
                      aria-label={`Open work order ${f.work_order_id}`}>
                      {f.work_order_id}
                    </button>
                    <span className="text-sm">{FLAG_LABEL[f.flag_type] || f.flag_type}</span>
                    {redo && (
                      <span className="text-sm text-base-content/70">
                        redone as{" "}
                        <button type="button" onClick={() => openWorkOrder(redo)}
                          className="btn btn-link btn-sm h-auto min-h-0 p-0 align-baseline font-mono text-sm font-medium text-primary no-underline hover:underline"
                          aria-label={`Open follow-up work order ${redo}`}>
                          {redo}
                        </button>
                      </span>
                    )}
                  </div>
                  <span className="num text-right font-semibold" title={redo ? `Bill of follow-up job ${redo}` : undefined}>
                    {inr(f.amount_at_risk_inr)}
                    {redo && <span className="sr-only"> billed on {redo}</span>}
                  </span>
                  <div className="col-span-2 truncate text-sm text-base-content/60">
                    <a href={href("wards", f.ward_code)} className="link link-hover" title={wardName.get(f.ward_code)?.ward_name}>
                      Ward {f.ward_code}
                    </a>
                    {cname && (
                      <>
                        <span aria-hidden> · </span>
                        <span title={cname}>{short(cname)}</span>
                      </>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
          <a href={href("flags")} className="link link-hover mt-4 inline-flex items-center gap-1 text-sm text-primary">
            All {num(st.data[0].length)} flags <ArrowRight size={16} aria-hidden />
          </a>
        </>
      )}
    </Panel>
  );
}

/* ---------------- method notes ---------------- */

function HowToRead({ summary: s }) {
  const notes = useMemo(() => {
    const all = s.fairness_notes || [];
    const picked = NOTE_PICKS.map((p) => all.find((n) => n.startsWith(p))).filter(Boolean);
    return picked.length >= 3 ? picked : all.slice(0, 4);
  }, [s]);
  const d = s.dedup || {};

  return (
    <section className="enter enter-d3 grid gap-6 border-t border-base-300 pt-6 md:grid-cols-12">
      <div className="md:col-span-7">
        <h2 className="flex items-center gap-2 font-semibold">
          <Info size={18} className="text-base-content/60" aria-hidden />
          How to read this
        </h2>
        <ul className="mt-3 flex flex-col gap-2 text-sm leading-relaxed text-base-content/80">
          {notes.map((n) => (
            <li key={n} className="flex gap-2.5">
              <span className="mt-2 size-1.5 shrink-0 rounded-full bg-base-content/30" aria-hidden />
              <span>{n}</span>
            </li>
          ))}
        </ul>
      </div>
      {d.precision != null && (
        <div className="md:col-span-5">
          <h2 className="font-semibold">Duplicate complaints</h2>
          <p className="mt-3 text-sm leading-relaxed text-base-content/80">
            Complaints about the same problem are grouped, then checked against the work-order links.
          </p>
          <dl className="mt-4 grid grid-cols-2 gap-6">
            <div>
              <dt className="text-sm text-base-content/60">Groupings correct</dt>
              <dd className="num mt-0.5 text-2xl font-semibold tracking-tight">{pct(100 * d.precision, 0)}</dd>
              <dd className="text-xs text-base-content/60">precision</dd>
            </div>
            <div>
              <dt className="text-sm text-base-content/60">True duplicates found</dt>
              <dd className="num mt-0.5 text-2xl font-semibold tracking-tight">{pct(100 * d.recall, 0)}</dd>
              <dd className="text-xs text-base-content/60">recall</dd>
            </div>
          </dl>
        </div>
      )}
    </section>
  );
}
