"""Shared fixtures for the Layer-1 regression suite.

Each module test runs that module's `run(data_dir, out_dir)` entry point once per
session (blueprint §10) and reads the parquet files it wrote. If a module isn't
written yet, its tests are skipped, not failed, so the suite is green from day one
and starts biting as soon as code lands.
"""
from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def read_csv(name: str, data_dir: Path = DATA) -> pd.DataFrame:
    return pd.read_csv(data_dir / f"{name}.csv", encoding="utf-8")


def import_module_or_skip(dotted: str):
    try:
        mod = importlib.import_module(dotted)
    except ModuleNotFoundError as e:
        if e.name and (dotted == e.name or dotted.startswith(e.name + ".")):
            pytest.skip(f"{dotted} not implemented yet")
        raise
    if not hasattr(mod, "run"):
        pytest.skip(f"{dotted}.run() not implemented yet")
    return mod


def run_module(dotted: str, data_dir: Path, out_dir: Path) -> Path:
    mod = import_module_or_skip(dotted)
    out_dir.mkdir(parents=True, exist_ok=True)
    mod.run(Path(data_dir), Path(out_dir))
    return out_dir


def read_output(out_dir: Path, name: str) -> pd.DataFrame:
    path = out_dir / f"{name}.parquet"
    assert path.exists(), f"module did not write {path.name}"
    return pd.read_parquet(path)


def copy_data(dst: Path) -> Path:
    shutil.copytree(DATA, dst)
    return dst


# ---- session-scoped pipeline runs on the real data ------------------------------

@pytest.fixture(scope="session")
def connect_out(tmp_path_factory):
    return run_module("pipeline.connect", DATA, tmp_path_factory.mktemp("connect"))


@pytest.fixture(scope="session")
def audit_out(tmp_path_factory):
    return run_module("pipeline.audit", DATA, tmp_path_factory.mktemp("audit"))


@pytest.fixture(scope="session")
def risk_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("risk")
    # risk reads open_issues.parquet from out_dir when present (blueprint §10)
    try:
        run_module("pipeline.connect", DATA, out)
    except pytest.skip.Exception:
        pass
    return run_module("pipeline.risk", DATA, out)


@pytest.fixture(scope="session")
def work_orders():
    return read_csv("work_orders")


@pytest.fixture(scope="session")
def complaints():
    return read_csv("complaints")
