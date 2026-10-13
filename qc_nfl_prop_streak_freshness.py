"""QC (synthetic): Riding-the-Wave player prop-streak board never shows a stale run as current.

Regression guard for the under-streak freshness correction. `/tools/riding-the-wave` ->
build_nfl_wave_context -> build_nfl_prop_streaks renders each player's active OVER/UNDER run from
the ROUTINELY-REFRESHED graded record (NFL_AllPropResults.csv, written weekly by
refresh_all_prop_results.py). This test drives the LOGIC with small synthetic frames through the
source loader (_load_nfl_all_prop_results). The companion qc_nfl_prop_streak_integration.py proves
the same behavior against the real on-disk source schema. Defects this locks down:

  1. "Active" meant only "ran into the latest season IN THE FILE" -- if the graded source lagged
     the calendar, last season's final runs showed as current (Mike Evans' 6 straight unders were
     the END of 2025). Now a run is current only when the graded data reaches the calendar's
     completed week AND the player is available; else historical.
  2. No through-week / pending disclosure. Now the board states what it is graded through and
     flags pending when the completed week is missing.

Headline fixture: Mike Evans on a 6-game UNDER run, then the next graded week goes OVER -- the run
ends and he is no longer a current streak. Exits 0 when the board behaves correctly, 1 otherwise.
"""
from __future__ import annotations

import pandas as pd

import app

LINE = 53.5
STAT = 'Rec Yds'


def _history(weeks_actuals: dict[int, float], season: int = 2026, player: str = 'Mike Evans',
             team: str = 'TB') -> pd.DataFrame:
    """One player's graded results in the NFL_AllPropResults shape: {week: result} vs a fixed
    line. OVER-direction rows only (the builder keeps OVER to dedupe the O/U pair)."""
    rows = []
    for wk, result in sorted(weeks_actuals.items()):
        rows.append({
            'Sport': 'NFL', 'SeasonType': 'REG', 'Season': season, 'Week': wk,
            'Player': player, 'Team': team, 'Stat': STAT, 'Direction': 'OVER',
            'Line': LINE, 'ResultValue': result,
        })
    return pd.DataFrame(rows)


def _evans(board: dict):
    for r in board['rows']:
        if r['player'] == 'Mike Evans':
            return r
    return None


def run_qc() -> dict:
    issues: list[str] = []
    notes: list[str] = []

    saved = {
        '_load_nfl_all_prop_results': app._load_nfl_all_prop_results,
        'load_sport_injuries': app.load_sport_injuries,
        '_nfl_expected_completed_week': app._nfl_expected_completed_week,
    }
    no_inj = pd.DataFrame(columns=['Player', 'Team', 'Status', 'Reason', 'Updated'])

    try:
        app.load_sport_injuries = lambda sport_key='nfl': no_inj

        # ---- Scenario A: current data, Evans on a live 6-game UNDER run --------------------
        unders = {1: 30, 2: 40, 3: 25, 4: 35, 5: 45, 6: 20}   # all below 53.5
        app._load_nfl_all_prop_results = lambda: _history(unders)
        app._nfl_expected_completed_week = lambda today=None: (6, 2026)
        a = app.build_nfl_prop_streaks()

        if a['pending']:
            issues.append("A: board pending when data reaches the completed week")
        if a['through_week'] != 6 or a['through_season'] != 2026:
            issues.append(f"A: through {a['through_season']} wk {a['through_week']} (want 2026 wk 6)")
        ev = _evans(a)
        if ev is None:
            issues.append("A: Evans missing from a current 6-game under run")
        else:
            if ev['side'] != 'Under' or ev['streak'] != 6:
                issues.append(f"A: Evans run {ev['side']} {ev['streak']} (want Under 6)")
            if not ev['active']:
                issues.append("A: Evans not marked active with a current under run")
            if ev['status_label'] != 'Active run':
                issues.append(f"A: Evans status {ev['status_label']!r} (want 'Active run')")

        # ---- Scenario B (the reported bug): Week 7 loads, Evans goes OVER -> run ends ------
        with_over = dict(unders); with_over[7] = 80   # 80 > 53.5 breaks the under run
        app._load_nfl_all_prop_results = lambda: _history(with_over)
        app._nfl_expected_completed_week = lambda today=None: (7, 2026)
        b = app.build_nfl_prop_streaks()
        ev_b = _evans(b)
        if ev_b is not None and ev_b['side'] == 'Under' and ev_b['active']:
            issues.append("B: Evans STILL a current UNDER run after yesterday's over (the bug)")
        if ev_b is None:
            notes.append("reported sequence: Week-7 over ended Evans' under run; off the board")
        else:
            notes.append(f"reported sequence: Evans now {ev_b['side']} x{ev_b['streak']} active={ev_b['active']}")

        # ---- Scenario C: graded file a whole season behind -> pending, nothing current -----
        app._load_nfl_all_prop_results = lambda: _history({1: 30, 2: 40, 3: 25, 4: 35, 5: 45, 6: 20},
                                                      season=2025)
        app._nfl_expected_completed_week = lambda today=None: (4, 2026)   # calendar is 2026
        c = app.build_nfl_prop_streaks()
        if not c['pending'] or not c['stale_season']:
            issues.append("C: a season-behind graded file not flagged pending/stale")
        if any(r['active'] for r in c['rows']):
            issues.append("C: a run shown as current while the graded file is a season behind")
        if '2025' not in (c['through_label'] or '') or 'pending' not in (c['through_label'] or '').lower():
            issues.append(f"C: through_label doesn't disclose stale season: {c['through_label']!r}")
        if not issues:
            notes.append("stale-season: last year's final runs are held as historical, not current")

        # ---- Scenario D: availability gate -- an Out player's run is not current -----------
        app._load_nfl_all_prop_results = lambda: _history(unders)
        app._nfl_expected_completed_week = lambda today=None: (6, 2026)
        app.load_sport_injuries = lambda sport_key='nfl': pd.DataFrame(
            [{'Player': 'Mike Evans', 'Team': 'TB', 'Status': 'OUT', 'Reason': 'Hamstring',
              'Updated': '2026-10-10'}])
        d = app.build_nfl_prop_streaks()
        ev_d = _evans(d)
        if ev_d is None:
            issues.append("D: Evans dropped (should persist as historical when Out)")
        elif ev_d['active']:
            issues.append("D: an Out player's run shown as current")
        elif 'Out' not in ev_d['status_label']:
            issues.append(f"D: Out status not surfaced: {ev_d['status_label']!r}")
        else:
            notes.append("availability: an Out player's run is preserved as historical, not current")

    finally:
        for name, val in saved.items():
            setattr(app, name, val)
        app._NFL_WAVE_CACHE.clear()

    return {'issues': issues, 'notes': notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS NFL PROP-STREAK FRESHNESS QC")
    print("=" * 60)
    for note in report["notes"]:
        print(f"[NOTE] {note}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("No prop-streak freshness issues detected.")
        return 0
    for msg in report["issues"]:
        print(f"[FAIL] {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
