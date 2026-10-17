"""QC: CFB Active ATS Wave admission + GAME-ID reconciliation (docs/ats_wave_contract.md +
docs/cfb_runtime_data_corrective.md).

Authoritative identity is (GameID, TeamSide) with FBS decided by provider conference -- never normalized
names (prod cff._resolve is data-dependent and merges distinct teams). Proves the directive's required
behavior with controlled fixtures. Exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import pandas as pd

import app
import cfb_current_form as cff


def grow(gid, side, team, opp, state, wk, date, conf='SEC', line=-3.5):
    return {'Sport': 'NCAAF', 'Season': 2026, 'GameID': gid, 'TeamSide': side, 'Team': team,
            'Opponent': opp, 'Conf': conf, 'Week': wk, 'GameDate': date, 'MarketType': 'SPREAD',
            'OutcomeState': state, 'Line': line}


def mgame(gid, home, away, wk, home_conf='SEC', away_conf='SEC', spread_now=-3.5, completed=True):
    return {'game_id': gid, 'home': home, 'away': away, 'week': wk, 'home_conf': home_conf,
            'away_conf': away_conf, 'spread_now': spread_now, 'completed': completed}


def _lm(games, season=2026, updated='2026-10-17 01:00 UTC'):
    return {'season': season, 'updated': updated, 'games': games}


def _streaks(rows):
    return app._cfb_cover_streaks_from_df(pd.DataFrame(rows), 2026)


def qc_streak_truth_table():
    """Push interrupts a strict cover streak, a loss resets it; grouping is by exact team name across
    games (each its own GameID), ordered by GameDate."""
    issues = []
    cases = {  # team -> (states oldest->newest, expected cover_streak)
        'T33': (['L', 'L', 'L', 'W', 'W', 'W'], 3), 'T51': (['W', 'W', 'L', 'W', 'W', 'W'], 3),
        'T50': (['W', 'W', 'W', 'W', 'W'], 5), 'T42': (['W', 'W', 'W', 'L', 'W', 'W'], 2),
        'Tpush': (['W', 'W', 'P', 'W'], 1), 'Tloss': (['W', 'W', 'W', 'L'], 0)}
    _M = {'W': 'Hit', 'L': 'Miss', 'P': 'Push'}
    rows = []
    for team, (states, _want) in cases.items():
        for i, s in enumerate(states, 1):
            rows.append(grow(f'{team}_g{i}', 'HOME', team, f'Opp{i}', _M[s], i, f'2026-09-{i:02d}'))
    per = _streaks(rows)['per']
    for team, (_states, want) in cases.items():
        got = per.get(team, {}).get('cover_streak')
        if got != want:
            issues.append(f'{team}: cover_streak {got} want {want}')
    return issues


def qc_two_decisions_per_fbs_fbs():
    """An FBS-vs-FBS game = exactly two graded decisions (HOME + AWAY), both reconcile with the manifest."""
    rows = [grow('G1', 'HOME', 'Georgia', 'Alabama', 'Hit', 1, '2026-09-01'),
            grow('G1', 'AWAY', 'Alabama', 'Georgia', 'Miss', 1, '2026-09-01')]
    d = _streaks(rows)
    sync = app._cfb_ats_sync(d, _lm([mgame('G1', 'Georgia', 'Alabama', 1)]), 1, 2026)
    issues = []
    if d['graded_keys'] != {('G1', 'HOME'), ('G1', 'AWAY')}:
        issues.append(f'graded keys not both sides: {d["graded_keys"]}')
    if not sync['synchronized'] or sync['expected_decisions'] != 2 or sync['missing_count'] != 0:
        issues.append(f'FBS-FBS did not reconcile to 2: {sync}')
    return issues


def qc_one_decision_fbs_fcs():
    """FBS-vs-FCS = exactly one counted decision (the FBS side); the FCS side is an exclusion."""
    rows = [grow('G2', 'HOME', 'App State', 'Maine', 'Hit', 1, '2026-09-01', conf='Sun Belt')]
    sync = app._cfb_ats_sync(_streaks(rows),
                             _lm([mgame('G2', 'App State', 'Maine', 1, home_conf='Sun Belt',
                                        away_conf='CAA')]), 1, 2026)
    issues = []
    if not sync['synchronized'] or sync['expected_decisions'] != 1 or sync['missing_count'] != 0:
        issues.append(f'FBS-FCS did not reconcile to 1 FBS side: {sync}')
    return issues


def qc_ambiguous_names_distinct_by_gameid():
    """Miami/Miami (OH), Tennessee/UT Martin, Louisiana/UL Monroe, Southern/Southern Miss stay distinct:
    different games -> different GameIDs -> separate decisions, never merged by name."""
    pairs = [('Miami', 'Miami (OH)'), ('Tennessee', 'UT Martin'),
             ('Louisiana', 'UL Monroe'), ('Southern', 'Southern Miss')]
    issues = []
    rows = []
    for i, (a, b) in enumerate(pairs):
        rows.append(grow(f'GA{i}', 'HOME', a, f'X{i}', 'Hit', 1, f'2026-09-0{i+1}'))
        rows.append(grow(f'GB{i}', 'HOME', b, f'Y{i}', 'Miss', 1, f'2026-09-0{i+1}'))
    per = _streaks(rows)['per']
    for a, b in pairs:
        if a not in per or b not in per:
            issues.append(f'{a!r}/{b!r} not both present as distinct teams: {a in per}/{b in per}')
        elif per[a]['results'] == per[b]['results'] and per[a]['cover_streak'] == per[b]['cover_streak'] \
                and a == b:
            issues.append(f'{a}/{b} merged')
    # explicit: distinct team count preserved
    if len({*(t for a, b in pairs for t in (a, b))}) != len([t for a, b in pairs for t in (a, b)]):
        issues.append('fixture team names not distinct')
    if len(per) != 8:
        issues.append(f'expected 8 distinct teams, got {len(per)}')
    return issues


def qc_presentation_alias_no_identity_effect():
    """App State (manifest) / Appalachian State (graded) reconcile on the SAME GameID -- the name
    spelling is presentation only and does not affect the decision identity."""
    rows = [grow('G3', 'HOME', 'Appalachian State', 'Marshall', 'Hit', 1, '2026-09-01', conf='Sun Belt'),
            grow('G3', 'AWAY', 'Marshall', 'Appalachian State', 'Miss', 1, '2026-09-01', conf='Sun Belt')]
    sync = app._cfb_ats_sync(_streaks(rows),
                             _lm([mgame('G3', 'App State', 'Marshall', 1, home_conf='Sun Belt',
                                        away_conf='Sun Belt')]), 1, 2026)
    if not sync['synchronized'] or sync['missing_count'] != 0:
        return [f'short/long spelling broke identity reconciliation: {sync}']
    return []


def qc_doubleheader_distinct():
    """Same team, same week, two different games (GameIDs) -> two decisions, both retained in date order."""
    rows = [grow('D1', 'HOME', 'Team', 'OppA', 'Hit', 1, '2026-08-29'),
            grow('D2', 'AWAY', 'Team', 'OppB', 'Miss', 1, '2026-09-05')]
    rec = _streaks(rows)['per'].get('Team', {})
    if rec.get('decisions') != 2 or rec.get('results') != ['W', 'L']:
        return [f'same-week doubleheader not two date-ordered decisions: {rec.get("results")}']
    return []


def qc_dup_collapse_vs_conflict():
    issues = []
    base = grow('G4', 'HOME', 'Georgia', 'Alabama', 'Hit', 1, '2026-09-01')
    d = _streaks([base, dict(base)])
    if d['collapsed'] != 1 or d['conflicts']:
        issues.append(f'identical (GameID,TeamSide) not collapsed: collapsed={d["collapsed"]} conf={d["conflicts"]}')
    d2 = _streaks([base, dict(base, OutcomeState='Miss')])
    if not d2['conflicts']:
        issues.append('conflicting (GameID,TeamSide) not flagged')
    s2 = app._cfb_ats_sync(d2, _lm([mgame('G4', 'Georgia', 'Alabama', 1)]), 1, 2026)
    if s2['synchronized']:
        issues.append('conflicting duplicate did not fail closed')
    return issues


def qc_missing_gameid_fails_closed():
    issues = []
    # graded row with no GameID -> ineligible -> fail closed
    row = grow(None, 'HOME', 'Georgia', 'Alabama', 'Hit', 1, '2026-09-01')
    row['GameID'] = ''
    d = _streaks([row])
    if d['ineligible'] != 1 or d['graded_keys']:
        issues.append(f'GameID-less graded row not ineligible: {d["ineligible"]}/{d["graded_keys"]}')
    s = app._cfb_ats_sync(d, _lm([mgame('G5', 'Georgia', 'Alabama', 1)]), 1, 2026)
    if s['synchronized']:
        issues.append('ineligible graded row did not fail sync closed')
    # manifest game with no game_id (completed, line-bearing) -> fail closed
    g = mgame('G6', 'Georgia', 'Alabama', 1)
    g['game_id'] = None
    s2 = app._cfb_ats_sync(_streaks([grow('G6', 'HOME', 'Georgia', 'Alabama', 'Hit', 1, '2026-09-01')]),
                           _lm([g]), 1, 2026)
    if s2['synchronized'] or s2.get('manifest_missing_gameid', 0) < 1:
        issues.append(f'manifest game without game_id did not fail closed: {s2}')
    return issues


def qc_inconsistent_gameid_fails_closed():
    """A GameID whose teams/kickoff are inconsistent across rows is a conflict -> fail closed."""
    rows = [grow('G7', 'HOME', 'Georgia', 'Alabama', 'Hit', 1, '2026-09-01'),
            grow('G7', 'AWAY', 'Clemson', 'Duke', 'Miss', 1, '2026-09-08')]   # same id, different teams/date
    d = _streaks(rows)
    if not d['conflicts']:
        return [f'inconsistent GameID identity not flagged as conflict: {d["conflicts"]}']
    return []


def qc_overlay_cannot_change_membership():
    """Membership = active cover streak >= 3, order = streak-desc then team-asc; the model/ranking overlay
    (tier chip, SoS) can never add, remove, or reorder a team."""
    issues = []

    def s(cov, name, conf='SEC'):
        return {'team_name': name, 'conf': conf, 'cover_streak': cov, 'loss_streak': 0,
                'results': ['W'] * cov, 'recent': ['W'] * min(cov, 6), 'covers': cov, 'losses': 0,
                'pushes': 0, 'decisions': cov, 'last_week': 7}
    synth = {'Georgia': s(5, 'Georgia'), 'Alabama': s(3, 'Alabama'), 'Oregon': s(3, 'Oregon'),
             'Ohio State': s(2, 'Ohio State')}
    o1, o2, o3 = app._cfb_active_cover_streaks, app._cfb_ats_sync, app._cfb_rankings
    o4, o5 = cff._srs_observed, cff.prior_divergence
    app._cfb_active_cover_streaks = lambda season=2026: {'per': synth, 'through': 7, 'graded_keys': set(),
                                                         'conflicts': [], 'collapsed': 0, 'ineligible': 0}
    app._cfb_ats_sync = lambda *a, **k: {'synchronized': True, 'through_week': 7, 'reason': None}
    app._cfb_rankings = lambda: {}
    _srs = lambda: {}                       # noqa: E731
    _srs.cache_clear = lambda: None
    cff._srs_observed = _srs
    cff.prior_divergence = lambda *a, **k: None
    try:
        app._CFB_WAVE_CACHE.clear()
        ctx = app.build_cfb_wave_context()
    finally:
        app._cfb_active_cover_streaks, app._cfb_ats_sync, app._cfb_rankings = o1, o2, o3
        cff._srs_observed, cff.prior_divergence = o4, o5
        app._CFB_WAVE_CACHE.clear()
    if ctx.get('wave_unsynced'):
        return ['synced fixture reported unsynced']
    members = [m['team'] for m in ctx.get('wave_members', [])]
    if members != ['Georgia', 'Alabama', 'Oregon']:   # streak-desc, then team-asc for the 3-way tie
        issues.append(f'membership/order wrong (overlay interfered?): {members}')
    if not all('tier_label' in m for m in ctx.get('wave_members', [])):
        issues.append('members missing the overlay chip field')
    return issues


CHECKS = [('streak_truth_table', qc_streak_truth_table),
          ('two_decisions_per_fbs_fbs', qc_two_decisions_per_fbs_fbs),
          ('one_decision_fbs_fcs', qc_one_decision_fbs_fcs),
          ('ambiguous_names_distinct_by_gameid', qc_ambiguous_names_distinct_by_gameid),
          ('presentation_alias_no_identity_effect', qc_presentation_alias_no_identity_effect),
          ('doubleheader_distinct', qc_doubleheader_distinct),
          ('dup_collapse_vs_conflict', qc_dup_collapse_vs_conflict),
          ('missing_gameid_fails_closed', qc_missing_gameid_fails_closed),
          ('inconsistent_gameid_fails_closed', qc_inconsistent_gameid_fails_closed),
          ('overlay_cannot_change_membership', qc_overlay_cannot_change_membership)]


def main() -> int:
    print('=' * 60)
    print('BANKROLL KINGS CFB ATS WAVE ADMISSION QC (game-id reconciliation)')
    print('=' * 60)
    failed = 0
    for name, fn in CHECKS:
        try:
            issues = fn()
        except Exception as e:  # noqa
            import traceback
            issues = [f'EXCEPTION {type(e).__name__}: {e}']
            traceback.print_exc()
        if issues:
            failed += 1
            for i in issues:
                print(f'[FAIL] {name}: {i}')
        else:
            print(f'[PASS] {name}')
    print('-' * 60)
    print(f'FAIL: {failed}' if failed else 'CFB ATS Wave admission (game-id) verified.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
