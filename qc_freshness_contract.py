"""
QC: the ONE freshness contract is used consistently (incident 2026-10-24, directive #1).

The incident's headline defect: the availability report called 39-40h NFL/NCAAF props STALE while
qc_odds_feed called the SAME files FRESH -- two monitoring tools, two hand-picked thresholds, opposite
verdicts. This proves that can't happen again:

  A. all monitoring surfaces read the identical props-cadence window from services.freshness_contract;
  B. pointed at ONE synthetic tree (NFL game lines 1h, props 39h), qc_odds_feed, generate_run_status,
     and report_feed_availability ALL agree NFL props is stale -- no surface dissents;
  C. the two clocks are intentionally distinct (CLOCK A render=6h vs CLOCK B cadence=30h) and labeled.

Offline: builds a temp data tree and points each module's BASE_DIR at it.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import qc_odds_feed as qof
import generate_run_status as grs
import report_feed_availability as rfa
from services.freshness_contract import (
    LIVE_MARKET_MAX_AGE_HOURS,
    refresh_cadence_hours,
)


def _write(path: Path, age_hours: float, rows: int = 3, with_date: bool = False, today=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if with_date:
        data = [{"Date": (today + timedelta(days=i % 3)).isoformat(), "Away": "A", "Home": "H"} for i in range(rows)]
    else:
        data = [{"Player": f"P{i}", "LastUpdated": "2026-01-01"} for i in range(rows)]
    pd.DataFrame(data).to_csv(path, index=False)
    ts = datetime.now().timestamp() - age_hours * 3600
    os.utime(path, (ts, ts))


def main() -> int:
    failures: list[str] = []

    # A. single source: the props window qc_odds_feed exposes IS the contract value, and nothing
    #    hand-picks a different one.
    contract_props = refresh_cadence_hours("props")
    if qof.STALE_HOURS != contract_props:
        failures.append(f"qc_odds_feed.STALE_HOURS ({qof.STALE_HOURS}) != contract props ({contract_props})")

    # C. two distinct, labeled clocks.
    if LIVE_MARKET_MAX_AGE_HOURS == contract_props:
        failures.append("render window (CLOCK A) and cadence window (CLOCK B) must be distinct values")
    if not (LIVE_MARKET_MAX_AGE_HOURS < contract_props):
        failures.append("render window should be tighter than the refresh-cadence window")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        today = date.today()
        # NFL: game lines FRESH (1h), props STALE (39h -- the incident's exact age). Futures + grading
        # fresh so only the NFL props rule is under test. Schedule has in-window events.
        _write(base / "data/odds/NFL_Odds.csv", 1)
        _write(base / "data/props/NFL_Props.csv", 39)
        _write(base / "data/futures/Futures_Odds.csv", 1)
        _write(base / "data/tracking/NFL_AllPropResults.csv", 1)
        _write(base / "data/schedules/NFL_Schedule.csv", 1, rows=5, with_date=True, today=today)

        saved = (qof.BASE_DIR, grs.BASE_DIR, rfa.BASE_DIR, dict.copy(rfa.SPORTS))
        qof.BASE_DIR = base
        grs.BASE_DIR = base
        rfa.BASE_DIR = base
        rfa.SPORTS = {"NFL": {"schedule": ["data/schedules/NFL_Schedule.csv"],
                              "lines": ["data/odds/NFL_Odds.csv"], "props": ["data/props/NFL_Props.csv"]}}
        try:
            # qc_odds_feed: NFL props STALE while lines FRESH => a failure naming NFL props.
            rep = qof.run_qc(check_key=False)
            qof_stale = any("NFL props" in f for f in rep["failures"])
            if not qof_stale:
                failures.append(f"qc_odds_feed did not flag NFL props stale; failures={rep['failures']}")

            # generate_run_status: a DEGRADED reason naming NFL props.
            _, reasons = grs._odds_family_signals()
            grs_stale = any("NFL props" in r for r in reasons)
            if not grs_stale:
                failures.append(f"generate_run_status did not flag NFL props stale; reasons={reasons}")

            # availability: NFL props STALE (=> PROBE_JUSTIFIED, events present) at the CONTRACT window.
            arep = rfa.build_report(["NFL"], props_window=7, lines_window=5, stale_hours=None)
            row = arep["rows"][0]
            rfa_stale = row["verdict"] == "PROBE_JUSTIFIED"
            if not rfa_stale:
                failures.append(f"availability verdict should be PROBE_JUSTIFIED; got {row['verdict']}")
            if row["props_stale_hours"] != contract_props:
                failures.append(f"availability used {row['props_stale_hours']}h, not contract {contract_props}h")

            # B. the anti-contradiction assertion: NO surface dissents.
            if not (qof_stale and grs_stale and rfa_stale):
                failures.append("the three surfaces disagree on a 39h props file -- the exact incident bug")
        finally:
            qof.BASE_DIR, grs.BASE_DIR, rfa.BASE_DIR, rfa.SPORTS = saved

    print("=" * 64)
    print("QC: ONE FRESHNESS CONTRACT (anti-contradiction)")
    print("=" * 64)
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        return 1
    print(f"[OK] render={LIVE_MARKET_MAX_AGE_HOURS}h, props cadence={contract_props}h; all three surfaces "
          f"agree a 39h props file is STALE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
