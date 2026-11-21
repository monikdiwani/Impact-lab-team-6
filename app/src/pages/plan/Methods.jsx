import { useMemo } from "react";
import { inr, pct } from "../../lib/format";

/*
  City-wide method comparison from methods.json, one row per kind of problem:
  the recommended method (lowest re-open rate) with its numbers, other methods as a footnote line.
*/
export default function Methods({ methods }) {
  const groups = useMemo(() => {
    const m = new Map();
    for (const r of methods) {
      if (!m.has(r.work_type)) m.set(r.work_type, []);
      m.get(r.work_type).push(r);
    }
    return [...m.entries()]
      .map(([type, list]) => {
        const sorted = [...list].sort((a, b) => a.method_rank - b.method_rank);
        return { type, best: sorted.find((r) => r.recommended) || sorted[0], others: sorted.filter((r) => !r.recommended), jobs: list.reduce((s, r) => s + r.n_jobs, 0) };
      })
      .sort((a, b) => b.jobs - a.jobs);
  }, [methods]);

  const maxRate = Math.max(...methods.map((r) => r.reopen_rate));

  return (
    <div>
      <div className="hidden grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_6rem_7rem] gap-4 pb-2 text-sm text-base-content/60 md:grid">
        <span>Problem and recommended method</span>
        <span>Re-open rate</span>
        <span className="text-right">Typical cost</span>
        <span className="text-right">Per lasting repair</span>
      </div>
      <ul className="divide-y divide-base-300 border-t border-base-300">
        {groups.map(({ type, best, others }) => (
          <li key={type} className="grid grid-cols-2 gap-x-4 gap-y-2 py-3 md:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_6rem_7rem] md:items-center">
            <div className="col-span-2 md:col-span-1">
              <div className="text-sm text-base-content/60">{type}</div>
              <div className="font-medium leading-snug">{best.repair_method}</div>
              {others.length > 0 && (
                <div className="mt-0.5 text-xs leading-snug text-base-content/60">
                  Also used:{" "}
                  {others.map((o, i) => (
                    <span key={o.repair_method}>
                      {i > 0 && "; "}
                      {o.repair_method} <span className="num">{pct(o.reopen_rate * 100)}</span> re-open,{" "}
                      <span className="num">{inr(o.cost_per_lasting_repair_inr)}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="col-span-2 flex items-center gap-2 md:col-span-1">
              <span className="h-2 flex-1 rounded-full bg-base-200" aria-hidden>
                <span className="block h-full rounded-full bg-primary" style={{ width: `${(100 * best.reopen_rate) / maxRate}%` }} />
              </span>
              <span className="num w-12 text-right text-sm">{pct(best.reopen_rate * 100)}</span>
            </div>
            <div className="md:text-right">
              <div className="text-xs text-base-content/60 md:hidden">Typical cost</div>
              <span className="num text-sm text-base-content/70">{inr(best.est_cost_inr)}</span>
            </div>
            <div className="text-right">
              <div className="text-xs text-base-content/60 md:hidden">Per lasting repair</div>
              <span className="num font-semibold">{inr(best.cost_per_lasting_repair_inr)}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
