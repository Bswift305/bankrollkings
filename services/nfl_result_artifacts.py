"""Single-writer-per-file contract for the NFL graded prop-result artifacts (incident 2026-10-24).

Two populations must NEVER share a file. The 2026-10-24 clobber: the Edge-Engine historical backfill
(`build_nfl_historical_calibration.py`) and the in-season grader (`refresh_all_prop_results.py`) both
REPLACED `NFL_AllPropResults.csv`; whichever ran last erased the other's rows. The live Wave/Heating-Up
boards then read a file that held only the historical backfill and correctly showed "unavailable".

Ownership (authoritative path -> SOLE writer):
  NFL_AllPropResults.csv          -> refresh_all_prop_results   (LIVE / current-season grades only)
  NFL_AllPropResults_Backfill.csv -> build_nfl_historical_calibration  (historical calibration only)

Consumers that need BOTH populations use `load_combined()` -- an explicitly owned READ-TIME union. They
never write either source, and no job read-modify-writes another job's file. There is no third writer.
This is the contract `qc_writer_ownership.py` enforces and `qc_nfl_result_artifact_isolation.py` proves.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

LIVE_NAME = "NFL_AllPropResults.csv"
BACKFILL_NAME = "NFL_AllPropResults_Backfill.csv"

# authoritative basename -> its one and only writer. qc_writer_ownership fails if any basename maps to
# more than one pipeline, or if the code constants drift from this registry.
WRITER_OWNERSHIP = {
    LIVE_NAME: "refresh_all_prop_results",
    BACKFILL_NAME: "build_nfl_historical_calibration",
}

_UNION_KEY = ("Player", "Stat", "Direction", "Line", "Season", "Week")


def live_path(tracking_dir) -> Path:
    return Path(tracking_dir) / LIVE_NAME


def backfill_path(tracking_dir) -> Path:
    return Path(tracking_dir) / BACKFILL_NAME


def _read(path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def load_live(tracking_dir) -> pd.DataFrame:
    return _read(live_path(tracking_dir))


def load_backfill(tracking_dir) -> pd.DataFrame:
    return _read(backfill_path(tracking_dir))


def load_combined(tracking_dir) -> pd.DataFrame:
    """Read-time union for calibration consumers that need historical + live. Backfill first, live LAST
    so a prop present in both keeps the LIVE grade on dedup. Neither source file is modified."""
    bf = load_backfill(tracking_dir)
    live = load_live(tracking_dir)
    frames = [df for df in (bf, live) if not df.empty]
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    key = [c for c in _UNION_KEY if c in out.columns]
    if key:
        out = out.drop_duplicates(subset=key, keep="last").reset_index(drop=True)
    return out


def write_atomic(df: pd.DataFrame, path) -> Path:
    """Atomic publication: write a sibling .tmp then os.replace -- a crash mid-write can never leave a
    half-written/corrupt artifact (a reader always sees the old file or the new one, never a partial)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)
    return path


def write_backfill(df: pd.DataFrame, tracking_dir) -> Path:
    """Sole-writer entry point for the historical backfill artifact."""
    return write_atomic(df, backfill_path(tracking_dir))
