"""Issue clustering (owner: M1).

Primary method (`cluster`): a pairwise model + average-linkage clustering, per ward.
  1. Candidate pairs: same ward, received within MAX_GAP_H of each other.
  2. Features: time gap, GPS distance, same locality, same category (cleaned and as
     reported), road-name mention agree/disagree, character-n-gram text similarity,
     same language and channel.
  3. A gradient-boosting classifier is trained on pairs where both complaints are linked
     to a work order (same work order = duplicate). It is fitted OUT-OF-FOLD by ward
     (5 folds), so a ward's pairs are always scored by a model that never saw that ward.
     The reported precision/recall is therefore a held-out number.
  4. Average-linkage clustering on 1 - p, cut at p >= LINK_P. Average linkage stops one
     weak link from chaining unrelated complaints together.
Fallback (`cluster_rules`) is the earlier greedy rule set, used if scikit-learn is absent.

Rule-based description of the fallback:

Greedy streaming clustering in time order. A complaint joins the best open cluster in
its ward with the same category when
  - the gap since the cluster's latest complaint is <= WINDOW_H (and cluster span <= 2x),
  - both have GPS and are within RADIUS_M of the cluster point, or either lacks GPS and
    they share a normalised locality.
Parameters were tuned against the data's own ground truth (complaints linked to the
same work order): GPS pairs inside one work order are all within ~80 m of each other.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from pipeline.common.geo import haversine_m

WINDOW_H, RADIUS_M, TIME_WEIGHT = 72, 80, 0.5


def cluster_rules(df: pd.DataFrame) -> pd.Series:
    """Rule-based fallback (no scikit-learn needed)."""
    ids: dict = {}
    open_by: dict = {}
    n = 0
    for r in df.sort_values(["received_at", "complaint_id"]).itertuples():
        best, best_score = None, float("inf")
        for c in open_by.get(r.ward_code, []):
            gap = (r.received_at - c["last"]).total_seconds() / 3600
            span = (r.received_at - c["first"]).total_seconds() / 3600
            if gap > WINDOW_H or span > 2 * WINDOW_H or c["cat"] != r.category_clean:
                continue
            if not np.isnan(r.lat) and not np.isnan(c["lat"]):
                d = float(haversine_m(r.lat, r.lon, c["lat"], c["lon"]))
                ok = d <= RADIUS_M
            else:
                d = RADIUS_M * 0.5
                ok = r.locality_norm is not None and r.locality_norm == c["loc"]
            if ok and d + gap * TIME_WEIGHT < best_score:
                best, best_score = c, d + gap * TIME_WEIGHT
        if best is None:
            best = {"first": r.received_at, "last": r.received_at, "loc": r.locality_norm,
                    "lat": r.lat, "lon": r.lon, "cat": r.category_clean, "id": n}
            n += 1
            open_by.setdefault(r.ward_code, []).append(best)
        else:
            best["last"] = r.received_at
            if np.isnan(best["lat"]) and not np.isnan(r.lat):
                best["lat"], best["lon"] = r.lat, r.lon
        ids[r.Index] = best["id"]
    # complaints with no ward each form their own issue
    for i in df.index.difference(list(ids)):
        ids[i] = n
        n += 1
    return pd.Series(ids).reindex(df.index).map(lambda k: f"ISS-{k + 1:05d}")


def metrics(df: pd.DataFrame) -> dict:
    """Pairwise precision/recall vs ground truth (complaints linked to the same WO)."""
    linked = df.dropna(subset=["linked_work_order_id"])

    def pairs(col):
        out = set()
        for _, g in linked.groupby(col):
            out.update(combinations(sorted(g.complaint_id), 2))
        return out

    truth, pred = pairs("linked_work_order_id"), pairs("issue_id")
    tp = len(truth & pred)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(truth) if truth else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4),
            "f1": round(2 * p * r / (p + r), 4) if tp else 0.0,
            "n_truth_pairs": len(truth), "n_pred_pairs": len(pred)}


# ---------------------------------------------------------------- model-based -------
MAX_GAP_H, LINK_P = 144, 0.30
FEATURES = ["gap", "dist", "gps", "sameloc", "locnone", "samecat", "samerep",
            "roadsame", "roaddiff", "txt", "samelang", "samech"]


def _road_mention(desc: pd.Series, road_names) -> pd.Series:
    names = sorted(set(road_names), key=lambda n: (-len(n), n))

    def find(t):
        t = str(t).lower()
        return next((n for n in names if n.lower() in t), None)
    return desc.map(find)


def build_pairs(df: pd.DataFrame, road_names) -> pd.DataFrame:
    """Candidate pairs with features. Index labels refer to df's positional index."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    d = df.reset_index(drop=True)
    X = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=3,
                        sublinear_tf=True).fit_transform(d.description)
    road = _road_mention(d.description, road_names).to_numpy(object)
    loc = d.locality_norm.to_numpy(object)
    lat, lon = d.lat.to_numpy(float), d.lon.to_numpy(float)
    cat, rep = d.category_clean.to_numpy(object), d.category_reported.to_numpy(object)
    lang, ch = d.language.to_numpy(object), d.channel.to_numpy(object)
    tm = d.received_at.to_numpy().astype("datetime64[m]").astype(np.int64) / 60.0
    wo = d.linked_work_order_id.to_numpy(object)
    out = []
    for w, g in d.dropna(subset=["ward_code"]).groupby("ward_code"):
        idx = g.index.to_numpy()
        idx = idx[np.argsort(tm[idx], kind="stable")]
        for k, a in enumerate(idx):
            rest = idx[k + 1:]
            rest = rest[tm[rest] - tm[a] <= MAX_GAP_H]
            if not len(rest):
                continue
            gps = ~np.isnan(lat[a] + lat[rest])
            dist = np.where(gps, haversine_m(lat[a], lon[a], lat[rest], lon[rest]), -1.0)
            sim = np.asarray(X[rest].dot(X[a].T).todense()).ravel()
            la = loc[a]
            sameloc = np.array([la is not None and la == loc[j] for j in rest], int)
            locnone = np.array([la is None or loc[j] is None for j in rest], int)
            ra = road[a]
            rs = np.array([ra is not None and ra == road[j] for j in rest], int)
            rd = np.array([ra is not None and road[j] is not None and ra != road[j] for j in rest], int)
            both = np.array([wo[a] is not None and not pd.isna(wo[a]) and not pd.isna(wo[j])
                             for j in rest])
            same = np.array([bool(b) and wo[a] == wo[j] for b, j in zip(both, rest)])
            out.append(pd.DataFrame({
                "a": a, "b": rest, "ward": w, "gap": tm[rest] - tm[a], "dist": dist,
                "gps": gps.astype(int), "sameloc": sameloc, "locnone": locnone,
                "samecat": (cat[rest] == cat[a]).astype(int),
                "samerep": (rep[rest] == rep[a]).astype(int),
                "roadsame": rs, "roaddiff": rd, "txt": sim,
                "samelang": (lang[rest] == lang[a]).astype(int),
                "samech": (ch[rest] == ch[a]).astype(int),
                "both": both.astype(int), "y": same.astype(int)}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(
        columns=["a", "b", "ward", "both", "y", *FEATURES])


def score_pairs(P: pd.DataFrame, folds: int = 5) -> pd.Series:
    """Out-of-fold duplicate probability for every candidate pair (folds split by ward)."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import GroupKFold
    p = np.zeros(len(P))
    lab = P["both"].to_numpy() == 1
    for tr, te in GroupKFold(min(folds, P.ward.nunique())).split(P, groups=P.ward):
        tr_lab = tr[lab[tr]]
        m = GradientBoostingClassifier(n_estimators=150, max_depth=3, random_state=0)
        m.fit(P.iloc[tr_lab][FEATURES], P.iloc[tr_lab]["y"])
        p[te] = m.predict_proba(P.iloc[te][FEATURES])[:, 1]
    return pd.Series(p, index=P.index)


def cluster_model(df: pd.DataFrame, road_names) -> pd.Series:
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    P = build_pairs(df, road_names)
    P["p"] = score_pairs(P)
    n = len(df)
    lbl = np.arange(n)
    nxt = n
    for _, g in P.groupby("ward"):
        ids = np.unique(np.concatenate([g.a.to_numpy(), g.b.to_numpy()]))
        pos = {v: i for i, v in enumerate(ids)}
        D = np.ones((len(ids), len(ids)))
        np.fill_diagonal(D, 0)
        ia, ib = g.a.map(pos).to_numpy(), g.b.map(pos).to_numpy()
        D[ia, ib] = D[ib, ia] = 1 - g.p.to_numpy()
        c = fcluster(linkage(squareform(D, checks=False), method="average"),
                     t=1 - LINK_P, criterion="distance")
        lbl[ids] = nxt + c
        nxt += c.max() + 1
    # order issue numbers by first appearance for stable, readable ids
    first = pd.Series(df.received_at.to_numpy()).groupby(lbl).transform("min")
    rank = pd.Series(lbl).map({l: i + 1 for i, l in enumerate(
        pd.Series(lbl).groupby(lbl).apply(lambda s: (first[s.index[0]], s.index[0])).sort_values().index)})
    return pd.Series([f"ISS-{r:05d}" for r in rank], index=df.index)


def cluster(df: pd.DataFrame, road_names=None) -> pd.Series:
    """Model-based clustering; falls back to the rule-based clusterer if scikit-learn or
    scipy are missing."""
    try:
        return cluster_model(df, road_names if road_names is not None else [])
    except ImportError:
        return cluster_rules(df)
