"""QC (synthetic): Hot Hand F3 -- explicit absence/exclusion disclosure, 2026-10-25.

An eligible board prop with no player-appearance log must be DISCLOSED with a governed
absent-reason, not silently dropped:
  * a team DEFENSE prop (D/ST) -> `defense_no_player_appearance` (expected by design)
  * a name with no player-week row -> `no_player_log` (indeterminate)
  * a resolved player with no column for the stat -> `no_matching_stat_columns`

Deterministic via monkeypatched deps + a synthetic nflverse log and props board (no network,
no real data). app import needs SECRET_KEY (a throwaway local value is set here for the QC).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "qc-only-not-a-real-secret")  # local QC: import the dev app

import pandas as pd

import app


def _log():
    rows = []
    for w in range(1, 7):   # one real player who clears every week -> a shown streak
        rows.append({"_full": "Alpha Back", "player_display_name": "Alpha Back", "season": 2026,
                     "week": w, "team": "GB", "rushing_yards": 80})
    return pd.DataFrame(rows)


def _props(tmp: Path):
    rows = [
        {"Player": "Alpha Back", "Stat": "Rush Yds", "Line": 50.5,
         "Game": "Green Bay Packers@Chicago Bears", "OverOdds": -110},          # shown
        {"Player": "Arizona Cardinals D/ST", "Stat": "Rush Yds", "Line": 50.5,
         "Game": "Green Bay Packers@Chicago Bears", "OverOdds": -110},          # defense absence
        {"Player": "CJ Daniels", "Stat": "Rush Yds", "Line": 50.5,
         "Game": "Green Bay Packers@Chicago Bears", "OverOdds": -110},          # no-log absence
    ]
    (tmp / "props").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(tmp / "props" / "NFL_Props.csv", index=False)


def _patch(tmp: Path, log):
    app.DATA_DIR = tmp
    app._nfl_player_week_data = lambda: log
    app._nfl_expected_completed_week = lambda *a, **k: (6, 2026)
    app._nfl_injury_source_state = lambda: {"lookup": {}, "fresh": True, "gated": False, "updated": ""}
    app._nfl_player_availability = lambda name, lookup, feed_fresh=True: {
        "available": True, "label": "Active", "status": "active", "state": "ACTIVE", "reason": ""}
    app._nfl_player_log_sources = lambda: []
    app._nfl_player_log_signature = lambda: "sig-f3"
    app._nfl_disk_cache_load = lambda *a, **k: None
    app._nfl_disk_cache_store = lambda *a, **k: None
    try:
        app._NFL_HOTHAND_CACHE.clear(); app._NFL_PLAYER_IDX_CACHE.clear()
    except Exception:
        pass


def run_qc() -> dict:
    checks, failures = [], []

    def ok(cond, label):
        (checks if cond else failures).append(label)

    # Helper classification is governed and correct.
    ok(app._is_nfl_defense_prop("Arizona Cardinals D/ST")
       and app._is_nfl_defense_prop("San Francisco 49ers Defense")
       and not app._is_nfl_defense_prop("CJ Daniels"), "defense-prop detection is name-governed")
    ok(app._nfl_hot_hand_absent_reason("Arizona Cardinals D/ST", None, []) == "defense_no_player_appearance"
       and app._nfl_hot_hand_absent_reason("CJ Daniels", None, []) == "no_player_log"
       and app._nfl_hot_hand_absent_reason("Josh Allen", object(), []) == "no_matching_stat_columns",
       "absent-reason classification covers defense / no-log / no-stat-column")

    orig = {k: getattr(app, k) for k in (
        "DATA_DIR", "_nfl_player_week_data", "_nfl_expected_completed_week", "_nfl_injury_source_state",
        "_nfl_player_availability", "_nfl_player_log_sources", "_nfl_player_log_signature",
        "_nfl_disk_cache_load", "_nfl_disk_cache_store")}
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _props(tmp)
            _patch(tmp, _log())
            out = app.build_nfl_hot_hand(limit=100, min_streak=2)
            shown = {r["player"] for r in out.get("streaks", [])}
            absc = out.get("absences") or {}

            ok("Alpha Back" in shown, "the real streak player is shown")
            ok("Arizona Cardinals D/ST" not in shown and "CJ Daniels" not in shown,
               "absent props are NOT in the streak rows")
            ok(absc.get("count") == 2, f"two eligible props are disclosed as absences (got {absc.get('count')})")
            ok(absc.get("by_reason", {}).get("defense_no_player_appearance") == 1,
               "defense prop disclosed as defense_no_player_appearance (expected absence)")
            ok(absc.get("by_reason", {}).get("no_player_log") == 1,
               "fringe no-log name disclosed as no_player_log (indeterminate)")
            reasons = {i["reason"] for i in absc.get("items", [])}
            players = {i["player"] for i in absc.get("items", [])}
            ok({"defense_no_player_appearance", "no_player_log"} <= reasons
               and {"Arizona Cardinals D/ST", "CJ Daniels"} <= players,
               "absence items carry player + governed reason (disclosed, not silently dropped)")

            # Empty board still carries a well-formed (zero) absences disclosure.
            _patch(tmp, pd.DataFrame())
            empty = app.build_nfl_hot_hand(limit=100, min_streak=2)
            ea = empty.get("absences")
            ok(isinstance(ea, dict) and ea.get("count") == 0 and ea.get("by_reason") == {},
               "empty board carries a zero absences disclosure (never missing)")
    finally:
        for k, v in orig.items():
            setattr(app, k, v)
        try:
            app._NFL_HOTHAND_CACHE.clear(); app._NFL_PLAYER_IDX_CACHE.clear()
        except Exception:
            pass

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 72)
    print("HOT HAND F3 ABSENCE/EXCLUSION DISCLOSURE QC")
    print("=" * 72)
    for c in r["checks"]:
        print(f"  [ok] {c}")
    for f in r["failures"]:
        print(f"  [FAIL] {f}")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
