import { useEffect, useState } from "react";
import { ChartPieSlice, MapTrifold, ShieldWarning, HardHat, Compass, MagnifyingGlass, ChatCircleText, List, Moon, Sun } from "@phosphor-icons/react";
import { href, go } from "../lib/router";
import { useWorkOrder } from "./WorkOrderPanel";

export const NAV = [
  { page: "overview", label: "Overview", icon: ChartPieSlice },
  { page: "wards", label: "Ward money trail", icon: MapTrifold },
  { page: "flags", label: "Audit flags", icon: ShieldWarning },
  { page: "contractors", label: "Contractors", icon: HardHat },
  { page: "plan", label: "Next rupee", icon: Compass },
  { page: "track", label: "Complaint tracker", icon: ChatCircleText },
];

/** App frame: sidebar on desktop, drawer on mobile, top bar with quick search and theme toggle. */
export default function Shell({ page, children }) {
  return (
    <div className="drawer lg:drawer-open">
      <input id="nav-drawer" type="checkbox" className="drawer-toggle" aria-label="Toggle navigation" />
      <div className="drawer-content flex min-h-[100dvh] min-w-0 flex-col bg-base-200">
        <TopBar />
        <main id="main" className="mx-auto w-full min-w-0 max-w-[1400px] flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
        <footer className="mx-auto w-full max-w-[1400px] px-4 pb-8 text-sm text-base-content/60 md:px-8">
          All data is synthetic and every contractor is fictional. Real Mumbai place names appear only for realism. Every number comes
          from the audit pipeline; Claude only words the summaries. A flag means a job needs review, not that anyone did wrong.
        </footer>
      </div>
      <div className="drawer-side z-30">
        <label htmlFor="nav-drawer" aria-label="Close navigation" className="drawer-overlay" />
        <aside className="flex min-h-full w-64 flex-col border-r border-base-300 bg-base-100">
          <a href={href("overview")} className="flex items-center gap-2.5 px-5 py-5">
            <span className="grid size-8 place-items-center rounded-field bg-primary text-lg font-semibold text-primary-content" aria-hidden>₹</span>
            <span className="leading-tight">
              <span className="block font-semibold">Follow the Rupee</span>
              <span className="block text-xs text-base-content/60">Mumbai monsoon roads 2025</span>
            </span>
          </a>
          <ul className="menu w-full gap-0.5 px-3">
            {NAV.map(({ page: p, label, icon: Icon }) => (
              <li key={p}>
                <a href={href(p)} className={page === p ? "menu-active" : ""} aria-current={page === p ? "page" : undefined}
                  onClick={() => (document.getElementById("nav-drawer").checked = false)}>
                  <Icon size={18} weight={page === p ? "fill" : "regular"} aria-hidden />
                  {label}
                </a>
              </li>
            ))}
          </ul>
          <div className="mt-auto px-5 py-5 text-xs leading-relaxed text-base-content/60">
            Jun to early Oct 2025. 2,499 work orders, 6,501 complaints, 24 wards, 8 contractors.
          </div>
        </aside>
      </div>
    </div>
  );
}

function TopBar() {
  const { openWorkOrder } = useWorkOrder();
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");

  // quick jump: a work order ID opens the drill-down, a complaint ID opens the tracker, a ward code opens the ward
  const submit = (e) => {
    e.preventDefault();
    const v = q.trim().toUpperCase();
    setMsg("");
    if (/^WO25-\d{5}$/.test(v)) return openWorkOrder(v), setQ("");
    if (/^BMC25-\d{6}$/.test(v)) return go("track", v), setQ("");
    if (/^[A-T](\/[A-Z])?$/.test(v)) return go("wards", v), setQ("");
    if (v.length >= 3) return go("track", null, { q: q.trim() }), setQ(""); // any words: search complaints in any language
    setMsg("Try a work order (WO25-02456), complaint (BMC25-000005), ward (F/S) or a few words.");
  };

  return (
    <div className="sticky top-0 z-20 border-b border-base-300 bg-base-100/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-3 px-4 md:px-8">
        <label htmlFor="nav-drawer" className="btn btn-ghost btn-sm btn-square lg:hidden" aria-label="Open navigation"><List size={20} /></label>
        <form onSubmit={submit} className="relative flex-1 md:max-w-md" role="search">
          <label className="input input-sm w-full">
            <MagnifyingGlass size={16} className="opacity-60" aria-hidden />
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Work order, complaint, ward or words"
              aria-label="Jump to a work order, complaint or ward" aria-describedby="jump-msg" />
          </label>
          {msg && <p id="jump-msg" className="absolute left-0 top-full mt-1 rounded-field bg-base-100 px-2 py-1 text-xs text-error shadow-sm">{msg}</p>}
        </form>
        <ThemeToggle />
      </div>
    </div>
  );
}

function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.getAttribute("data-theme") === "rupee-dark");
  useEffect(() => {
    const t = dark ? "rupee-dark" : "rupee";
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem("theme", t);
  }, [dark]);
  return (
    <button className="btn btn-ghost btn-sm btn-square ml-auto" onClick={() => setDark((d) => !d)} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}
