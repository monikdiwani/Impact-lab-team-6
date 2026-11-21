import { CaretRight } from "@phosphor-icons/react";
import { inrShort, num, pct, short, GRADE_CLASS } from "../../lib/format";
import { href } from "../../lib/router";

export const totalFlags = (c) => Object.values(c.n_flags_by_type || {}).reduce((a, b) => a + b, 0);
export const ratioX = (r) => (r == null ? "-" : `${Number(r).toFixed(2)}x`);

/*
  Ranked list of every contractor. Table from md up, compact list on phones.
  Each row is a real link (keyboard + middle-click work); the click handler keeps
  the scroll position so the reader does not lose their place.
*/
export default function Leaderboard({ rows, selectedId, onSelect, city }) {
  const click = (e, cid) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
    e.preventDefault();
    onSelect(cid);
  };
  const maxBilled = Math.max(...rows.map((r) => r.billed_inr || 0));

  return (
    <section className="enter enter-d1 rounded-box border border-base-300 bg-base-100" aria-labelledby="lb-title">
      <div className="flex flex-col gap-1 px-5 pt-4 pb-3 md:flex-row md:items-end md:justify-between md:gap-6">
        <div>
          <h2 id="lb-title" className="font-semibold">Leaderboard</h2>
          <p className="mt-0.5 text-sm text-base-content/60">Ranked by score out of 100. Select a contractor to see how the score is built.</p>
        </div>
        {city && (
          <p className="text-sm text-base-content/60 md:text-right">
            City average: <span className="num text-base-content">{pct(city.sla_met_pct)}</span> on time,{" "}
            <span className="num text-base-content">{pct(city.reopened_pct)}</span> re-opened
          </p>
        )}
      </div>

      {/* md and up: full table */}
      <div className="hidden overflow-x-auto md:block">
        <table className="table">
          <thead>
            <tr className="border-base-300 text-base-content/60">
              <th className="w-10 ps-5 text-right font-medium">#</th>
              <th className="font-medium">Contractor</th>
              <th className="text-center font-medium">Grade</th>
              <th className="text-right font-medium">Score</th>
              <th className="text-right font-medium">Jobs</th>
              <th className="font-medium">Billed</th>
              <th className="text-right font-medium" title="SLA: the deadline, counted from the first citizen complaint">
                Deadline met
              </th>
              <th className="text-right font-medium" title="Share of repairs that re-opened within 30 days, next to the share expected for this contractor's mix of repair methods">
                Re-opened vs expected
              </th>
              <th className="text-right font-medium" title="Median bill divided by the rate card price for the same repair. 1.00x means exactly the rate card.">
                Cost vs rate card
              </th>
              <th className="pe-5 text-right font-medium">Flags</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const sel = c.contractor_id === selectedId;
              const worse = c.reopen_pct > c.reopen_expected_pct;
              return (
                <tr
                  key={c.contractor_id}
                  onClick={(e) => click(e, c.contractor_id)}
                  className={`cursor-pointer border-base-300 transition-colors ${sel ? "bg-primary/8" : "hover:bg-base-200"}`}
                >
                  <td className={`num border-l-2 ps-5 text-right text-base-content/60 ${sel ? "border-primary" : "border-transparent"}`}>{c.rank}</td>
                  <td className="whitespace-nowrap">
                    <a
                      href={href("contractors", c.contractor_id)}
                      onClick={(e) => {
                        e.stopPropagation();
                        click(e, c.contractor_id);
                      }}
                      aria-current={sel ? "true" : undefined}
                      title={c.contractor_name}
                      className={`rounded-field font-medium outline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-primary ${sel ? "text-primary" : ""}`}
                    >
                      {short(c.contractor_name)}
                    </a>
                  </td>
                  <td className={`text-center text-2xl leading-none font-semibold ${GRADE_CLASS[c.grade] || ""}`}>
                    <span aria-label={`Grade ${c.grade}`}>{c.grade}</span>
                  </td>
                  <td className="num text-right font-medium">{num(c.score_0_100, 1)}</td>
                  <td className="num text-right">{num(c.n_jobs)}</td>
                  <td className="min-w-32">
                    <div className="num">{inrShort(c.billed_inr)}</div>
                    <div className="mt-1 h-1.5 w-full max-w-24">
                      <span className="block h-full rounded-full bg-base-content/20" style={{ width: `${(100 * c.billed_inr) / maxBilled}%` }} aria-hidden />
                    </div>
                  </td>
                  <td className="num text-right">{pct(c.sla_pct)}</td>
                  <td className="num text-right whitespace-nowrap">
                    <span className={`font-medium ${worse ? "text-error" : ""}`}>{pct(c.reopen_pct)}</span>
                    <span className="text-base-content/60"> vs {pct(c.reopen_expected_pct)}</span>
                  </td>
                  <td className="num text-right">{ratioX(c.facts?.median_cost_vs_rate_card ?? c.median_cost_ratio)}</td>
                  <td className="num pe-5 text-right">{num(totalFlags(c))}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* phones: compact list */}
      <ul className="divide-y divide-base-300 border-t border-base-300 md:hidden">
        {rows.map((c) => {
          const sel = c.contractor_id === selectedId;
          const worse = c.reopen_pct > c.reopen_expected_pct;
          return (
            <li key={c.contractor_id}>
              <a
                href={href("contractors", c.contractor_id)}
                onClick={(e) => click(e, c.contractor_id)}
                aria-current={sel ? "true" : undefined}
                className={`grid grid-cols-[1.5rem_1fr_auto_auto] items-center gap-3 border-l-2 px-4 py-3 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary ${
                  sel ? "border-primary bg-primary/8" : "border-transparent"
                }`}
              >
                <span className="num text-right text-sm text-base-content/60">{c.rank}</span>
                <span className="min-w-0">
                  <span className={`block truncate font-medium ${sel ? "text-primary" : ""}`}>{short(c.contractor_name)}</span>
                  <span className="num block text-xs text-base-content/60">
                    {pct(c.sla_pct)} on time, <span className={worse ? "text-error" : ""}>{pct(c.reopen_pct)}</span> re-opened vs {pct(c.reopen_expected_pct)}
                  </span>
                </span>
                <span className="text-right">
                  <span className={`block text-2xl leading-none font-semibold ${GRADE_CLASS[c.grade] || ""}`} aria-label={`Grade ${c.grade}`}>
                    {c.grade}
                  </span>
                  <span className="num block text-xs text-base-content/60">{num(c.score_0_100, 1)}</span>
                </span>
                <CaretRight size={16} className="text-base-content/40" aria-hidden />
              </a>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
