import { num } from "../../lib/format";
import { ACTIONS } from "./shared";

/** How the 0 to 100 road risk score is built: five weighted parts as one labelled bar. */
export function RiskWeights({ factors }) {
  return (
    <div>
      <div className="flex h-9 w-full overflow-hidden rounded-field" role="img"
        aria-label={factors.map((f) => `${f.label} ${Math.round(f.weight * 100)} points`).join(", ")}>
        {factors.map((f, i) => (
          <span key={f.key} className={`flex items-center justify-center text-xs font-medium ${i < 2 ? "text-primary-content" : "text-base-content"}`}
            style={{ width: `${f.weight * 100}%`, background: f.shade }}>
            <span className="num truncate px-1">{Math.round(f.weight * 100)}</span>
          </span>
        ))}
      </div>
      <dl className="mt-4 divide-y divide-base-300">
        {factors.map((f) => (
          <div key={f.key} className="grid grid-cols-[auto_1fr_auto] items-baseline gap-x-3 py-2.5">
            <span className="size-2.5 translate-y-px rounded-full" style={{ background: f.shade }} aria-hidden />
            <div>
              <dt className="font-medium">{f.label}</dt>
              <dd className="text-sm text-base-content/70">{f.help}</dd>
            </div>
            <dd className="num text-sm text-base-content/70">
              up to <span className="font-medium text-base-content">{Math.round(f.weight * 100)}</span> pts
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** One road's score broken into the same five parts (points = weight x component x 100). */
export function RoadBreakdown({ road, plan, factors, pinned }) {
  if (!road) return null;
  return (
    <div className="border-t border-base-300 pt-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm text-base-content/60">{pinned ? "Selected road" : "Top of the plan"}</div>
          <div className="font-medium leading-snug">{road.road_name}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono text-xs text-base-content/60">{road.road_id}</span>
            {plan && <span className={`badge badge-sm ${ACTIONS[plan.action]?.badge || ""}`}>{plan.action}</span>}
          </div>
        </div>
        <div className="text-right">
          <div className="num text-2xl font-semibold tracking-tight">{num(road.risk_score, 1)}</div>
          <div className="text-xs text-base-content/60">of 100</div>
        </div>
      </div>
      <ul className="mt-3 flex flex-col gap-2">
        {factors.map((f) => {
          const max = f.weight * 100;
          const pts = (road[f.key] || 0) * max;
          return (
            <li key={f.key} className="grid grid-cols-[8.5rem_1fr_4.5rem] items-center gap-2 text-sm">
              <span className="truncate text-base-content/70">{f.label}</span>
              {/* track width = the factor's maximum share, fill = points this road earned */}
              <span className="h-2 rounded-full bg-base-200" style={{ width: `${max / factors[0].weight}%` }} aria-hidden>
                <span className="block h-full rounded-full" style={{ width: `${max ? (100 * pts) / max : 0}%`, background: f.shade }} />
              </span>
              <span className="num text-right">
                {num(pts, 1)}
                <span className="text-base-content/50"> / {Math.round(max)}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
