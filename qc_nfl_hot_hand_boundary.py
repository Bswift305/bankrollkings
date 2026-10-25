"""QC (synthetic): Hot Hand F5 (completed-week boundary) + F2 (appearance-truthful label), 2026-10-25.

F5 -- the resolver's CURRENT SEASON + COMPLETED WEEK is the calculation boundary, applied by FILTERING
rows before the streak is computed (not merely capping the label), so an in-progress week and all prior
seasons cannot influence membership / streak length / ordering / through-week.

F2 -- the unit is consecutive qualifying APPEARANCES within the boundary; the weeks label preserves gaps
(a bye/non-appearance is never shown as a played week) and comes from the same builder evidence.

Deterministic via monkeypatched deps + a synthetic nflverse log and props board (no network, no real data).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

import app


def _log():
    rows = []
    def add(full, season, week, ry, team="GB"):
        rows.append({"_full": full, "player_display_name": full, "season": season, "week": week,
                     "team": team, "rushing_yards": ry})
    # Alpha: current-season weeks 1-6 all clear (80 > 50.5) + an IN-PROGRESS week 7 + a PRIOR-season 2025 row
    for w in range(1, 7):
        add("Alpha Back", 2026, w, 80)
    add("Alpha Back", 2026, 7, 80)       # in-progress week (beyond completed week 6)
    add("Alpha Back", 2025, 18, 80)      # prior season (must never enter the run)
    # Bravo: weeks 1-5 clear, did NOT play week 6 -> historical (1 week behind)
    for w in range(1, 6):
        add("Bravo Back", 2026, w, 80)
    # Charlie: weeks 2,3,4,6 clear, byed/absent week 5 -> gap-bridged appearances
    for w in (2, 3, 4, 6):
        add("Charlie Back", 2026, w, 80)
    # a NaN-week row (invalid) -> must be excluded, not counted
    rows.append({"_full": "Alpha Back", "player_display_name": "Alpha Back", "season": 2026,
                 "week": None, "team": "GB", "rushing_yards": 80})
    return pd.DataFrame(rows)


def _props(tmp: Path):
    rows = []
    for p in ("Alpha Back", "Bravo Back", "Charlie Back"):
        rows.append({"Player": p, "Stat": "Rush Yds", "Line": 50.5,
                     "Game": "Green Bay Packers@Chicago Bears", "OverOdds": -110})
    (tmp / "props").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(tmp / "props" / "NFL_Props.csv", index=False)


def _patch(tmp: Path, completed_week: int):
    log = _log()
    app.DATA_DIR = tmp
    app._nfl_player_week_data = lambda: log
    app._nfl_expected_completed_week = lambda *a, **k: (completed_week, 2026)
    app._nfl_injury_source_state = lambda: {"lookup": {}, "fresh": True, "gated": False, "updated": ""}
    app._nfl_player_availability = lambda name, lookup, feed_fresh=True: {
        "available": True, "label": "Active", "status": "active", "state": "ACTIVE", "reason": ""}
    app._nfl_player_log_sources = lambda: []
    app._nfl_player_log_signature = lambda: f"sig-{completed_week}"
    app._nfl_disk_cache_load = lambda *a, **k: None
    app._nfl_disk_cache_store = lambda *a, **k: None
    try:
        app._NFL_HOTHAND_CACHE.clear()
        app._NFL_PLAYER_IDX_CACHE.clear()
    except Exception:
        pass


def run_qc() -> dict:
    f5, f2 = [], []
    orig = {k: getattr(app, k) for k in (
        "DATA_DIR", "_nfl_player_week_data", "_nfl_expected_completed_week", "_nfl_injury_source_state",
        "_nfl_player_availability", "_nfl_player_log_sources", "_nfl_player_log_signature",
        "_nfl_disk_cache_load", "_nfl_disk_cache_store")}
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _props(tmp)
            _patch(tmp, completed_week=6)
            out = app.build_nfl_hot_hand(limit=100, min_streak=2)
            rows = {(r["player"], r["stat_key"]): r for r in out.get("streaks", [])}

            # ---- F5 ----
            if out.get("through_week") == 6:
                f5.append("[F5.7] displayed through_week == completed boundary (6)")
            else:
                f5.append(f"[F5.7 FAIL] through_week={out.get('through_week')} (want 6)")
            a = rows.get(("Alpha Back", "rushing_yards"))
            if a and a["streak"] == 6:
                f5.append("[F5.1/5] in-progress Wk7 + prior-season 2025 excluded -> Alpha streak=6 (not 7+)")
            else:
                f5.append(f"[F5.1/5 FAIL] Alpha streak={a and a['streak']} (want 6)")
            if a and a["active"] is True:
                f5.append("[F5.2] player through completed week (Alpha, Wk6) is ACTIVE")
            else:
                f5.append(f"[F5.2 FAIL] Alpha active={a and a.get('active')}")
            b = rows.get(("Bravo Back", "rushing_yards"))
            if b and b["active"] is False and b["weeks_behind"] == 1:
                f5.append("[F5.3] player ending Wk5 stays HISTORICAL (1 week behind)")
            else:
                f5.append(f"[F5.3 FAIL] Bravo active={b and b.get('active')} behind={b and b.get('weeks_behind')}")
            if not out.get("pending_latest"):
                f5.append("[F5] pending_latest False when source reaches the completed week")

            # F5.4: when the resolver ADVANCES to week 7, the same Wk7 row becomes eligible
            _patch(tmp, completed_week=7)
            out7 = app.build_nfl_hot_hand(limit=100, min_streak=2)
            a7 = next((r for r in out7["streaks"] if r["player"] == "Alpha Back" and r["stat_key"] == "rushing_yards"), None)
            if a7 and a7["streak"] == 7 and out7.get("through_week") == 7:
                f5.append("[F5.4] resolver advancing to Wk7 makes the Wk7 row eligible (streak=7, through=7)")
            else:
                f5.append(f"[F5.4 FAIL] after advance Alpha streak={a7 and a7['streak']} through={out7.get('through_week')}")

            # ---- F2 (back at boundary 6) ----
            _patch(tmp, completed_week=6)
            out = app.build_nfl_hot_hand(limit=100, min_streak=2)
            rows = {(r["player"], r["stat_key"]): r for r in out.get("streaks", [])}
            a = rows.get(("Alpha Back", "rushing_yards"))
            c = rows.get(("Charlie Back", "rushing_yards"))
            if a and a["weeks_label"] == "Appearances: Wks 1–6":
                f2.append("[F2] contiguous appearances format correctly ('Wks 1–6')")
            else:
                f2.append(f"[F2 FAIL] Alpha label={a and a.get('weeks_label')!r}")
            if c and c["weeks_label"] == "Appearances: Wks 2–4, 6":
                f2.append("[F2] non-contiguous appearances PRESERVE the gap ('Wks 2–4, 6'); bye Wk5 not shown as played")
            else:
                f2.append(f"[F2 FAIL] Charlie label={c and c.get('weeks_label')!r} weeks={c and c.get('streak_weeks')}")
            if c and c["streak"] == len(c["streak_weeks"]) == 4:
                f2.append("[F2] label + streak length derive from the same builder evidence (4 appearances)")
            else:
                f2.append(f"[F2 FAIL] Charlie streak={c and c.get('streak')} weeks={c and c.get('streak_weeks')}")
            # bye not inflated: Charlie's streak_weeks must not contain week 5
            if c and 5 not in (c.get("streak_weeks") or []):
                f2.append("[F2] non-appearance (Wk5) is not represented as a played week")
            else:
                f2.append("[F2 FAIL] Charlie streak_weeks contains the byed week 5")
    finally:
        for k, v in orig.items():
            setattr(app, k, v)
        try:
            app._NFL_HOTHAND_CACHE.clear(); app._NFL_PLAYER_IDX_CACHE.clear()
        except Exception:
            pass

    failures = [x for x in (f5 + f2) if "FAIL" in x]
    return {"clean": not failures, "f5": f5, "f2": f2, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 72)
    print("HOT HAND F5 (completed-week boundary) + F2 (appearance label) QC")
    print("=" * 72)
    print("F5 -- completed-week boundary:")
    for x in r["f5"]:
        print(f"  {x}")
    print("F2 -- appearance-truthful label:")
    for x in r["f2"]:
        print(f"  {x}")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
