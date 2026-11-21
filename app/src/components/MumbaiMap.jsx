import { useMemo, useState } from "react";
import { geoArea, geoMercator, geoPath } from "d3-geo";
import { useData } from "../lib/data";

/*
  SVG map of Mumbai's 24 wards (synthetic boundaries from data/wards.geojson), no tiles, works offline.

  Props
    values      { [ward_code]: number }   choropleth values (optional)
    color       (value) => css colour     fill for a ward value (required with values)
    selected    ward_code                  outlined in the accent colour
    onSelect    (ward_code) => void        click / Enter on a ward
    focus       ward_code                  zoom the view to this ward
    roads       [{ road_id, coords: [[lon,lat],...], color, width, title }]   lines on top
    points      [{ lat, lon, r, className, title }]                            dots on top (hotspots, facilities)
    label       (ward_code) => string      tooltip text per ward
    height      px (default 520)
*/
export default function MumbaiMap({ values, color, selected, onSelect, focus, roads, points, label, height = 520, ariaLabel = "Map of Mumbai wards" }) {
  const geo = useData("wards_geo");
  const [hover, setHover] = useState(null);
  const W = 420;
  const H = height;

  // d3 wants clockwise outer rings; this file is counter-clockwise (RFC 7946), so rewind any ring that covers the globe
  const features = useMemo(() => {
    if (!geo.data) return null;
    return geo.data.features.map((f) =>
      geoArea(f) > 2 * Math.PI ? { ...f, geometry: { ...f.geometry, coordinates: f.geometry.coordinates.map((r) => [...r].reverse()) } } : f,
    );
  }, [geo.data]);

  const { path, project } = useMemo(() => {
    if (!features) return {};
    const target = { type: "FeatureCollection", features: focus ? features.filter((f) => f.properties.ward_code === focus) : features };
    const pad = focus ? 28 : 8;
    const proj = geoMercator().fitExtent([[pad, pad], [W - pad, H - pad]], target);
    return { path: geoPath(proj), project: proj };
  }, [features, focus, H]);

  if (geo.loading) return <div className="skeleton w-full" style={{ height }} />;
  if (geo.error || !path) return <div className="text-sm text-error">Map unavailable.</div>;

  const tip = hover && (label ? label(hover) : hover);

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={ariaLabel} style={{ maxHeight: height }}>
        <g>
          {features.map((f) => {
            const code = f.properties.ward_code;
            const v = values?.[code];
            const isSel = code === selected;
            const dim = focus && code !== focus;
            return (
              <path
                key={code}
                d={path(f)}
                className="ward-shape"
                tabIndex={onSelect ? 0 : -1}
                role={onSelect ? "button" : undefined}
                aria-label={label ? label(code) : `Ward ${code}`}
                fill={v != null && color ? color(v) : "var(--color-base-200)"}
                fillOpacity={dim ? 0.25 : 1}
                stroke={isSel ? "var(--color-primary)" : "var(--color-base-100)"}
                strokeWidth={isSel ? 3 : 1.2}
                onMouseEnter={() => setHover(code)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(code)}
                onBlur={() => setHover(null)}
                onClick={() => onSelect?.(code)}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect?.(code))}
              />
            );
          })}
        </g>
        {!focus && (
          <g pointerEvents="none">
            {features.map((f) => {
              const [x, y] = path.centroid(f);
              return (
                <text key={f.properties.ward_code} x={x} y={y} textAnchor="middle" dominantBaseline="middle"
                  className="fill-base-content/70 font-mono" style={{ fontSize: 9, paintOrder: "stroke", stroke: "var(--color-base-100)", strokeWidth: 2.5 }}>
                  {f.properties.ward_code}
                </text>
              );
            })}
          </g>
        )}
        {roads && (
          <g>
            {roads.map((r) =>
              r.coords ? (
                <polyline key={r.road_id} points={r.coords.map((c) => project(c).join(",")).join(" ")}
                  fill="none" stroke={r.color || "var(--color-base-content)"} strokeWidth={r.width || 2} strokeLinecap="round">
                  {r.title && <title>{r.title}</title>}
                </polyline>
              ) : null,
            )}
          </g>
        )}
        {points && (
          <g>
            {points.map((p, i) => {
              const [x, y] = project([p.lon, p.lat]);
              return (
                <circle key={i} cx={x} cy={y} r={p.r || 3.5} className={p.className || "fill-info"} stroke="var(--color-base-100)" strokeWidth={1}>
                  {p.title && <title>{p.title}</title>}
                </circle>
              );
            })}
          </g>
        )}
      </svg>
      {tip && (
        <div className="pointer-events-none absolute left-3 top-3 max-w-[16rem] rounded-field border border-base-300 bg-base-100/95 px-3 py-2 text-sm shadow-sm">
          {tip}
        </div>
      )}
    </div>
  );
}

/** Sequential colour ramp from base-200 to the accent, for "more is worse/higher" values in [0,1]. */
export function ramp(t) {
  const p = Math.max(0, Math.min(1, t));
  return `color-mix(in oklab, var(--color-primary) ${Math.round(8 + p * 82)}%, var(--color-base-200))`;
}

/** Warm ramp for "risk / money flagged" values in [0,1] (uses the error colour). */
export function riskRamp(t) {
  const p = Math.max(0, Math.min(1, t));
  return `color-mix(in oklab, var(--color-error) ${Math.round(6 + p * 84)}%, var(--color-base-200))`;
}
