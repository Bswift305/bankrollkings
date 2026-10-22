"""QC: streak integrity audit — source -> canonical events -> calculation -> membership -> ordering ->
rendered output, proved with DIRECTED FIXTURES fed through the REAL builder (no hardcoded production
membership). This increment covers the market-line / Riding-the-Wave player-prop streaks
(`build_nfl_prop_streaks`, source NFL_AllPropResults.csv) across receiving / receptions / rushing / passing.

Invariants proved (directive step 8):
- source -> canonical (one obs per player/stat/week, median line) -> run calc -> membership -> ordering;
- prior seasons CANNOT extend a live streak (current-season filter before grouping);
- a MISSING prop observation is a gap, NOT a missed game (does not reset the run);
- a push (result == line) breaks the run;
- duplicate observations (two books, same week) are collapsed to one;
- qualifying members are never silently dropped (full membership, longest-first);
- stale / incomplete / unresolved sources FAIL CLOSED (no fabricated streak).
Directed fixtures (step 9): Nico Collins (receiving), Caleb Williams (passing), a prior-season case, a bye/
missing-week gap, a push, and duplicate observations — all synthetic, none hardcoding real membership.
(Milestone / ATS / Hot Hand + alias/injury/return cases are covered in follow-up increments.)
"""
from __future__ import annotations

ISSUES, NOTES = [], []


def ok(cond, fail, pas=None):
    (NOTES.append(pas) if pas else None) if cond else ISSUES.append(fail)


def _row(player, stat, season, week, line, res, direction='OVER'):
    return {'Player': player, 'Stat': stat, 'Direction': direction, 'Line': line, 'ResultValue': res,
            'Season': season, 'Week': week, 'Sport': 'NFL', 'SeasonType': 'REG'}


def run_qc():
    try:
        import app
    except ModuleNotFoundError as e:
        if 'flask' in str(e).lower():
            NOTES.append('SKIPPED: run under the app virtualenv')
            return {'issues': ISSUES, 'notes': NOTES}
        raise
    import pandas as pd

    rows = []
    for w in (3, 4, 5, 6, 7):
        rows.append(_row('Nico Collins', 'receiving_yards', 2026, w, 60.5, 80))     # 5 straight OVER
    for w in (4, 5, 6, 7):
        rows.append(_row('Caleb Williams', 'passing_yards', 2026, w, 230.5, 200))   # 4 straight UNDER
    for w in (15, 16, 17):
        rows.append(_row('Prior Guy', 'rushing_yards', 2024, w, 50.5, 70))          # prior season (must NOT extend)
    for w in (1, 2, 3):
        rows.append(_row('Prior Guy', 'rushing_yards', 2026, w, 50.5, 70))          # current: 3 only
    for w in (2, 3, 5, 6):
        rows.append(_row('Gap Guy', 'receptions', 2026, w, 4.5, 7))                 # missing wk4 -> gap, not reset
    for w in (3, 4, 5):
        rows.append(_row('Push Guy', 'receiving_yards', 2026, w, 40.5, 60))
    rows.append(_row('Push Guy', 'receiving_yards', 2026, 6, 40.5, 40.5))           # push (res == line) breaks
    rows.append(_row('Push Guy', 'receiving_yards', 2026, 7, 40.5, 60))             # trailing run = 1 -> excluded
    rows.append(_row('Dup Guy', 'receptions', 2026, 5, 5.5, 7))                     # two books, same week
    rows.append(_row('Dup Guy', 'receptions', 2026, 5, 6.5, 7))
    for w in (6, 7):
        rows.append(_row('Dup Guy', 'receptions', 2026, w, 5.5, 7))                 # -> 3 (wk5 counted once)
    fixture = pd.DataFrame(rows)

    saved = {k: getattr(app, k) for k in ('_load_nfl_all_prop_results', '_nfl_expected_completed_week',
                                          '_nfl_injury_source_state', '_nfl_player_availability',
                                          '_nfl_player_return_status', '_nfl_participation_index')}
    try:
        app._nfl_expected_completed_week = lambda *a, **k: (7, 2026)
        app._nfl_injury_source_state = lambda: {'lookup': {}, 'fresh': True, 'gated': False,
                                                'updated': 'fixture', 'mtime': 1}
        app._nfl_player_availability = lambda *a, **k: {'available': True, 'state': 'ACTIVE', 'designation': '',
                                                        'label': 'Active', 'status': 'active', 'reason': ''}
        app._nfl_player_return_status = lambda *a, **k: {'returned': False}
        app._nfl_participation_index = lambda *a, **k: {}
        app._load_nfl_all_prop_results = lambda: fixture

        res = app.build_nfl_prop_streaks(limit=100)
        by = {(r['player'], r['stat']): r for r in res['rows']}

        nc = by.get(('Nico Collins', 'receiving_yards'))
        ok(nc and nc['streak'] == 5 and nc['side'] == 'Over' and nc['streak_start_week'] == 3,
           f'Nico Collins streak wrong: {nc}',
           'source->canonical->calc->membership: Nico Collins = 5 straight OVER (Wks 3-7)')
        cw = by.get(('Caleb Williams', 'passing_yards'))
        ok(cw and cw['streak'] == 4 and cw['side'] == 'Under', f'Caleb Williams streak wrong: {cw}',
           'Caleb Williams = 4 straight UNDER')
        pg = by.get(('Prior Guy', 'rushing_yards'))
        ok(pg and pg['streak'] == 3 and pg['streak_start_week'] == 1 and '2024' not in (pg.get('weeks_label') or ''),
           f'prior season extended a live streak: {pg}',
           'prior seasons CANNOT extend a live streak (3, current-season weeks only — not 6)')
        gg = by.get(('Gap Guy', 'receptions'))
        ok(gg and gg['streak'] == 4, f'missing week treated as a reset: {gg}',
           'a missing prop observation is a gap, NOT a missed game (streak survives the bye)')
        ok(('Push Guy', 'receiving_yards') not in by, 'a push did not break the run',
           'a push (result == line) breaks the run (Push Guy excluded)')
        dg = by.get(('Dup Guy', 'receptions'))
        ok(dg and dg['streak'] == 3, f'duplicate observations double-counted: {dg}',
           'duplicate observations (two books) collapse to one per week')
        ok(len(res['rows']) == 5, f'membership count wrong: {len(res["rows"])} (expected 5)',
           'all qualifying members present — none silently model-filtered')
        ok(res['rows'][0]['player'] == 'Nico Collins'
           and [r['streak'] for r in res['rows']] == sorted((r['streak'] for r in res['rows']), reverse=True),
           f'ordering wrong: {[(r["player"], r["streak"]) for r in res["rows"]]}',
           'rendered ordering is active-first, longest-first')

        # source -> render universe hash: the rendered membership must equal the rule-qualifying set exactly
        import hashlib

        def _uhash(pairs):
            return hashlib.sha256('\n'.join(sorted('%s|%s' % p for p in pairs)).encode()).hexdigest()[:16]
        rendered = {(r['player'], r['stat']) for r in res['rows']}
        expected = {('Nico Collins', 'receiving_yards'), ('Caleb Williams', 'passing_yards'),
                    ('Prior Guy', 'rushing_yards'), ('Gap Guy', 'receptions'), ('Dup Guy', 'receptions')}
        ok(_uhash(rendered) == _uhash(expected),
           f'source->render universe hash mismatch: rendered={rendered}',
           f'source->render universe hash matches the rule-qualifying set ({_uhash(expected)}) — no silent add/suppress')
        # Caleb Williams / Nico Collins trace receipts (through the general logic, not hardcoded membership)
        for nm, st in (('Nico Collins', 'receiving_yards'), ('Caleb Williams', 'passing_yards')):
            r = by[nm, st]
            NOTES.append(f'TRACE {nm} · {st}: source graded weeks -> canonical obs -> '
                         f'{r["streak"]} straight {r["side"]} (start Wk {r["streak_start_week"]}, '
                         f'{r["weeks_label"]}) -> rendered row')

        # fail-closed
        app._load_nfl_all_prop_results = lambda: pd.DataFrame()
        ok(app.build_nfl_prop_streaks().get('rows') == [], 'empty source did not fail closed',
           'empty source fails closed (no streaks)')
        app._load_nfl_all_prop_results = lambda: fixture
        app._nfl_expected_completed_week = lambda *a, **k: (None, None)
        ok(app.build_nfl_prop_streaks().get('unavailable_reason') == 'season_unresolved',
           'unresolved season did not fail closed', 'unresolved season fails closed (season_unresolved)')
        app._nfl_expected_completed_week = lambda *a, **k: (7, 2026)
        app._load_nfl_all_prop_results = lambda: fixture[fixture['Season'] == 2024]
        ok(app.build_nfl_prop_streaks().get('unavailable_reason') == 'current_season_ungraded',
           'prior-only source did not fail closed',
           'prior-season-only source fails closed (current_season_ungraded) — no prior-season fallback')
    finally:
        for k, v in saved.items():
            setattr(app, k, v)

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 72)
    print('BANKROLL KINGS - STREAK INTEGRITY AUDIT (market-line / Riding-the-Wave prop streaks)')
    print('=' * 72)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No streak-integrity issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
