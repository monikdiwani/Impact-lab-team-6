import { useEffect, useMemo, useRef } from "react";
import { CaretDown, ShieldCheck } from "@phosphor-icons/react";
import { useData } from "../lib/data";
import { go } from "../lib/router";
import { PageHeader, Loaded, EmptyState } from "../components/ui";
import Leaderboard from "./contractors/Leaderboard";
import Detail from "./contractors/Detail";
import ReopenChart from "./contractors/ReopenChart";

/*
  Contractors: fair accountability. A leaderboard of all contractors, one selected
  contractor explained in full (how the score is built, flags, methods, jobs to check),
  a method-adjusted re-open comparison, and the fairness notes behind the scoring.
  Route: #/contractors (top scorer selected) or #/contractors/CT05.
*/
export default function Contractors({ id }) {
  const state = useData(["contractors", "summary"]);
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Contractors"
        lede="How each repair contractor performed this monsoon: did repairs last, were deadlines met, and did bills match the rate card. Re-open rates are judged against what each contractor's repair methods would predict, so the comparison is fair. All contractors are fictional."
      />
      <Loaded state={state} what="contractor scores">
        {([contractors, summary]) => <Body contractors={contractors} summary={summary} id={id} />}
      </Loaded>
    </div>
  );
}

function Body({ contractors, summary, id }) {
  const ranked = useMemo(
    () => [...contractors].sort((a, b) => b.score_0_100 - a.score_0_100).map((c, i) => ({ ...c, rank: i + 1 })),
    [contractors],
  );
  const selected = ranked.find((c) => c.contractor_id === id) || ranked[0];
  const unknownId = id && !ranked.some((c) => c.contractor_id === id);

  // The app scrolls to the top on every route change. Keep the reader where they were
  // (desktop, leaderboard click) or bring the detail into view (mobile, or chart click).
  const detailRef = useRef(null);
  const pending = useRef(null);
  const select = (cid, { reveal = false } = {}) => {
    // Compare with the route id, not the fallback selection, so clicking the top scorer
    // on an unknown id (#/contractors/XYZ) still fixes the URL and clears the notice.
    if (cid === id) return;
    const narrow = window.matchMedia("(max-width: 767px)").matches;
    pending.current = reveal || narrow ? { reveal: true } : { y: window.scrollY };
    go("contractors", cid);
  };
  useEffect(() => {
    const p = pending.current;
    if (!p) return;
    pending.current = null;
    const raf = requestAnimationFrame(() => {
      if (p.reveal) {
        const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        detailRef.current?.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
      } else {
        window.scrollTo(0, p.y);
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [id]);

  if (!ranked.length) {
    return <EmptyState title="No contractor scores yet" hint="Run python app/export_data.py from the repo root to build contractors.json, then reload." />;
  }

  return (
    <>
      {unknownId && (
        <div role="status" className="alert alert-soft alert-info">
          There is no contractor with the code {id}. Showing the top scorer instead.
        </div>
      )}

      <Leaderboard rows={ranked} selectedId={selected.contractor_id} onSelect={select} city={selected.facts?.city_average} />

      <div ref={detailRef} className="scroll-mt-20">
        <Detail key={selected.contractor_id} c={selected} total={ranked.length} weights={summary.score_weights} />
      </div>

      <ReopenChart rows={ranked} selectedId={selected.contractor_id} onSelect={(cid) => select(cid, { reveal: true })} cityPct={summary.reopen_pct} />

      <FairnessNotes notes={summary.fairness_notes || []} />
    </>
  );
}

function FairnessNotes({ notes }) {
  if (!notes.length) return null;
  return (
    <details className="enter enter-d3 collapse rounded-box border border-base-300 bg-base-100 group">
      <summary className="collapse-title flex items-center gap-3 pe-5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary rounded-box">
        <ShieldCheck size={20} className="shrink-0 text-primary" aria-hidden />
        <span className="flex-1">
          <span className="block font-semibold">Fairness notes</span>
          <span className="block text-sm font-normal text-base-content/60">{notes.length} rules that keep these scores fair to every contractor.</span>
        </span>
        <CaretDown size={18} className="shrink-0 text-base-content/60 transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="collapse-content">
        <ul className="ms-8 flex max-w-3xl list-disc flex-col gap-2 ps-4 text-sm leading-relaxed text-base-content/80 marker:text-base-content/40">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </div>
    </details>
  );
}
