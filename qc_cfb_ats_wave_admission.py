"""QC: CFB Active ATS Wave admission + integrity (docs/ats_wave_contract.md, FROZEN).

Proves the frozen factual rule AND the two integrity corrections:
  * membership iterates the AUTHORITATIVE per-game streak index (the season aggregate can never suppress
    a qualifying team), and the displayed season record derives from the per-game sequence;
  * synchronization is a COMPLETENESS check against the expected completed-game manifest (not max(Week)),
    enforcing one canonical ATS decision per team-game and failing closed on missing/duplicate identities.

Uses controlled fixtures. Exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import pandas as pd

import app
import cfb_current_form as cff


def _rows(team, tokens, opp='Opp', season=2026):
    rows, wk = [], 1
    for t in tokens:
        if t == 'Bye':
            wk += 1
            continue
        state = {'W': 'Hit', 'L': 'Miss', 'P': 'Push', 'U': 'Pending', 'N': 'Hit'}[t]  # N = cover w/o line
        rows.append({'Sport': 'NCAAF', 'Season': season, 'Week': wk, 'GameDate': f'2026-09-{wk:02d}',
                     'Team': team, 'Opponent': opp, 'MarketType': 'SPREAD', 'OutcomeState': state,
                     'Line': '' if t == 'N' else -3.5})
        wk += 1
    return rows


def _streaks(cases):
    rows = []
    for team, toks in cases.items():
        rows += _rows(team, toks)
    per, through, canon, dups = app._cfb_cover_streaks_from_df(pd.DataFrame(rows), 2026)
    return {team: per.get(cff._resolve(team), {}) for team in cases}, through, canon, dups


def qc_truth_table():
    cases = {'T 3-3': ['L', 'L', 'L', 'W', 'W', 'W'], 'T 5-1': ['W', 'W', 'L', 'W', 'W', 'W'],
             'T 5-0': ['W', 'W', 'W', 'W', 'W'], 'T 4-2': ['W', 'W', 'W', 'L', 'W', 'W'],
             'T push': ['W', 'W', 'P', 'W']}
    per, _, _, _ = _streaks(cases)
    want = {'T 3-3': 3, 'T 5-1': 3, 'T 5-0': 5, 'T 4-2': 2, 'T push': 1}
    issues = [f'{t}: {per[t].get("cover_streak")} want {w}' for t, w in want.items()
              if per[t].get('cover_streak') != w]
    quals = {t for t, s in per.items() if s.get('cover_streak', 0) >= 3}
    if quals != {'T 3-3', 'T 5-1', 'T 5-0'}:
        issues.append(f'wrong qualifiers: {sorted(quals)}')
    return issues


def qc_edges():
    cases = {'bye': ['W', 'Bye', 'W', 'W'], 'ungraded': ['W', 'U', 'W', 'W'],
             'noline': ['W', 'N', 'W', 'W'], 'loss': ['W', 'W', 'W', 'L']}
    per, through, _, _ = _streaks(cases)
    issues = []
    for t, w in {'bye': 3, 'ungraded': 3, 'noline': 3, 'loss': 0}.items():
        if per[t].get('cover_streak') != w:
            issues.append(f'{t}: cover_streak {per[t].get("cover_streak")} want {w}')
    if through != 4:
        issues.append(f'results_through_week {through} want 4')
    return issues


def qc_duplicate_grain():
    """One canonical ATS decision per team-game: a duplicate same-result row does NOT add a cover; a
    conflicting duplicate is flagged as a duplicate identity."""
    issues = []
    # team weeks 1(W),2(W) + a DUPLICATE week-2 W row -> 2 covers, not 3; no conflict
    rows = _rows('DupTeam', ['W', 'W']) + [dict(_rows('DupTeam', ['W'])[0], Week=2, GameDate='2026-09-02')]
    per, _, _, dups = app._cfb_cover_streaks_from_df(pd.DataFrame(rows), 2026)
    rec = per.get(cff._resolve('DupTeam'), {})
    if rec.get('cover_streak') != 2 or rec.get('decisions') != 2:
        issues.append(f'duplicate extended the streak: streak {rec.get("cover_streak")} decisions {rec.get("decisions")}')
    # conflicting duplicate (week-2 W and week-2 L) -> flagged
    rows2 = _rows('ConfTeam', ['W', 'W']) + [dict(_rows('ConfTeam', ['L'])[0], Week=2, GameDate='2026-09-02')]
    _, _, _, dups2 = app._cfb_cover_streaks_from_df(pd.DataFrame(rows2), 2026)
    if not dups2:
        issues.append('conflicting duplicate identity was not flagged')
    return issues


def qc_sync_completeness():
    """Completeness, not max(Week): an isolated graded row does not mark a week complete; a missing
    required FBS decision fails closed; a no-line/cancelled game is an accepted exclusion."""
    issues = []
    g1, g2 = 'Georgia', 'Alabama'
    lm_two = [{'completed': True, 'week': 1, 'home': g1, 'away': g2, 'spread_now': -7.0},
              {'completed': True, 'week': 1, 'home': 'Oregon', 'away': 'Ohio State', 'spread_now': -3.0}]
    # only ONE of the four FBS decisions graded -> incomplete -> not synchronized
    canon_one = {(1, cff._resolve(g1)): {'res': 'W'}}
    r = app._cfb_ats_sync(canon_one, [], lm_two, 1)
    if r['synchronized'] or r['missing_count'] != 3:
        issues.append(f'isolated row marked complete: {r}')
    # all four graded -> synchronized, through_week set
    canon_all = {(1, cff._resolve(t)): {'res': 'W'} for t in (g1, g2, 'Oregon', 'Ohio State')}
    r2 = app._cfb_ats_sync(canon_all, [], lm_two, 1)
    if not r2['synchronized'] or r2['through_week'] != 1:
        issues.append(f'complete manifest not synchronized: {r2}')
    # a no-line game is an accepted exclusion (not counted as missing)
    lm_excl = lm_two[:1] + [{'completed': True, 'week': 1, 'home': 'Baylor', 'away': 'TCU',
                             'spread_now': None, 'spread_open': None}]
    canon_g1 = {(1, cff._resolve(g1)): {'res': 'W'}, (1, cff._resolve(g2)): {'res': 'L'}}
    r3 = app._cfb_ats_sync(canon_g1, [], lm_excl, 1)
    if not r3['synchronized'] or r3['exclusions'] < 1:
        issues.append(f'no-line game not treated as an accepted exclusion: {r3}')
    # a duplicate identity fails closed even with nothing missing
    r4 = app._cfb_ats_sync(canon_all, [(1, cff._resolve(g1))], lm_two, 1)
    if r4['synchronized']:
        issues.append('duplicate identity did not fail closed')
    return issues


def qc_membership_iterates_streaks():
    """Membership iterates the authoritative streak index (aggregate can't suppress), and the displayed
    season record derives from the per-game sequence -- not the aggregate. Also: deterministic order,
    model-independent membership, aliases resolve to one canonical."""
    issues = []

    def s(cov, loss=0, push=0, name='X'):
        dec = cov + loss + push
        return {'team_name': name, 'cover_streak': cov, 'loss_streak': loss,
                'results': ['W'] * cov, 'recent': ['W'] * min(cov, 6), 'covers': cov,
                'losses': loss, 'pushes': push, 'decisions': dec, 'last_week': 7}
    synth = {cff._resolve('Georgia'): s(5, name='Georgia'),
             cff._resolve('Alabama'): s(3, name='Alabama'),
             cff._resolve('Oregon'): s(3, name='Oregon'),
             cff._resolve('Ohio State'): s(2, name='Ohio State')}
    o1, o2 = app._cfb_active_cover_streaks, app._cfb_ats_sync
    app._cfb_active_cover_streaks = lambda season=2026: (synth, 7, {}, [])
    app._cfb_ats_sync = lambda canon, dups, lm, cw: {'synchronized': True, 'through_week': 7,
                                                     'completed_week': 7, 'expected_decisions': 0,
                                                     'graded_decisions': 0, 'exclusions': 0,
                                                     'missing_count': 0, 'duplicate_count': 0}
    try:
        app._CFB_WAVE_CACHE.clear()
        ctx = app.build_cfb_wave_context()
    finally:
        app._cfb_active_cover_streaks, app._cfb_ats_sync = o1, o2
        app._CFB_WAVE_CACHE.clear()
    if ctx.get('wave_unsynced'):
        return ['synced fixture reported unsynced']
    members = {cff._resolve(m['team']): m for m in ctx.get('wave_members', [])}
    want = {cff._resolve(t) for t in ('Georgia', 'Alabama', 'Oregon')}
    if set(members) != want:
        issues.append(f'membership not by streak>=3 (aggregate suppressed?): {sorted(members)}')
    # season record DERIVED from the sequence (synth Georgia 5-0), not the aggregate
    g = members.get(cff._resolve('Georgia'))
    if g and g.get('ats') != '5-0':
        issues.append(f'season record not derived from the sequence: {g.get("ats")}')
    streaks = [m['cover_streak'] for m in ctx['wave_members']]
    if streaks != sorted(streaks, reverse=True):
        issues.append(f'not streak-DESC: {streaks}')
    tie = [m['team'] for m in ctx['wave_members'] if m['cover_streak'] == 3]
    if tie != sorted(tie):
        issues.append(f'tie not broken by team name: {tie}')
    if not all('tier_label' in m for m in ctx['wave_members']):
        issues.append('members missing model overlay field')
    return issues


def qc_alias_resolution():
    """Aliases resolve to ONE canonical team without suppressing membership (two source spellings of the
    same FBS team across weeks combine into one 3-cover streak, not split below threshold)."""
    aliases = getattr(cff, 'CFB_TEAM_ALIASES', {}) or {}
    pair = next(((a, c) for a, c in aliases.items() if cff._resolve(a) == cff._resolve(c)
                 and cff._resolve(c) in cff._fbs_teams()), None)
    if not pair:
        return []  # no alias pair available in this build; nothing to assert
    a, c = pair
    rows = _rows(c, ['W']) + [dict(_rows(a, ['W'])[0], Week=2, GameDate='2026-09-02')] \
        + [dict(_rows(c, ['W'])[0], Week=3, GameDate='2026-09-03')]
    per, _, _, _ = app._cfb_cover_streaks_from_df(pd.DataFrame(rows), 2026)
    rec = per.get(cff._resolve(c), {})
    if rec.get('cover_streak') != 3:
        return [f'aliases split the team ({a!r}/{c!r}): streak {rec.get("cover_streak")} want 3']
    return []


def qc_fail_closed_real():
    app._CFB_WAVE_CACHE.clear()
    ctx = app.build_cfb_wave_context()
    if ctx.get('wave_unsynced') and ctx.get('wave_members'):
        return ['unsynced board still produced members (cover-% fallback?)']
    return []


CHECKS = [('truth_table', qc_truth_table), ('edges', qc_edges), ('duplicate_grain', qc_duplicate_grain),
          ('sync_completeness', qc_sync_completeness),
          ('membership_iterates_streaks', qc_membership_iterates_streaks),
          ('alias_resolution', qc_alias_resolution), ('fail_closed_real', qc_fail_closed_real)]


def main() -> int:
    print('=' * 60)
    print('BANKROLL KINGS CFB ACTIVE ATS WAVE ADMISSION QC')
    print('=' * 60)
    failed = 0
    for name, fn in CHECKS:
        try:
            issues = fn()
        except Exception as e:  # noqa
            issues = [f'EXCEPTION {type(e).__name__}: {e}']
        if issues:
            failed += 1
            for i in issues:
                print(f'[FAIL] {name}: {i}')
        else:
            print(f'[PASS] {name}')
    print('-' * 60)
    print(f'FAIL: {failed}' if failed else 'Active ATS Wave admission + integrity verified.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
