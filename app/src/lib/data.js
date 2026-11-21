import { useEffect, useState } from "react";

/*
  Every page reads JSON written by app/export_data.py into public/data/.
  Files are fetched once and cached for the session.

  Available names (see export_data.py for exact fields):
    summary, wards, contractors, flags, work_orders, roads, plan, methods,
    complaints (4 MB, tracker only), wards_geo, hotspots, facilities, contractor_names
*/
const cache = new Map();

export function load(name) {
  if (!cache.has(name)) {
    const p = fetch(`${import.meta.env.BASE_URL}data/${name}.json`).then((r) => {
      if (!r.ok) throw new Error(`${name}.json: HTTP ${r.status}`);
      return r.json();
    });
    p.catch(() => cache.delete(name)); // allow a retry after a failed fetch
    cache.set(name, p);
  }
  return cache.get(name);
}

/** useData("flags") or useData(["flags", "wards"]) -> { data, error, loading } */
export function useData(names) {
  const list = Array.isArray(names) ? names : [names];
  const key = list.join("|");
  const [state, setState] = useState({ data: null, error: null, loading: true });

  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.all(list.map(load))
      .then((res) => alive && setState({ data: Array.isArray(names) ? res : res[0], error: null, loading: false }))
      .catch((error) => alive && setState({ data: null, error, loading: false }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}

/** index an array of records by a key: byKey(wards, "ward_code") */
export function byKey(rows, key) {
  const m = new Map();
  for (const r of rows || []) m.set(r[key], r);
  return m;
}
