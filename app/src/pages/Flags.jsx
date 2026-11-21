import { useEffect, useMemo, useRef, useState } from "react";
import { MagnifyingGlass, X, DownloadSimple, Info, CaretDown, CaretUp, CaretUpDown, CaretLeft, CaretRight } from "@phosphor-icons/react";
import { useData, byKey } from "../lib/data";
import { inr, inrShort, num, short, FLAG_LABEL, FLAG_HELP } from "../lib/format";
import { setQuery } from "../lib/router";
import { PageHeader, Loaded, EmptyState, FlagBadge, SevBadge, WardSelect, ContractorName } from "../components/ui";
import { useWorkOrder } from "../components/WorkOrderPanel";
import { toCsv, csvName, downloadCsv, evidenceText } from "./flags/csv";

/*
  Audit flags: the auditor's worklist.
  URL: #/flags?type=&ward=&contractor=&severity=&q=&sort=&page=
  The URL is the source of truth for filters, sort and page, so any view can be linked.
*/

const PAGE_SIZE = 50;
const SEVERITIES = ["high", "medium", "low"];
const SEV_RANK = { high: 0, medium: 1, low: 2 };
const SORTS = {
  "-risk": ["amount_at_risk_inr", -1],
  risk: ["amount_at_risk_inr", 1],
  "-billed": ["billed_inr", -1],
  billed: ["billed_inr", 1],
};
const DEFAULT_SORT = "-risk";
const FILTER_KEYS = ["type", "ward", "contractor", "severity", "q"];
const AT_RISK_HELP =
  "At risk: money the city may not have needed to pay (billed above the rate card, paid during warranty, billed twice, or paid again for a redo). For a repair that did not last, it is what the follow-up job billed.";

export default function Flags({ query = {} }) {
  const state = useData(["flags", "wards", "contractor_names"]);
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Audit flags"
        lede="Every repair job the audit checks marked for review, with the evidence behind it. Filter the list, sort by money, and open a row to follow the rupee from complaint to payment. Amount at risk is money the city may not have needed to pay."
      />
      <Loaded state={state} what="the audit flags">
        {([flags, wards, names]) => <Worklist flags={flags} wards={wards} names={names} query={query} />}
      </Loaded>
    </div>
  );
}

/** read and validate the URL query against the real data */
function readFilters(query, wardMap, names) {
  return {
    type: FLAG_LABEL[query.type] ? query.type : "",
    ward: wardMap.has(query.ward) ? query.ward : "",
    contractor: names[query.contractor] ? query.contractor : "",
    severity: SEVERITIES.includes(query.severity) ? query.severity : "",
    q: (query.q || "").trim(),
    sort: SORTS[query.sort] ? query.sort : DEFAULT_SORT,
    page: Math.max(1, parseInt(query.page, 10) || 1),
  };
}

function Worklist({ flags, wards, names, query }) {
  const { openWorkOrder } = useWorkOrder();
  const wardMap = useMemo(() => byKey(wards, "ward_code"), [wards]);
  const wardName = useMemo(() => new Map(wards.map((w) => [w.ward_code, w.ward_name])), [wards]);
  const f = readFilters(query, wardMap, names);
  const active = FILTER_KEYS.some((k) => f[k]);
  // latest filters, so a delayed search push never writes back stale filters
  const fRef = useRef(f);
  fRef.current = f;

  const contractorOptions = useMemo(
    () =>
      Object.entries(names)
        .map(([id, name]) => ({ id, label: short(name) }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [names],
  );

  // search box keeps its own text and pushes to the URL after a short pause
  const [text, setText] = useState(f.q);
  const textRef = useRef(text);
  textRef.current = text;
  const pushed = useRef(f.q);
  const timer = useRef(0);

  /**
   * Write a patch to the URL; any filter change sends you back to page 1.
   * Reads the latest filters and search text from refs and cancels a pending
   * search push, so typing then quickly changing a select keeps both changes.
   */
  const update = (patch) => {
    clearTimeout(timer.current);
    const next = { ...fRef.current, q: textRef.current.trim(), ...patch };
    if (!("page" in patch)) next.page = 1;
    pushed.current = next.q;
    setQuery({
      type: next.type,
      ward: next.ward,
      contractor: next.contractor,
      severity: next.severity,
      q: next.q,
      sort: next.sort === DEFAULT_SORT ? "" : next.sort,
      page: next.page > 1 ? next.page : "",
    });
  };
  const clearAll = () => {
    clearTimeout(timer.current);
    pushed.current = "";
    textRef.current = "";
    setText("");
    const s = fRef.current.sort;
    setQuery({ sort: s === DEFAULT_SORT ? "" : s });
  };
  /** Enter in the search box pushes the text right away */
  const flushSearch = () => {
    if (textRef.current.trim() !== fRef.current.q) update({});
  };

  useEffect(() => {
    if (f.q !== pushed.current) {
      pushed.current = f.q;
      setText(f.q);
    }
  }, [f.q]);
  useEffect(() => {
    const t = text.trim();
    if (t === pushed.current) return;
    timer.current = setTimeout(() => update({}), 250);
    return () => clearTimeout(timer.current);
    // update() reads refs, so the timer never acts on stale filters
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const rows = useMemo(() => {
    const needle = f.q.toLowerCase();
    const out = flags.filter(
      (r) =>
        (!f.type || r.flag_type === f.type) &&
        (!f.ward || r.ward_code === f.ward) &&
        (!f.contractor || r.contractor_id === f.contractor) &&
        (!f.severity || r.severity === f.severity) &&
        (!needle ||
          r.work_order_id.toLowerCase().includes(needle) ||
          (r.related_work_order_id || "").toLowerCase().includes(needle) ||
          (r.road_id || "").toLowerCase().includes(needle) ||
          (r.evidence || "").toLowerCase().includes(needle)),
    );
    const [key, dir] = SORTS[f.sort];
    return out.sort(
      (a, b) =>
        dir * ((a[key] || 0) - (b[key] || 0)) ||
        SEV_RANK[a.severity] - SEV_RANK[b.severity] ||
        a.work_order_id.localeCompare(b.work_order_id),
    );
  }, [flags, f.type, f.ward, f.contractor, f.severity, f.q, f.sort]);

  const summary = useMemo(() => {
    // money at risk is counted once per billed job (largest flag), the same rule as the pipeline
    // (pipeline/audit/scorecards.py _money_by_wo, used by export_data.py flagged_inr). A REPEAT_REPAIR
    // amount is the follow-up job's bill, so it is keyed to related_work_order_id. Missed deadlines
    // carry no rupee amount.
    const perWo = new Map();
    const sev = { high: 0, medium: 0, low: 0 };
    let money = 0;
    for (const r of rows) {
      sev[r.severity] += 1;
      if (r.flag_type === "SLA_MISS") continue;
      money += 1;
      const job = r.flag_type === "REPEAT_REPAIR" && r.related_work_order_id ? r.related_work_order_id : r.work_order_id;
      perWo.set(job, Math.max(perWo.get(job) || 0, r.amount_at_risk_inr || 0));
    }
    let atRisk = 0;
    for (const v of perWo.values()) atRisk += v;
    const onlySla = rows.length > 0 && money === 0;
    return { n: rows.length, wos: new Set(rows.map((r) => r.work_order_id)).size, atRisk, sev, onlySla };
  }, [rows]);

  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const page = Math.min(f.page, pages);
  const start = (page - 1) * PAGE_SIZE;
  const view = rows.slice(start, start + PAGE_SIZE);
  const maxRisk = useMemo(() => rows.reduce((m, r) => Math.max(m, r.amount_at_risk_inr || 0), 0), [rows]);

  const tableRef = useRef(null);
  const goPage = (p) => {
    update({ page: p });
    tableRef.current?.scrollTo({ top: 0 });
  };

  const onDownload = () => downloadCsv(toCsv(rows, { names, wardName }), csvName(f));

  return (
    <div className="flex flex-col gap-5">
      {/* filters */}
      <form
        role="search"
        aria-label="Filter flags"
        onSubmit={(e) => {
          e.preventDefault();
          flushSearch();
        }}
        className="enter enter-d1 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:flex lg:flex-wrap lg:items-end"
      >
        <Field label="Flag type" id="f-type">
          <select id="f-type" className="select select-sm w-full lg:w-44" value={f.type} onChange={(e) => update({ type: e.target.value })}>
            <option value="">All types</option>
            {Object.entries(FLAG_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>

        <div className="[&_select]:w-full lg:[&_select]:w-60">
          <WardSelect id="f-ward" wards={wards} value={f.ward} allowAll onChange={(v) => update({ ward: v || "" })} />
        </div>

        <Field label="Contractor" id="f-contractor">
          <select
            id="f-contractor"
            className="select select-sm w-full lg:w-52"
            value={f.contractor}
            onChange={(e) => update({ contractor: e.target.value })}
          >
            <option value="">All contractors</option>
            {contractorOptions.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Severity" id="f-sev">
          <select
            id="f-sev"
            className="select select-sm w-full lg:w-32"
            value={f.severity}
            onChange={(e) => update({ severity: e.target.value })}
          >
            <option value="">Any severity</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s[0].toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Search" id="f-q" className="sm:col-span-2 lg:min-w-44 lg:flex-1">
          <label className="input input-sm w-full">
            <MagnifyingGlass size={16} className="text-base-content/50" aria-hidden />
            <input
              id="f-q"
              type="search"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="WO, road ID or words"
              autoComplete="off"
            />
          </label>
        </Field>

        {active && (
          <button type="button" className="btn btn-sm btn-ghost justify-self-start" onClick={clearAll}>
            <X size={16} aria-hidden />
            Clear filters
          </button>
        )}
      </form>

      {f.type && (
        <p className="enter flex items-start gap-2 text-sm text-base-content/80">
          <Info size={18} className="mt-px shrink-0 text-primary" aria-hidden />
          <span>
            <span className="font-medium text-base-content">{FLAG_LABEL[f.type]}:</span> {FLAG_HELP[f.type]}
          </span>
        </p>
      )}

      {/* result summary + export */}
      <div className="enter enter-d2 flex flex-col gap-3 border-t border-base-300 pt-4 md:flex-row md:items-center md:justify-between">
        <p className="text-sm text-base-content/70" aria-live="polite">
          <span className="num font-semibold text-base-content">{num(summary.n)}</span> {summary.n === 1 ? "flag" : "flags"} on{" "}
          <span className="num">{num(summary.wos)}</span> {summary.wos === 1 ? "work order" : "work orders"},{" "}
          {summary.onlySla ? (
            <span title={AT_RISK_HELP}>no rupee amount (missed deadlines cost time)</span>
          ) : (
            <span
              title={`${inr(summary.atRisk)}. ${AT_RISK_HELP} Counted once per work order, the same rule as the Overview, so a redo flag and a flag on its follow-up job can still share one bill.`}
            >
              <span className="num font-semibold text-base-content">{inrShort(summary.atRisk)}</span> at risk
            </span>
          )}
          {summary.n > 0 && (
            <>
              <span className="mx-2 hidden text-base-content/30 md:inline" aria-hidden>
                |
              </span>
              <span className="mt-1 block md:mt-0 md:inline">
                <SevCount n={summary.sev.high} label="high" dot="bg-error" />
                <SevCount n={summary.sev.medium} label="medium" dot="bg-warning" />
                <SevCount n={summary.sev.low} label="low" dot="bg-base-content/30" />
              </span>
            </>
          )}
        </p>
        {rows.length > 0 && (
          <button type="button" className="btn btn-sm btn-outline self-start md:self-auto" onClick={onDownload}>
            <DownloadSimple size={16} aria-hidden />
            Download CSV
          </button>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="rounded-box border border-base-300 bg-base-100">
          <EmptyState
            title="No flags match these filters"
            hint={
              f.q
                ? `Nothing matches "${f.q}". Search looks at work order IDs (WO25-00003), road IDs (RD0239) and evidence text.`
                : "Try another ward, contractor or severity, or clear the filters to see the full list."
            }
            action={
              <button type="button" className="btn btn-sm btn-primary mt-2" onClick={clearAll}>
                Clear filters
              </button>
            }
          />
        </div>
      ) : (
        <div className="enter enter-d3 flex flex-col gap-3">
          <div ref={tableRef} className="max-h-[75vh] overflow-auto rounded-box border border-base-300 bg-base-100 [contain:inline-size]">
            <table className="table table-sm table-pin-rows">
              <caption className="sr-only">
                Audit flags, sorted by {SORTS[f.sort][0] === "billed_inr" ? "billed amount" : "amount at risk"},{" "}
                {SORTS[f.sort][1] < 0 ? "largest first" : "smallest first"}. Select a work order to open its details.
              </caption>
              <thead>
                <tr className="border-b border-base-300 text-base-content/70">
                  <th scope="col">Flag</th>
                  <th scope="col">Severity</th>
                  <th scope="col">Work order</th>
                  <th scope="col">Ward</th>
                  <th scope="col">Road</th>
                  <th scope="col">Contractor</th>
                  <SortTh label="Billed" field="billed" sort={f.sort} onSort={(s) => update({ sort: s })} />
                  <SortTh label="At risk" field="risk" sort={f.sort} onSort={(s) => update({ sort: s })} title={AT_RISK_HELP} />
                  <th scope="col">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {view.map((r) => (
                  <tr
                    key={r.flag_id}
                    onClick={() => openWorkOrder(r.work_order_id)}
                    className="cursor-pointer border-base-300 hover:bg-base-200 focus-within:bg-base-200"
                  >
                    <td>
                      <FlagBadge type={r.flag_type} />
                    </td>
                    <td>
                      <SevBadge severity={r.severity} />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="rounded-field font-mono text-xs whitespace-nowrap text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                        aria-label={`Open work order ${r.work_order_id}`}
                      >
                        {r.work_order_id}
                      </button>
                    </td>
                    <td className="whitespace-nowrap" title={wardName.get(r.ward_code)}>
                      {r.ward_code}
                    </td>
                    <td className="font-mono text-xs whitespace-nowrap">{r.road_id}</td>
                    <td className="whitespace-nowrap">
                      <ContractorName name={names[r.contractor_id]} />
                    </td>
                    <td className="num text-right whitespace-nowrap">{inr(r.billed_inr)}</td>
                    <td className="num text-right whitespace-nowrap">
                      {r.flag_type === "SLA_MISS" || !r.amount_at_risk_inr ? (
                        <span className="text-base-content/40" title={r.flag_type === "SLA_MISS" ? "A missed deadline costs time, not a billed amount" : "No follow-up job was billed, so no rupee amount is attached"}>
                          -
                        </span>
                      ) : (
                        <span className="inline-flex flex-col items-end">
                          <span className="inline-flex items-center justify-end gap-2">
                            <span className="hidden w-12 justify-end xl:flex">
                              <Bar value={r.amount_at_risk_inr} max={maxRisk} />
                            </span>
                            <span className="font-medium">{inr(r.amount_at_risk_inr)}</span>
                          </span>
                          {r.flag_type === "REPEAT_REPAIR" && r.related_work_order_id && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                openWorkOrder(r.related_work_order_id);
                              }}
                              title={`Billed on follow-up job ${r.related_work_order_id}`}
                              aria-label={`Open follow-up work order ${r.related_work_order_id}, where this amount was billed`}
                              className="rounded-field text-xs font-normal text-base-content/60 underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                            >
                              on <span className="font-mono">{r.related_work_order_id}</span>
                            </button>
                          )}
                        </span>
                      )}
                    </td>
                    <td className="w-full max-w-0 min-w-64 truncate text-base-content/70" title={evidenceText(r.evidence)}>
                      {evidenceText(r.evidence)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pager page={page} pages={pages} start={start} shown={view.length} total={rows.length} onPage={goPage} />
        </div>
      )}
    </div>
  );
}

function Field({ label, id, className = "", children }) {
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label htmlFor={id} className="text-sm text-base-content/70">
        {label}
      </label>
      {children}
    </div>
  );
}

function SevCount({ n, label, dot }) {
  return (
    <span className="mr-3 inline-flex items-center gap-1.5 whitespace-nowrap last:mr-0">
      <span className={`size-2 rounded-full ${dot}`} aria-hidden />
      <span className="num text-base-content">{num(n)}</span> {label}
    </span>
  );
}

/** right-aligned bar with no track; width relative to the largest amount in the current result */
function Bar({ value, max }) {
  const w = max > 0 ? Math.max(4, Math.round((100 * value) / max)) : 0;
  return <span className="inline-block h-1.5 rounded-full bg-primary/60" style={{ width: `${w}%` }} aria-hidden />;
}

function SortTh({ label, field, sort, onSort, title }) {
  const on = sort === field || sort === `-${field}`;
  const desc = sort === `-${field}`;
  const Icon = !on ? CaretUpDown : desc ? CaretDown : CaretUp;
  const next = on && desc ? field : `-${field}`;
  return (
    <th scope="col" aria-sort={on ? (desc ? "descending" : "ascending") : "none"} className="text-right" title={title}>
      <button
        type="button"
        onClick={() => onSort(next)}
        className={`inline-flex items-center gap-1 rounded-field px-1 -mx-1 hover:text-base-content focus-visible:outline-2 focus-visible:outline-primary ${on ? "text-base-content" : ""}`}
        aria-label={`Sort by ${label.toLowerCase()}, ${next.startsWith("-") ? "largest first" : "smallest first"}`}
      >
        {label}
        <Icon size={16} aria-hidden className={on ? "text-primary" : "text-base-content/40"} />
      </button>
    </th>
  );
}

/** page numbers around the current page, plus first and last */
function pageList(page, pages) {
  const set = new Set([1, pages, page - 1, page, page + 1].filter((p) => p >= 1 && p <= pages));
  const out = [];
  let prev = 0;
  for (const p of [...set].sort((a, b) => a - b)) {
    if (p - prev > 1) out.push(`gap-${p}`);
    out.push(p);
    prev = p;
  }
  return out;
}

function Pager({ page, pages, start, shown, total, onPage }) {
  return (
    <nav aria-label="Flag pages" className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-sm text-base-content/70">
        Rows <span className="num text-base-content">{num(start + 1)}</span>-
        <span className="num text-base-content">{num(start + shown)}</span> of <span className="num text-base-content">{num(total)}</span>
      </p>
      {pages > 1 && (
        <div className="join">
          <button
            type="button"
            className="join-item btn btn-sm"
            onClick={() => onPage(page - 1)}
            disabled={page <= 1}
            aria-label="Previous page"
          >
            <CaretLeft size={16} aria-hidden />
          </button>
          {pageList(page, pages).map((p) =>
            typeof p === "string" ? (
              <span key={p} className="join-item btn btn-sm btn-disabled pointer-events-none" aria-hidden>
                ...
              </span>
            ) : (
              <button
                key={p}
                type="button"
                className={`join-item btn btn-sm num ${p === page ? "btn-active btn-primary" : ""}`}
                onClick={() => onPage(p)}
                aria-label={`Page ${p}`}
                aria-current={p === page ? "page" : undefined}
              >
                {p}
              </button>
            ),
          )}
          <button
            type="button"
            className="join-item btn btn-sm"
            onClick={() => onPage(page + 1)}
            disabled={page >= pages}
            aria-label="Next page"
          >
            <CaretRight size={16} aria-hidden />
          </button>
        </div>
      )}
    </nav>
  );
}
