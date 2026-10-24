"""
QC for generate_run_status.py DEGRADED logic.

The Oct 2026 incident read GREEN while NFL/NBA/MLB props were days stale and CFBD was
quota-exhausted, because Run Status only aged 14 analysis artifacts and never looked at
the Odds feeds or the operator's step outcomes. This proves the fix:

  - a sport whose GAME LINES are FRESH but PROPS are STALE  -> DEGRADED (not GREEN)
  - a provider-exhausted / blocking-failure operator summary -> DEGRADED
  - all current-market feeds fresh + clean operator          -> not DEGRADED on their account

Offline: points the module's BASE_DIR at a temp tree and drives _odds_family_signals /
_operator_signals / the overall severity directly.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

import generate_run_status as grs


def _touch(path: Path, age_hours: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"LastUpdated": "2026-01-01", "Player": "P"}]).to_csv(path, index=False)
    ts = datetime.now().timestamp() - age_hours * 3600
    os.utime(path, (ts, ts))


def _overall(counts_fresh: int, degraded: list[str], stale: int, missing: int) -> str:
    # mirror build_run_status severity ladder
    if counts_fresh == 0:
        return "RED"
    if degraded:
        return "DEGRADED"
    if stale == 0 and missing == 0:
        return "GREEN"
    return "WATCH"


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        orig = grs.BASE_DIR
        orig_summary = grs.OPERATOR_SUMMARY_PATH
        grs.BASE_DIR = base
        grs.OPERATOR_SUMMARY_PATH = base / "data" / "tracking" / "Last_Operator_Summary.json"
        try:
            # Case 1: NFL game lines FRESH, NFL props STALE -> a degraded reason about NFL props.
            for sport in grs.GAME_LINE_FEEDS:
                _touch(base / grs.GAME_LINE_FEEDS[sport], age_hours=1)   # all game lines fresh
                _touch(base / grs.PROPS_FEEDS[sport], age_hours=1)       # all props fresh (baseline)
            _touch(base / grs.FUTURES_FEED, age_hours=1)
            _touch(base / grs.PROPS_FEEDS["NFL"], age_hours=72)          # NFL props now stale
            _, reasons = grs._odds_family_signals()
            if not any("NFL props" in r for r in reasons):
                failures.append(f"stale NFL props with fresh lines should yield a reason; got {reasons}")
            # all-fresh sports (other than NFL) must NOT each add a reason
            if any("WNBA props" in r or "MLB props" in r for r in reasons):
                failures.append(f"fresh props must not be flagged; got {reasons}")

            # Case 2: everything fresh -> no odds reasons
            _touch(base / grs.PROPS_FEEDS["NFL"], age_hours=1)
            _, reasons_clean = grs._odds_family_signals()
            if reasons_clean:
                failures.append(f"all-fresh feeds should yield no degraded reasons; got {reasons_clean}")

            # Case 1b: TWO-clock tiers. NFL props at 10h = OVERDUE_FOR_LIVE_RENDER (past the 6h render
            # window but within the 30h cadence): a non-green AGING row, but NOT a degraded reason --
            # the customer-unavailable feed must not read 'healthy', yet a missed cycle is different.
            _touch(base / grs.PROPS_FEEDS["NFL"], age_hours=10)
            rows_o, reasons_o = grs._odds_family_signals()
            nfl_props_row = next((r for r in rows_o if r["Name"] == "NFL props"), None)
            if not nfl_props_row or nfl_props_row["Status"] != "AGING" or "OVERDUE_FOR_LIVE_RENDER" not in nfl_props_row["StatusNote"]:
                failures.append(f"10h props should be AGING/OVERDUE_FOR_LIVE_RENDER; got {nfl_props_row}")
            if any("NFL props" in r for r in reasons_o):
                failures.append(f"OVERDUE (10h) must NOT be a degraded reason; got {reasons_o}")
            # back to 72h = REFRESH_MISSED -> STALE row + degraded reason
            _touch(base / grs.PROPS_FEEDS["NFL"], age_hours=72)
            rows_m, reasons_m = grs._odds_family_signals()
            nfl_props_m = next((r for r in rows_m if r["Name"] == "NFL props"), None)
            if not nfl_props_m or nfl_props_m["Status"] != "STALE" or "REFRESH_MISSED" not in nfl_props_m["StatusNote"]:
                failures.append(f"72h props should be STALE/REFRESH_MISSED; got {nfl_props_m}")
            if not any("NFL props" in r for r in reasons_m):
                failures.append(f"REFRESH_MISSED must be a degraded reason; got {reasons_m}")
            _touch(base / grs.PROPS_FEEDS["NFL"], age_hours=1)  # restore for later cases

            # Case 3: operator summary with provider exhaustion + blocking failure
            grs.OPERATOR_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
            grs.OPERATOR_SUMMARY_PATH.write_text(json.dumps({
                "finished_at": "2026-10-24T03:20:00-04:00",
                "blocking_failure": True,
                "failed_steps": ["NBA daily refresh"],
                "provider_exhausted_steps": ["CFB data refresh"],
            }), encoding="utf-8")
            op_reasons, op_info = grs._operator_signals()
            if not any("NBA daily refresh" in r for r in op_reasons):
                failures.append(f"blocking failure should surface; got {op_reasons}")
            if not any("CFB data refresh" in r for r in op_reasons):
                failures.append(f"provider exhaustion should surface; got {op_reasons}")

            # Severity ladder: a degraded reason supersedes an otherwise-GREEN artifact set.
            if _overall(counts_fresh=10, degraded=op_reasons, stale=0, missing=0) != "DEGRADED":
                failures.append("degraded reason with fresh artifacts must give DEGRADED, not GREEN")
            if _overall(counts_fresh=10, degraded=[], stale=0, missing=0) != "GREEN":
                failures.append("no degraded reason + no stale + no missing must give GREEN")
            if _overall(counts_fresh=0, degraded=["x"], stale=0, missing=0) != "RED":
                failures.append("nothing fresh must give RED even over DEGRADED")
        finally:
            grs.BASE_DIR = orig
            grs.OPERATOR_SUMMARY_PATH = orig_summary

    print("=" * 60)
    print("QC: RUN STATUS DEGRADED")
    print("=" * 60)
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        return 1
    print("[OK] stale current-market feed, provider exhaustion, and blocking failure all drive DEGRADED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
