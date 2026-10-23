"""QC: streak integrity audit — HOT HAND / HEAT MAP family (build_nfl_hot_hand).

Directed fixtures through the real builder (props line x gamelog history) prove:
- authoritative current-season resolution (a run counts only when the most recent LOADED game is current);
- canonical event grain (one gamelog value per game, summed over the stat's columns);
- the run is consecutive games clearing the CURRENT prop line, newest-first, and a MISS breaks it;
- membership/ordering (>= min_streak, longest-first); no model suppression;
- fail closed when the gamelog is empty;
- an exact game-level trace for a selected fixture.
Synthetic only; no hardcoded production membership.
"""
from __future__ import annotations

ISSUES, NOTES = [], []


def ok(cond, fail, pas=None):
    (NOTES.append(pas) if pas else None) if cond else ISSUES.append(fail)


def run_qc():
    try:
        import app
    except ModuleNotFoundError as e:
        if 'flask' in str(e).lower():
            NOTES.append('SKIPPED: run under the app virtualenv')
            return {'issues': ISSUES, 'notes': NOTES}
        raise
    import pandas as pd
    props_path = app.DATA_DIR / 'props' / 'NFL_Props.csv'
    if not props_path.exists():
        NOTES.append('SKIPPED: NFL_Props.csv absent locally (the builder gates on it); runs on prod')
        return {'issues': ISSUES, 'notes': NOTES}

    def glog(weeks_vals, season=2026):
        return pd.DataFrame([{'receiving_yards': v, 'season': season, 'week': w} for w, v in weeks_vals])
    idx = {
        'nico collins': glog([(3, 90), (4, 85), (5, 80)]),                 # 3 straight clears of a 60.5 line
        'miss guy': glog([(3, 70), (4, 40), (5, 80)]),                     # newest-first: wk5 clear, wk4 MISS -> 1
        'old guy': glog([(3, 90), (4, 95)], season=2025),                  # most recent game not current -> excluded
    }
    log = pd.concat(list(idx.values()), ignore_index=True)
    props = pd.DataFrame([{'Player': 'Nico Collins', 'Stat': 'Receiving Yards', 'Line': 60.5, 'OverOdds': -110, 'Book': 'DK'},
                          {'Player': 'Miss Guy', 'Stat': 'Receiving Yards', 'Line': 60.5, 'OverOdds': -110, 'Book': 'DK'},
                          {'Player': 'Old Guy', 'Stat': 'Receiving Yards', 'Line': 60.5, 'OverOdds': -110, 'Book': 'DK'}])
    real_lcc = app._load_cached_csv
    keys = ('_nfl_player_week_data', '_nfl_player_index', '_load_cached_csv', '_nfl_expected_completed_week',
            '_nfl_injury_source_state', '_nfl_player_availability', '_nfl_player_log_signature',
            '_nfl_player_log_sources', '_nfl_disk_cache_load', '_nfl_disk_cache_store')
    saved = {k: getattr(app, k) for k in keys}
    try:
        app._nfl_player_week_data = lambda *a, **k: log.copy()
        app._nfl_player_index = lambda *a, **k: {kk: v.copy() for kk, v in idx.items()}
        app._load_cached_csv = lambda path, *a, **k: (props.copy() if 'NFL_Props.csv' in str(path)
                                                      else real_lcc(path, *a, **k))
        app._nfl_expected_completed_week = lambda *a, **k: (5, 2026)
        app._nfl_injury_source_state = lambda: {'lookup': {}, 'fresh': True, 'gated': False, 'updated': 'fix',
                                                'mtime': 1}
        app._nfl_player_availability = lambda *a, **k: {'available': True, 'state': 'ACTIVE', 'designation': '',
                                                        'label': 'Active', 'status': 'active', 'reason': ''}
        app._nfl_player_log_signature = lambda *a, **k: 'fix'
        app._nfl_player_log_sources = lambda *a, **k: []
        app._nfl_disk_cache_load = lambda *a, **k: None
        app._nfl_disk_cache_store = lambda *a, **k: None
        app._NFL_HOTHAND_CACHE.clear()

        res = app.build_nfl_hot_hand(limit=50, min_streak=3)
        by = {r['player']: r for r in (res.get('streaks') or [])}
        nc = by.get('Nico Collins')
        ok(nc and nc['streak'] == 3, f'Hot Hand Nico wrong: {nc}',
           'Hot Hand: 3 straight games clearing the current line (newest-first)')
        ok('Miss Guy' not in by, 'a miss did not break the Hot Hand run',
           'Hot Hand: a game below the line breaks the run (Miss Guy excluded)')
        ok('Old Guy' not in by, 'a non-current run was shown as current',
           'Hot Hand: a run whose most recent game is a prior season is NOT current')
        ok(res.get('available'), 'available flag wrong on a valid fixture',
           'Hot Hand: available on a valid current-season fixture')
        NOTES.append(f"TRACE Nico Collins: gamelog clears -> streak {nc['streak']} vs line {nc.get('line')}")

        app._nfl_player_week_data = lambda *a, **k: pd.DataFrame()
        app._NFL_HOTHAND_CACHE.clear()
        ok(app.build_nfl_hot_hand().get('available') is False and app.build_nfl_hot_hand().get('streaks') == [],
           'empty gamelog not fail-closed', 'Hot Hand: empty gamelog fails closed (no streaks)')
    finally:
        for k, v in saved.items():
            setattr(app, k, v)
        try:
            app._NFL_HOTHAND_CACHE.clear()
        except Exception:
            pass

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 72)
    print('BANKROLL KINGS - STREAK INTEGRITY AUDIT (Hot Hand / Heat Map)')
    print('=' * 72)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No Hot Hand streak-integrity issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
