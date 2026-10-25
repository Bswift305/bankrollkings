"""QC: NFL Hot Hand Heat Map never presents a stale streak as current.

Regression guard for the NFL Heat-Map Freshness Correction. The heat map walks each player's
real game logs newest-first and shows who has a run intact. Three freshness defects this locks
down, all of which made last week's runs read as "hot right now":

  1. Cache keyed to NFL_Props.csv mtime ALONE -- a fresh week of game logs (new parquet) was
     ignored for the whole TTL, so the board served pre-result streaks. The cache key now folds
     in the player-log signature (+ injury mtime + ET date).
  2. "Active" meant only "most recent LOADED game is current season" -- it never checked the
     week. A player who played Weeks 1-3 then went to IR, or simply hasn't appeared in the
     latest loaded week, kept showing as a current streak. Now gated on availability AND the
     player keeping pace with the log's own through-week; otherwise preserved as HISTORICAL.
  3. No freshness gate -- when the calendar says a completed week should be loaded but isn't,
     the whole board must say "pending" and stop claiming the runs are current.

The headline fixture is Mike Evans: with logs through Week 4 his over run is active; once Week 5
loads with a result that breaks it (and the player-log signature changes), the cache invalidates
and he is no longer presented as an active streak. Exits 0 when the board behaves correctly,
1 otherwise (so run_all_scorecards flags a regression).
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

import app


LINE = 49.5          # the Rec Yds line all three fixture players are measured against
CUR = 2026           # fixture season


def _subframe(team: str, week_values: dict[int, float]) -> pd.DataFrame:
    """One player's game log: {week: receiving_yards}. season=CUR."""
    return pd.DataFrame([
        {'season': CUR, 'week': wk, 'team': team, 'receiving_yards': val,
         'position': 'WR', 'targets': 8}
        for wk, val in sorted(week_values.items())
    ])


def _install_fixture(tmp: Path, logs: dict[str, pd.DataFrame], injuries: list[dict]):
    """Point the builder at a controlled props file, injury file, and player log."""
    (tmp / 'props').mkdir(parents=True, exist_ok=True)
    (tmp / 'injuries').mkdir(parents=True, exist_ok=True)

    props = pd.DataFrame([
        {'Player': name, 'Stat': 'Rec Yds', 'Line': LINE,
         'Game': 'Arizona Cardinals @ Seattle Seahawks', 'OverOdds': -110}
        for name in logs
    ])
    props.to_csv(tmp / 'props' / 'NFL_Props.csv', index=False)

    inj = pd.DataFrame(injuries or [], columns=['Player', 'Team', 'Status', 'Reason', 'Updated'])
    inj.to_csv(tmp / 'injuries' / 'NFL_Injuries.csv', index=False)

    idx = {name.strip().lower(): df for name, df in logs.items()}
    log = pd.concat(list(logs.values()), ignore_index=True) if logs else pd.DataFrame()

    app.DATA_DIR = tmp
    app._nfl_player_week_data = lambda: log
    app._nfl_player_index = lambda: idx
    app._NFL_HOTHAND_CACHE.clear()


def _row(board: dict, player: str):
    for r in board.get('streaks', []):
        if r['player'] == player:
            return r
    return None


def run_qc() -> dict:
    issues: list[str] = []
    notes: list[str] = []

    # Snapshot everything we monkeypatch so the module is left clean for later scorecards.
    saved = {
        'DATA_DIR': app.DATA_DIR,
        '_nfl_player_week_data': app._nfl_player_week_data,
        '_nfl_player_index': app._nfl_player_index,
        '_nfl_player_log_signature': app._nfl_player_log_signature,
        '_nfl_expected_completed_week': app._nfl_expected_completed_week,
    }

    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            # Evans: clears every week 1-4 (active run). Lagging Back: cleared weeks 1-2 then
            # stopped appearing (last loaded game Week 2). Hurt Guy: cleared weeks 1-4 but is OUT.
            logs_wk4 = {
                'Mike Evans':   _subframe('TB',  {1: 62, 2: 71, 3: 58, 4: 80}),
                'Lagging Back': _subframe('ARI', {1: 55, 2: 60}),
                'Hurt Guy':     _subframe('SEA', {1: 66, 2: 70, 3: 64, 4: 77}),
            }
            injuries = [{'Player': 'Hurt Guy', 'Team': 'SEA', 'Status': 'OUT',
                         'Reason': 'Hamstring', 'Updated': '2026-10-10'}]

            # ---- Scenario A: feed current (through Wk 4, expected Wk 4) --------------------
            _install_fixture(tmp, logs_wk4, injuries)
            app._nfl_player_log_signature = lambda: (('__qc_wk4__', 1, 1),)
            app._nfl_expected_completed_week = lambda today=None: (4, CUR)
            board_a = app.build_nfl_hot_hand(min_streak=2)

            if board_a.get('pending_latest'):
                issues.append("A: board flagged pending when through_week == expected_week")
            if board_a.get('through_week') != 4:
                issues.append(f"A: through_week={board_a.get('through_week')} (want 4)")
            if 'Results through Week 4' not in (board_a.get('through_label') or ''):
                issues.append(f"A: through_label missing 'Results through Week 4': "
                              f"{board_a.get('through_label')!r}")

            ev = _row(board_a, 'Mike Evans')
            if ev is None:
                issues.append("A: Mike Evans missing from an active-through-Wk4 board")
            else:
                if not ev['active']:
                    issues.append("A: Evans not marked active with a clean current run")
                if ev['streak'] != 4:
                    issues.append(f"A: Evans streak={ev['streak']} (want 4)")
                if ev['weeks_label'] != 'Appearances: Wks 1–4':
                    issues.append(f"A: Evans weeks_label={ev['weeks_label']!r} (want 'Appearances: Wks 1–4')")

            lag = _row(board_a, 'Lagging Back')
            if lag is None:
                issues.append("A: Lagging Back dropped (should persist as historical)")
            else:
                if lag['active']:
                    issues.append("A: a player behind the through-week shown as active")
                if lag['weeks_behind'] != 2:
                    issues.append(f"A: Lagging Back weeks_behind={lag['weeks_behind']} (want 2)")
                if 'Historical' not in lag['status_label']:
                    issues.append(f"A: Lagging Back status not historical: {lag['status_label']!r}")

            hurt = _row(board_a, 'Hurt Guy')
            if hurt is None:
                issues.append("A: Hurt Guy dropped (should persist as a paused run)")
            else:
                if hurt['active']:
                    issues.append("A: an OUT player shown as an active streak")
                if hurt['availability_status'] != 'OUT':
                    issues.append(f"A: Hurt Guy availability={hurt['availability_status']!r} (want OUT)")
                if hurt.get('availability_state') != 'PAUSED':
                    issues.append(f"A: Hurt Guy state={hurt.get('availability_state')!r} (want PAUSED)")
                if 'before absence' not in hurt['status_label']:
                    issues.append(f"A: Hurt Guy paused run not labeled 'before absence': {hurt['status_label']!r}")

            # Active runs must lead; no stale row may sit above an active one.
            seen_stale = False
            for r in board_a.get('streaks', []):
                if not r['active']:
                    seen_stale = True
                elif seen_stale:
                    issues.append("A: an active streak ranked below a stale one")
                    break

            sig_after_a = app._NFL_HOTHAND_CACHE.get('sig')

            # ---- Scenario B (fix 8 + fix 1): Week 5 loads and BREAKS Evans' run -----------
            # Evans goes UNDER in Week 5; the player-log signature changes (as a real parquet
            # refresh would). The cache MUST invalidate and Evans must no longer be an active
            # streak -- yesterday's result ended the run.
            logs_wk5 = {k: v.copy() for k, v in logs_wk4.items()}
            logs_wk5['Mike Evans'] = _subframe('TB', {1: 62, 2: 71, 3: 58, 4: 80, 5: 20})
            _install_fixture(tmp, logs_wk5, injuries)   # clears _NFL_HOTHAND_CACHE
            # Re-warm with the OLD signature/expected, then flip ONLY the signature to prove the
            # key depends on it (fix 1): the stored sig must change and the board must rebuild.
            app._nfl_player_log_signature = lambda: (('__qc_wk4__', 1, 1),)
            app._nfl_expected_completed_week = lambda today=None: (4, CUR)
            _warm = app.build_nfl_hot_hand(min_streak=2)
            sig_warm = app._NFL_HOTHAND_CACHE.get('sig')
            app._nfl_player_log_signature = lambda: (('__qc_wk5__', 2, 2),)
            app._nfl_expected_completed_week = lambda today=None: (5, CUR)
            board_b = app.build_nfl_hot_hand(min_streak=2)
            sig_after_b = app._NFL_HOTHAND_CACHE.get('sig')

            if sig_after_b == sig_warm:
                issues.append("B: cache did not invalidate when the player-log signature changed (fix 1)")
            if board_b.get('through_week') != 5:
                issues.append(f"B: through_week={board_b.get('through_week')} (want 5 once Wk5 loaded)")

            ev_b = _row(board_b, 'Mike Evans')
            if ev_b is not None and ev_b['active']:
                issues.append("B: Evans STILL active after a Week-5 result broke the run (fix 8)")
            if ev_b is not None and ev_b['streak'] >= 2:
                issues.append(f"B: Evans run not reset by the Week-5 miss (streak={ev_b['streak']})")
            if ev_b is None:
                notes.append("fix 8: Week-5 miss removed Evans from the hot-hand board entirely")
            else:
                notes.append(f"fix 8: Evans no longer active after Week 5 (streak={ev_b['streak']})")

            # ---- Scenario C (fix 7): a completed week is missing -> pending, nothing current -
            _install_fixture(tmp, logs_wk4, injuries)
            app._nfl_player_log_signature = lambda: (('__qc_pending__', 3, 3),)
            app._nfl_expected_completed_week = lambda today=None: (5, CUR)  # expect Wk5, have Wk4
            board_c = app.build_nfl_hot_hand(min_streak=2)

            if not board_c.get('pending_latest'):
                issues.append("C: expected pending_latest when a completed week is missing (fix 7)")
            if 'pending' not in (board_c.get('through_label') or '').lower():
                issues.append(f"C: through_label doesn't surface pending: {board_c.get('through_label')!r}")
            if any(r['active'] for r in board_c.get('streaks', [])):
                issues.append("C: a streak shown as active while latest results are pending")
            else:
                notes.append("fix 7: no streak presented as current while a completed week is missing")

            # ---- Calendar math the gate + the fetcher retry both rely on ------------------
            # 2026 Week-1 Thursday is Sep 10; a week is 'complete' only after its Tuesday.
            # Call the real helper via the saved reference, since we patched the name.
            real_week = saved['_nfl_expected_completed_week']
            wk_mon = real_week(datetime(2026, 10, 12).date())[0]   # Mon of Wk5 -> Wk4 complete
            wk_tue = real_week(datetime(2026, 10, 13).date())[0]   # Tue after -> Wk5 complete
            if wk_mon != 4:
                issues.append(f"calendar: Mon 2026-10-12 completed week={wk_mon} (want 4)")
            if wk_tue != 5:
                issues.append(f"calendar: Tue 2026-10-13 completed week={wk_tue} (want 5)")
            if not issues:
                notes.append("calendar: completed-week boundary lands on Tuesday as intended")

    finally:
        for name, val in saved.items():
            setattr(app, name, val)
        app._NFL_HOTHAND_CACHE.clear()
        app._NFL_PLAYER_WEEK_CACHE.clear()
        app._NFL_PLAYER_IDX_CACHE.clear()

    return {'issues': issues, 'notes': notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS NFL HEAT-MAP FRESHNESS QC")
    print("=" * 60)
    for note in report["notes"]:
        print(f"[NOTE] {note}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("No heat-map freshness issues detected.")
        return 0
    for msg in report["issues"]:
        print(f"[FAIL] {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
