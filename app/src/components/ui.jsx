import { WarningCircle, Tray } from "@phosphor-icons/react";
import { FLAG_LABEL, FLAG_HELP, SEV_BADGE, short } from "../lib/format";

/*
  Shared building blocks. Pages compose these instead of inventing their own,
  so spacing, type and states stay identical across the app.
*/

/** Page title block. One h1 per page, optional one-line lede and right-side actions. */
export function PageHeader({ title, lede, actions }) {
  return (
    <header className="enter flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">{title}</h1>
        {lede && <p className="mt-2 text-base-content/70 leading-relaxed">{lede}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** Content panel. Use for grouped content that needs a surface; prefer plain spacing otherwise. */
export function Panel({ title, subtitle, actions, children, className = "", bodyClass = "" }) {
  return (
    <section className={`rounded-box border border-base-300 bg-base-100 ${className}`}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 px-5 pt-4">
          <div>
            {title && <h2 className="font-semibold">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-base-content/60">{subtitle}</p>}
          </div>
          {actions}
        </div>
      )}
      <div className={`p-5 ${bodyClass}`}>{children}</div>
    </section>
  );
}

/** KPI tile: label, big number, optional context line. `tone` colours the value only. */
export function Kpi({ label, value, note, tone = "", icon: Icon }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5 text-sm text-base-content/60">
        {Icon && <Icon size={16} weight="regular" aria-hidden />}
        {label}
      </div>
      <div className={`num text-2xl font-semibold tracking-tight md:text-3xl ${tone}`}>{value}</div>
      {note && <div className="text-sm text-base-content/60">{note}</div>}
    </div>
  );
}

/** Loading placeholder shaped like a page: header, KPI row, two panels. */
export function PageSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Loading">
      <div className="skeleton h-9 w-72" />
      <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skeleton h-20" />
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="skeleton h-96 lg:col-span-2" />
        <div className="skeleton h-96" />
      </div>
    </div>
  );
}

export function ErrorState({ error, what = "this data" }) {
  return (
    <div role="alert" className="alert alert-error alert-soft">
      <WarningCircle size={20} aria-hidden />
      <div>
        <div className="font-medium">Could not load {what}.</div>
        <div className="text-sm opacity-80">
          {String(error?.message || error)}. Run <code className="font-mono">python app/export_data.py</code> from the repo root, then reload.
        </div>
      </div>
    </div>
  );
}

export function EmptyState({ title, hint, action }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <Tray size={32} className="text-base-content/40" aria-hidden />
      <div className="font-medium">{title}</div>
      {hint && <p className="max-w-sm text-sm text-base-content/60">{hint}</p>}
      {action}
    </div>
  );
}

/** Wraps the three data states so pages only handle the success case. */
export function Loaded({ state, what, children }) {
  if (state.loading) return <PageSkeleton />;
  if (state.error) return <ErrorState error={state.error} what={what} />;
  return children(state.data);
}

export function FlagBadge({ type }) {
  return (
    <span className="badge badge-outline badge-sm whitespace-nowrap" title={FLAG_HELP[type]}>
      {FLAG_LABEL[type] || type}
    </span>
  );
}

export function SevBadge({ severity }) {
  const label = severity ? severity[0].toUpperCase() + severity.slice(1) : "";
  return <span className={`badge badge-sm badge-soft ${SEV_BADGE[severity] || ""}`}>{label}</span>;
}

/** Native select for wards; label above, per form rules. */
export function WardSelect({ wards, value, onChange, label = "Ward", allowAll = false, id = "ward-select", className = "w-60" }) {
  return (
    <label className="flex flex-col gap-1.5" htmlFor={id}>
      <span className="text-sm text-base-content/70">{label}</span>
      <select id={id} className={`select select-sm ${className}`} value={value || ""} onChange={(e) => onChange(e.target.value || null)}>
        {allowAll && <option value="">All wards</option>}
        {wards.map((w) => (
          <option key={w.ward_code} value={w.ward_code}>
            {w.ward_code}: {w.ward_name}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ContractorName({ name }) {
  return <span title={name}>{short(name)}</span>;
}

/** Simple horizontal value bar with no background track (used inside tables). */
export function InlineBar({ value, max, className = "bg-primary" }) {
  const w = max > 0 ? Math.max(2, Math.round((100 * value) / max)) : 0;
  return <span className={`inline-block h-1.5 rounded-full align-middle ${className}`} style={{ width: `${w}%` }} aria-hidden />;
}
