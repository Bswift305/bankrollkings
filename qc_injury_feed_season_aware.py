"""
QC: injury-feed staleness is SEASON-AWARE (incident 2026-10-24 scorecard follow-up, WNBA finding).

A stale/absent injury feed must only FAIL the board when games are actually expected. When the
independent schedule/game-lines manifest shows NO games in the window (offseason / season wound down,
e.g. WNBA in late October), a stale feed is NO_ACTIVE_EVENTS -- a WATCH, surfaced honestly, never a
board failure. In-season behavior (games present) is unchanged, and a MISSING schedule keeps the strict
default so a real failure is never masked.

Proves:
 1. games in window + stale feed            -> FAILURE, outcome STALE
 2. NO games in window + stale feed          -> WATCH, outcome NO_ACTIVE_EVENTS (not a failure)
 3. no schedule readable + stale feed        -> FAILURE (safe default; not masked)
 4. games in window + fresh feed             -> clean, outcome UPDATED
Offline: temp injuries + schedule dirs; app import needs SECRET_KEY (set by caller).
"""
from __future__ import annotations

import os
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import services.injury_feed_qc as ifq


def _write_injuries(base: Path, prefix: str, updated_age_h: float, rows: int = 5, file_age_h: float = 48):
    d = base / "injuries"
    d.mkdir(parents=True, exist_ok=True)
    updated = (datetime.now() - timedelta(hours=updated_age_h)).strftime("%Y-%m-%d %H:%M:%S")
    pd.DataFrame([{"Player": f"P{i}", "Team": "T", "Status": "Out", "Updated": updated} for i in range(rows)]
                 ).to_csv(d / f"{prefix}_Injuries.csv", index=False)
    ts = time.time() - file_age_h * 3600
    os.utime(d / f"{prefix}_Injuries.csv", (ts, ts))


def _write_schedule(base: Path, prefix: str, game_day_offsets):
    d = base / "schedules"
    d.mkdir(parents=True, exist_ok=True)
    today = date.today()
    rows = [{"Date": (today + timedelta(days=o)).isoformat(), "Away": "A", "Home": "H"} for o in game_day_offsets]
    pd.DataFrame(rows or [{"Date": "", "Away": "", "Home": ""}]).iloc[:len(rows)].to_csv(
        d / f"{prefix}_Schedule.csv", index=False)


def _run(base: Path):
    saved = (ifq.INJURIES_DIR, ifq._SCHED_DIR, ifq._ODDS_DIR)
    ifq.INJURIES_DIR = base / "injuries"
    ifq._SCHED_DIR = base / "schedules"
    ifq._ODDS_DIR = base / "odds"
    try:
        return ifq.run_injury_feed_qc("wnba", persist=False)
    finally:
        ifq.INJURIES_DIR, ifq._SCHED_DIR, ifq._ODDS_DIR = saved


def main() -> int:
    f = []

    # 1. games in window + stale feed -> FAILURE / STALE
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write_injuries(base, "WNBA", updated_age_h=66, file_age_h=48)
        _write_schedule(base, "WNBA", [0, 1])           # games today/tomorrow
        r = _run(base)
        if r["failure_count"] == 0 or r["outcome"] != "STALE":
            f.append(f"1 in-season stale should FAIL/STALE; got fails={r['failure_count']} outcome={r['outcome']}")

    # 2. NO games in window + stale feed -> WATCH / NO_ACTIVE_EVENTS
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write_injuries(base, "WNBA", updated_age_h=66, file_age_h=48)
        _write_schedule(base, "WNBA", [-40, -39])       # last games were weeks ago (season over)
        r = _run(base)
        if r["failure_count"] != 0 or r["outcome"] != "NO_ACTIVE_EVENTS":
            f.append(f"2 offseason stale should WATCH/NO_ACTIVE_EVENTS; got fails={r['failure_count']} "
                     f"outcome={r['outcome']} warns={r['warning_count']}")
        if r["warning_count"] == 0:
            f.append("2 offseason stale should still surface a WATCH (honest, not silent)")

    # 3. no schedule readable + stale feed -> FAILURE (safe default)
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write_injuries(base, "WNBA", updated_age_h=66, file_age_h=48)
        # no schedule written
        r = _run(base)
        if r["failure_count"] == 0:
            f.append(f"3 no-schedule stale must keep the strict default FAIL; got fails={r['failure_count']}")

    # 4. games in window + fresh feed -> clean / UPDATED
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _write_injuries(base, "WNBA", updated_age_h=1, file_age_h=1)
        _write_schedule(base, "WNBA", [0, 1])
        r = _run(base)
        if r["failure_count"] != 0 or r["outcome"] != "UPDATED":
            f.append(f"4 fresh in-season should be clean/UPDATED; got fails={r['failure_count']} outcome={r['outcome']}")

    print("=" * 60)
    print("QC: INJURY FEED SEASON-AWARE")
    print("=" * 60)
    if f:
        for x in f:
            print(f"[FAIL] {x}")
        return 1
    print("[OK] stale injuries fail in-season, are NO_ACTIVE_EVENTS off-season, and a missing schedule "
          "keeps the strict default -- freshness never manufactured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
