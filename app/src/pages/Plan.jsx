import { useMemo, useState } from "react";
import { Info } from "@phosphor-icons/react";
import { useData, byKey } from "../lib/data";
import { num } from "../lib/format";
import { go, href } from "../lib/router";
import { PageHeader, Panel, Loaded, EmptyState, WardSelect } from "../components/ui";
import Budget from "./plan/Budget";
import PlanTable from "./plan/PlanTable";
import WardMap from "./plan/WardMap";
import Methods from "./plan/Methods";
import { RiskWeights, RoadBreakdown } from "./plan/RiskScore";
import { factorsWithWeights } from "./plan/shared";

/*
  Next rupee (#/plan, #/plan/<ward>): where each ward's remaining monsoon money should go.
  Data: wards (budget, memo), plan (ranked actions), roads (names, risk parts, geometry),
  hotspots, methods (city-wide method durability), summary (risk weights).
*/
const FILES = ["wards", "plan", "roads", "hotspots", "methods", "summary"];

export default function Plan({ id }) {
  const state = useData(FILES);
  return (
    <Loaded state={state} what="the budget plan">
      {([wards, plan, roads, hotspots, methods, summary]) => (
        <PlanView id={id} wards={wards} plan={plan} roads={roads} hotspots={hotspots} methods={methods} summary={summary} />
      )}
    </Loaded>
  );
}

function PlanView({ id, wards, plan, roads, hotspots, methods, summary }) {
  const riskiest = useMemo(() => [...wards].sort((a, b) => b.risk_score - a.risk_score)[0], [wards]);
  const code = id || riskiest?.ward_code;
  const ward = wards.find((w) => w.ward_code === code);

  const roadsById = useMemo(() => byKey(roads, "road_id"), [roads]);
  const factors = useMemo(() => factorsWithWeights(summary.risk_weights), [summary]);

  // money each ward still has after its own plan, for the "reallocate from" hint
  const donors = useMemo(() => {
    const spend = new Map();
    for (const p of plan) if (p.action === "Repair") spend.set(p.ward_code, (spend.get(p.ward_code) || 0) + p.est_cost_inr);
    return wards
      .map((w) => ({ ward_code: w.ward_code, after: w.remaining_budget_inr - (spend.get(w.ward_code) || 0) }))
      .filter((d) => d.after > 0)
      .sort((a, b) => b.after - a.after)
      .slice(0, 3);
  }, [wards, plan]);

  const rows = useMemo(() => plan.filter((p) => p.ward_code === code).sort((a, b) => a.rank - b.rank), [plan, code]);
  const planByRoad = useMemo(() => byKey(rows, "road_id"), [rows]);
  const wardRoads = useMemo(() => roads.filter((r) => r.ward_code === code), [roads, code]);
  const wardHotspots = useMemo(() => hotspots.filter((h) => h.ward_code === code), [hotspots, code]);

  const [hover, setHover] = useState(null);
  const [pinned, setPinned] = useState(null);
  // reset the selection when the ward changes (state is keyed by ward below)
  const [stateWard, setStateWard] = useState(code);
  if (stateWard !== code) {
    setStateWard(code);
    setHover(null);
    setPinned(null);
  }
  const shown = hover || pinned;
  const detailId = shown || rows[0]?.road_id;

  // On an unknown ward the shared WardSelect would show the first ward as selected, and picking it
  // would fire no change. Render a local select with a placeholder in that one case.
  const picker = ward ? (
    <WardSelect wards={wards} value={code} onChange={(c) => c && go("plan", c)} label="Ward" id="plan-ward" />
  ) : (
    <label className="flex flex-col gap-1.5" htmlFor="plan-ward">
      <span className="text-sm text-base-content/70">Ward</span>
      <select id="plan-ward" className="select select-sm w-60" value="" onChange={(e) => e.target.value && go("plan", e.target.value)}>
        <option value="" disabled>
          Pick a ward
        </option>
        {wards.map((w) => (
          <option key={w.ward_code} value={w.ward_code}>
            {w.ward_code}: {w.ward_name}
          </option>
        ))}
      </select>
    </label>
  );

  const header = (
    <PageHeader
      title="Next rupee"
      lede="Where each ward's remaining monsoon repair money should go next: highest-risk roads first, free warranty repairs claimed before any new spending."
      actions={picker}
    />
  );

  if (!ward) {
    return (
      <div className="flex flex-col gap-6">
        {header}
        <div className="rounded-box border border-base-300 bg-base-100">
          <EmptyState
            title={`No ward called "${code}"`}
            hint="Pick a ward from the list above, or start with the ward that has the highest risk score."
            action={<a className="btn btn-sm btn-primary mt-2" href={href("plan", riskiest.ward_code)}>Open ward {riskiest.ward_code}</a>}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {header}

      {!id && (
        <p className="enter -mt-2 flex items-start gap-2 text-sm text-base-content/70">
          <Info size={16} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            Showing ward {ward.ward_code} ({ward.ward_name}), which has the highest risk score in the city:{" "}
            <span className="num font-medium text-base-content">{num(ward.risk_score, 1)}</span> of 100. Pick any ward to see its plan.
          </span>
        </p>
      )}

      <Budget ward={ward} rows={rows} donors={donors} />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel
          className="enter enter-d2 order-2 xl:order-1"
          title="Ranked plan"
          subtitle={`${rows.length} roads in ward ${ward.ward_code}, highest risk first. Hover or select a row to find the road on the map.`}
        >
          {rows.length ? (
            <PlanTable rows={rows} roadsById={roadsById} shown={shown} onHover={setHover} onPin={(r) => setPinned((p) => (p === r ? null : r))} />
          ) : (
            <EmptyState title="No roads in this ward's plan" hint="Pick another ward from the list above." />
          )}
        </Panel>

        <aside className="enter enter-d2 order-1 flex flex-col gap-4 rounded-box border border-base-300 bg-base-100 p-5 xl:order-2 xl:sticky xl:top-20"
          aria-label={`Map of ward ${ward.ward_code}`}>
          <h2 className="font-semibold">Ward {ward.ward_code} roads</h2>
          <WardMap code={code} wardName={ward.ward_name} roads={wardRoads} planByRoad={planByRoad} hotspots={wardHotspots} highlight={shown} />
          <RoadBreakdown road={roadsById.get(detailId)} plan={planByRoad.get(detailId)} factors={factors} pinned={!!shown} />
        </aside>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-12">
        <Panel
          className="enter enter-d3 lg:col-span-7"
          title="Which repair methods last"
          subtitle="City-wide, all 24 wards. Cost per lasting repair is the typical cost divided by the share of repairs that hold up (do not re-open within 30 days). The plan uses the method with the lowest re-open rate."
        >
          <Methods methods={methods} />
        </Panel>
        <Panel
          className="enter enter-d3 lg:col-span-5"
          title="How the risk score works"
          subtitle="Every road gets 0 to 100 points from five parts. The weights were tuned by back-testing on earlier months of data."
        >
          <RiskWeights factors={factors} />
        </Panel>
      </div>
    </div>
  );
}
