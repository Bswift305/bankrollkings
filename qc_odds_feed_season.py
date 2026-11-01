"""QC: Odds feed health judges game lines + props against the GOVERNED season state (F6, Nov 2026).

Incident: the daily operator's authoritative "Odds feed health (post-refresh)" step (qc_odds_feed.py)
FAILed on prod because off-season MLB/WNBA lines/props were 89-96h old -- feeds the operator now
deliberately does not refresh (season_utils.season_state() == OFF_SEASON). Staleness must be judged
WITH that same season state:
  * OFF_SEASON stale  -> not a failure, but visibly labelled "OFF_SEASON (not judged)";
  * ACTIVE stale      -> FAIL;   UNKNOWN stale -> FAIL (fail-open never means a silent pass);
  * ACTIVE fresh      -> PASS;   lines fresh + props stale -> FAIL (truth rule kept).

Pure/offline: synthetic temp tree, fixed Eastern "today", the Odds API key check is never invoked
(run_qc(check_key=False) with _key_valid booby-trapped), qc run-log writes are stubbed. Never calls
qc_odds_feed.main() (that hits /v4/sports). Prints [ok]/[FAIL]; exits 1 on any failure.
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

import qc_odds_feed as qof
import season_utils as su

TODAY = date(2026, 11, 1)
RESULTS: list[tuple[bool, str]] = []


def check(cond: bool, desc: str) -> None:
    RESULTS.append((bool(cond), desc))
    print(f"[{'ok' if cond else 'FAIL'}] {desc}")


def S(sport, state):
    return su.SeasonState(sport, state, f"synthetic {state}")


def _touch(path: Path, age_h: float, rows=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "Away", "Home"])
        for r in rows or []:
            w.writerow(r)
    t = time.time() - age_h * 3600
    os.utime(path, (t, t))


def main() -> int:
    # ---- pure judgement ---------------------------------------------------------------------------
    fams, fails = qof.judge_sport_feeds("MLB", 96.0, 89.0, S("MLB", su.OFF_SEASON))
    check(not fails, "OFF_SEASON + stale lines/props (96h/89h) -> NOT a failure")
    check(all(v.startswith("OFF_SEASON (not judged)") for v in fams.values()) and len(fams) == 2,
          f"... and visibly labelled: {fams['MLB game lines']}")
    check("96h" in fams["MLB game lines"] and "89h" in fams["MLB props"], "... with the real ages kept in the label")

    fams, fails = qof.judge_sport_feeds("WNBA", None, None, S("WNBA", su.OFF_SEASON))
    check(not fails and "missing" in fams["WNBA props"], "OFF_SEASON + MISSING files -> not judged, labelled missing")

    fams, fails = qof.judge_sport_feeds("NBA", 50.0, 60.0, S("NBA", su.ACTIVE))
    check(len(fails) == 1 and "NBA" in fails[0] and "ACTIVE" in fails[0],
          f"ACTIVE + stale lines AND props -> FAIL (old rule let this pass): {fails}")

    fams, fails = qof.judge_sport_feeds("MLB", 96.0, 89.0, S("MLB", su.UNKNOWN))
    check(len(fails) == 1 and "UNKNOWN" in fails[0], "UNKNOWN + stale -> FAIL (fail-open never silently passes)")

    fams, fails = qof.judge_sport_feeds("MLB", 96.0, 89.0, None)
    check(len(fails) == 1 and "UNKNOWN" in fails[0], "no season state at all -> treated as UNKNOWN -> FAIL")

    fams, fails = qof.judge_sport_feeds("NFL", 2.0, 3.0, S("NFL", su.ACTIVE))
    check(not fails and fams["NFL game lines"].startswith("FRESH") and fams["NFL props"].startswith("FRESH"),
          "ACTIVE + fresh lines/props -> PASS")

    fams, fails = qof.judge_sport_feeds("NFL", 1.0, 39.0, S("NFL", su.ACTIVE))
    check(len(fails) == 1 and "props STALE" in fails[0] and "no markets posted" in fails[0],
          "ACTIVE lines FRESH + props STALE (39h) -> FAIL with the props-pipeline hint (truth rule kept)")

    fams, fails = qof.judge_sport_feeds("NCAAF", 1.0, None, S("NCAAF", su.ACTIVE))
    check(len(fails) == 1 and "props MISSING" in fails[0], "ACTIVE + props MISSING -> FAIL")

    fams, fails = qof.judge_sport_feeds("NBA", 1.0, 2.0, S("NBA", su.UNKNOWN))
    check(not fails, "UNKNOWN + fresh -> PASS (strict, not punitive)")

    # ---- integration: run_qc on a prod-shaped tree, states from the SAME governed function -----------
    def _trap():
        raise AssertionError("network key check must not run in this QC")

    saved = (qof.BASE_DIR, qof.append_qc_run_log, qof._key_valid, su.season_states)
    calls = []

    def fixed_states(sports=su.GOVERNED_SPORTS, today=None, window_days=su.DEFAULT_ACTIVE_WINDOW_DAYS,
                     base_dir=None):
        calls.append(base_dir)
        return saved[3](sports, TODAY, window_days, base_dir)

    with tempfile.TemporaryDirectory() as td:
        b = Path(td)
        d = lambda off: (TODAY + timedelta(days=off)).isoformat()
        # prod shape: NFL/NCAAF/NBA live + fresh; MLB/WNBA last season, 89-96h stale
        _touch(b / "data/odds/NFL_Odds.csv", 2, [[d(0), "A", "H"]]); _touch(b / "data/props/NFL_Props.csv", 3)
        _touch(b / "data/odds/NCAAF_Odds.csv", 2, [[d(2), "A", "H"]]); _touch(b / "data/props/NCAAF_Props.csv", 3)
        _touch(b / "data/odds/NBA_Odds.csv", 2, [[d(1), "A", "H"]]); _touch(b / "data/props/NBA_Props.csv", 3)
        _touch(b / "data/odds/MLB_Odds.csv", 96, [[d(-5), "A", "H"]]); _touch(b / "data/props/MLB_Props.csv", 89)
        _touch(b / "data/odds/WNBA_Odds.csv", 95, [[d(-95), "A", "H"]]); _touch(b / "data/props/WNBA_Props.csv", 95)
        _touch(b / "data/futures/Futures_Odds.csv", 2)
        _touch(b / "data/tracking/NFL_AllPropResults.csv", 2)
        su._EVENT_DATE_MEMO.clear()
        qof.BASE_DIR = b
        qof.append_qc_run_log = lambda *a, **k: None
        qof._key_valid = _trap
        su.season_states = fixed_states
        try:
            rep = qof.run_qc(check_key=False)
            check(calls and Path(calls[0]) == b,
                  "run_qc derives season state from season_utils.season_states(base_dir=BASE_DIR) (same governed state)")
            check(rep["season_states"] == {"NFL": "ACTIVE", "NCAAF": "ACTIVE", "NBA": "ACTIVE",
                                           "WNBA": "OFF_SEASON", "MLB": "OFF_SEASON"},
                  f"prod-shaped states: {rep['season_states']}")
            check(rep["clean"] and rep["failure_count"] == 0,
                  f"prod-shaped post-refresh health PASSES (no false FAIL on 89-96h MLB/WNBA): failures={rep['failures']}")
            check("MLB game lines=OFF_SEASON (not judged)" in rep["notes"]
                  and "WNBA props=OFF_SEASON (not judged)" in rep["notes"]
                  and rep["not_judged_off_season"] == ["WNBA", "MLB"],
                  "MLB/WNBA are visibly labelled 'OFF_SEASON (not judged)' in the report notes")

            # same tree, but NBA (ACTIVE) lines + props go stale -> must FAIL
            for rel in ("data/odds/NBA_Odds.csv", "data/props/NBA_Props.csv"):
                t = time.time() - 50 * 3600
                os.utime(b / rel, (t, t))
            rep2 = qof.run_qc(check_key=False)
            check(not rep2["clean"] and any(f.startswith("NBA ") for f in rep2["failures"]),
                  f"ACTIVE NBA stale (50h) on the same tree -> FAIL: {rep2['failures']}")

            # MLB schedule evidence removed -> UNKNOWN -> its 89-96h staleness is judged -> FAIL
            (b / "data/odds/MLB_Odds.csv").unlink()
            su._EVENT_DATE_MEMO.clear()
            rep3 = qof.run_qc(check_key=False)
            check(rep3["season_states"]["MLB"] == "UNKNOWN"
                  and any(f.startswith("MLB ") and "UNKNOWN" in f for f in rep3["failures"]),
                  "MLB schedule evidence missing -> UNKNOWN -> stale/missing MLB feeds FAIL (no silent pass)")
        finally:
            qof.BASE_DIR, qof.append_qc_run_log, qof._key_valid, su.season_states = saved

    n_fail = sum(1 for ok, _ in RESULTS if not ok)
    print()
    print(f"Odds feed season QC: {len(RESULTS) - n_fail} ok, {n_fail} FAIL")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
