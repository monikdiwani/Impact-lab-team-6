"""M1 entry point: run(data_dir, out_dir) -> {name: Path} (blueprint section 10)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.common import io
from pipeline.common.geo import haversine_m
from pipeline.connect import dedup, extract, ward

OPEN = ["Open", "In Progress"]


def _trail(wo: pd.DataFrame, cl: pd.DataFrame) -> pd.DataFrame:
    by_id = cl.set_index("complaint_id")
    rows = []
    for r in wo.itertuples():
        g = by_id.reindex(r.linked_complaint_ids).dropna(subset=["received_at"])
        first = g.received_at.min() if len(g) else pd.NaT
        hrs = (r.completed_at - first).total_seconds() / 3600 if pd.notna(first) else np.nan
        rows.append({"work_order_id": r.work_order_id, "n_complaints": len(r.linked_complaint_ids),
                     "first_complaint_at": first, "channels": "|".join(sorted(g.channel.unique())),
                     "total_upvotes": int(g.upvotes.sum()) if len(g) else 0,
                     "hours_to_complete": hrs})
    return pd.DataFrame(rows)


def _open_issues(cl: pd.DataFrame, roads: pd.DataFrame, wards: pd.DataFrame) -> pd.DataFrame:
    roads = roads.assign(mlat=(roads.start_lat + roads.end_lat) / 2,
                         mlon=(roads.start_lon + roads.end_lon) / 2)
    wc = wards.set_index("ward_code")[["centroid_lat", "centroid_lon"]]
    cl = cl[cl.issue_id.notna()]                      # non-road complaints have no issue
    ids = cl[cl.status.isin(OPEN)].issue_id.unique()
    rows = []
    for iid, g in cl[cl.issue_id.isin(ids)].groupby("issue_id"):
        w = g.ward_code.dropna().mode()
        w = w.iloc[0] if len(w) else None
        # point: GPS -> locality centroid -> ward centroid
        lat = g.lat.mean() if g.lat.notna().any() else g.loc_lat.mean()
        lon = g.lon.mean() if g.lon.notna().any() else g.loc_lon.mean()
        if (np.isnan(lat) or np.isnan(lon)) and w in wc.index:
            lat, lon = wc.loc[w]
        road = None
        cand = roads[roads.ward_code == w]
        if len(cand) and not np.isnan(lat):
            d = haversine_m(lat, lon, cand.mlat.to_numpy(), cand.mlon.to_numpy())
            road = cand.road_id.iloc[int(np.argmin(d))]
        rows.append({"issue_id": iid, "ward_code": w, "road_id": road,
                     "category_clean": g.category_clean.mode().iloc[0],
                     "severity_1_5": int(g.severity_1_5.max()), "n_complaints": len(g),
                     "first_reported_at": g.received_at.min(),
                     "total_upvotes": int(g.upvotes.sum())})
    return pd.DataFrame(rows)


def run(data_dir: Path, out_dir: Path) -> dict[str, Path]:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    comp, wo = io.load_complaints(data_dir), io.load_work_orders(data_dir)

    df = ward.recover_wards(comp, io.load_localities(data_dir), io.load_wards_geojson(data_dir))
    df = extract.extract(df)
    links = {c: w for w, ids in zip(wo.work_order_id, wo.linked_complaint_ids) for c in ids}
    df["linked_work_order_id"] = df.complaint_id.map(links)
    # non-road complaints (garbage, street lights, junk text) stay in complaints_clean for the
    # trail, but form no road issue: they are kept out of de-dup and of M3's open issues
    road = df.category_clean != extract.NOT_ROAD
    df["issue_id"] = None
    df.loc[road, "issue_id"] = dedup.cluster(df[road], io.load_roads(data_dir).road_name)

    clean = df[["complaint_id", "received_at", "channel", "ward_code", "ward_source", "lat", "lon",
                "category_clean", "severity_1_5", "language", "english_summary", "issue_id",
                "linked_work_order_id", "status"]]
    trail = _trail(wo, df)
    oi = _open_issues(df, io.load_roads(data_dir), io.load_wards(data_dir))

    m = dedup.metrics(df)
    m["extraction_source_counts"] = df.extraction_source.value_counts().to_dict()
    m["not_road_complaints"] = int((~road).sum())
    m["ward_source_counts"] = df.ward_source.fillna("unresolved").value_counts().to_dict()
    paths = {}
    for name, frame in (("complaints_clean", clean), ("wo_trail", trail), ("open_issues", oi)):
        paths[name] = out_dir / f"{name}.parquet"
        frame.to_parquet(paths[name], index=False)
    paths["dedup_metrics"] = out_dir / "dedup_metrics.json"
    paths["dedup_metrics"].write_text(json.dumps(m, indent=2), encoding="utf-8")
    from pipeline.db.sync import after_run  # keep outputs/follow_the_rupee.db in step (no-op outside outputs/)
    after_run(data_dir, out_dir, "M1")
    return paths
