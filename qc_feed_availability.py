"""
QC for report_feed_availability.py -- proves the zero-network paid-fetch gate
classifies the four cases the Oct 2026 incident conflated:

  PROBE_JUSTIFIED  events in-window + props stale   (e.g. NBA opening week)
  NO_FETCH         no events in-window              (off-season / between slates)
  FRESH            props fresh                       (no spend needed)
  NO_SCHEDULE      no schedule on disk               (fix the free feed first)

Pure/offline: builds temp CSVs and points the report's BASE_DIR at them. Exits
non-zero on any mismatch so the scorecard runner catches a regression.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import report_feed_availability as rfa


def _write_schedule(path: Path, day_offsets: list[int], today: date) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"Date": (today + timedelta(days=d)).isoformat(), "Away": "A", "Home": "H"} for d in day_offsets]
    pd.DataFrame(rows or [{"Date": "", "Away": "", "Home": ""}]).iloc[: len(rows)].to_csv(path, index=False)


def _touch_csv(path: Path, rows: int, age_hours: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"Player": f"P{i}", "LastUpdated": "2026-01-01"} for i in range(rows)]).to_csv(path, index=False)
    import os
    ts = datetime.now().timestamp() - age_hours * 3600
    os.utime(path, (ts, ts))


def main() -> int:
    failures: list[str] = []
    today = rfa._eastern_today()

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        orig_base = rfa.BASE_DIR
        orig_sports = rfa.SPORTS
        rfa.BASE_DIR = base
        # Four synthetic sports, one per expected verdict.
        rfa.SPORTS = {
            "PROBE": {"schedule": ["data/schedules/PROBE_Schedule.csv"],
                      "lines": ["data/odds/PROBE_Odds.csv"], "props": ["data/props/PROBE_Props.csv"]},
            "NOEVT": {"schedule": ["data/schedules/NOEVT_Schedule.csv"],
                      "lines": ["data/odds/NOEVT_Odds.csv"], "props": ["data/props/NOEVT_Props.csv"]},
            "FRESH": {"schedule": ["data/schedules/FRESH_Schedule.csv"],
                      "lines": ["data/odds/FRESH_Odds.csv"], "props": ["data/props/FRESH_Props.csv"]},
            "NOSCH": {"schedule": ["data/schedules/NOSCH_Schedule.csv"],
                      "lines": ["data/odds/NOSCH_Odds.csv"], "props": ["data/props/NOSCH_Props.csv"]},
        }
        try:
            # PROBE: 3 games in the next 2 days, props 48h stale -> PROBE_JUSTIFIED
            _write_schedule(base / "data/schedules/PROBE_Schedule.csv", [0, 1, 2], today)
            _touch_csv(base / "data/props/PROBE_Props.csv", 10, age_hours=48)
            # NOEVT: games exist but only 40 days out (outside the 7d window) -> NO_FETCH
            _write_schedule(base / "data/schedules/NOEVT_Schedule.csv", [40, 41], today)
            _touch_csv(base / "data/props/NOEVT_Props.csv", 10, age_hours=48)
            # FRESH: games in-window, props 1h old -> FRESH
            _write_schedule(base / "data/schedules/FRESH_Schedule.csv", [0, 1], today)
            _touch_csv(base / "data/props/FRESH_Props.csv", 10, age_hours=1)
            # NOSCH: no schedule file written -> NO_SCHEDULE
            _touch_csv(base / "data/props/NOSCH_Props.csv", 10, age_hours=48)

            report = rfa.build_report(["PROBE", "NOEVT", "FRESH", "NOSCH"],
                                      props_window=7, lines_window=5, stale_hours=6.0)
            got = {r["sport"]: r["verdict"] for r in report["rows"]}
            expected = {"PROBE": "PROBE_JUSTIFIED", "NOEVT": "NO_FETCH",
                        "FRESH": "FRESH", "NOSCH": "NO_SCHEDULE"}
            for sport, want in expected.items():
                if got.get(sport) != want:
                    failures.append(f"{sport}: expected {want}, got {got.get(sport)}")
            if report["probe_justified"] != ["PROBE"]:
                failures.append(f"probe_justified should be ['PROBE'], got {report['probe_justified']}")
        finally:
            rfa.BASE_DIR = orig_base
            rfa.SPORTS = orig_sports

    print("=" * 60)
    print("QC: FEED AVAILABILITY GATE")
    print("=" * 60)
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        return 1
    print("[OK] PROBE_JUSTIFIED / NO_FETCH / FRESH / NO_SCHEDULE all classified correctly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
