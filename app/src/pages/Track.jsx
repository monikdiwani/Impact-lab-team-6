import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { MagnifyingGlass, CaretRight, X } from "@phosphor-icons/react";
import { useData, byKey } from "../lib/data";
import { num, when } from "../lib/format";
import { href, go, setQuery } from "../lib/router";
import { PageHeader, ErrorState, EmptyState } from "../components/ui";
import ComplaintView, { StatusBadge } from "./track/ComplaintView";
import { LANG, LANG_ATTR, STATUS, parseComplaintId, excerpt, isOpen, same } from "./track/helpers";

/*
  Complaint tracker: "what happened to my complaint?"
    #/track                  intro, search, three example complaints
    #/track?q=khadda         search results (any language, substring match)
    #/track/BMC25-000005     one complaint and its timeline
  complaints.json is 4 MB, so it is loaded here and in the work order sheet only.
*/
const MAX_RESULTS = 20;
const TRY = ["BMC25-000005", "Hindmata", "khadda", "खड्डा"];
const DEVANAGARI = /[ऀ-ॿ]/;

export default function Track({ id, query }) {
  const state = useData(["complaints", "work_orders", "flags", "contractor_names", "wards"]);
  const idx = useMemo(() => (state.data ? buildIndex(state.data) : null), [state.data]);

  // small file, loaded separately so the "Loading N complaints" line does not wait on the 4 MB one
  const summary = useData("summary");

  /*
    The URL is the source of truth for the search box: Back/Forward, the nav link and shared
    links all restore exactly what the box shows. Opening a complaint (no ?q) clears it.
    Typing writes ?q= back to the URL after a short pause, with replaceState (no history spam).
  */
  const urlQ = query?.q || "";
  const [input, setInput] = useState(urlQ);
  useEffect(() => {
    setInput((cur) => (cur.trim() === urlQ ? cur : urlQ));
  }, [id, urlQ]);
  useEffect(() => {
    const v = input.trim();
    if (v === urlQ) return;
    const t = setTimeout(() => setQuery(v ? { q: v } : null), 350);
    return () => clearTimeout(t);
  }, [input, urlQ]);
  const term = useDeferredValue(input.trim());
  const searching = term.length > 0 && !parseComplaintId(term);
  const cid = id ? parseComplaintId(id) || id.toUpperCase() : null;

  const submit = (e) => {
    e.preventDefault();
    const v = input.trim();
    const asId = parseComplaintId(v);
    if (asId) return go("track", asId);
    if (v) go("track", null, { q: v });
  };

  let body;
  if (state.error) body = <ErrorState error={state.error} what="the complaints" />;
  else if (!idx) body = <BodySkeleton detail={!!cid && !searching} />;
  else if (searching) body = <Results term={term} idx={idx} />;
  else if (cid) {
    const c = idx.byId.get(cid);
    body = c ? (
      <ComplaintView key={c.complaint_id} c={c} idx={idx} />
    ) : (
      <section className="rounded-box border border-base-300 bg-base-100">
        <EmptyState
          title={`No complaint with ID ${cid}`}
          hint="Complaint IDs look like BMC25-000005. Check the number on your SMS or app receipt, or search by the words you used."
          action={<a className="btn btn-sm mt-2" href={href("track")}>Back to the tracker</a>}
        />
      </section>
    );
  } else body = <Intro idx={idx} />;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Complaint tracker"
        lede="What happened to a road complaint: who it was grouped with, which repair job it became, whether the fix lasted and what it cost."
      />
      <SearchBox input={input} setInput={setInput} onSubmit={submit} ready={!!idx} total={summary.data?.n_complaints} />
      {body}
    </div>
  );
}

/* ---------- data index, built once per load ---------- */

function buildIndex([complaints, workOrders, flags, names, wards]) {
  const byIssue = new Map();
  const openByWard = new Map();
  const statusCount = {};
  const hay = new Array(complaints.length);
  let first = null;
  let last = null;
  complaints.forEach((c, i) => {
    if (c.received_at) {
      if (!first || c.received_at < first) first = c.received_at;
      if (!last || c.received_at > last) last = c.received_at;
    }
    if (!byIssue.has(c.issue_id)) byIssue.set(c.issue_id, []);
    byIssue.get(c.issue_id).push(c);
    if (isOpen(c.status)) {
      if (!openByWard.has(c.ward_code)) openByWard.set(c.ward_code, []);
      openByWard.get(c.ward_code).push(c);
    }
    statusCount[c.status] = (statusCount[c.status] || 0) + 1;
    hay[i] = `${c.complaint_id}\n${c.description || ""}\n${c.locality_text || ""}\n${c.english_summary || ""}`.toLowerCase();
  });
  const group = (rows, k) => {
    const m = new Map();
    for (const r of rows) if (r[k]) (m.get(r[k]) || m.set(r[k], []).get(r[k])).push(r);
    return m;
  };
  return {
    complaints,
    hay,
    byId: byKey(complaints, "complaint_id"),
    byIssue,
    openByWard,
    statusCount,
    firstDay: first && first.split(" ")[0],
    lastDay: last && last.split(" ")[0],
    woById: byKey(workOrders, "work_order_id"),
    flagsByWo: group(flags, "work_order_id"),
    flagsByRelated: group(flags, "related_work_order_id"),
    names,
    wardByCode: byKey(wards, "ward_code"),
  };
}

/* ---------- search ---------- */

function SearchBox({ input, setInput, onSubmit, ready, total }) {
  return (
    <form onSubmit={onSubmit} role="search" className="enter enter-d1 rounded-box border border-base-300 bg-base-100 p-5">
      <label htmlFor="track-q" className="block font-semibold">Find a complaint</label>
      <p id="track-q-help" className="mt-0.5 text-sm text-base-content/60">
        Type the complaint ID, or any words from it in English, Hinglish, Marathi or Hindi.
      </p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <label className="input w-full sm:max-w-xl">
          <MagnifyingGlass size={18} className="opacity-60" aria-hidden />
          <input id="track-q" type="search" value={input} onChange={(e) => setInput(e.target.value)} autoComplete="off"
            placeholder="BMC25-000005 or a place, road or problem" aria-describedby="track-q-help" />
          {input && (
            <button type="button" className="btn btn-ghost btn-xs btn-circle" onClick={() => setInput("")} aria-label="Clear search">
              <X size={16} />
            </button>
          )}
        </label>
        <button type="submit" className="btn btn-primary">Track</button>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-base-content/60">
        <span>Try</span>
        {TRY.map((t) => (
          <button key={t} type="button" className="btn btn-xs btn-ghost border border-base-300 font-normal"
            lang={DEVANAGARI.test(t) ? "mr" : undefined}
            onClick={() => (parseComplaintId(t) ? go("track", t) : setInput(t))}>
            {t}
          </button>
        ))}
        {!ready && <span className="ml-auto flex items-center gap-2"><span className="loading loading-spinner loading-xs" aria-hidden /> Loading {total ? <><span className="num">{num(total)}</span> complaints</> : "complaints"}</span>}
      </div>
    </form>
  );
}

function Results({ term, idx }) {
  const { list, total } = useMemo(() => {
    const t = term.toLowerCase();
    const list = [];
    let total = 0;
    idx.hay.forEach((h, i) => {
      if (h.includes(t)) {
        total++;
        if (list.length < MAX_RESULTS) list.push(idx.complaints[i]);
      }
    });
    return { list, total };
  }, [term, idx]);

  if (!total) {
    return (
      <section className="rounded-box border border-base-300 bg-base-100">
        <EmptyState
          title={`No complaints mention "${term}"`}
          hint="Try a shorter word, a locality such as Hindmata or Dadar, or the same word in another language, for example pothole, khadda or खड्डा."
        />
      </section>
    );
  }

  return (
    <section className="enter rounded-box border border-base-300 bg-base-100" aria-labelledby="results-h">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-base-300 px-5 py-4">
        <h2 id="results-h" className="font-semibold">
          <span className="num">{num(total)}</span> complaint{total === 1 ? "" : "s"} mention "{term}"
        </h2>
        {total > MAX_RESULTS && <p className="text-sm text-base-content/60">Showing the first {MAX_RESULTS}. Add a word to narrow it down.</p>}
      </div>
      <ComplaintRows rows={list} />
    </section>
  );
}

/** clickable complaint rows shared by search results and the examples */
function ComplaintRows({ rows, notes }) {
  return (
    <ul className="divide-y divide-base-300">
      {rows.map((c, i) => (
        <li key={c.complaint_id}>
          <a href={href("track", c.complaint_id)}
            className="group grid grid-cols-[1fr_auto] items-center gap-x-4 px-5 py-4 hover:bg-base-200/60 focus-visible:bg-base-200/60 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary">
            <div className="min-w-0">
              {notes?.[i] && <div className="mb-1 font-medium">{notes[i]}</div>}
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                <span className="font-mono text-primary">{c.complaint_id}</span>
                <span className="text-base-content/60">{when(c.received_at.split(" ")[0])}</span>
                <span className="text-base-content/60">Ward {c.ward_code}</span>
                <span className="badge badge-ghost badge-sm">{LANG[c.language] || c.language}</span>
                <StatusBadge status={c.status} />
              </div>
              <p className="mt-1.5 text-sm text-base-content/80" lang={LANG_ATTR[c.language]}>{excerpt(c.description)}</p>
              {notes && c.english_summary && !same(c.english_summary, c.description) && (
                <p className="mt-0.5 text-sm text-base-content/60">In English: {excerpt(c.english_summary)}</p>
              )}
            </div>
            <CaretRight size={18} className="text-base-content/40 transition-transform group-hover:translate-x-0.5" aria-hidden />
          </a>
        </li>
      ))}
    </ul>
  );
}

/* ---------- landing: intro, examples, what statuses mean ---------- */

function pickExamples(idx) {
  const wo = (c) => idx.woById.get(c.linked_work_order_id);
  const flagTypes = (c) => (idx.flagsByWo.get(c.linked_work_order_id) || []).map((f) => f.flag_type);
  // prefer the most telling record of each kind, but always fall back to any match
  const first = (...tests) => {
    for (const t of tests) {
      const hit = idx.complaints.find(t);
      if (hit) return hit;
    }
    return null;
  };
  const mr = first(
    // a job that held up but still has a money flag, so it tells a different story from the Hinglish one
    (c) => c.language === "mr" && DEVANAGARI.test(c.description) && wo(c)?.reopened_within_30d === "N" && flagTypes(c).some((t) => t === "OVERBILL" || t === "DLP_PAID"),
    (c) => c.language === "mr" && wo(c)?.reopened_within_30d === "N" && flagTypes(c).some((t) => t === "OVERBILL" || t === "DLP_PAID"),
    (c) => c.language === "mr" && DEVANAGARI.test(c.description) && c.status === "Resolved" && flagTypes(c).some((t) => t !== "SLA_MISS"),
    (c) => c.language === "mr" && DEVANAGARI.test(c.description) && flagTypes(c).length > 0,
    (c) => c.language === "mr" && flagTypes(c).some((t) => t !== "SLA_MISS"),
    (c) => c.language === "mr" && flagTypes(c).length > 0,
  );
  const hien = first(
    (c) => c.language === "hi-en" && c.status === "Resolved" && wo(c)?.reopened_within_30d === "Y" && c.photo_description,
    (c) => c.language === "hi-en" && wo(c)?.reopened_within_30d === "Y",
  );
  const dup = first(
    (c) => c.status === "Closed - Duplicate" && (idx.byIssue.get(c.issue_id) || []).length >= 3 && wo(c)?.reopened_within_30d === "N",
    (c) => c.status === "Closed - Duplicate" && wo(c)?.reopened_within_30d === "N",
    (c) => c.status === "Closed - Duplicate" && (idx.byIssue.get(c.issue_id) || []).length >= 3,
    (c) => c.status === "Closed - Duplicate",
  );
  return [
    mr && { c: mr, note: "Marathi complaint, and the repair job has audit flags" },
    hien && { c: hien, note: "Hinglish complaint, and the repair did not last 30 days" },
    dup && { c: dup, note: "Closed as a duplicate of an earlier report" },
  ].filter(Boolean);
}

const STATUS_ORDER = [
  "Resolved", "Closed - Duplicate", "Open", "In Progress",
  "Forwarded to MMRDA/PWD", "Forwarded to SWM dept", "Rejected - Not BMC road", "Rejected - Not road issue",
];

function Intro({ idx }) {
  const examples = useMemo(() => pickExamples(idx), [idx]);
  const total = idx.complaints.length;
  return (
    <div className="grid items-start gap-6 lg:grid-cols-12">
      <section className="enter enter-d2 rounded-box border border-base-300 bg-base-100 lg:col-span-7" aria-labelledby="try-h">
        <div className="border-b border-base-300 px-5 py-4">
          <h2 id="try-h" className="font-semibold">Start with a real complaint</h2>
          <p className="mt-0.5 text-sm text-base-content/60">
            Each one shows a different ending. Open it to follow the complaint through to the repair and the bill.
          </p>
        </div>
        {examples.length ? <ComplaintRows rows={examples.map((e) => e.c)} notes={examples.map((e) => e.note)} /> : (
          <EmptyState title="No example complaints found" hint="Search by ID or words above instead." />
        )}
      </section>

      <section className="enter enter-d3 lg:col-span-5" aria-labelledby="status-h">
        <h2 id="status-h" className="font-semibold">What each status means</h2>
        <p className="mt-0.5 text-sm text-base-content/60">
          All <span className="num">{num(total)}</span> complaints
          {idx.firstDay && idx.lastDay ? <>, received <span className="num">{when(idx.firstDay)}</span> to <span className="num">{when(idx.lastDay)}</span></> : ""}.
        </p>
        <dl className="mt-3 divide-y divide-base-300 border-y border-base-300">
          {STATUS_ORDER.filter((s) => idx.statusCount[s]).map((s) => (
            <div key={s} className="grid grid-cols-[1fr_auto] gap-x-4 py-3">
              <dt className="flex items-center gap-2">
                <StatusBadge status={s} />
                <span className="text-sm font-medium">{STATUS[s].title}</span>
              </dt>
              <dd className="num row-span-2 text-right text-sm">
                <div className="font-semibold">{num(idx.statusCount[s])}</div>
                <div className="text-base-content/60">{((100 * idx.statusCount[s]) / total).toFixed(1)}%</div>
              </dd>
              <dd className="mt-1 text-sm text-base-content/60">{STATUS[s].text}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

function BodySkeleton({ detail }) {
  return (
    <div className="grid items-start gap-6 lg:grid-cols-12" aria-busy="true" aria-label="Loading complaints">
      <div className={`skeleton ${detail ? "h-[34rem] lg:col-span-5" : "h-80 lg:col-span-7"}`} />
      <div className={`skeleton ${detail ? "h-[40rem] lg:col-span-7" : "h-[28rem] lg:col-span-5"}`} />
    </div>
  );
}
