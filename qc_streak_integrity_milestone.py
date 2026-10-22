"""QC: streak integrity audit — MILESTONE family (build_nfl_milestone_streaks, fixed-threshold game stats).

Directed fixtures through the REAL builder (no hardcoded prod membership) prove, for the milestone surface:
- authoritative source -> canonical _key (ALIAS MERGE: 'N.Collins' + 'Nico Collins' -> one key, longest
  display name) -> threshold run -> membership -> rendered;
- season boundary: the current-season (live) streak counts ONLY the resolved current season, never a prior
  season (a prior run cannot extend it);
- a BYE / missing game is a gap, not a reset (the run spans an absent week);
- the freshness gate: a run whose last game does NOT reach the latest graded week is NOT shown as current;
- fail closed when the source is empty or the season is unresolved.
Fixtures: Nico Collins (alias + bye), a season-boundary case, a stale (non-current) run. Synthetic only.
"""
from __future__ import annotations

ISSUES, NOTES = [], []


def ok(cond, fail, pas=None):
    (NOTES.append(pas) if pas else None) if cond else ISSUES.append(fail)


def _g(key, full, season, week, opp, team, recv):
    return {'_key': key, '_full': full, '__season': season, 'week': week,
            'opponent_team': opp, 'recent_team': team, 'receiving_yards': recv}


def run_qc():
    try:
        import app
    except ModuleNotFoundError as e:
        if 'flask' in str(e).lower():
            NOTES.append('SKIPPED: run under the app virtualenv')
            return {'issues': ISSUES, 'notes': NOTES}
        raise
    import pandas as pd

    rows = [_g('n.collins', 'N.Collins', 2026, 3, 'JAX', 'HOU', 110)]           # alias (short form)
    for i, w in enumerate((4, 5, 6, 7)):
        rows.append(_g('n.collins', 'Nico Collins', 2026, w, ('KC', 'IND', 'JAX', 'TEN')[i], 'HOU', 110))  # 100+ x5
    for w in (15, 16, 17):
        rows.append(_g('bound.guy', 'Bound Guy', 2025, w, 'X', 'DAL', 120))     # prior season (must NOT extend)
    for w in (5, 6, 7):
        rows.append(_g('bound.guy', 'Bound Guy', 2026, w, 'Y', 'DAL', 120))     # current: 3 only
    for w in (4, 5, 7):
        rows.append(_g('bye.guy', 'Bye Guy', 2026, w, 'Z', 'MIA', 105))         # bye wk6 -> gap, not reset
    for w in (3, 4, 5):
        rows.append(_g('stale.guy', 'Stale Guy', 2026, w, 'W', 'NYJ', 130))     # last game wk5 != cur_through 7
    df = pd.DataFrame(rows)

    keys = ('_nfl_player_week_data', '_nfl_expected_completed_week', '_nfl_injury_source_state',
            '_nfl_player_availability', '_nfl_player_return_status', '_nfl_participation_index',
            '_nfl_player_log_signature', '_nfl_player_log_sources', '_nfl_disk_cache_load',
            '_nfl_disk_cache_store')
    saved = {k: getattr(app, k) for k in keys}
    try:
        app._nfl_player_week_data = lambda *a, **k: df.copy()
        app._nfl_expected_completed_week = lambda *a, **k: (7, 2026)
        app._nfl_injury_source_state = lambda: {'lookup': {}, 'fresh': True, 'gated': False,
                                                'updated': 'fix', 'mtime': 1}
        app._nfl_player_availability = lambda *a, **k: {'available': True, 'state': 'ACTIVE', 'designation': '',
                                                        'label': 'Active', 'status': 'active', 'reason': ''}
        app._nfl_player_return_status = lambda *a, **k: {'returned': False}
        app._nfl_participation_index = lambda *a, **k: {}
        app._nfl_player_log_signature = lambda *a, **k: 'fix'
        app._nfl_player_log_sources = lambda *a, **k: []
        app._nfl_disk_cache_load = lambda *a, **k: None
        app._nfl_disk_cache_store = lambda *a, **k: None
        app._NFL_MILESTONE_CACHE.clear()

        res = app.build_nfl_milestone_streaks(min_run=3, limit=400)
        season = res.get('season_streaks') or []

        def find(key, thr):
            return next((r for r in season if r['key'] == key and r['stat'] == 'receiving_yards'
                         and r['threshold'] == thr), None)

        nc = find('n.collins', 100)
        ok(nc and nc['run'] == 5 and nc['player'] == 'Nico Collins',
           f'alias merge / run wrong: {nc}',
           "alias merge: 'N.Collins'+'Nico Collins' -> one key, longest name, run 5 at 100+")
        bg = find('bound.guy', 100)
        ok(bg and bg['run'] == 3 and all((gm.get('season') == 2026) for gm in (bg.get('games') or [])),
           f'prior season extended the live milestone streak: {bg}',
           'season boundary: current milestone streak = 3 (2026 only), prior season excluded')
        by = find('bye.guy', 100)
        ok(by and by['run'] == 3, f'bye reset the milestone run: {by}',
           'a bye / missing game is a gap, not a reset (run spans the absent week)')
        ok(find('stale.guy', 100) is None,
           'a non-current run (last game behind the latest week) was shown as current',
           'freshness gate: a run not reaching the latest graded week is NOT current')
        ok(res.get('available') and res.get('season_available'), 'availability flags wrong',
           'milestone build available + season_available on a valid current-season fixture')

        # fail-closed
        app._nfl_player_week_data = lambda *a, **k: pd.DataFrame()
        app._NFL_MILESTONE_CACHE.clear()
        ok(app.build_nfl_milestone_streaks().get('unavailable_reason') == 'no_game_stat_logs',
           'empty source did not fail closed', 'empty source fails closed (no_game_stat_logs)')
        app._nfl_player_week_data = lambda *a, **k: df.copy()
        app._nfl_expected_completed_week = lambda *a, **k: (None, None)
        app._NFL_MILESTONE_CACHE.clear()
        r2 = app.build_nfl_milestone_streaks()
        ok(not r2.get('season_available') and (r2.get('season_streaks') == []),
           'unresolved season still produced current milestone streaks',
           'unresolved season -> no current milestone streaks (season_available False)')
    finally:
        for k, v in saved.items():
            setattr(app, k, v)
        try:
            app._NFL_MILESTONE_CACHE.clear()
        except Exception:
            pass

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 72)
    print('BANKROLL KINGS - STREAK INTEGRITY AUDIT (milestone family)')
    print('=' * 72)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No milestone streak-integrity issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
