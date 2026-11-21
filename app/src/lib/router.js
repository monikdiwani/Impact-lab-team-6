import { useEffect, useState } from "react";

/*
  Tiny hash router: works on any static host with no server config.
  Routes:  #/  #/wards  #/wards/F%2FS  #/flags?type=OVERBILL&ward=A  #/contractors  #/contractors/CT05
           #/plan  #/plan/F%2FS  #/track  #/track/BMC25-000005
  Ward codes contain "/", so always build links with href().
*/
function parse() {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  return { page: parts[0] || "overview", id: parts[1] || null, query: Object.fromEntries(new URLSearchParams(query)) };
}

export function useRoute() {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => {
      setRoute(parse());
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

/** href("wards", "F/S") -> "#/wards/F%2FS";  href("flags", null, {type: "OVERBILL"}) -> "#/flags?type=OVERBILL" */
export function href(page, id = null, query = null) {
  let h = `#/${page === "overview" ? "" : page}`;
  if (id != null) h += `/${encodeURIComponent(id)}`;
  const q = query && Object.entries(query).filter(([, v]) => v != null && v !== "");
  if (q && q.length) h += `?${new URLSearchParams(q).toString()}`;
  return h;
}

export function go(page, id = null, query = null) {
  window.location.hash = href(page, id, query);
}

/** replace the query string without adding history entries (for filters) */
export function setQuery(query) {
  const { page, id } = parse();
  history.replaceState(null, "", href(page, id, query));
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}
