"""QC (integration): prop-streak board against the REAL NFL_AllPropResults source schema.

Companion to the synthetic qc_nfl_prop_streak_freshness.py. This one writes an actual
data/tracking/NFL_AllPropResults.csv -- the real column names, the real OVER/UNDER row pair per
graded prop -- into a temp DATA_DIR and drives build_nfl_prop_streaks through its real on-disk read
path (_load_nfl_all_prop_results -> _load_cached_csv). It proves the reported production sequence:
an Under streak that is current through the latest graded week DISAPPEARS once the next graded game
goes Over -- exactly what happens when a new week lands in the routinely-refreshed graded record.

Exits 0 when the board behaves correctly against the real schema, 1 otherwise.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

import app

# A faithful subset of the 77-column NFL_AllPropResults schema -- every column the builder reads,
# plus the structural ones (both Direction rows per prop). Unused columns are omitted; the real
# file has ~70 more, but the builder only consumes these, so this exercises the real read path.
COLS = ['SnapshotDate', 'Sport', 'SeasonType', 'Season', 'Week', 'Player', 'Team',
        'Stat', 'Direction', 'Line', 'ResultValue']
LINE = 53.5


def _rows(player, team, stat, weeks_results, season=2026):
    """Both the OVER and UNDER graded rows per (player, stat, week), as the real file writes them."""
    out = []
    for wk, res in sorted(weeks_results.items()):
        for direction in ('OVER', 'UNDER'):
            out.append({
                'SnapshotDate': f'{season}-09-{wk:02d}T06:00:00Z', 'Sport': 'NFL',
                'SeasonType': 'REG', 'Season': season, 'Week': wk, 'Player': player,
                'Team': team, 'Stat': stat, 'Direction': direction, 'Line': LINE,
                'ResultValue': res,
            })
    return out


def _write(tmp: Path, frame_rows):
    (tmp / 'tracking').mkdir(parents=True, exist_ok=True)
    pd.DataFrame(frame_rows, columns=COLS).to_csv(tmp / 'tracking' / 'NFL_AllPropResults.csv',
                                                  index=False)


def _evans(board):
    for r in board['rows']:
        if r['player'] == 'Mike Evans':
            return r
    return None


def run_qc() -> dict:
    issues: list[str] = []
    notes: list[str] = []
    saved = {
        'DATA_DIR': app.DATA_DIR,
        'load_sport_injuries': app.load_sport_injuries,
        '_nfl_expected_completed_week': app._nfl_expected_completed_week,
        '_nfl_injury_source_state': app._nfl_injury_source_state,
    }
    no_inj = pd.DataFrame(columns=['Player', 'Team', 'Status', 'Reason', 'Updated'])
    try:
        app.load_sport_injuries = lambda sport_key='nfl': no_inj
        # Deterministic fresh injury state (no players listed -> everyone documented available),
        # decoupled from the ambient repo NFL_Injuries.csv mtime so the active-run assertions hold.
        app._nfl_injury_source_state = lambda: {
            'lookup': {}, 'updated': '2026-10-17 18:30 ET', 'mtime': 1.0, 'fresh': True, 'gated': False}

        # Evans: 4 straight UNDERs (results below the 53.5 line) through week 4, plus a couple of
        # other players so it isn't a one-row file. Graded through week 4, calendar expects week 4.
        base = (_rows('Mike Evans', 'TB', 'Rec Yds', {1: 30, 2: 40, 3: 25, 4: 35})
                + _rows('Chris Godwin', 'TB', 'Rec Yds', {1: 70, 2: 65, 3: 80, 4: 72})   # overs
                + _rows('Rachaad White', 'TB', 'Rush Yds', {1: 30, 2: 28, 3: 25, 4: 20}))  # unders

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (4, 2026)
            _write(tmp, base)
            a = app.build_nfl_prop_streaks()

            if a['pending']:
                issues.append("A: current graded file flagged pending")
            if a['through_week'] != 4 or a['through_season'] != 2026:
                issues.append(f"A: through {a['through_season']} wk {a['through_week']} (want 2026/4)")
            if not a['source_updated']:
                issues.append("A: no source refresh timestamp surfaced")
            ev = _evans(a)
            if ev is None:
                issues.append("A: Evans missing from a current 4-game under run")
            elif ev['side'] != 'Under' or ev['streak'] != 4 or not ev['active']:
                issues.append(f"A: Evans {ev['side']} x{ev['streak']} active={ev['active']} "
                              "(want Under x4 active)")
            else:
                notes.append(f"real schema: Evans Under x4 active, {a['through_label']}")

        # Week 5 lands in the graded record and Evans' game went OVER -> the under run must end.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (5, 2026)
            over_week5 = base + _rows('Mike Evans', 'TB', 'Rec Yds', {5: 85})  # 85 > 53.5 -> over
            # Godwin + White also get a week-5 row so the board's through-week is 5.
            over_week5 += _rows('Chris Godwin', 'TB', 'Rec Yds', {5: 60})
            over_week5 += _rows('Rachaad White', 'TB', 'Rush Yds', {5: 18})
            _write(tmp, over_week5)
            b = app.build_nfl_prop_streaks()

            if b['through_week'] != 5:
                issues.append(f"B: through_week {b['through_week']} (want 5 once week 5 lands)")
            ev_b = _evans(b)
            if ev_b is not None and ev_b['side'] == 'Under' and ev_b['active']:
                issues.append("B: Evans STILL a current Under run after a week-5 over (the bug)")
            if ev_b is None:
                notes.append("real schema: week-5 over ended Evans' under run; off the board")
            else:
                notes.append(f"real schema: Evans now {ev_b['side']} x{ev_b['streak']} "
                             f"active={ev_b['active']} after the over")
    finally:
        for name, val in saved.items():
            setattr(app, name, val)
        app._NFL_WAVE_CACHE.clear()
    return {'issues': issues, 'notes': notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS NFL PROP-STREAK INTEGRATION QC (real schema)")
    print("=" * 60)
    for note in report["notes"]:
        print(f"[NOTE] {note}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("No prop-streak integration issues detected.")
        return 0
    for msg in report["issues"]:
        print(f"[FAIL] {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
