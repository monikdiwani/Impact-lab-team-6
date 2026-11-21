import { pct, short } from "../../lib/format";

/*
  Dumbbell chart: each contractor's actual 30-day re-open rate against the rate their
  own mix of repair methods would predict. Plain HTML/CSS so it stays crisp and
  responsive without measuring the container; each row is a button that selects.
*/
export default function ReopenChart({ rows, selectedId, onSelect, cityPct }) {
  const top = Math.max(...rows.flatMap((r) => [r.reopen_pct, r.reopen_expected_pct]), cityPct || 0);
  const max = Math.max(10, Math.ceil(top / 10) * 10);
  const ticks = Array.from({ length: max / 10 + 1 }, (_, i) => i * 10);
  const x = (v) => `${(100 * v) / max}%`;
  const better = rows.filter((r) => r.reopen_pct <= r.reopen_expected_pct).length;

  return (
    <section className="enter enter-d3 rounded-box border border-base-300 bg-base-100" aria-labelledby="rc-title">
      <div className="flex flex-col gap-3 px-5 pt-4 md:flex-row md:items-start md:justify-between md:gap-8">
        <div className="max-w-2xl">
          <h2 id="rc-title" className="font-semibold">Did repairs last as long as expected?</h2>
          <p className="mt-1 text-sm leading-relaxed text-base-content/70">
            Some repair methods re-open more often than others, no matter who does the work. So each contractor is measured against the rate its own mix of
            methods predicts, not one city-wide number.
          </p>
        </div>
        <ul className="flex shrink-0 flex-wrap gap-x-4 gap-y-1.5 text-sm text-base-content/70 md:flex-col" aria-label="Legend">
          <li className="flex items-center gap-2">
            <span className="size-3 rounded-full border-2 border-base-content/50 bg-base-100" aria-hidden /> Expected for its methods
          </li>
          <li className="flex items-center gap-2">
            <span className="size-3 rounded-full bg-success" aria-hidden /> Actual, lower than expected
          </li>
          <li className="flex items-center gap-2">
            <span className="size-3 rounded-full bg-error" aria-hidden /> Actual, higher than expected
          </li>
        </ul>
      </div>

      <div className="px-2 pt-4 pb-4 md:px-3">
        <ul>
          {rows.map((r) => {
            const sel = r.contractor_id === selectedId;
            const worse = r.reopen_pct > r.reopen_expected_pct;
            const lo = Math.min(r.reopen_pct, r.reopen_expected_pct);
            const hi = Math.max(r.reopen_pct, r.reopen_expected_pct);
            return (
              <li key={r.contractor_id}>
                <button
                  type="button"
                  onClick={() => onSelect(r.contractor_id)}
                  aria-pressed={sel}
                  aria-label={`${short(r.contractor_name)}: ${pct(r.reopen_pct)} re-opened, ${pct(r.reopen_expected_pct)} expected`}
                  className={`grid w-full grid-cols-[1fr_auto] items-stretch gap-x-4 rounded-field px-3 text-left transition-colors md:grid-cols-[11rem_1fr_8.5rem] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary ${
                    sel ? "bg-primary/8" : "hover:bg-base-200"
                  }`}
                >
                  <span className={`col-start-1 row-start-1 self-center truncate pt-2 text-sm md:pt-0 ${sel ? "font-medium text-primary" : ""}`} title={r.contractor_name}>
                    {short(r.contractor_name)}
                  </span>
                  <span className="relative col-span-2 col-start-1 row-start-2 h-9 md:col-span-1 md:col-start-2 md:row-start-1 md:h-11" aria-hidden>
                    {cityPct != null && <span className="absolute inset-y-0 border-l border-dashed border-base-content/30" style={{ left: x(cityPct) }} />}
                    <span
                      className={`absolute top-1/2 h-1 -translate-y-1/2 rounded-full ${worse ? "bg-error/35" : "bg-success/35"}`}
                      style={{ left: x(lo), width: `calc(${x(hi)} - ${x(lo)})` }}
                    />
                    <span
                      className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-base-content/50 bg-base-100"
                      style={{ left: x(r.reopen_expected_pct) }}
                    />
                    <span
                      className={`absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-base-100 ${worse ? "bg-error" : "bg-success"}`}
                      style={{ left: x(r.reopen_pct) }}
                    />
                  </span>
                  <span className="num col-start-2 row-start-1 self-center pt-2 text-right text-sm whitespace-nowrap md:col-start-3 md:pt-0">
                    <span className={`font-medium ${worse ? "text-error" : "text-success"}`}>{pct(r.reopen_pct)}</span>
                    <span className="text-base-content/60"> vs {pct(r.reopen_expected_pct)}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        {/* x axis */}
        <div className="grid grid-cols-[1fr] gap-x-4 px-3 md:grid-cols-[11rem_1fr_8.5rem]" aria-hidden>
          <span className="hidden md:block" />
          <span className="relative h-10 border-t border-base-300">
            {ticks.map((t) => (
              <span key={t} className="num absolute top-1.5 -translate-x-1/2 text-xs text-base-content/50" style={{ left: x(t) }}>
                {t}%
              </span>
            ))}
            {cityPct != null && (
              <span className="num absolute top-5 -translate-x-1/2 text-xs whitespace-nowrap text-base-content/60" style={{ left: x(cityPct) }}>
                city {pct(cityPct)}
              </span>
            )}
          </span>
        </div>

        <p className="px-3 text-sm text-base-content/70">
          {better} of {rows.length} contractors had fewer repairs re-open than their methods predict. Re-opened means the same problem came back within 30 days.
        </p>
      </div>
    </section>
  );
}
