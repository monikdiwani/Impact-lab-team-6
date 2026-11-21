import { useMemo } from "react";
import MumbaiMap, { riskRamp } from "../../components/MumbaiMap";
import { num } from "../../lib/format";
import { ACTIONS, roadT, ROAD_CASING } from "./shared";

/* line width per plan action: paid repairs read first, then warranty jobs, then watch-only roads */
const WIDTH = { Repair: 6, "Invoke DLP": 4, Monitor: 2.5 };
const LEGEND_H = { Repair: "h-1.5", "Invoke DLP": "h-1", Monitor: "h-0.5" };
const ORDER = { Monitor: 0, "Invoke DLP": 1, Repair: 2 };

/** Ward close-up: roads coloured by risk, plan roads thicker, flood hotspots, one highlighted road. */
export default function WardMap({ code, wardName, roads, planByRoad, hotspots, highlight }) {
  const lines = useMemo(() => {
    const out = roads.map((r) => {
      const p = planByRoad.get(r.road_id);
      const action = p?.action || "Monitor";
      return {
        road_id: r.road_id,
        coords: r.coords,
        color: riskRamp(roadT(r.risk_score)),
        width: WIDTH[action],
        order: ORDER[action],
        title: `${r.road_name} (${r.road_id}): risk ${num(r.risk_score, 1)}${p ? `, plan rank ${p.rank}, ${action}` : ""}`,
      };
    });
    out.sort((a, b) => a.order - b.order);
    // casings go first so every coloured line sits on a thin neutral outline
    const casings = out.map((l) => ({ ...l, road_id: `${l.road_id}-case`, color: ROAD_CASING, width: l.width + 2 }));
    const all = [...casings, ...out];
    const hi = out.find((l) => l.road_id === highlight);
    if (hi) all.push({ ...hi, road_id: `${hi.road_id}-hi`, color: "var(--color-primary)", width: 9 });
    return all;
  }, [roads, planByRoad, highlight]);

  const points = useMemo(
    () =>
      hotspots.map((h) => ({
        lat: h.lat,
        lon: h.lon,
        r: 5.5,
        className: "fill-info",
        title: `${h.name}, flood hotspot: floods above ${h.flood_threshold_mm_per_day} mm of rain a day, water about ${h.avg_water_depth_cm} cm deep, flagged in ${h.years_flagged_last_5} of the last 5 years`,
      })),
    [hotspots],
  );

  return (
    <div>
      <MumbaiMap
        focus={code}
        selected={code}
        roads={lines}
        points={points}
        height={420}
        label={(c) => (c === code ? `Ward ${c}: ${wardName}` : `Ward ${c}`)}
        ariaLabel={`Map of ward ${code} roads coloured by risk score, with ${hotspots.length} flood hotspots`}
      />
      <div className="mt-3 grid gap-3 text-sm text-base-content/70 sm:grid-cols-2">
        <div>
          <div className="mb-1.5">Road risk score</div>
          <div className="h-2 w-full max-w-48 rounded-full"
            style={{ background: `linear-gradient(to right, ${riskRamp(roadT(10))}, ${riskRamp(roadT(45))}, ${riskRamp(roadT(80))})` }} aria-hidden />
          <div className="num mt-1 flex max-w-48 justify-between text-xs text-base-content/60">
            <span>low</span>
            <span>high</span>
          </div>
        </div>
        <ul className="flex flex-col gap-1">
          {Object.keys(ACTIONS).map((k) => (
            <li key={k} className="flex items-center gap-2">
              <span className={`w-6 rounded-full bg-base-content/50 ${LEGEND_H[k]}`} aria-hidden />
              {k === "Repair" ? "Paid repair" : k}
            </li>
          ))}
          <li className="flex items-center gap-2">
            <span className="flex w-6 justify-center" aria-hidden>
              <span className="size-2.5 rounded-full bg-info" />
            </span>
            Flood hotspot
          </li>
          <li className="flex items-center gap-2">
            <span className="h-1 w-6 rounded-full bg-primary" aria-hidden />
            Selected road
          </li>
        </ul>
      </div>
    </div>
  );
}
