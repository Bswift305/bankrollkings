"""QC: season-calendar COVERAGE contract (Nov 2026, F2v2 calendar audit).

The season gate (season_utils.season_state) is bootstrapped by the governed calendar in
season_calendar.py. That calendar is per-season data, so it EXPIRES. This check makes an expiring or
unverified future season visible COVERAGE_LOOKAHEAD_DAYS (60) before it can affect production:

  every date in [today, today + 60] must be covered by a VERIFIED entry (official dates + source URL +
  retrieval date). Per sport:
    OK       -- fully verified through the horizon
    WATCH    -- covered, but only by an UNVERIFIED (conservative, wide) entry inside the horizon: add the
                verified season once the league publishes it
    FAIL     -- a date in the horizon is covered by NO entry (the gate would fall to UNKNOWN/fail-open),
                or the calendar is structurally unsound (gap/overlap, missing provenance)

Exit 1 when any sport is not OK (the contract "fails"). The final summary carries `FAIL: <n>` = hard
failures only, so run_all_scorecards reports an unverified-only result as WATCH (not blocking) and a
lapse / structural problem as FAIL.

Usage: py -3 qc_season_calendar_coverage.py [--today YYYY-MM-DD] [--lookahead N]
Pure; no network; Eastern 'today' by default.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

import season_calendar as sc
from season_utils import GOVERNED_SPORTS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--lookahead", type=int, default=sc.COVERAGE_LOOKAHEAD_DAYS)
    args = ap.parse_args(argv)
    if args.today is None:
        from services.timeutils import eastern_today
        today = eastern_today()
    else:
        today = args.today

    print(f"Season calendar coverage: today={today} look-ahead={args.lookahead}d")
    hard, watch, ok = 0, 0, 0
    for p in sc.validate_calendar():
        print(f"[FAIL] structure: {p}")
        hard += 1
    for sport in GOVERNED_SPORTS:
        r = sc.coverage_status(sport, today, args.lookahead)
        cur = sc.entry_for(sport, today)
        cur_txt = cur.label() if cur else "NO ENTRY COVERS TODAY"
        if r["lapse"]:
            status, hard = "FAIL", hard + 1
            msg = f"date {r['first_uncovered']} is covered by NO calendar entry (gate would be UNKNOWN)"
        elif not r["ok"]:
            status, watch = "WATCH", watch + 1
            msg = f"date {r['first_unverified']} covered only by an UNVERIFIED entry"
        else:
            status, ok = "ok", ok + 1
            msg = "verified through the horizon"
        print(f"[{status}] {sport}: {msg}; current: {cur_txt}")
        print(f"       first unverified {r['first_unverified']} (check fires {r['unverified_fire']}); "
              f"first uncovered {r['first_uncovered']} (lapse fires {r['uncovered_fire']})")
        for u in r["unverified_entries"]:
            print(f"       unverified entry: {u}")
    print()
    print(f"Season calendar coverage QC: {ok} ok, {watch} WATCH (unverified), FAIL: {hard}")
    return 0 if (hard == 0 and watch == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
