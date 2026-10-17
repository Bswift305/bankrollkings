"""QC: CFB Active ATS Wave admission + integrity (docs/ats_wave_contract.md, FROZEN).

Proves the frozen factual rule AND the three integrity corrections:
  * membership iterates the AUTHORITATIVE per-game streak index (the season aggregate can never suppress
    a qualifying team), and the displayed season record derives from the per-game sequence;
  * canonical team-GAME identity = (resolved team, resolved opponent, GameDate) -- NOT (week, team) --
    so two opponents a team plays under one week number are both retained in date order; an exact repeat
    collapses once; a conflicting repeat fails closed; a different opponent/date is never a duplicate;
  * synchronization is a COMPLETENESS check with MANIFEST-LINEAGE validation (not max(Week)): the
    manifest must declare the requested season, expected and graded identities match at
    (week, team, opponent) grain, and a stale/wrong-season/malformed manifest fails closed.

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
    d = app._cfb_cover_streaks_from_df(pd.DataFrame(rows), 2026)
    per = d['per']
    return {team: per.get(cff._resolve(team), {}) for team in cases}, d['through']


def _patch_fbs(teams=('Georgia', 'Alabama', 'Oregon', 'Ohio State', 'Auburn')):
    """Make the FBS universe deterministic for the sync/membership fixtures. cfb_current_form derives
    _fbs_teams() from cfb_2026_results.json, which now lives in the runtime dir (absent in a clean
    checkout), so pin it to the fixture teams here -- the sync LOGIC is what's under test, not the feed."""
    fn = lambda: frozenset(cff._resolve(t) for t in teams)  # noqa: E731
    fn.cache_clear = lambda: None                            # cff.clear_cache() calls this
    cff._fbs_teams = fn


def _sd(graded_keys=None, conflicts=None, collapsed=0):
    """A minimal streak_data payload in the shape _cfb_cover_streaks_from_df returns."""
    return {'per': {}, 'through': None, 'graded_keys': set(graded_keys or set()),
            'conflicts': list(conflicts or []), 'collapsed': collapsed}


def _lm(games, season=2026, updated='2026-10-15 23:58 UTC'):
    """A cfb_line_moves.json-shaped manifest."""
    return {'season': season, 'updated': updated, 'games': games}


def qc_truth_table():
    cases = {'T 3-3': ['L', 'L', 'L', 'W', 'W', 'W'], 'T 5-1': ['W', 'W', 'L', 'W', 'W', 'W'],
             'T 5-0': ['W', 'W', 'W', 'W', 'W'], 'T 4-2': ['W', 'W', 'W', 'L', 'W', 'W'],
             'T push': ['W', 'W', 'P', 'W']}
    per, _ = _streaks(cases)
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
    per, through = _streaks(cases)
    issues = []
    for t, w in {'bye': 3, 'ungraded': 3, 'noline': 3, 'loss': 0}.items():
        if per[t].get('cover_streak') != w:
            issues.append(f'{t}: cover_streak {per[t].get("cover_streak")} want {w}')
    if through != 4:
        issues.append(f'results_through_week {through} want 4')
    return issues


def qc_canonical_identity():
    """Canonical team-GAME identity = (resolved team, resolved opponent, GameDate), NOT (week, team).
    Two opponents under one week number -> both retained, date order. Exact repeat -> collapsed once.
    Conflicting repeat -> a conflict (fails sync closed). Different opponent/date -> separate game."""
    issues = []
    base = {'Sport': 'NCAAF', 'Season': 2026, 'MarketType': 'SPREAD', 'Line': -3.5}

    def row(team, opp, date, state, wk):
        return dict(base, Team=team, Opponent=opp, GameDate=date, OutcomeState=state, Week=wk)

    rt = cff._resolve('TwoGame')
    oa, ob = cff._resolve('OppA'), cff._resolve('OppB')
    # (1) same week number, two opponents, OPPOSITE results -> both retained, ordered by GameDate
    rows = [row('TwoGame', 'OppA', '2026-08-29 18:00:00+00:00', 'Hit', 1),
            row('TwoGame', 'OppB', '2026-09-05 19:30:00+00:00', 'Miss', 1)]
    d = app._cfb_cover_streaks_from_df(pd.DataFrame(rows), 2026)
    rec = d['per'].get(rt, {})
    if rec.get('decisions') != 2 or rec.get('results') != ['W', 'L']:
        issues.append(f'same-week two-opponent games not both retained in date order: {rec.get("results")}')
    if rec.get('cover_streak') != 0 or rec.get('loss_streak') != 1:
        issues.append(f'date-ordered streak wrong: cover {rec.get("cover_streak")} loss {rec.get("loss_streak")}')
    if {k for k in d['graded_keys'] if k[1] == rt} != {(1, rt, oa), (1, rt, ob)}:
        issues.append(f'graded_keys not at (week,team,opponent) grain: {sorted(d["graded_keys"])}')
    # (2) exact repeat of the same canonical game -> collapsed once, decisions unchanged, no conflict
    d2 = app._cfb_cover_streaks_from_df(
        pd.DataFrame(rows + [row('TwoGame', 'OppA', '2026-08-29 18:00:00+00:00', 'Hit', 1)]), 2026)
    rec2 = d2['per'].get(rt, {})
    if d2['collapsed'] != 1 or rec2.get('decisions') != 2:
        issues.append(f'exact duplicate not collapsed once: collapsed {d2["collapsed"]} decisions {rec2.get("decisions")}')
    if d2['conflicts']:
        issues.append('exact duplicate wrongly flagged as a conflict')
    # (3) same canonical game, CONFLICTING result -> a conflict (fail closed), not a collapse
    d3 = app._cfb_cover_streaks_from_df(
        pd.DataFrame(rows + [row('TwoGame', 'OppA', '2026-08-29 18:00:00+00:00', 'Miss', 1)]), 2026)
    if not d3['conflicts'] or d3['collapsed']:
        issues.append(f'conflicting duplicate not flagged: conflicts {d3["conflicts"]} collapsed {d3["collapsed"]}')
    # (4) different opponent, same week -> two separate legitimate games, never a duplicate
    d4 = app._cfb_cover_streaks_from_df(pd.DataFrame(
        [row('Multi', 'OppA', '2026-08-29 18:00:00+00:00', 'Hit', 1),
         row('Multi', 'OppB', '2026-08-30 18:00:00+00:00', 'Hit', 1)]), 2026)
    rec4 = d4['per'].get(cff._resolve('Multi'), {})
    if rec4.get('cover_streak') != 2 or d4['collapsed'] or d4['conflicts']:
        issues.append(f'different-opponent same-week games wrongly deduped: streak {rec4.get("cover_streak")} '
                      f'collapsed {d4["collapsed"]}')
    return issues


def qc_sync_completeness():
    """Completeness, not max(Week): an isolated graded row does not mark a week complete; a missing
    required FBS decision fails closed; a no-line/cancelled game is an accepted exclusion; a conflicting
    duplicate fails closed. Expected and graded identities are matched at (week, team, opponent) grain."""
    issues = []
    _patch_fbs()
    r1, r2 = cff._resolve('Georgia'), cff._resolve('Alabama')
    ro, rohio = cff._resolve('Oregon'), cff._resolve('Ohio State')
    games = [{'completed': True, 'week': 1, 'home': 'Georgia', 'away': 'Alabama', 'spread_now': -7.0},
             {'completed': True, 'week': 1, 'home': 'Oregon', 'away': 'Ohio State', 'spread_now': -3.0}]
    # only ONE of the four FBS decisions graded -> incomplete -> not synchronized
    r = app._cfb_ats_sync(_sd({(1, r1, r2)}), _lm(games), 1, 2026)
    if r['synchronized'] or r['missing_count'] != 3:
        issues.append(f'isolated row marked complete: {r}')
    # all four graded -> synchronized, through_week set
    allk = {(1, r1, r2), (1, r2, r1), (1, ro, rohio), (1, rohio, ro)}
    r2c = app._cfb_ats_sync(_sd(allk), _lm(games), 1, 2026)
    if not r2c['synchronized'] or r2c['through_week'] != 1:
        issues.append(f'complete manifest not synchronized: {r2c}')
    # a no-line game is an accepted exclusion (not counted as missing)
    games_excl = games[:1] + [{'completed': True, 'week': 1, 'home': 'Baylor', 'away': 'TCU',
                               'spread_now': None, 'spread_open': None}]
    r3 = app._cfb_ats_sync(_sd({(1, r1, r2), (1, r2, r1)}), _lm(games_excl), 1, 2026)
    if not r3['synchronized'] or r3['exclusions'] < 1:
        issues.append(f'no-line game not treated as an accepted exclusion: {r3}')
    # a conflicting duplicate identity fails closed even with nothing missing
    r4 = app._cfb_ats_sync(_sd(allk, conflicts=[(r1, r2, '2026-08-29')]), _lm(games), 1, 2026)
    if r4['synchronized']:
        issues.append('conflicting duplicate identity did not fail closed')
    return issues


def qc_sync_lineage():
    """Manifest lineage gates synchronization: expected and graded match on (week, team, opponent); a
    wrong-season or malformed manifest fails closed with a reason; the manifest `updated` is reported."""
    issues = []
    _patch_fbs()
    r1, r2 = cff._resolve('Georgia'), cff._resolve('Alabama')
    games = [{'completed': True, 'week': 1, 'home': 'Georgia', 'away': 'Alabama', 'spread_now': -7.0}]
    graded = {(1, r1, r2), (1, r2, r1)}
    # matching identities -> synchronized, manifest_updated surfaced for the operator
    ok = app._cfb_ats_sync(_sd(graded), _lm(games), 1, 2026)
    if not ok['synchronized'] or ok.get('manifest_updated') != '2026-10-15 23:58 UTC':
        issues.append(f'matching identities not synchronized / updated not reported: {ok}')
    # opponent mismatch -> the manifest decision is missing (identity includes opponent, not just team)
    mis = app._cfb_ats_sync(_sd({(1, r1, cff._resolve('Auburn')), (1, r2, r1)}), _lm(games), 1, 2026)
    if mis['synchronized'] or mis['missing_count'] < 1:
        issues.append(f'opponent mismatch not detected at identity grain: {mis}')
    # wrong-season manifest -> fail closed with a lineage reason, never synchronized
    stale = app._cfb_ats_sync(_sd(graded), _lm(games, season=2025), 1, 2026)
    if stale['synchronized'] or 'lineage' not in (stale.get('reason') or ''):
        issues.append(f'wrong-season manifest did not fail closed: {stale}')
    # malformed manifest (no games list) -> fail closed
    bad = app._cfb_ats_sync(_sd(graded), {'season': 2026, 'updated': 'x'}, 1, 2026)
    if bad['synchronized']:
        issues.append(f'malformed manifest (no games) did not fail closed: {bad}')
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
    _patch_fbs()
    o1, o2 = app._cfb_active_cover_streaks, app._cfb_ats_sync
    o3, o4 = cff._srs_observed, cff.prior_divergence
    app._cfb_active_cover_streaks = lambda season=2026: {'per': synth, 'through': 7, 'graded_keys': set(),
                                                         'conflicts': [], 'collapsed': 0}
    app._cfb_ats_sync = lambda streak_data, line_moves, completed_week, season=2026: {
        'synchronized': True, 'through_week': 7, 'completed_week': 7, 'expected_decisions': 0,
        'graded_decisions': 0, 'exclusions': 0, 'missing_count': 0, 'missing': [], 'conflicts': 0,
        'duplicates_collapsed': 0, 'manifest_season': 2026, 'manifest_updated': 'fixture'}
    # The fixture forces synchronized=True with no CFB results on disk (clean checkout -> runtime dir
    # empty); stub the srs/divergence reads the builder makes AFTER the sync gate so it doesn't divide
    # by an empty ratings set. Membership is what's under test, not the ratings.
    _srs_stub = lambda: {}                 # noqa: E731
    _srs_stub.cache_clear = lambda: None   # cff.clear_cache() calls this
    cff._srs_observed = _srs_stub
    cff.prior_divergence = lambda *a, **k: None
    try:
        app._CFB_WAVE_CACHE.clear()
        ctx = app.build_cfb_wave_context()
    finally:
        app._cfb_active_cover_streaks, app._cfb_ats_sync = o1, o2
        cff._srs_observed, cff.prior_divergence = o3, o4
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
    per = app._cfb_cover_streaks_from_df(pd.DataFrame(rows), 2026)['per']
    rec = per.get(cff._resolve(c), {})
    if rec.get('cover_streak') != 3:
        return [f'aliases split the team ({a!r}/{c!r}): streak {rec.get("cover_streak")} want 3']
    return []


def qc_canon_short_long_reconciles():
    """Wave-local canonicalization: a manifest game under the SHORT CFBD name (App State) reconciles with
    a graded row under the LONG name (Appalachian State) -- synchronized, 0 missing; the same game under
    BOTH names collapses (no double-count); an FBS-vs-FCS game retains the FBS side."""
    issues = []
    _patch_fbs(('Appalachian State', 'Marshall', 'Southern Mississippi'))

    def row(team, opp, state='Hit', wk=1, date='2026-08-30 18:00:00+00:00', line=-3.5):
        return {'Sport': 'NCAAF', 'Season': 2026, 'Week': wk, 'GameDate': date, 'Team': team,
                'Opponent': opp, 'MarketType': 'SPREAD', 'OutcomeState': state, 'Line': line}

    # (a) graded uses LONG name; manifest uses SHORT name -> reconciles. The real grader writes BOTH
    # team-side rows per game, so include the reciprocal (both teams are FBS here).
    d = app._cfb_cover_streaks_from_df(pd.DataFrame([row('Appalachian State', 'Marshall', 'Hit'),
                                                     row('Marshall', 'Appalachian State', 'Miss')]), 2026)
    games = [{'completed': True, 'week': 1, 'home': 'App State', 'away': 'Marshall', 'spread_now': -3.5}]
    sync = app._cfb_ats_sync(d, _lm(games), 1, 2026)
    if not sync['synchronized'] or sync['missing_count'] != 0:
        issues.append(f'short/long name did not reconcile: {sync}')
    # (b) same game under BOTH names in the graded df -> collapses to one canonical, no double-count
    d2 = app._cfb_cover_streaks_from_df(
        pd.DataFrame([row('Appalachian State', 'Marshall'), row('App State', 'Marshall')]), 2026)
    rec = d2['per'].get(cff._resolve('Appalachian State'), {})
    if rec.get('decisions') != 1 or rec.get('cover_streak') != 1 or d2['collapsed'] != 1:
        issues.append(f'short/long double-counted: decisions={rec.get("decisions")} collapsed={d2["collapsed"]}')
    # (c) FBS-vs-FCS: FBS side graded under the long name reconciles with the manifest short name
    d3 = app._cfb_cover_streaks_from_df(pd.DataFrame([row('Southern Mississippi', 'Alcorn State')]), 2026)
    g3 = [{'completed': True, 'week': 1, 'home': 'Southern Miss', 'away': 'Alcorn State', 'spread_now': -20.0}]
    s3 = app._cfb_ats_sync(d3, _lm(g3), 1, 2026)
    if not s3['synchronized'] or s3['missing_count'] != 0:
        issues.append(f'FBS-vs-FCS FBS side did not reconcile: {s3}')
    return issues


def qc_fail_closed_real():
    app._CFB_WAVE_CACHE.clear()
    ctx = app.build_cfb_wave_context()
    if ctx.get('wave_unsynced') and ctx.get('wave_members'):
        return ['unsynced board still produced members (cover-% fallback?)']
    return []


CHECKS = [('truth_table', qc_truth_table), ('edges', qc_edges),
          ('canonical_identity', qc_canonical_identity),
          ('sync_completeness', qc_sync_completeness), ('sync_lineage', qc_sync_lineage),
          ('membership_iterates_streaks', qc_membership_iterates_streaks),
          ('alias_resolution', qc_alias_resolution),
          ('canon_short_long_reconciles', qc_canon_short_long_reconciles),
          ('fail_closed_real', qc_fail_closed_real)]


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
