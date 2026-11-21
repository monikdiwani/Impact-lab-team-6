import {
  ChatCircleText, UsersThree, Wrench, CheckCircle, Clock, ArrowCounterClockwise, ShieldCheck, Warning, CurrencyInr,
  ArrowSquareOut, Camera, HourglassMedium, ArrowBendUpRight, XCircle, MapPin,
} from "@phosphor-icons/react";
import { inr, num, when, short, FLAG_HELP } from "../../lib/format";
import { href } from "../../lib/router";
import { FlagBadge, SevBadge } from "../../components/ui";
import { useWorkOrder } from "../../components/WorkOrderPanel";
import { LANG, LANG_ATTR, WARD_SOURCE, statusInfo, isOpen, same, span } from "./helpers";

/*
  One complaint, start to finish: what the citizen said, then a vertical timeline
  from "received" to "money billed and audit flags".
*/
export default function ComplaintView({ c, idx }) {
  const wo = c.linked_work_order_id ? idx.woById.get(c.linked_work_order_id) : null;
  return (
    <div className="grid items-start gap-6 lg:grid-cols-12">
      <ComplaintCard c={c} idx={idx} className="enter lg:col-span-5 lg:sticky lg:top-24" />
      <Timeline c={c} wo={wo} idx={idx} className="enter enter-d1 lg:col-span-7" />
    </div>
  );
}

/* ---------- the complaint as the citizen filed it ---------- */

export function StatusBadge({ status, className = "" }) {
  const s = statusInfo(status);
  const style = s.tone.includes("badge-solid") ? s.tone.replace("badge-solid", "") : `badge-soft ${s.tone}`;
  return <span className={`badge badge-sm whitespace-nowrap ${style} ${className}`} title={status}>{s.short}</span>;
}

function ComplaintCard({ c, idx, className }) {
  const ward = idx.wardByCode.get(c.ward_code);
  const corrected = c.category_reported && c.category_clean && c.category_reported !== c.category_clean;
  const showEnglish = c.english_summary && !same(c.english_summary, c.description);
  const closedAt = c.resolved_at && (c.status === "Resolved" || c.status === "Closed - Duplicate");

  return (
    <section className={`rounded-box border border-base-300 bg-base-100 ${className}`} aria-labelledby="complaint-h">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-base-300 px-5 py-4">
        <h2 id="complaint-h" className="font-mono text-lg font-semibold">{c.complaint_id}</h2>
        <StatusBadge status={c.status} className="badge-md" />
      </div>

      <div className="px-5 py-5">
        <div className="flex items-center gap-2 text-sm text-base-content/60">
          <ChatCircleText size={16} aria-hidden />
          <span>What the citizen wrote</span>
          <span className="badge badge-ghost badge-sm">{LANG[c.language] || c.language}</span>
        </div>
        <blockquote lang={LANG_ATTR[c.language] || undefined} className="mt-2 border-l-2 border-primary/50 pl-4 text-lg leading-relaxed">
          {c.description}
        </blockquote>
        {showEnglish && (
          <p className="mt-3 pl-4 text-sm leading-relaxed text-base-content/70">
            <span className="font-medium text-base-content/80">In English: </span>
            {c.english_summary}
          </p>
        )}
        {c.photo_description && (
          <p className="mt-4 flex gap-2 rounded-field bg-base-200 px-3 py-2 text-sm">
            <Camera size={16} className="mt-0.5 shrink-0 text-base-content/60" aria-hidden />
            <span><span className="text-base-content/60">Photo shows: </span>{c.photo_description}</span>
          </p>
        )}

        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-base-300 pt-5 text-sm">
          <Fact label="Received">{when(c.received_at)}</Fact>
          <Fact label="Channel">{c.channel}</Fact>
          <Fact label="Ward">
            <a className="link link-hover" href={href("wards", c.ward_code)}>
              {c.ward_code}{ward ? `: ${ward.ward_name}` : ""}
            </a>
            <div className="text-base-content/60">{WARD_SOURCE[c.ward_source] || c.ward_source}</div>
          </Fact>
          <Fact label="Locality">{c.locality_text || "-"}</Fact>
          <Fact label="Category" wide>
            <div className="flex flex-wrap items-center gap-2">
              <span>{c.category_clean}</span>
              {corrected && <span className="badge badge-soft badge-primary badge-sm">corrected</span>}
            </div>
            <div className="text-base-content/60">
              {corrected ? <>Citizen picked "{c.category_reported}". Re-checked against the text and photo.</> : "Same as the citizen picked."}
            </div>
          </Fact>
          <Fact label="Severity">
            <Severity n={c.severity_1_5} />
          </Fact>
          <Fact label="Upvotes"><span className="num">{num(c.upvotes)}</span></Fact>
          {closedAt && <Fact label={c.status === "Resolved" ? "Marked resolved" : "Closed"} wide>{when(c.resolved_at)}</Fact>}
        </dl>
      </div>
    </section>
  );
}

function Fact({ label, children, wide }) {
  return (
    <div className={wide ? "col-span-2" : ""}>
      <dt className="text-base-content/60">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}

function Severity({ n }) {
  if (n == null) return "-";
  return (
    <span className="inline-flex items-center gap-2" aria-label={`Severity ${n} of 5`}>
      <span className="inline-flex gap-1" aria-hidden>
        {[1, 2, 3, 4, 5].map((i) => (
          <span key={i} className={`h-2 w-3 rounded-full ${i <= n ? (n >= 4 ? "bg-error" : "bg-base-content/70") : "bg-base-300"}`} />
        ))}
      </span>
      <span className="num">{n} of 5</span>
    </span>
  );
}

/* ---------- timeline ---------- */

const TONE = {
  done: "border-primary/30 bg-primary/10 text-primary",
  good: "border-success/30 bg-success/10 text-success",
  bad: "border-error/30 bg-error/10 text-error",
  warn: "border-warning/40 bg-warning/15 text-base-content",
  wait: "border-dashed border-base-content/30 bg-base-100 text-base-content/60",
};

function Step({ icon: Icon, tone = "done", title, time, children, last }) {
  return (
    <li className="relative grid grid-cols-[2rem_1fr] gap-x-4 pb-8 last:pb-0">
      {!last && <span className="absolute bottom-0 left-4 top-9 w-px -translate-x-1/2 bg-base-300" aria-hidden />}
      <span className={`relative grid size-8 place-items-center rounded-full border ${TONE[tone]}`} aria-hidden>
        <Icon size={16} weight={tone === "wait" ? "regular" : "bold"} />
      </span>
      <div className="min-w-0 pt-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <h3 className="font-semibold">{title}</h3>
          {time && <span className="num text-sm text-base-content/60">{time}</span>}
        </div>
        {children && <div className="mt-1.5 text-sm leading-relaxed text-base-content/80">{children}</div>}
      </div>
    </li>
  );
}

function IdLinks({ list, max = 12 }) {
  const shown = list.slice(0, max);
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1">
      {shown.map((o) => (
        <a key={o.complaint_id} href={href("track", o.complaint_id)} className="link link-hover link-primary font-mono text-sm">{o.complaint_id}</a>
      ))}
      {list.length > max && <span className="text-base-content/60">and {list.length - max} more</span>}
    </span>
  );
}

function Timeline({ c, wo, idx, className }) {
  const { openWorkOrder } = useWorkOrder();
  const siblings = (idx.byIssue.get(c.issue_id) || []).filter((o) => o.complaint_id !== c.complaint_id);
  const steps = [];

  steps.push(
    <Step key="rx" icon={ChatCircleText} title="Complaint received" time={when(c.received_at)}>
      Filed through {c.channel} in {LANG[c.language] || c.language}, about {c.category_clean.toLowerCase()} in ward {c.ward_code}.
    </Step>,
  );

  steps.push(
    <Step key="grp" icon={UsersThree} tone={siblings.length ? "done" : "wait"}
      title={siblings.length ? `Grouped with ${siblings.length} other complaint${siblings.length > 1 ? "s" : ""} about the same issue` : "No other complaints about this issue"}>
      {siblings.length ? (
        <>
          <p className="mb-2">
            Reports of the same problem at the same spot are treated as one issue (<span className="font-mono">{c.issue_id}</span>), so the crew handles them together.
            {c.status === "Closed - Duplicate" && " This report was closed as a duplicate and follows the same repair."}
          </p>
          <IdLinks list={siblings} />
        </>
      ) : (
        <p>This was the only report of issue <span className="font-mono">{c.issue_id}</span>.</p>
      )}
    </Step>,
  );

  if (!wo) return <NoRepair c={c} idx={idx} steps={steps} className={className} />;

  const flags = idx.flagsByWo.get(wo.work_order_id) || [];
  const repeat = flags.find((f) => f.flag_type === "REPEAT_REPAIR");
  const followUp = repeat?.related_work_order_id ? idx.woById.get(repeat.related_work_order_id) : null;
  const redoOf = (idx.flagsByRelated.get(wo.work_order_id) || []).find((f) => f.flag_type === "REPEAT_REPAIR");
  const others = wo.linked_complaint_ids.length - 1;
  // one job can cover several issues on a road; count the complaints not already listed in the grouping step
  const sameIssue = new Set([c.complaint_id, ...siblings.map((o) => o.complaint_id)]);
  const nearby = wo.linked_complaint_ids.filter((x) => !sameIssue.has(x)).length;
  const late = wo.sla_met !== "Y" && wo.hours_to_complete != null ? wo.hours_to_complete - wo.sla_hours : null;
  const reopened = wo.reopened_within_30d === "Y";
  // flag amounts overlap (one job can be overbilled, under warranty and redone at once); same rule as
  // export_data.py flagged_inr: the most at stake on a job is the max over non-SLA flags
  const atRisk = flags.filter((f) => f.amount_at_risk_inr > 0);
  const maxAtRisk = Math.max(0, ...flags.filter((f) => f.flag_type !== "SLA_MISS").map((f) => f.amount_at_risk_inr || 0));

  steps.push(
    <Step key="wo" icon={Wrench} title="Repair job assigned" time={when(wo.assigned_at)}>
      <p>
        <button className="link link-hover font-mono" onClick={() => openWorkOrder(wo.work_order_id)}>{wo.work_order_id}</button>{" "}
        went to <a className="link link-hover" href={href("contractors", wo.contractor_id)} title={idx.names[wo.contractor_id]}>{short(idx.names[wo.contractor_id])}</a>.
      </p>
      <p className="mt-1"><span className="text-base-content/60">Method: </span>{wo.repair_method}</p>
      <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-base-content/70">
        <MapPin size={14} aria-hidden /> {wo.road_name} <span className="font-mono">{wo.road_id}</span>
        {wo.under_dlp === "Y" && <span className="badge badge-soft badge-warning badge-sm">under warranty</span>}
      </p>
      {nearby > 0 && (
        <p className="mt-1 text-base-content/70">
          This job also covers {others} other complaint{others > 1 ? "s" : ""} on this road
          {nearby === others ? (others > 1 ? ", all about nearby issues" : ", about a nearby issue") : `, ${nearby} of them about nearby issues`}.
        </p>
      )}
      {redoOf && (
        <p className="mt-1 text-base-content/70">
          This job redid{" "}
          <button className="link link-hover font-mono" onClick={() => openWorkOrder(redoOf.work_order_id)}>{redoOf.work_order_id}</button>, an earlier repair here that did not last.
        </p>
      )}
    </Step>,
  );

  steps.push(
    <Step key="done" icon={wo.sla_met === "Y" ? CheckCircle : Clock} tone={wo.sla_met === "Y" ? "done" : "bad"}
      title={wo.sla_met === "Y" ? "Completed within the deadline" : "Completed after the deadline"} time={when(wo.completed_at)}>
      {wo.hours_to_complete != null ? (
        <p>
          Finished <span className="num font-medium">{span(wo.hours_to_complete, num)}</span> after the first complaint about it. The deadline
          (SLA, the time allowed for this kind of repair) was <span className="num">{num(wo.sla_hours)} h</span>
          {wo.sla_met === "Y" ? (
            <>, so it was <span className="font-medium text-success">met</span>.</>
          ) : (
            <>, so it was <span className="font-medium text-error">missed{late > 0 ? ` by ${num(late)} h` : ""}</span>
              {late != null && late <= 0 ? " (it finished right at the limit, and the record marks it late)" : ""}.</>
          )}
        </p>
      ) : (
        <p>Deadline {num(wo.sla_hours)} h: {wo.sla_met === "Y" ? "met" : "missed"}.</p>
      )}
    </Step>,
  );

  steps.push(
    <Step key="held" icon={reopened ? ArrowCounterClockwise : ShieldCheck} tone={reopened ? "bad" : "good"}
      title={reopened ? "Re-opened within 30 days" : "Held up for 30 days"}>
      {reopened ? (
        followUp ? (
          <p>
            The repair failed and the spot had to be fixed again as{" "}
            <button className="link link-hover font-mono" onClick={() => openWorkOrder(followUp.work_order_id)}>{followUp.work_order_id}</button>,
            assigned {when(followUp.assigned_at)} and billed <span className="num font-medium">{inr(followUp.cost_inr)}</span>.
          </p>
        ) : (
          <p>The repair failed within a month and the problem came back.</p>
        )
      ) : (
        <p>No repeat repair was needed on this spot in the 30 days after the job.</p>
      )}
    </Step>,
  );

  steps.push(
    <Step key="money" icon={CurrencyInr} tone={flags.length ? "warn" : "done"} title="Money billed" last>
      <p>
        <span className="num text-xl font-semibold text-base-content">{inr(wo.cost_inr)}</span>
        <span className="text-base-content/60"> billed to the BMC for {wo.work_order_id}{wo.area_sqm ? `, ${num(wo.area_sqm, 1)} sqm` : ""}.</span>
      </p>
      {flags.length === 0 ? (
        <p className="mt-2 flex items-center gap-1.5 text-base-content/70"><CheckCircle size={16} className="text-success" aria-hidden /> No audit flags on this job.</p>
      ) : (
        <>
          <p className="mt-2">{flags.length === 1 ? "The audit marked one thing on this job that needs review:" : `The audit marked ${flags.length} things on this job that need review:`}</p>
          {atRisk.length > 1 && maxAtRisk > 0 && (
            <p className="mt-1 text-base-content/70">
              These amounts overlap, so do not add them up. The most at stake on this job is{" "}
              <span className="num font-semibold text-base-content">{inr(maxAtRisk)}</span>.
            </p>
          )}
          <ul className="mt-2 divide-y divide-base-300 rounded-box border border-base-300">
            {flags.map((f) => (
              <li key={f.flag_id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <FlagBadge type={f.flag_type} />
                  <SevBadge severity={f.severity} />
                  {f.amount_at_risk_inr > 0 && <span className="num ml-auto text-sm font-semibold text-base-content">{inr(f.amount_at_risk_inr)} to review</span>}
                </div>
                <p className="mt-2 text-base-content">{neutral(f.evidence)}</p>
                <p className="mt-1 text-xs text-base-content/60">{FLAG_HELP[f.flag_type]}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </Step>,
  );

  return (
    <section className={`rounded-box border border-base-300 bg-base-100 ${className}`} aria-labelledby="timeline-h">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 px-5 py-4">
        <div>
          <h2 id="timeline-h" className="font-semibold">What happened next</h2>
          <p className="mt-0.5 text-sm text-base-content/60">From the report to the money spent on the fix</p>
        </div>
        <button className="btn btn-sm btn-primary" onClick={() => openWorkOrder(wo.work_order_id)}>
          Open full work order <ArrowSquareOut size={16} aria-hidden />
        </button>
      </div>
      <ol className="px-5 py-6">{steps}</ol>
    </section>
  );
}

/** keep the "needs review" tone on a citizen page: drop the audit pipeline's "(paid twice)" verdict */
const neutral = (s) => (s || "").replace(/\s*\(paid twice\)\s*$/, "");

/* ---------- complaints that never became a repair job ---------- */

const WAIT_ICON = {
  Open: HourglassMedium,
  "In Progress": HourglassMedium,
  "Forwarded to MMRDA/PWD": ArrowBendUpRight,
  "Forwarded to SWM dept": ArrowBendUpRight,
  "Rejected - Not road issue": XCircle,
  "Rejected - Not BMC road": XCircle,
};

function NoRepair({ c, idx, steps, className }) {
  const s = statusInfo(c.status);
  const openHere = (idx.openByWard.get(c.ward_code) || []).filter((o) => o.complaint_id !== c.complaint_id);
  const ward = idx.wardByCode.get(c.ward_code);
  const pending = isOpen(c.status);

  steps.push(
    <Step key="status" icon={WAIT_ICON[c.status] || Warning} tone={pending ? "warn" : "wait"} title={s.title} last>
      <p>{s.text}</p>
      <p className="mt-1 text-base-content/60">No repair job is linked to this complaint, so no money has been billed against it.</p>
    </Step>,
  );

  const sample = openHere.slice().sort((a, b) => (b.severity_1_5 - a.severity_1_5) || (b.upvotes - a.upvotes)).slice(0, 5);

  return (
    <div className={`flex flex-col gap-6 ${className}`}>
      <section className="rounded-box border border-base-300 bg-base-100" aria-labelledby="timeline-h">
        <div className="border-b border-base-300 px-5 py-4">
          <h2 id="timeline-h" className="font-semibold">What happened next</h2>
          <p className="mt-0.5 text-sm text-base-content/60">This complaint has not turned into a repair job</p>
        </div>
        <ol className="px-5 py-6">{steps}</ol>
      </section>

      <section className="rounded-box border border-base-300 bg-base-100 px-5 py-5" aria-labelledby="ward-open-h">
        <h2 id="ward-open-h" className="font-semibold">Other open complaints in ward {c.ward_code}</h2>
        <p className="mt-1 text-sm text-base-content/70">
          <span className="num text-2xl font-semibold text-base-content">{num(openHere.length)}</span>{" "}
          other complaint{openHere.length === 1 ? " is" : "s are"} still open or in progress in {ward ? ward.ward_name : `ward ${c.ward_code}`}, with no repair job yet.
        </p>
        {sample.length > 0 && (
          <>
            <h3 className="mt-4 text-sm text-base-content/60">Most severe of them</h3>
            <ul className="mt-1 divide-y divide-base-300">
              {sample.map((o) => (
                <li key={o.complaint_id}>
                  <a href={href("track", o.complaint_id)} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 rounded-field py-2 hover:bg-base-200 focus-visible:outline-2 focus-visible:outline-primary">
                    <span className="font-mono text-sm text-primary">{o.complaint_id}</span>
                    <span className="text-sm">{o.category_clean}</span>
                    <span className="text-sm text-base-content/60">{o.locality_text}</span>
                    <span className="num ml-auto text-sm text-base-content/60">severity {o.severity_1_5}, {when(o.received_at.split(" ")[0])}</span>
                  </a>
                </li>
              ))}
            </ul>
          </>
        )}
        <a className="btn btn-sm mt-4" href={href("wards", c.ward_code)}>See ward {c.ward_code} money trail</a>
      </section>
    </div>
  );
}

