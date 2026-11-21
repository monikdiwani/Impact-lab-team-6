"""Typed loaders for every CSV in data/ (owner: M1). Always UTF-8."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data"
_TS = "%Y-%m-%d %H:%M"


def _csv(data_dir, name: str) -> pd.DataFrame:
    return pd.read_csv(Path(data_dir or DEFAULT_DATA) / f"{name}.csv", encoding="utf-8")


def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format=_TS, errors="coerce")


def load_complaints(data_dir=None) -> pd.DataFrame:
    df = _csv(data_dir, "complaints")
    df["received_at"] = _ts(df["received_at"])
    df["resolved_at"] = _ts(df["resolved_at"])
    return df


def load_work_orders(data_dir=None) -> pd.DataFrame:
    df = _csv(data_dir, "work_orders")
    for c in ("assigned_at", "work_started_at", "completed_at"):
        df[c] = _ts(df[c])
    df["linked_complaint_ids"] = df["linked_complaint_ids"].apply(
        lambda v: [x for x in str(v).split("|") if x] if pd.notna(v) else [])
    return df


def load_localities(data_dir=None) -> pd.DataFrame:
    return _csv(data_dir, "localities")


def load_wards(data_dir=None) -> pd.DataFrame:
    return _csv(data_dir, "wards")


def load_roads(data_dir=None) -> pd.DataFrame:
    return _csv(data_dir, "roads")


def load_contractors(data_dir=None) -> pd.DataFrame:
    return _csv(data_dir, "contractors")


def load_wards_geojson(data_dir=None) -> dict:
    with open(Path(data_dir or DEFAULT_DATA) / "wards.geojson", encoding="utf-8") as f:
        return json.load(f)
