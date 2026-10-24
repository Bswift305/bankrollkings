"""QC: CFB Active ATS Wave admission + GAME-ID reconciliation (docs/ats_wave_contract.md +
docs/cfb_runtime_data_corrective.md).

Authoritative identity is (GameID, TeamSide) with FBS decided by provider conference (tri-state:
FBS/NON_FBS/UNKNOWN) -- never normalized names. GameIDs are canonical numeric strings (CFBD form).
Controlled fixtures; exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import io

import pandas as pd

import app
import bk_runtime
import build_ncaaf_game_line_backfill as grader
import cfb_current_form as cff
import fetch_cfbd_game_lines_history as hist
import report_cfb_wave_sync as rep


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
    games (each its own numeric GameID), ordered by GameDate."""
    issues = []
    _M = {'W': 'Hit', 'L': 'Miss', 'P': 'Push'}
    cases = {'T33': (['L', 'L', 'L', 'W', 'W', 'W'], 3), 'T51': (['W', 'W', 'L', 'W', 'W', 'W'], 3),
             'T50': (['W', 'W', 'W', 'W', 'W'], 5), 'T42': (['W', 'W', 'W', 'L', 'W', 'W'], 2),
             'Tpush': (['W', 'W', 'P', 'W'], 1), 'Tloss': (['W', 'W', 'W', 'L'], 0)}
    rows, gid = [], 10000
    for team, (states, _want) in cases.items():
        for i, s in enumerate(states, 1):
            gid += 1
            rows.append(grow(str(gid), 'HOME', team, f'Opp{gid}', _M[s], i, f'2026-09-{i:02d}'))
    per = _streaks(rows)['per']
    for team, (_states, want) in cases.items():
        if per.get(team, {}).get('cover_streak') != want:
            issues.append(f'{team}: cover_streak {per.get(team, {}).get("cover_streak")} want {want}')
    return issues


def qc_two_decisions_per_fbs_fbs():
    rows = [grow('400101', 'HOME', 'Georgia', 'Alabama', 'Hit', 1, '2026-09-01'),
            grow('400101', 'AWAY', 'Alabama', 'Georgia', 'Miss', 1, '2026-09-01')]
    d = _streaks(rows)
    sync = app._cfb_ats_sync(d, _lm([mgame('400101', 'Georgia', 'Alabama', 1)]), 1, 2026)
    issues = []
    if d['graded_keys'] != {('400101', 'HOME'), ('400101', 'AWAY')}:
        issues.append(f'graded keys not both sides: {d["graded_keys"]}')
    if not sync['synchronized'] or sync['expected_decisions'] != 2 or sync['missing_count'] != 0:
        issues.append(f'FBS-FBS did not reconcile to 2: {sync}')
    return issues


def qc_one_decision_fbs_fcs():
    rows = [grow('400102', 'HOME', 'App State', 'Maine', 'Hit', 1, '2026-09-01', conf='Sun Belt')]
    sync = app._cfb_ats_sync(_streaks(rows),
                             _lm([mgame('400102', 'App State', 'Maine', 1, home_conf='Sun Belt',
                                        away_conf='CAA')]), 1, 2026)
    issues = []
    if not sync['synchronized'] or sync['expected_decisions'] != 1 or sync['missing_count'] != 0:
        issues.append(f'FBS-FCS did not reconcile to 1 FBS side: {sync}')
    return issues


def qc_ambiguous_names_distinct_by_gameid():
    """Similar-name teams stay distinct: different games -> different GameIDs -> separate decisions, never
    merged by name. Includes the exact families the non-authoritative name key collapses (Miami (FL)/
    Miami (OH), Louisiana-Lafayette/UL Monroe, Sam Houston/Sam Houston State) -- proving the authoritative
    (GameID, TeamSide) model keeps them separate where the name key cannot."""
    pairs = [('Miami', 'Miami (OH)'), ('Miami (FL)', 'Miami (OH)'), ('Tennessee', 'UT Martin'),
             ('Louisiana', 'UL Monroe'), ('Louisiana-Lafayette', 'UL Monroe'),
             ('Southern', 'Southern Miss'), ('Sam Houston', 'Sam Houston State')]
    issues, rows, gid = [], [], 420000
    names = set()
    for a, b in pairs:
        names.add(a)
        names.add(b)
    for name in sorted(names):
        gid += 1
        rows.append(grow(str(gid), 'HOME', name, f'X{gid}', 'Hit', 1, '2026-09-01'))
    per = _streaks(rows)['per']
    for a, b in pairs:
        if a not in per or b not in per:
            issues.append(f'{a!r}/{b!r} not both present: {a in per}/{b in per}')
        if a in per and b in per and a == b:
            issues.append(f'{a!r} and {b!r} merged')
    if len(per) != len(names):
        issues.append(f'expected {len(names)} distinct teams, got {len(per)}')
    return issues


def qc_presentation_alias_no_identity_effect():
    """App State (manifest) / Appalachian State (graded) reconcile on the SAME GameID -- name spelling is
    presentation only."""
    rows = [grow('400103', 'HOME', 'Appalachian State', 'Marshall', 'Hit', 1, '2026-09-01', conf='Sun Belt'),
            grow('400103', 'AWAY', 'Marshall', 'Appalachian State', 'Miss', 1, '2026-09-01', conf='Sun Belt')]
    sync = app._cfb_ats_sync(_streaks(rows),
                             _lm([mgame('400103', 'App State', 'Marshall', 1, home_conf='Sun Belt',
                                        away_conf='Sun Belt')]), 1, 2026)
    if not sync['synchronized'] or sync['missing_count'] != 0:
        return [f'short/long spelling broke identity reconciliation: {sync}']
    return []


def qc_doubleheader_distinct():
    rows = [grow('400301', 'HOME', 'Team', 'OppA', 'Hit', 1, '2026-08-29'),
            grow('400302', 'AWAY', 'Team', 'OppB', 'Miss', 1, '2026-09-05')]
    rec = _streaks(rows)['per'].get('Team', {})
    if rec.get('decisions') != 2 or rec.get('results') != ['W', 'L']:
        return [f'same-week doubleheader not two date-ordered decisions: {rec.get("results")}']
    return []


def qc_dup_collapse_vs_conflict():
    issues = []
    base = grow('400104', 'HOME', 'Georgia', 'Alabama', 'Hit', 1, '2026-09-01')
    d = _streaks([base, dict(base)])
    if d['collapsed'] != 1 or d['conflicts']:
        issues.append(f'identical not collapsed: collapsed={d["collapsed"]} conf={d["conflicts"]}')
    d2 = _streaks([base, dict(base, OutcomeState='Miss')])
    if not d2['conflicts']:
        issues.append('conflicting (GameID,TeamSide) not flagged')
    s2 = app._cfb_ats_sync(d2, _lm([mgame('400104', 'Georgia', 'Alabama', 1)]), 1, 2026)
    if s2['synchronized']:
        issues.append('conflicting duplicate did not fail closed')
    return issues


def qc_missing_gameid_fails_closed():
    issues = []
    row = grow('', 'HOME', 'Georgia', 'Alabama', 'Hit', 1, '2026-09-01')
    d = _streaks([row])
    if d['ineligible'] != 1 or d['graded_keys']:
        issues.append(f'GameID-less graded row not ineligible: {d["ineligible"]}/{d["graded_keys"]}')
    s = app._cfb_ats_sync(d, _lm([mgame('400105', 'Georgia', 'Alabama', 1)]), 1, 2026)
    if s['synchronized']:
        issues.append('ineligible graded row did not fail sync closed')
    g = mgame(None, 'Georgia', 'Alabama', 1)
    s2 = app._cfb_ats_sync(_streaks([grow('400106', 'HOME', 'Georgia', 'Alabama', 'Hit', 1, '2026-09-01')]),
                           _lm([g]), 1, 2026)
    if s2['synchronized'] or s2.get('manifest_missing_gameid', 0) < 1:
        issues.append(f'manifest game without game_id did not fail closed: {s2}')
    return issues


def qc_inconsistent_gameid_fails_closed():
    rows = [grow('400107', 'HOME', 'Georgia', 'Alabama', 'Hit', 1, '2026-09-01'),
            grow('400107', 'AWAY', 'Clemson', 'Duke', 'Miss', 1, '2026-09-08')]
    if not _streaks(rows)['conflicts']:
        return ['inconsistent GameID identity not flagged as conflict']
    return []


def qc_gameid_canonical_roundtrip():
    g = bk_runtime.cfb_game_id
    issues = []
    for v in (401856678, '401856678', 401856678.0, '401856678.0', ' 401856678 '):
        if g(v) != '401856678':
            issues.append(f'{v!r} -> {g(v)!r} want "401856678"')
    for bad in (None, '', 'nan', 'none', float('nan'), 12345.5, '12.5', '4.01e8', '1.2e4', 'abc'):
        if g(bad) is not None:
            issues.append(f'{bad!r} should be rejected, got {g(bad)!r}')
    df = pd.DataFrame({'GameID': [401856678, None]})
    back = pd.read_csv(io.StringIO(df.to_csv(index=False)))
    if g(back['GameID'].iloc[0]) != '401856678' or g(back['GameID'].iloc[1]) is not None:
        issues.append(f'CSV round-trip not stable: {[g(x) for x in back["GameID"]]}')
    return issues


def qc_unknown_conference_fails_closed():
    issues = []
    rows = [grow('400510', 'HOME', 'NewU', 'Foe', 'Hit', 1, '2026-09-01', conf='Brand New League')]
    sync = app._cfb_ats_sync(_streaks(rows),
                             _lm([mgame('400510', 'NewU', 'Foe', 1, home_conf='Brand New League',
                                        away_conf='SEC')]), 1, 2026)
    if sync.get('unknown_conference', 0) < 1 or sync['synchronized']:
        issues.append(f'unknown conference did not fail closed: {sync}')
    s2 = app._cfb_ats_sync(_streaks([grow('400511', 'HOME', 'App State', 'Maine', 'Hit', 1, '2026-09-01',
                                          conf='Sun Belt')]),
                           _lm([mgame('400511', 'App State', 'Maine', 1, home_conf='Sun Belt',
                                      away_conf='CAA')]), 1, 2026)
    if s2.get('unknown_conference', 0) != 0 or not s2['synchronized']:
        issues.append(f'known FCS conf wrongly UNKNOWN / not synced: {s2}')
    return issues


def qc_missing_name_fails_closed():
    d = _streaks([grow('400120', 'HOME', '', 'Alabama', 'Hit', 1, '2026-09-01')])
    if d['ineligible'] != 1 or d['graded_keys']:
        return [f'missing team name not ineligible: {d["ineligible"]}/{d["graded_keys"]}']
    return []


def qc_manifest_dup_gameid_fails_closed():
    games = [mgame('400701', 'Georgia', 'Alabama', 1), mgame('400701', 'Clemson', 'Duke', 1)]
    rows = [grow('400701', 'HOME', 'Georgia', 'Alabama', 'Hit', 1, '2026-09-01'),
            grow('400701', 'AWAY', 'Alabama', 'Georgia', 'Miss', 1, '2026-09-01')]
    sync = app._cfb_ats_sync(_streaks(rows), _lm(games), 1, 2026)
    if sync.get('manifest_dup_gameid', 0) < 1 or sync['synchronized']:
        return [f'duplicate manifest GameID with different identity did not fail closed: {sync}']
    return []


def qc_overlay_abstains_not_misattributes():
    issues = []

    def s(name, conf):
        return {'team_name': name, 'conf': conf, 'cover_streak': 4, 'loss_streak': 0, 'results': ['W'] * 4,
                'recent': ['W'] * 4, 'covers': 4, 'losses': 0, 'pushes': 0, 'decisions': 4, 'last_week': 6}
    synth = {'Miami': s('Miami', 'ACC'), 'Miami (OH)': s('Miami (OH)', 'Mid-American')}
    o = (app._cfb_active_cover_streaks, app._cfb_ats_sync, app._cfb_rankings,
         cff._srs_observed, cff.prior_divergence)
    app._cfb_active_cover_streaks = lambda season=2026: {'per': synth, 'through': 6, 'graded_keys': set(),
                                                         'conflicts': [], 'collapsed': 0, 'ineligible': 0}
    app._cfb_ats_sync = lambda *a, **k: {'synchronized': True, 'through_week': 6, 'reason': None}
    app._cfb_rankings = lambda: {'Miami': {'trend': 'rising', 'fell_out': False}}
    _srs = lambda: {}                       # noqa: E731
    _srs.cache_clear = lambda: None
    cff._srs_observed = _srs
    cff.prior_divergence = lambda *a, **k: None
    try:
        app._CFB_WAVE_CACHE.clear()
        ctx = app.build_cfb_wave_context()
    finally:
        (app._cfb_active_cover_streaks, app._cfb_ats_sync, app._cfb_rankings,
         cff._srs_observed, cff.prior_divergence) = o
        app._CFB_WAVE_CACHE.clear()
    mem = {m['team']: m for m in ctx.get('wave_members', [])}
    if ctx.get('overlay_misattributions') != 0:
        issues.append(f'overlay_misattributions != 0: {ctx.get("overlay_misattributions")}')
    if mem.get('Miami', {}).get('status') != 'rising':
        issues.append(f'Miami lost its own exact overlay: {mem.get("Miami", {}).get("status")!r}')
    if mem.get('Miami (OH)', {}).get('status') == 'rising':
        issues.append("Miami (OH) misattributed Miami's 'rising' overlay")
    return issues


def _hist_row(gid='401901', home='Georgia', away='Alabama', hc='SEC', ac='SEC',
              wk=1, date='2026-09-05T19:30:00+00:00', season=2026):
    return {'GameID': gid, 'HomeTeamRaw': home, 'AwayTeamRaw': away, 'HomeConf': hc, 'AwayConf': ac,
            'Week': wk, 'Season': season, 'Date': date}


def _res_row(gid='401901', side='HOME', team='Georgia', opp='Alabama', conf='SEC', wk=1,
             date='2026-09-05T19:30:00+00:00', line=-3.5, season=2026, market='SPREAD'):
    return {'MarketType': market, 'Season': season, 'GameID': gid, 'TeamSide': side, 'Team': team,
            'Opponent': opp, 'Conf': conf, 'Week': wk, 'GameDate': date, 'Line': line}


def _good_sync():
    return {**{k: 0 for k in rep.DECLARED_COUNTERS}, 'synchronized': True}


def qc_validators_shared():
    """Shared validators reject the str(pd.NA)/str(np.nan) traps, non-positive/fractional weeks, and
    unparseable dates; accept real values."""
    issues = []
    for bad in ('', 'nan', 'NaN', 'none', 'null', '<NA>', '<na>', 'NaT', None, True):
        if bk_runtime.valid_text(bad):
            issues.append(f'valid_text wrongly accepted {bad!r}')
    for good in ('Georgia', 'Miami (OH)', 'App State'):
        if not bk_runtime.valid_text(good):
            issues.append(f'valid_text wrongly rejected {good!r}')
    for bad in (0, -1, 1.5, '1.5', 'nan', None, 99):
        if bk_runtime.valid_week(bad):
            issues.append(f'valid_week wrongly accepted {bad!r}')
    if not (bk_runtime.valid_week(1) and bk_runtime.valid_week('18') and bk_runtime.valid_week(18.0)):
        issues.append('valid_week rejected a good week')
    for bad in ('', '<NA>', 'nan', 'garbage', None):
        if bk_runtime.valid_date(bad):
            issues.append(f'valid_date wrongly accepted {bad!r}')
    if not bk_runtime.valid_date('2026-09-05T19:30:00+00:00') or not bk_runtime.valid_date('2026-09-05'):
        issues.append('valid_date rejected a good provider date')
    return issues


def qc_prepublish_empty_current_season():
    """A nonempty multi-year file with ZERO current-season rows must FAIL pre-publish (both artifacts)."""
    issues = []
    h = pd.DataFrame([_hist_row(season=2025)])
    ok, _ = hist.validate_history_current_season(h, 2026)
    if ok:
        issues.append('history validation passed with no 2026 rows')
    r = pd.DataFrame([_res_row(season=2025)])
    ok2, _ = grader.validate_results_current_season(r, 2026)
    if ok2:
        issues.append('results validation passed with no 2026 SPREAD rows')
    # a valid current-season frame passes
    if not hist.validate_history_current_season(pd.DataFrame([_hist_row()]), 2026)[0]:
        issues.append('valid history frame failed validation')
    if not grader.validate_results_current_season(pd.DataFrame([_res_row()]), 2026)[0]:
        issues.append('valid results frame failed validation')
    return issues


def qc_prepublish_bad_text_date_week():
    """nan/<NA> names and dates, and a fractional/zero week, fail pre-publish validation."""
    issues = []
    cases = [('nan name', _hist_row(home='<NA>')), ('nan date', _hist_row(date='<NA>')),
             ('null conf', _hist_row(hc='')), ('zero week', _hist_row(wk=0)),
             ('frac week', _hist_row(wk=1.5)), ('bad date', _hist_row(date='garbage'))]
    for label, row in cases:
        if hist.validate_history_current_season(pd.DataFrame([row]), 2026)[0]:
            issues.append(f'history accepted invalid row: {label}')
    rcases = [('nan team', _res_row(team='nan')), ('<NA> date', _res_row(date='<NA>')),
              ('zero week', _res_row(wk=0)), ('frac week', _res_row(wk=2.5)),
              ('bad line', _res_row(line='n/a')), ('bad side', _res_row(side='X'))]
    for label, row in rcases:
        if grader.validate_results_current_season(pd.DataFrame([row]), 2026)[0]:
            issues.append(f'results accepted invalid row: {label}')
    return issues


def qc_reporter_missing_counter_fails():
    """A missing/None/Boolean/negative counter fails the reporter (never a silent zero)."""
    issues = []
    rc, _ = rep.evaluate_closure(_good_sync(), 0, False)
    if rc != 0:
        issues.append('a fully-valid all-zero sync did not pass')
    for mutate in ({'malformed_rows': None}, {'unknown_conference': True}, {'missing_count': -1},
                   {'conflicting_duplicates': '0'}):
        s = {**_good_sync(), **mutate}
        if rep.evaluate_closure(s, 0, False)[0] == 0:
            issues.append(f'reporter passed with bad counter {mutate}')
    s2 = _good_sync()
    del s2['overdue_decisions']
    if rep.evaluate_closure(s2, 0, False)[0] == 0:
        issues.append('reporter passed with a MISSING counter')
    # overlay misattribution missing/None/nonzero fails
    for om in (None, 1, True):
        if rep.evaluate_closure(_good_sync(), om, False)[0] == 0:
            issues.append(f'reporter passed with overlay_misattributions={om!r}')
    return issues


def qc_reporter_gates_exact_duplicates():
    """exact_duplicates_collapsed is gated at zero for launch: =1 -> reporter exit 1."""
    s = {**_good_sync(), 'exact_duplicates_collapsed': 1}
    if rep.evaluate_closure(s, 0, False)[0] != 1:
        return ['exact_duplicates_collapsed=1 did not cause reporter exit 1']
    return []


def qc_overlay_cannot_change_membership():
    issues = []

    def s(cov, name, conf='SEC'):
        return {'team_name': name, 'conf': conf, 'cover_streak': cov, 'loss_streak': 0,
                'results': ['W'] * cov, 'recent': ['W'] * min(cov, 6), 'covers': cov, 'losses': 0,
                'pushes': 0, 'decisions': cov, 'last_week': 7}
    synth = {'Georgia': s(5, 'Georgia'), 'Alabama': s(3, 'Alabama'), 'Oregon': s(3, 'Oregon'),
             'Ohio State': s(2, 'Ohio State')}
    o = (app._cfb_active_cover_streaks, app._cfb_ats_sync, app._cfb_rankings,
         cff._srs_observed, cff.prior_divergence)
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
        (app._cfb_active_cover_streaks, app._cfb_ats_sync, app._cfb_rankings,
         cff._srs_observed, cff.prior_divergence) = o
        app._CFB_WAVE_CACHE.clear()
    if ctx.get('wave_unsynced'):
        return ['synced fixture reported unsynced']
    members = [m['team'] for m in ctx.get('wave_members', [])]
    if members != ['Georgia', 'Alabama', 'Oregon']:
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
          ('gameid_canonical_roundtrip', qc_gameid_canonical_roundtrip),
          ('unknown_conference_fails_closed', qc_unknown_conference_fails_closed),
          ('missing_name_fails_closed', qc_missing_name_fails_closed),
          ('manifest_dup_gameid_fails_closed', qc_manifest_dup_gameid_fails_closed),
          ('overlay_abstains_not_misattributes', qc_overlay_abstains_not_misattributes),
          ('validators_shared', qc_validators_shared),
          ('prepublish_empty_current_season', qc_prepublish_empty_current_season),
          ('prepublish_bad_text_date_week', qc_prepublish_bad_text_date_week),
          ('reporter_missing_counter_fails', qc_reporter_missing_counter_fails),
          ('reporter_gates_exact_duplicates', qc_reporter_gates_exact_duplicates),
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
