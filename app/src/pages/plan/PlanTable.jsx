import { riskRamp } from "../../components/MumbaiMap";
import { inr, num } from "../../lib/format";
import { ACTIONS, roadT } from "./shared";

/*
  Ranked plan for one ward. Hovering or focusing a row reports the road up (onHover) so the map
  can highlight it; click or Enter pins it. Table on md+, stacked list on phones.
*/
export default function PlanTable({ rows, roadsById, shown, onHover, onPin }) {
  const name = (id) => roadsById.get(id)?.road_name || id;
  const rowProps = (r) => ({
    onMouseEnter: () => onHover(r.road_id),
    onMouseLeave: () => onHover(null),
    onFocus: () => onHover(r.road_id),
    onBlur: () => onHover(null),
    onClick: () => onPin(r.road_id),
    onKeyDown: (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onPin(r.road_id)),
    tabIndex: 0,
    "aria-current": shown === r.road_id ? "true" : undefined,
  });

  return (
    <>
      <ul className="flex flex-col gap-1.5 text-sm md:flex-row md:flex-wrap md:gap-x-6">
        {Object.entries(ACTIONS).map(([k, a]) => (
          <li key={k} className="flex items-start gap-2">
            <span className={`badge badge-sm shrink-0 ${a.badge}`}>{k}</span>
            <span className="text-base-content/70">{a.line}</span>
          </li>
        ))}
      </ul>

      {/* phones */}
      <ol className="mt-4 divide-y divide-base-300 md:hidden">
        {rows.map((r) => (
          <li key={r.road_id} {...rowProps(r)}
            className={`flex gap-3 py-3 outline-none focus-visible:rounded-field focus-visible:ring-2 focus-visible:ring-primary ${shown === r.road_id ? "bg-base-200" : ""}`}>
            <span className="num w-6 shrink-0 pt-0.5 text-right text-base-content/60">{r.rank}</span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="font-medium">{name(r.road_id)}</span>
                <span className="font-mono text-xs text-base-content/60">{r.road_id}</span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <span className={`badge badge-sm ${ACTIONS[r.action]?.badge || ""}`}>{r.action}</span>
                <Cost r={r} />
                <span className="text-base-content/60">
                  risk <span className="num">{num(r.risk_score, 1)}</span>
                </span>
              </div>
              <div className="mt-1 text-base-content/70">{r.recommended_method}</div>
              <p className="mt-1 text-base-content/70">{r.reason}</p>
            </div>
          </li>
        ))}
      </ol>

      {/* tablets and up */}
      <div className="mt-4 hidden overflow-x-auto md:block">
        <table className="table table-sm">
          <thead>
            <tr className="text-base-content/60">
              <th className="w-8 text-right">#</th>
              <th>Road and why it ranks here</th>
              <th>Action, method</th>
              <th className="text-right">Est.<br />cost</th>
              <th className="text-right">Running<br />total</th>
              <th className="text-right">Risk</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.road_id} {...rowProps(r)} title="Show on map"
                className={`cursor-pointer align-top outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary ${shown === r.road_id ? "bg-base-200" : "hover:bg-base-200/60"}`}>
                <td className="num text-right text-base-content/60">{r.rank}</td>
                <td className="min-w-48">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-medium leading-snug">{name(r.road_id)}</span>
                    <span className="font-mono text-xs text-base-content/60">{r.road_id}</span>
                  </div>
                  <p className="mt-1 text-sm leading-snug text-base-content/70">{r.reason}</p>
                </td>
                <td className="w-36">
                  <span className={`badge badge-sm ${ACTIONS[r.action]?.badge || ""}`}>{r.action}</span>
                  <div className="mt-1 text-xs leading-snug text-base-content/70">{r.recommended_method}</div>
                </td>
                <td className="text-right whitespace-nowrap">
                  <Cost r={r} />
                </td>
                <td className="num text-right whitespace-nowrap text-base-content/70">{inr(r.cumulative_inr)}</td>
                <td className="text-right whitespace-nowrap">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-2.5 rounded-full" style={{ background: riskRamp(roadT(r.risk_score)) }} aria-hidden />
                    <span className="num">{num(r.risk_score, 1)}</span>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Cost({ r }) {
  if (r.action === "Invoke DLP") return <span className="text-base-content/70">₹0 to BMC</span>;
  if (r.action === "Monitor") return <span className="text-base-content/50" aria-label="No cost">-</span>;
  return <span className="num font-medium">{inr(r.est_cost_inr)}</span>;
}
