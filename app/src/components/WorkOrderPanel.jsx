import { createContext, useContext, useEffect, useRef, useState } from "react";
import { X, ArrowSquareOut, Warning, CheckCircle, Clock, MapPin, HardHat, ChatCircleText } from "@phosphor-icons/react";
import { useData, byKey, load } from "../lib/data";
import { inr, when, short, num, FLAG_LABEL } from "../lib/format";
import { href } from "../lib/router";
import { FlagBadge, SevBadge } from "./ui";

/*
  The "follow one rupee" drill-down. Any page can open it:
     const { openWorkOrder } = useWorkOrder();  openWorkOrder("WO25-02456")
  Shows the work order, the citizen complaints behind it, the road, the contractor,
  every audit flag with its evidence, and links to related work orders.
*/
const Ctx = createContext({ openWorkOrder: () => {} });
export const useWorkOrder = () => useContext(Ctx);

export function WorkOrderProvider({ children }) {
  const [stack, setStack] = useState([]); // history so "related WO" links can go back
  const open = (id) => setStack((s) => [...s, id]);
  const back = () => setStack((s) => s.slice(0, -1));
  const close = () => setStack([]);
  return (
    <Ctx.Provider value={{ openWorkOrder: open }}>
      {children}
      <Sheet id={stack[stack.length - 1]} canGoBack={stack.length > 1} onBack={back} onClose={close} onOpen={open} />
    </Ctx.Provider>
  );
}

function Sheet({ id, canGoBack, onBack, onClose, onOpen }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (id && !d.open) d.showModal();
    if (!id && d.open) d.close();
  }, [id]);

  return (
    <dialog ref={ref} className="modal modal-end" onClose={onClose} aria-label="Work order details">
      <div className="modal-box flex h-full max-h-none w-full max-w-xl flex-col gap-0 rounded-none p-0 sm:rounded-l-box">
        {id && <Body id={id} canGoBack={canGoBack} onBack={onBack} onClose={onClose} onOpen={onOpen} />}
      </div>
      <form method="dialog" className="modal-backdrop">
        <button aria-label="Close">close</button>
      </form>
    </dialog>
  );
}

function Body({ id, canGoBack, onBack, onClose, onOpen }) {
  const s = useData(["work_orders", "flags", "contractor_names", "roads"]);
  const [complaints, setComplaints] = useState(null);

  const wo = s.data && byKey(s.data[0], "work_order_id").get(id);
  useEffect(() => {
    if (!wo?.linked_complaint_ids?.length) return setComplaints([]);
    let alive = true;
    setComplaints(null);
    load("complaints").then((all) => {
      if (!alive) return;
      const want = new Set(wo.linked_complaint_ids);
      setComplaints(all.filter((c) => want.has(c.complaint_id)));
    });
    return () => {
      alive = false;
    };
  }, [wo]);

  if (s.loading) return <div className="p-6"><div className="skeleton h-8 w-48" /><div className="skeleton mt-6 h-64" /></div>;
  if (s.error || !wo) return <div className="p-6 text-error">Work order {id} not found.</div>;

  const [, flags, names, roads] = s.data;
  const woFlags = flags.filter((f) => f.work_order_id === id);
  const pointedBy = flags.filter((f) => f.related_work_order_id === id);
  const road = byKey(roads, "road_id").get(wo.road_id);
  const ratio = wo.cost_inr && woFlags.find((f) => f.flag_type === "OVERBILL")?.expected_inr;

  return (
    <>
      <div className="flex items-center justify-between gap-2 border-b border-base-300 px-5 py-3">
        <div className="flex items-center gap-2">
          {canGoBack && <button className="btn btn-ghost btn-sm" onClick={onBack}>Back</button>}
          <h2 className="font-mono text-lg font-semibold">{wo.work_order_id}</h2>
        </div>
        <button className="btn btn-ghost btn-sm btn-square" onClick={onClose} aria-label="Close panel"><X size={18} /></button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <div className="text-sm text-base-content/60">{wo.work_type}</div>
            <div className="text-lg font-semibold">{wo.repair_method}</div>
          </div>
          <div className="text-right">
            <div className="text-sm text-base-content/60">Billed</div>
            <div className="num text-2xl font-semibold">{inr(wo.cost_inr)}</div>
            {ratio ? <div className="num text-sm text-error">Rate card {inr(ratio)}</div> : null}
          </div>
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <Item icon={MapPin} label="Road">
            {road ? <a className="link link-hover" href={href("plan", wo.ward_code)}>{wo.road_name}</a> : wo.road_name}{" "}
            <span className="font-mono text-base-content/60">{wo.road_id}</span>
            {wo.under_dlp === "Y" && <span className="badge badge-sm badge-soft badge-warning ml-1">under warranty</span>}
          </Item>
          <Item icon={MapPin} label="Ward"><a className="link link-hover" href={href("wards", wo.ward_code)}>{wo.ward_code}</a></Item>
          <Item icon={HardHat} label="Contractor">
            <a className="link link-hover" href={href("contractors", wo.contractor_id)}>{short(names[wo.contractor_id])}</a>
          </Item>
          <Item icon={Clock} label="Deadline">
            {wo.sla_hours} h{" "}
            {wo.sla_met === "Y" ? <span className="text-success">met</span> : <span className="text-error">missed</span>}
            {wo.hours_to_complete != null && <span className="text-base-content/60"> ({num(wo.hours_to_complete)} h taken)</span>}
          </Item>
          <Item icon={Clock} label="Assigned">{when(wo.assigned_at)}</Item>
          <Item icon={Clock} label="Completed">{when(wo.completed_at)}</Item>
          <Item icon={wo.reopened_within_30d === "Y" ? Warning : CheckCircle} label="Did it hold up?">
            {wo.reopened_within_30d === "Y" ? <span className="text-error">Re-opened within 30 days</span> : <span className="text-success">Held up for 30 days</span>}
          </Item>
          <Item label="Area">{wo.area_sqm ? `${num(wo.area_sqm, 1)} sqm` : "-"}</Item>
        </dl>

        {wo.engineer_remark && <p className="mt-4 rounded-field bg-base-200 px-3 py-2 text-sm">Engineer: “{wo.engineer_remark}”</p>}

        <h3 className="mt-7 font-semibold">Audit flags</h3>
        {woFlags.length === 0 ? (
          <p className="mt-2 text-sm text-base-content/60">No flags on this work order.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-3">
            {woFlags.map((f) => (
              <li key={f.flag_id} className="rounded-box border border-base-300 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <FlagBadge type={f.flag_type} />
                  <SevBadge severity={f.severity} />
                  {f.amount_at_risk_inr > 0 && <span className="num ml-auto text-sm font-semibold">{inr(f.amount_at_risk_inr)} at risk</span>}
                </div>
                <p className="mt-2 text-sm">{f.evidence}</p>
                {f.related_work_order_id && (
                  <button className="btn btn-link btn-sm h-auto min-h-0 px-0" onClick={() => onOpen(f.related_work_order_id)}>
                    Open {f.flag_type === "DOUBLE_BILL" ? "earlier job" : "follow-up job"} {f.related_work_order_id} <ArrowSquareOut size={14} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {pointedBy.length > 0 && (
          <p className="mt-3 text-sm text-base-content/70">
            Referenced by{" "}
            {pointedBy.map((f, i) => (
              <span key={f.flag_id}>
                {i > 0 && ", "}
                <button className="link link-hover font-mono" onClick={() => onOpen(f.work_order_id)}>{f.work_order_id}</button>{" "}
                ({FLAG_LABEL[f.flag_type].toLowerCase()})
              </span>
            ))}
          </p>
        )}

        <h3 className="mt-7 flex items-center gap-2 font-semibold"><ChatCircleText size={18} /> Citizen complaints behind it</h3>
        {wo.linked_complaint_ids.length === 0 ? (
          <p className="mt-2 text-sm text-warning">No complaint is linked to this work order.</p>
        ) : complaints == null ? (
          <div className="skeleton mt-3 h-24" />
        ) : (
          <ul className="mt-3 flex flex-col gap-3">
            {complaints.map((c) => (
              <li key={c.complaint_id} className="border-l-2 border-primary/40 pl-3">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <a className="link link-hover font-mono" href={href("track", c.complaint_id)}>{c.complaint_id}</a>
                  <span className="text-base-content/60">{when(c.received_at)} via {c.channel}</span>
                  <span className="badge badge-ghost badge-sm">{c.language}</span>
                </div>
                <p className="mt-1 text-sm" lang={{ mr: "mr", hi: "hi", "hi-en": "hi-Latn" }[c.language] || "en"}>{c.description}</p>
                {c.english_summary && c.english_summary !== c.description && (
                  <p className="mt-1 text-sm text-base-content/60">In English: {c.english_summary}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function Item({ icon: Icon, label, children }) {
  return (
    <div>
      <dt className="flex items-center gap-1 text-base-content/60">{Icon && <Icon size={14} aria-hidden />}{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}
