"""Layer 4: does M3's road risk score predict where trouble actually happened?

Builds a copy of data/ that only knows the world before --cutoff (default
2025-08-01), runs pipeline.risk.run on it, then scores the ranking against what
happened afterwards on each road:
    trouble = new work orders + re-opened ones among them + 2 x road-condition accidents
and compares with two baselines, a coin flip and "rank by past work-order count".
A risk model that can't beat the naive baseline isn't adding anything.

  python -m evals.backtest_risk                  # pipeline.risk (M3)
  python -m evals.backtest_risk --target naive   # harness self-check, no M3 code needed
"""
from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / ".claude" / "hillclimb" / "risk_backtest"
ROAD_CAUSES = ("Pothole", "Waterlogged road", "Uneven road / open chamber")
K = 20


def truncate(dst: Path, cutoff: pd.Timestamp) -> None:
    """Copy data/ keeping only what was knowable before the cutoff."""
    shutil.copytree(DATA, dst)
    rd = lambda n: pd.read_csv(dst / f"{n}.csv", encoding="utf-8")  # noqa: E731
    wr = lambda df, n: df.to_csv(dst / f"{n}.csv", index=False, encoding="utf-8")  # noqa: E731

    wo = rd("work_orders")
    wo = wo[pd.to_datetime(wo.assigned_at) < cutoff].copy()
    done = pd.to_datetime(wo.completed_at)
    wo.loc[done >= cutoff, ["completed_at"]] = None          # not finished yet
    wo.loc[done >= cutoff - pd.Timedelta(days=30), "reopened_within_30d"] = "N"   # outcome not yet known
    wr(wo, "work_orders")

    c = rd("complaints")
    c = c[pd.to_datetime(c.received_at) < cutoff].copy()
    later = pd.to_datetime(c.resolved_at) >= cutoff
    c.loc[later, "status"], c.loc[later, "resolved_at"] = "In Progress", None
    wr(c, "complaints")

    for name, col in (("accidents", "occurred_at"), ("rainfall_daily", "date"), ("tides", "date"),
                      ("social_posts", "posted_at")):
        df = rd(name)
        wr(df[pd.to_datetime(df[col]) < cutoff], name)


def outcomes(cutoff: pd.Timestamp) -> pd.Series:
    wo = pd.read_csv(DATA / "work_orders.csv")
    acc = pd.read_csv(DATA / "accidents.csv")
    roads = pd.read_csv(DATA / "roads.csv").road_id
    fut = wo[pd.to_datetime(wo.assigned_at) >= cutoff]
    a = acc[(pd.to_datetime(acc.occurred_at) >= cutoff) & acc.probable_cause.isin(ROAD_CAUSES)]
    t = (fut.road_id.value_counts()
         .add(fut[fut.reopened_within_30d == "Y"].road_id.value_counts(), fill_value=0)
         .add(2 * a.road_id.value_counts(), fill_value=0))
    return t.reindex(roads, fill_value=0).rename("trouble")


def score(pred: pd.Series, trouble: pd.Series) -> dict:
    df = pd.concat([pred.rename("pred"), trouble], axis=1).fillna(0)
    top_pred = set(df.pred.rank(method="first", ascending=False).loc[lambda r: r <= K].index)
    top_true = set(df.trouble.rank(method="first", ascending=False).loc[lambda r: r <= K].index)
    return {
        "spearman": round(df.pred.rank().corr(df.trouble.rank()), 3),
        f"precision_at_{K}": round(len(top_pred & top_true) / K, 3),
        f"trouble_captured_at_{K}": round(df.loc[list(top_pred), "trouble"].sum() / df.trouble.sum(), 3),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default="2025-08-01")
    ap.add_argument("--target", default="app", choices=["app", "naive"])
    args = ap.parse_args(argv)
    cutoff = pd.Timestamp(args.cutoff)

    with tempfile.TemporaryDirectory() as tmp:
        past = Path(tmp) / "data"
        truncate(past, cutoff)
        naive = pd.read_csv(past / "work_orders.csv").road_id.value_counts()
        if args.target == "app":
            try:
                risk = importlib.import_module("pipeline.risk")
            except ModuleNotFoundError:
                sys.exit("pipeline.risk not implemented yet (contract: run(data_dir, out_dir) -> road_risk.parquet)")
            out = Path(tmp) / "out"
            out.mkdir()
            try:   # open issues as of the cutoff, if M1's module exists
                importlib.import_module("pipeline.connect").run(past, out)
            except ModuleNotFoundError:
                pass
            risk.run(past, out)
            pred = pd.read_parquet(out / "road_risk.parquet").set_index("road_id").risk_score
        else:
            pred = naive

    trouble = outcomes(cutoff)
    roads = len(trouble)
    res = {
        "cutoff": args.cutoff, "target": args.target, "n_roads": roads,
        "model": score(pred, trouble),
        "baseline_past_work_orders": score(naive, trouble),
        "baseline_random": {"spearman": 0.0, f"precision_at_{K}": round(K / roads, 3),
                            f"trouble_captured_at_{K}": round(K / roads, 3)},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.target}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"risk backtest (train < {args.cutoff}, test >= {args.cutoff}, {roads} roads)")
    print(f"  {'':<28}{'spearman':>10}{'P@' + str(K):>8}{'captured@' + str(K):>14}")
    for name in ("model", "baseline_past_work_orders", "baseline_random"):
        r = res[name]
        print(f"  {name:<28}{r['spearman']:>10}{r[f'precision_at_{K}']:>8}{r[f'trouble_captured_at_{K}']:>14}")


if __name__ == "__main__":
    main()
