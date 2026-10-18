"""QC: NFL milestone streak product (build_nfl_milestone_streaks) + the membership firewall.

Proves the Nico-Collins integrity requirements:
  * the matchup milestone surfaces Nico's 5 straight 100+ receiving-yd games vs JAX;
  * identity: a short-form season ('N.Collins', _full) grouped by canonical key is NOT dropped;
  * MILESTONE is labeled distinctly and NEVER emits 'ATS'/'cover'/prop-line language;
  * the Streak Explainer carries every counted game;
  * membership FIREWALL: a factual qualifier cannot be hidden by a row limit or a sort, and the
    total qualifier count is exposed;
  * season-wide milestones FAIL CLOSED when the current season is absent/stale (matchup unaffected).

Driven by a controlled fixture (monkeypatched game-log loader) so it is fast + deterministic.
Exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import pandas as pd

import app

COLS = ['_key', '_full', '_name', '__season', 'week', 'opponent_team', 'recent_team',
        'receiving_yards', 'receptions', 'rushing_yards', 'passing_yards']


def _r(key, full, season, week, opp, ry=0, rec=0, rush=0, pas=0, team='HOU'):
    return {'_key': key, '_full': full, '_name': full, '__season': season, 'week': week,
            'opponent_team': opp, 'recent_team': team, 'receiving_yards': ry, 'receptions': rec,
            'rushing_yards': rush, 'passing_yards': pas}


def _fixture():
    rows = [
        # Nico vs JAX across seasons; 2025 rows carry the SHORT form in _full to prove the key
        # grouping unifies them (identity firewall).
        _r('n.collins', 'Nico Collins', 2021, 1, 'JAX', ry=7),
        _r('n.collins', 'Nico Collins', 2022, 5, 'JAX', ry=65),
        _r('n.collins', 'Nico Collins', 2023, 12, 'JAX', ry=104),
        _r('n.collins', 'Nico Collins', 2024, 4, 'JAX', ry=151),
        _r('n.collins', 'Nico Collins', 2024, 13, 'JAX', ry=119),
        _r('n.collins', 'N.Collins', 2025, 3, 'JAX', ry=104),    # short form, must still count
        _r('n.collins', 'N.Collins', 2025, 10, 'JAX', ry=136),   # short form, must still count
        # a filler player so the board isn't a single row
        _r('f.filler', 'Filler Guy', 2024, 1, 'JAX', ry=120),
        _r('f.filler', 'Filler Guy', 2024, 2, 'JAX', ry=130),
        _r('f.filler', 'Filler Guy', 2024, 3, 'JAX', ry=140),
    ]
    return pd.DataFrame(rows, columns=COLS)


def run_qc() -> dict:
    issues: list[str] = []
    notes: list[str] = []
    saved = {k: getattr(app, k) for k in ('_nfl_player_week_data', '_nfl_expected_completed_week',
                                          '_nfl_injury_source_state', '_nfl_player_log_sources')}
    try:
        app._nfl_player_week_data = lambda: _fixture()
        app._nfl_expected_completed_week = lambda today=None: (6, 2026)  # current season, no 2026 rows
        app._nfl_injury_source_state = lambda: {'lookup': {}, 'updated': '', 'mtime': 1.0,
                                                'fresh': True, 'gated': False}
        app._nfl_player_log_sources = lambda: []
        ms = app.build_nfl_milestone_streaks(min_run=3)

        # 1: Nico vs JAX 100+ = 5 (across both name forms)
        nico = [r for r in ms['matchup_streaks'] if r['key'] == 'n.collins'
                and r['opponent'] == 'JAX' and r['stat'] == 'receiving_yards' and r['threshold'] == 100]
        if not nico:
            issues.append("1: Nico's 100+ vs-JAX matchup milestone is ABSENT (the integrity failure)")
        elif nico[0]['run'] != 5:
            issues.append(f"1: Nico vs-JAX 100+ run = {nico[0]['run']} (want 5; short-form drop under-counts)")
        elif len(nico[0]['games']) != 5:
            issues.append(f"1: Streak Explainer has {len(nico[0]['games'])} games (want 5)")
        else:
            notes.append("matchup: Nico 100+ vs JAX = 5 (both name forms counted), explainer has 5 games")

        # 2: MILESTONE labeled distinctly; NEVER market-line/cover/ATS language
        blob = repr(ms).lower()
        for banned in ('ats', 'cover', 'prop-line', 'vigorish', 'juice'):
            if banned in blob:
                issues.append(f"2: milestone output contains market-line token '{banned}'")
        if nico and nico[0].get('kind') != 'matchup':
            issues.append("2: matchup milestone not labeled kind='matchup'")

        # 3: FIREWALL -- a qualifier cannot be hidden by a row limit; total count exposed
        ms_small = app.build_nfl_milestone_streaks(min_run=3, limit=1)
        total = ms_small['total_matchup']
        shown_keys = {(r['key'], r['opponent'], r['threshold']) for r in ms_small['matchup_streaks']}
        if total < 2:
            issues.append(f"3: total_matchup={total} (fixture has >=2 qualifiers; count not exposed)")
        # the total reflects ALL qualifiers even when the visible list is capped
        full = app.build_nfl_milestone_streaks(min_run=3, limit=400)
        if full['total_matchup'] != total:
            issues.append("3: total_matchup changed with the display limit (count must be limit-independent)")
        if not any(r['key'] == 'n.collins' for r in full['matchup_streaks']):
            issues.append("3: Nico missing from the full (unlimited) qualifier list")
        if not any(m.startswith('3:') for m in issues):
            notes.append(f"firewall: {total} total qualifiers exposed independent of display limit; Nico always present")

        # 4: season-wide FAILS CLOSED when current season absent (fixture has no 2026 rows)
        if ms['season_available'] or ms['season_streaks']:
            issues.append("4: season-wide milestones not failed closed with no current-season data")
        else:
            notes.append("fail-closed: no current-season game stats -> season-wide withheld; matchup unaffected")

        # 5: season-wide WORKS when current-season data present + reaches the latest week
        def _fix2():
            base = _fixture()
            extra = pd.DataFrame([
                _r('c.lamb', 'CeeDee Lamb', 2026, 4, 'NYG', ry=110),
                _r('c.lamb', 'CeeDee Lamb', 2026, 5, 'PHI', ry=105),
                _r('c.lamb', 'CeeDee Lamb', 2026, 6, 'WAS', ry=130),
            ], columns=COLS)
            return pd.concat([base, extra], ignore_index=True)
        app._nfl_player_week_data = _fix2
        app._NFL_MILESTONE_CACHE.clear()  # the fixture swap bypasses the signature; force a rebuild
        ms2 = app.build_nfl_milestone_streaks(min_run=3)
        lamb = [r for r in ms2['season_streaks'] if r['key'] == 'c.lamb'
                and r['stat'] == 'receiving_yards' and r['threshold'] == 100]
        if not ms2['season_available']:
            issues.append("5: season-wide marked unavailable despite current-season data through the latest week")
        elif not lamb or lamb[0]['run'] != 3:
            issues.append(f"5: expected CeeDee Lamb season-wide 100+ run of 3, got {lamb and lamb[0]['run']}")
        else:
            notes.append("season-wide: current-season 100+ streak surfaces (CeeDee Lamb x3) with explainer")
    finally:
        for k, v in saved.items():
            setattr(app, k, v)
        if hasattr(app, '_NFL_MILESTONE_CACHE'):
            app._NFL_MILESTONE_CACHE.clear()
    return {'issues': issues, 'notes': notes}


def main() -> int:
    report = run_qc()
    print('=' * 60)
    print('BANKROLL KINGS NFL MILESTONE STREAK QC')
    print('=' * 60)
    for note in report['notes']:
        print(f'[NOTE] {note}')
    if report['notes']:
        print()
    if not report['issues']:
        print('No milestone-streak issues detected.')
        return 0
    for msg in report['issues']:
        print(f'[FAIL] {msg}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
