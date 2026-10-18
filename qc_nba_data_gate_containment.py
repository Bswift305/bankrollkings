"""QC: NBA.com data-rights gate containment for injury-derived + boost data (docs/legal_register_v2.md).

The NBA.com Game-log / Injuries / tracking datasets are Prohibited Until Cleared. Their live loaders
(load_gamelogs, load_player_snapshot, ...) are already service-gated, but the PRE-BUILT injury/boost CSVs
(NBA_Injuries, Teammate_Boosts, Active_Boost_Plays, WNBA_Injuries) bypassed that gate and leaked on the
authenticated Injuries page. This QC proves the service-boundary gate at the LOADER level with POPULATED
fixtures (not just empty states): when BK_NBA_STATS_ENABLED is off, NO restricted NBA/WNBA value reaches
any consumer; when on, values are restored (technical test only); and NFL/MLB are unaffected in BOTH
states. Controlled fixtures in a temp tree; exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

import app
from services import nba_source_gate

# Distinctive restricted tokens that must NEVER appear anywhere in gated output.
NBA_PLAYER = 'Gui Santos'
WNBA_PLAYER = 'Angel Reese'
RESTRICTED_VALUES = ('305.5', '13.3', '3.3')   # boost pct + boosted/normal averages
NFL_PLAYER = 'Dak Testerson'                    # must REMAIN visible (NFL unaffected)


def _write_fixtures(tmp: Path):
    inj = tmp / 'injuries'
    inj.mkdir(parents=True, exist_ok=True)
    (tmp / 'gamelogs').mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{'Player': NBA_PLAYER, 'Team': 'GSW', 'Status': 'OUT', 'Reason': 'knee',
                   'Updated': '2026-10-16'}]).to_csv(inj / 'NBA_Injuries.csv', index=False)
    pd.DataFrame([{'Player': WNBA_PLAYER, 'Team': 'ATL', 'Status': 'OUT', 'Reason': 'ankle',
                   'Updated': '2026-10-16'}]).to_csv(inj / 'WNBA_Injuries.csv', index=False)
    pd.DataFrame([{'Player': NFL_PLAYER, 'Team': 'DAL', 'Status': 'OUT', 'Reason': 'hamstring',
                   'Updated': '2026-10-16'}]).to_csv(inj / 'NFL_Injuries.csv', index=False)
    boost = {'Beneficiary': NBA_PLAYER, 'Team': 'GSW', 'Stat': 'PTS', 'Key_Player_Out': 'Jimmy Butler',
             'Boost_Pct': 305.5, 'Avg_With': 3.3, 'Avg_Without': 13.3}
    pd.DataFrame([boost]).to_csv(inj / 'Teammate_Boosts.csv', index=False)
    pd.DataFrame([{**boost, 'Injury_Status': 'OUT', 'Injury_Reason': 'knee'}]).to_csv(
        inj / 'Active_Boost_Plays.csv', index=False)


def _set_gate(on: bool):
    os.environ['BK_NBA_STATS_ENABLED'] = '1' if on else '0'
    # Loaders gate on each call (env read live); clear the mtime cache so ON re-reads the temp files.
    try:
        app.DATAFRAME_CACHE.clear()
    except Exception:
        pass


def _blob(*frames_or_objs):
    """Serialize loader/context outputs to one string for token scanning."""
    parts = []
    for o in frames_or_objs:
        if isinstance(o, pd.DataFrame):
            parts.append(o.to_csv(index=False))
        else:
            parts.append(repr(o))
    return '\n'.join(parts)


def _gather(tmp: Path):
    """All injury/boost loader + context outputs a consumer could see."""
    inj_ctx = app.build_injury_report_context()
    return {
        'load_injuries': app.load_injuries(),
        'load_boosts': app.load_boosts(),
        'load_active_boosts': app.load_active_boosts(),
        'sport_nba': app.load_sport_injuries('nba'),
        'sport_wnba': app.load_sport_injuries('wnba'),
        'sport_nfl': app.load_sport_injuries('nfl'),
        'injury_report_ctx': inj_ctx,
    }


def run():
    issues = []
    tmp = Path(tempfile.mkdtemp(prefix='bk_nba_gate_'))
    _write_fixtures(tmp)
    saved_dir = app.DATA_DIR
    saved_env = os.environ.get('BK_NBA_STATS_ENABLED')
    app.DATA_DIR = tmp
    try:
        # ---- GATE OFF: no restricted value anywhere ----
        _set_gate(False)
        if nba_source_gate.nba_stats_enabled():
            issues.append('gate did not read OFF')
        g = _gather(tmp)
        for name in ('load_injuries', 'load_boosts', 'load_active_boosts', 'sport_nba', 'sport_wnba'):
            if not g[name].empty:
                issues.append(f'OFF: {name} returned {len(g[name])} rows (must be empty)')
        off_blob = _blob(*g.values())
        for tok in (NBA_PLAYER, WNBA_PLAYER, *RESTRICTED_VALUES):
            if tok in off_blob:
                issues.append(f'OFF: restricted token {tok!r} leaked into output')
        ctx = g['injury_report_ctx']
        if any(r['league'] in ('nba', 'wnba') for r in ctx.get('rows', [])):
            issues.append('OFF: injury-report context still lists NBA/WNBA rows')
        if any(r.get('boosts') for r in ctx.get('rows', [])):
            issues.append('OFF: injury-report context still carries boost values')
        if not ctx.get('nba_stats_gated'):
            issues.append('OFF: injury-report context missing nba_stats_gated=True')
        # NFL must REMAIN in both states
        if g['sport_nfl'].empty or NFL_PLAYER not in _blob(g['sport_nfl']):
            issues.append('OFF: NFL injuries were suppressed (must be unaffected)')

        # ---- GATE ON: restricted values restored (technical test only) ----
        _set_gate(True)
        if not nba_source_gate.nba_stats_enabled():
            issues.append('gate did not read ON')
        g2 = _gather(tmp)
        if g2['load_injuries'].empty or NBA_PLAYER not in _blob(g2['load_injuries']):
            issues.append('ON: load_injuries did not restore NBA data')
        if g2['load_boosts'].empty or '305.5' not in _blob(g2['load_boosts']):
            issues.append('ON: load_boosts did not restore boost values')
        if g2['sport_wnba'].empty or WNBA_PLAYER not in _blob(g2['sport_wnba']):
            issues.append('ON: load_sport_injuries(wnba) did not restore WNBA data')
        if g2['sport_nfl'].empty or NFL_PLAYER not in _blob(g2['sport_nfl']):
            issues.append('ON: NFL injuries missing (must be unaffected)')
        if g2['injury_report_ctx'].get('nba_stats_gated'):
            issues.append('ON: injury-report context still reports nba_stats_gated=True')
    finally:
        app.DATA_DIR = saved_dir
        if saved_env is None:
            os.environ.pop('BK_NBA_STATS_ENABLED', None)
        else:
            os.environ['BK_NBA_STATS_ENABLED'] = saved_env
        try:
            app.DATAFRAME_CACHE.clear()
        except Exception:
            pass
    return issues


def check_fantasy_projection_gate():
    """Service boundary: get_fantasy_projection_rows must NOT run the NBA.com-reading builder
    (_build_fantasy_projection_rows reads NBA_GameLogs + NBA_PlayerTracking/Advanced directly) while the
    gate is off; NFL is unaffected. Caching is bypassed so the signal is deterministic."""
    issues = []
    orig_build = app._build_fantasy_projection_rows
    orig_cache = app._get_disk_ttl_cached_value
    calls = []
    app._build_fantasy_projection_rows = lambda sport_key, scoring=None: (calls.append(sport_key) or [])
    app._get_disk_ttl_cached_value = lambda key, ttl, fn, version=None: fn()
    saved_env = os.environ.get('BK_NBA_STATS_ENABLED')
    try:
        os.environ['BK_NBA_STATS_ENABLED'] = '0'
        calls.clear()
        if app.get_fantasy_projection_rows('nba') != [] or app.get_fantasy_projection_rows('wnba') != []:
            issues.append('OFF: fantasy nba/wnba did not return [] (gated)')
        if 'nba' in calls or 'wnba' in calls:
            issues.append('OFF: NBA/WNBA fantasy builder ran (would read NBA.com files directly)')
        calls.clear()
        app.get_fantasy_projection_rows('nfl')
        if 'nfl' not in calls:
            issues.append('OFF: NFL fantasy builder did not run (must be unaffected)')
        os.environ['BK_NBA_STATS_ENABLED'] = '1'
        calls.clear()
        app.get_fantasy_projection_rows('nba')
        if 'nba' not in calls:
            issues.append('ON: NBA fantasy builder did not run (gate stuck on)')
    finally:
        app._build_fantasy_projection_rows = orig_build
        app._get_disk_ttl_cached_value = orig_cache
        if saved_env is None:
            os.environ.pop('BK_NBA_STATS_ENABLED', None)
        else:
            os.environ['BK_NBA_STATS_ENABLED'] = saved_env
    return issues


def check_no_ungated_tracking_claim():
    """Repo-wide: every "Tracking is live" claim in a template must sit behind a nba_stats_gated guard,
    so no surface claims NBA.com tracking is live while the gate is off. Auto-covers future matches."""
    import glob
    issues = []
    for path in sorted(glob.glob('templates/*.html')):
        try:
            lines = open(path, encoding='utf-8').read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            if 'Tracking is live' in line:
                window = '\n'.join(lines[max(0, i - 8):i + 1])
                if 'nba_stats_gated' not in window:
                    issues.append(f'{path}:{i + 1} "Tracking is live" is NOT guarded by nba_stats_gated')
    return issues


def main():
    print('=' * 60)
    print('NBA.com DATA-RIGHTS GATE CONTAINMENT QC (injury/boost/fantasy)')
    print('=' * 60)
    issues = run()
    issues += check_fantasy_projection_gate()
    issues += check_no_ungated_tracking_claim()
    if issues:
        for i in issues:
            print(f'[FAIL] {i}')
        print('-' * 60)
        print(f'{len(issues)} containment check(s) FAILED.')
        return 1
    print('[PASS] OFF exposes no restricted NBA/WNBA injury+boost values (populated fixtures)')
    print('[PASS] ON restores them (technical test); NFL unaffected in both states')
    print('[PASS] fantasy builder never runs for NBA/WNBA while gated; NFL unaffected')
    print('[PASS] no "Tracking is live" claim is ungated in any template')
    print('-' * 60)
    print('NBA data-rights gate containment verified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
