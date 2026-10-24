"""QC: Market Movers fail-closed on a stalled line-movement capture (Oct 23 containment).

The movers board shows each game's open->current line; the "current" is the latest snapshot. If the 4h
capture stalled, that "current" is stale and must NOT be presented as live. Populated-fixture proof: a
game whose latest snapshot is within the movers window surfaces; a game whose latest snapshot is stale
(capture stalled) is SUPPRESSED. app.DATA_DIR is redirected to a temp tree; no network. Exit 0 / 1.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import app


def _rows():
    now = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/New_York")).date().strftime("%Y-%m-%d")
    except Exception:
        today = datetime.now().date().strftime("%Y-%m-%d")

    def snap(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    # FRESH game: latest snapshot = now (within the 12h window) -> must surface
    for dt, sp, tot in ((now - timedelta(hours=6), -3.0, 44.0), (now, -4.5, 45.5)):
        rows.append({"SnapshotAt": snap(dt), "Date": today, "Away": "FreshA", "Home": "FreshH",
                     "GameID": "GFRESH", "Book": "DraftKings", "Spread": sp, "Total": tot, "HomeML": -150})
    # STALE game: latest snapshot = 24h ago (capture stalled) -> must be suppressed
    for dt, sp, tot in ((now - timedelta(hours=48), -3.0, 44.0), (now - timedelta(hours=24), -5.0, 46.0)):
        rows.append({"SnapshotAt": snap(dt), "Date": today, "Away": "StaleA", "Home": "StaleH",
                     "GameID": "GSTALE", "Book": "DraftKings", "Spread": sp, "Total": tot, "HomeML": -160})
    return pd.DataFrame(rows)


def run_qc():
    issues, notes = [], []
    d = Path(tempfile.mkdtemp(prefix="qc_movers_"))
    (d / "tracking").mkdir(parents=True, exist_ok=True)
    # MLB is in _MARKET_MOVER_SPECS (NBA line movement is not captured for movers); the gate is
    # sport-agnostic so MLB proves it.
    _rows().to_csv(d / "tracking" / "MLB_LineMovementHistory.csv", index=False)

    orig = app.DATA_DIR
    app.DATA_DIR = d
    try:
        games = app._build_market_movers_snapshot() or []
    finally:
        app.DATA_DIR = orig
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    matchups = {g.get("matchup") for g in games}
    if "FreshA @ FreshH" not in matchups:
        issues.append(f"fresh-capture game was NOT surfaced: {sorted(matchups)}")
    else:
        notes.append("fresh-capture game surfaces on Market Movers")
    if "StaleA @ StaleH" in matchups:
        issues.append("STALE-capture game surfaced (stale current line shown as live)")
    else:
        notes.append("stale-capture game SUPPRESSED (stalled capture -> no stale current line)")

    if not issues:
        notes.append("Market Movers fail-closed on a stalled capture verified")
    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS MARKET MOVERS FRESHNESS QC")
    print("=" * 60)
    for n in report["notes"]:
        print(f"[NOTE] {n}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("Market Movers freshness containment verified.")
        return 0
    for m in report["issues"]:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
