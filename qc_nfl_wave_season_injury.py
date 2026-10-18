"""QC: Riding-the-Wave player prop streaks -- current-season bound + injury-state safe (P0).

Drives build_nfl_prop_streaks through the REAL on-disk read path (a temp DATA_DIR) AND the REAL
injury-source freshness path (_nfl_injury_source_state reads an actual NFL_Injuries.csv whose mtime
this test controls with os.utime). Nothing about availability is mocked, so the freshness budget and
the gate state are exercised for real. Locks the P0 corrective:

  1. A trailing run is bound to the RESOLVED current season (from _nfl_expected_completed_week, never
     max(Season)): a run unbroken across 2025->2026 counts ONLY its 2026 weeks; a prior-season run
     never appears on the live board; a <3 current-season run is not a wave even if last year's was.
  2. No current-season graded record -> fail closed (unavailable), no prior-season fallback.
  3. Injury states are factual (ACTIVE / PAUSED / STATUS UNKNOWN), never a recommendation: a paused
     player's current-season run is preserved as fact but is not "actively continuing".
  4. A stale injury feed fails closed to STATUS UNKNOWN (never a silent "everyone active"), and the
     injury source exposes version + freshness + gate state so the Wave cache key moves with it.
  5. RETURNED is never fabricated: a mere gap in prop observations (missing rows) is not an absence.
  6. The board exposes the required markers: sport, season, graded-through, source timestamp, streak
     start, latest graded event, sample size.

Exits 0 when the board behaves correctly, 1 otherwise.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pandas as pd

import app

COLS = ['SnapshotDate', 'Sport', 'SeasonType', 'Season', 'Week', 'Player', 'Team',
        'Stat', 'Direction', 'Line', 'ResultValue']
LINE = 53.5


def _rows(player, team, stat, weeks_results, season):
    out = []
    for wk, res in sorted(weeks_results.items()):
        for direction in ('OVER', 'UNDER'):
            out.append({'SnapshotDate': f'{season}-09-{wk:02d}T06:00:00Z', 'Sport': 'NFL',
                        'SeasonType': 'REG', 'Season': season, 'Week': wk, 'Player': player,
                        'Team': team, 'Stat': stat, 'Direction': direction, 'Line': LINE,
                        'ResultValue': res})
    return out


def _write_props(tmp: Path, rows):
    (tmp / 'tracking').mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=COLS).to_csv(tmp / 'tracking' / 'NFL_AllPropResults.csv', index=False)


def _write_injuries(tmp: Path, records, age_hours=0.0):
    """Write a real NFL_Injuries.csv and set its mtime (age_hours in the past) so the freshness
    budget is exercised for real, not mocked."""
    (tmp / 'injuries').mkdir(parents=True, exist_ok=True)
    path = tmp / 'injuries' / 'NFL_Injuries.csv'
    cols = ['Player', 'Team', 'Status', 'Reason', 'Updated']
    pd.DataFrame(records or [], columns=cols).to_csv(path, index=False)
    when = time.time() - age_hours * 3600.0
    os.utime(path, (when, when))
    return path


def _find(board, player, stat=None):
    for r in board['rows']:
        if r['player'] == player and (stat is None or r['stat'] == stat):
            return r
    return None


OVER = 80   # > 53.5
UNDER = 30  # < 53.5


def run_qc() -> dict:
    issues: list[str] = []
    notes: list[str] = []
    saved = {'DATA_DIR': app.DATA_DIR,
             '_nfl_expected_completed_week': app._nfl_expected_completed_week,
             '_nfl_player_week_data': app._nfl_player_week_data}
    try:
        # Default: no participation record -> RETURNED never fires (the real jw26 parquet otherwise
        # loads from BASE_DIR and would contaminate). Scenario 7 installs a controlled fixture.
        app._nfl_player_week_data = lambda: pd.DataFrame()
        # ---- 1: season-crossing run counts ONLY the current (2026) season ---------------------
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (3, 2026)
            rows = (_rows('Crossover', 'TB', 'Rec Yds', {16: OVER, 17: OVER, 18: OVER}, 2025)
                    + _rows('Crossover', 'TB', 'Rec Yds', {1: OVER, 2: OVER, 3: OVER}, 2026)
                    + _rows('Filler', 'KC', 'Rec Yds', {1: OVER, 2: OVER, 3: OVER}, 2026))
            _write_props(tmp, rows)
            _write_injuries(tmp, [], age_hours=1.0)  # fresh, nobody listed -> ACTIVE
            b = app.build_nfl_prop_streaks()
            cx = _find(b, 'Crossover')
            if cx is None:
                issues.append("1: crossover player missing from a 3-week current run")
            elif cx['streak'] != 3:
                issues.append(f"1: season-crossing run counted {cx['streak']} (want 3 -- 2026 only, "
                              "the 2025 weeks must not extend it)")
            elif cx['sample_size'] != 3 or cx['streak_start_week'] != 1 or cx['last_graded_week'] != 3:
                issues.append(f"1: markers wrong (sample={cx['sample_size']} start={cx['streak_start_week']} "
                              f"last={cx['last_graded_week']}; want 3/1/3)")
            elif '16' in (cx['weeks_label'] or '') or '18' in (cx['weeks_label'] or ''):
                issues.append(f"1: weeks_label leaks 2025 weeks: {cx['weeks_label']!r}")
            elif str(cx['last_season']) != '2026' or cx['season'] != 2026:
                issues.append(f"1: run labeled season {cx['last_season']} (want 2026)")
            elif not cx['active']:
                issues.append("1: current-season available run not active")
            else:
                notes.append("season-bound: a 2025->2026 unbroken run counts only its 3 current-season weeks")

        # ---- 1b: a <3 current-season run is not a wave even though 2025's was long -------------
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (1, 2026)
            rows = (_rows('ShortNow', 'TB', 'Rec Yds', {14: OVER, 15: OVER, 16: OVER, 17: OVER, 18: OVER}, 2025)
                    + _rows('ShortNow', 'TB', 'Rec Yds', {1: OVER}, 2026)
                    + _rows('Filler', 'KC', 'Rec Yds', {1: OVER}, 2026))
            _write_props(tmp, rows)
            _write_injuries(tmp, [], age_hours=1.0)
            b = app.build_nfl_prop_streaks()
            if _find(b, 'ShortNow') is not None:
                issues.append("1b: a 1-game current run shown as a wave because last year's was long")
            else:
                notes.append("season-bound: last year's 5-game run does not resurrect a 1-game current start")

        # ---- 2: no current-season record -> fail closed, no prior-season fallback -------------
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (4, 2026)
            _write_props(tmp, _rows('OldOnly', 'TB', 'Rec Yds', {1: OVER, 2: OVER, 3: OVER}, 2025))
            _write_injuries(tmp, [], age_hours=1.0)
            b = app.build_nfl_prop_streaks()
            if not b.get('unavailable') or b.get('unavailable_reason') != 'current_season_ungraded':
                issues.append(f"2: not failed closed (unavailable={b.get('unavailable')}, "
                              f"reason={b.get('unavailable_reason')!r})")
            elif b['rows']:
                issues.append("2: prior-season rows leaked onto the live board")
            elif b.get('season') != 2026 or b.get('sport') != 'NFL':
                issues.append(f"2: markers wrong on unavailable (sport={b.get('sport')} season={b.get('season')})")
            else:
                notes.append("fail-closed: current season ungraded -> unavailable, zero prior-season runs")

        # ---- 3: injury states -- ACTIVE / PAUSED, factual and preserved -----------------------
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (3, 2026)
            rows = (_rows('Healthy', 'TB', 'Rec Yds', {1: OVER, 2: OVER, 3: OVER}, 2026)
                    + _rows('Hurt', 'KC', 'Rush Yds', {1: UNDER, 2: UNDER, 3: UNDER}, 2026))
            _write_props(tmp, rows)
            _write_injuries(tmp, [{'Player': 'Hurt', 'Team': 'KC', 'Status': 'OUT',
                                   'Reason': 'Knee', 'Updated': '2026-10-17'}], age_hours=1.0)
            b = app.build_nfl_prop_streaks()
            h, u = _find(b, 'Healthy'), _find(b, 'Hurt')
            if h is None or h.get('availability_state') != 'ACTIVE' or not h['active']:
                issues.append(f"3: healthy/absent player not ACTIVE (state={h and h.get('availability_state')})")
            if u is None:
                issues.append("3: paused player's current-season run dropped (must be preserved)")
            elif u['active'] or u.get('availability_state') != 'PAUSED':
                issues.append(f"3: Out player not PAUSED (active={u and u['active']}, "
                              f"state={u and u.get('availability_state')})")
            elif u['streak'] != 3 or 'before absence' not in u['status_label']:
                issues.append(f"3: paused run not preserved/labeled ({u['streak']}, {u['status_label']!r})")
            if not any(m.startswith('3:') for m in issues):
                notes.append("injury: absent+fresh=ACTIVE; Out=PAUSED with the factual run preserved")

        # ---- 3b: QUESTIONABLE/LIMITED with expected participation -> ACTIVE + designation shown ----
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (3, 2026)
            _write_props(tmp, _rows('Q Guy', 'TB', 'Rec Yds', {1: OVER, 2: OVER, 3: OVER}, 2026))
            _write_injuries(tmp, [{'Player': 'Q Guy', 'Team': 'TB', 'Status': 'QUESTIONABLE',
                                   'Reason': 'Hamstring', 'Updated': '2026-10-17'}], age_hours=1.0)
            b = app.build_nfl_prop_streaks()
            q = _find(b, 'Q Guy')
            if q is None or not q['active'] or q.get('availability_state') != 'ACTIVE':
                issues.append(f"3b: QUESTIONABLE not kept active (active={q and q['active']}, "
                              f"state={q and q.get('availability_state')})")
            elif not q.get('designation'):
                issues.append("3b: active QUESTIONABLE row dropped its injury designation")
            else:
                notes.append(f"injury-nuance: QUESTIONABLE stays ACTIVE with designation {q['designation']!r}")

        # ---- 7: RETURNED FROM ABSENCE from ACTUAL scheduled-game participation --------------------
        # Participation fixture (nflverse weekly shape): the team plays weeks 1-5; the player appears
        # 1,2, MISSES 3,4 (team played, no player row), and returns week 5. He is within his first
        # appearance back -> RETURNED, missed 2. (A teammate supplies the team's played weeks.)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (5, 2026)
            _write_props(tmp, _rows('Returner', 'TB', 'Rec Yds', {1: OVER, 2: OVER, 5: OVER}, 2026))
            _write_injuries(tmp, [], age_hours=1.0)  # off the current report (already back)
            part = []
            for wk in (1, 2, 3, 4, 5):          # teammate: team played all five weeks
                part.append({'season': 2026, 'week': wk, '_full': 'Team Mate', '_key': 't.mate',
                             'recent_team': 'TB'})
            for wk in (1, 2, 5):                 # returner: missed 3 and 4
                part.append({'season': 2026, 'week': wk, '_full': 'Returner', '_key': 'r.returner',
                             'recent_team': 'TB'})
            app._nfl_player_week_data = lambda: pd.DataFrame(part)
            try:
                b = app.build_nfl_prop_streaks()
            finally:
                app._nfl_player_week_data = lambda: pd.DataFrame()
            rp = _find(b, 'Returner')
            if rp is None:
                issues.append("7: returning player's run dropped")
            elif rp.get('availability_state') != 'RETURNED':
                issues.append(f"7: not flagged RETURNED (state={rp.get('availability_state')})")
            elif rp.get('returned_week') != 5 or rp.get('missed_games') != 2:
                issues.append(f"7: return detail wrong (week={rp.get('returned_week')}, "
                              f"missed={rp.get('missed_games')}; want 5 / 2)")
            elif not rp['active']:
                issues.append("7: a returned player should be active (first appearances back)")
            else:
                notes.append("returned: missed weeks 3-4 (team played, no appearance), back Wk 5 -> RETURNED x2")

        # ---- 4: STALE injury feed -> STATUS UNKNOWN (fail closed) + cache-key fields -----------
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (3, 2026)
            _write_props(tmp, _rows('Healthy', 'TB', 'Rec Yds', {1: OVER, 2: OVER, 3: OVER}, 2026))
            # Feed older than the freshness budget -> negative evidence can no longer be trusted.
            _write_injuries(tmp, [], age_hours=app._NFL_INJURY_FRESH_BUDGET_H + 48)
            st_stale = app._nfl_injury_source_state()
            if st_stale['fresh']:
                issues.append("4: an over-budget injury feed reported fresh")
            b = app.build_nfl_prop_streaks()
            h = _find(b, 'Healthy')
            if h is None:
                issues.append("4: run dropped under a stale feed (should persist as STATUS UNKNOWN)")
            elif h['active'] or h.get('availability_state') != 'STATUS UNKNOWN':
                issues.append(f"4: stale feed not failed closed (active={h['active']}, "
                              f"state={h.get('availability_state')})")
            # Fresh feed in the same dir must report fresh + a moving mtime (cache-key component).
            _write_injuries(tmp, [], age_hours=1.0)
            st_fresh = app._nfl_injury_source_state()
            for k in ('mtime', 'fresh', 'gated', 'updated'):
                if k not in st_fresh:
                    issues.append(f"4: injury source state missing cache-key field {k!r}")
            if not st_fresh['fresh']:
                issues.append("4: a 1-hour-old injury feed reported stale")
            if st_fresh['mtime'] == st_stale['mtime']:
                issues.append("4: injury mtime did not move when the feed was rewritten (cache would stick)")
            if st_fresh['gated'] is not False:
                issues.append("4: NFL injury feed reported gated (should be ungated)")
            if not any(m.startswith('4:') for m in issues):
                notes.append("freshness: stale feed -> STATUS UNKNOWN; fresh feed moves mtime (cache key sound)")

        # ---- 5: RETURNED is never fabricated from a gap in prop observations ------------------
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (5, 2026)
            # Weeks 1,2 then a gap at 3 then 4,5 -- a missing prop row, NOT a documented absence.
            _write_props(tmp, _rows('Gappy', 'TB', 'Rec Yds', {1: OVER, 2: OVER, 4: OVER, 5: OVER}, 2026))
            _write_injuries(tmp, [], age_hours=1.0)  # fresh, not listed -> available
            b = app.build_nfl_prop_streaks()
            gp = _find(b, 'Gappy')
            if gp is None:
                issues.append("5: player with a prop-row gap dropped unexpectedly")
            elif gp.get('availability_state') == 'RETURNED':
                issues.append("5: RETURNED fabricated from a missing prop row (not a documented absence)")
            elif gp.get('availability_state') != 'ACTIVE':
                issues.append(f"5: gap player not ACTIVE (state={gp.get('availability_state')})")
            elif ',' not in (gp['weeks_label'] or ''):
                issues.append(f"5: weeks_label hides the gap: {gp['weeks_label']!r} (want two ranges)")
            else:
                notes.append("negative-evidence: a prop-row gap is shown truthfully, never labeled an absence")

        # ---- 6: required markers exposed ------------------------------------------------------
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (3, 2026)
            _write_props(tmp, _rows('Marker', 'TB', 'Rec Yds', {1: OVER, 2: OVER, 3: OVER}, 2026))
            _write_injuries(tmp, [], age_hours=1.0)
            b = app.build_nfl_prop_streaks()
            for k in ('sport', 'season', 'graded_through', 'source_updated', 'injury_updated',
                      'injury_fresh', 'through_label'):
                if k not in b:
                    issues.append(f"6: board meta missing marker {k!r}")
            row = _find(b, 'Marker')
            for k in ('streak_start_week', 'last_graded_week', 'sample_size', 'availability_state'):
                if row is not None and k not in row:
                    issues.append(f"6: row missing marker {k!r}")
            if not any(m.startswith('6:') for m in issues):
                notes.append("markers: sport/season/graded-through/source-ts/streak-start/sample-size exposed")

        # ---- 8: the Heating Up board is ALSO current-season gated (same page, same defect) --------
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            app.DATA_DIR = tmp
            app._nfl_expected_completed_week = lambda today=None: (4, 2026)
            # stale: only 2025 rows while the resolver says 2026 -> fail closed, no prior-season runs
            _write_props(tmp, _rows('Hot Guy', 'TB', 'Rec Yds', {16: OVER, 17: OVER, 18: OVER}, 2025))
            hs = app.build_nfl_prop_hot_start()
            if not hs.get('unavailable') or hs.get('rows'):
                issues.append(f"8: Heating Up showed stale prior-season runs as current "
                              f"(unavailable={hs.get('unavailable')}, rows={len(hs.get('rows') or [])})")
            else:
                notes.append("heating-up: stale prior-season record -> unavailable, zero current runs")
            # fresh: current-season rows present -> board populates at the resolved season
            _write_props(tmp, _rows('Hot Guy', 'TB', 'Rec Yds', {1: OVER, 2: OVER, 3: OVER}, 2026))
            hs2 = app.build_nfl_prop_hot_start()
            if hs2.get('unavailable') or hs2.get('season') != 2026 or not hs2.get('rows'):
                issues.append(f"8: Heating Up did not populate from current-season data "
                              f"(season={hs2.get('season')}, rows={len(hs2.get('rows') or [])})")
            else:
                notes.append("heating-up: current-season data populates at the resolved season (2026)")
    finally:
        for name, val in saved.items():
            setattr(app, name, val)
        app._NFL_WAVE_CACHE.clear()
        app._NFL_RW_CACHE.clear()
    return {'issues': issues, 'notes': notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS NFL WAVE SEASON + INJURY QC (P0)")
    print("=" * 60)
    for note in report["notes"]:
        print(f"[NOTE] {note}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("No current-season/injury-safety issues detected.")
        return 0
    for msg in report["issues"]:
        print(f"[FAIL] {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
