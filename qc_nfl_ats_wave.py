"""QC: NFL Active ATS Wave on the current-season source (docs/ats_wave_contract.md +
docs/nfl_ats_wave_source_characterization.md).

Proves the NFL-specific implementation of the frozen rule WITHOUT copying CFB mechanics:
  * explicit active-season gate (never max(season));
  * game_id identity, two reciprocal team-side decisions per completed game;
  * recorded-spread sign verified with home-fav / away-fav / push fixtures;
  * EVENT-level completeness (completed Thursday counts mid-week; future ignored; overdue fails closed);
  * duplicate collapse vs conflict fail-closed; stale-source fail-closed;
  * membership purely factual (cover streak >= 3), deterministic order, model cannot alter it;
  * push interrupts the strict cover streak (W,W,P,W -> 1).

Controlled fixtures + a temp parquet for the end-to-end synchronized path. Exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime

import pandas as pd

import app

NOW = datetime(2026, 10, 20, 12, 0)   # a Tuesday, well past Week-7 Sunday games
PAST = '2026-10-12'                    # before NOW - grace
FUTURE = '2026-10-25'                  # after NOW


def _g(game_id, week, gameday, home, away, hs, as_, spread_line, season=2026, gametime='13:00'):
    """One nflverse-schema game row. result = home_score - away_score when scores are present."""
    res = (hs - as_) if (hs is not None and as_ is not None) else None
    return {'game_id': game_id, 'season': season, 'week': week, 'gameday': gameday, 'gametime': gametime,
            'home_team': home, 'away_team': away, 'home_score': hs, 'away_score': as_,
            'result': res, 'spread_line': spread_line}


def _dec(rows, season=2026, now=NOW):
    return app._nfl_ats_decisions_from_games(pd.DataFrame(rows), season, now)


def qc_season_gate_and_unavailable():
    """Active season is explicit: 2026 rows are used, 2025 rows ignored even when more numerous; and
    a source with no current-season rows is unavailable (fail closed)."""
    issues = []
    rows = ([_g(f'2025_0{w}_AAA_BBB', w, f'2025-09-{10+w:02d}', 'AAA', 'BBB', 30, 0, 3.0, season=2025)
             for w in range(1, 6)]                                   # a big 2025 streak that must NOT appear
            + [_g('2026_01_AAA_CCC', 1, PAST, 'AAA', 'CCC', 10, 0, 3.0)])
    dec = _dec(rows, season=2026)
    if dec['season_rows'] != 1:
        issues.append(f'season gate pulled non-2026 rows: season_rows={dec["season_rows"]}')
    if set(dec['per']) != {'AAA', 'CCC'} or dec['per']['AAA']['decisions'] != 1:
        issues.append(f'2025 rows leaked into decisions: {sorted(dec["per"])}')
    # no current-season rows -> unavailable
    only25 = _dec([_g('2025_01_AAA_BBB', 1, '2025-09-11', 'AAA', 'BBB', 10, 0, 3.0, season=2025)], season=2026)
    sync = app._nfl_ats_sync(only25, age_hours=1.0, last_refresh='x', season=2026)
    if sync['synchronized'] or 'no current-season rows' not in (sync['reason'] or ''):
        issues.append(f'empty current season not failed closed: {sync}')
    return issues


def qc_recorded_spread_signs():
    """spread_line > 0 => HOME favored; home ATS margin = (home-away) - spread_line. Verify cover/loss/
    push for a home favorite and an away favorite (spread_line < 0)."""
    issues = []
    cases = [
        # (desc, home_score, away_score, spread_line, expect_home_sign)
        ('home-fav cover', 20, 10, 3.0, 1),    # margin 10 > 3
        ('home-fav loss', 11, 10, 3.0, -1),    # margin 1 < 3
        ('home-fav push', 13, 10, 3.0, 0),     # margin 3 == 3
        ('away-fav cover', 0, 10, -3.0, -1),   # margin -10 < -3 -> home loses ATS -> away covers
        ('away-fav loss', 9, 10, -3.0, 1),     # margin -1 > -3 -> home covers ATS
        ('away-fav push', 7, 10, -3.0, 0),     # margin -3 == -3
    ]
    for i, (desc, hs, as_, sp, want) in enumerate(cases):
        dec = _dec([_g(f'2026_01_H{i}_A{i}', 1, PAST, f'H{i}', f'A{i}', hs, as_, sp)])
        got = dec['per'].get(f'H{i}', {}).get('results', [None])[-1]
        if got != want:
            issues.append(f'{desc}: home sign {got} want {want}')
    return issues


def qc_reciprocity():
    """Each completed game yields two reciprocal team rows: one cover / one loss, or two pushes."""
    issues = []
    dec = _dec([_g('2026_01_HOU_IND', 1, PAST, 'HOU', 'IND', 20, 10, 3.0),   # home cover
                _g('2026_02_KC_DEN', 2, PAST, 'KC', 'DEN', 13, 10, 3.0)])    # push
    for gid, h, a in dec['pairs']:
        if h + a != 0:
            issues.append(f'{gid}: non-reciprocal {h}/{a}')
        if (h == 0) != (a == 0):
            issues.append(f'{gid}: push not mirrored {h}/{a}')
    return issues


def qc_event_completeness():
    """A completed Thursday game counts during an otherwise-unfinished week; a future game is ignored
    (not overdue); an overdue ungraded past-grace game fails closed."""
    issues = []
    # Week 7: Thu (completed, past) + Sun (future, no result). now=Fri 10-16 so Sun is future.
    now_fri = datetime(2026, 10, 16, 12, 0)
    wk7 = [_g('2026_07_SEA_SF', 7, '2026-10-15', 'SEA', 'SF', 24, 20, 3.0, gametime='20:15'),  # Thu done
           _g('2026_07_GB_CHI', 7, '2026-10-18', 'GB', 'CHI', None, None, 2.5, gametime='13:00')]  # Sun future
    dec = app._nfl_ats_decisions_from_games(pd.DataFrame(wk7), 2026, now_fri)
    if ('2026_07_SEA_SF', 'SEA') not in dec['graded_keys']:
        issues.append('completed Thursday game not graded mid-week')
    if dec['overdue']:
        issues.append(f'future Sunday game wrongly marked overdue: {dec["overdue"]}')
    if 'GB' in dec['per'] or 'CHI' in dec['per']:
        issues.append('future game produced decisions')
    # overdue: a past-grace game with no result fails closed
    od = _dec([_g('2026_01_AAA_BBB', 1, PAST, 'AAA', 'BBB', None, None, 3.0)])
    sync = app._nfl_ats_sync(od, age_hours=1.0, last_refresh='x', season=2026)
    if not od['overdue'] or sync['synchronized']:
        issues.append(f'overdue ungraded game did not fail closed: overdue={od["overdue"]} sync={sync["synchronized"]}')
    return issues


def qc_duplicate_and_malformed():
    """Exact-duplicate game_id collapses once; a conflicting game_id fails closed; a malformed recorded
    spread on a past-grace game fails closed."""
    issues = []
    base = _g('2026_01_AAA_BBB', 1, PAST, 'AAA', 'BBB', 20, 10, 3.0)
    dup = _dec([base, dict(base)])
    if dup['collapsed'] != 1 or dup['conflicts']:
        issues.append(f'exact duplicate not collapsed once: collapsed={dup["collapsed"]} conflicts={dup["conflicts"]}')
    if dup['per'].get('AAA', {}).get('decisions') != 1:
        issues.append('duplicate inflated the decision count')
    conf = _dec([base, dict(base, result=-5, home_score=5, away_score=10)])
    s1 = app._nfl_ats_sync(conf, age_hours=1.0, last_refresh='x', season=2026)
    if not conf['conflicts'] or s1['synchronized']:
        issues.append(f'conflicting duplicate did not fail closed: {conf["conflicts"]} {s1["synchronized"]}')
    mal = _dec([_g('2026_01_CCC_DDD', 1, PAST, 'CCC', 'DDD', None, None, 'n/a')])
    s2 = app._nfl_ats_sync(mal, age_hours=1.0, last_refresh='x', season=2026)
    if not mal['malformed'] or s2['synchronized']:
        issues.append(f'malformed recorded spread did not fail closed: {mal["malformed"]} {s2["synchronized"]}')
    return issues


def qc_stale_source():
    """A source older than the freshness budget fails closed, even with clean decisions."""
    clean = _dec([_g('2026_01_AAA_BBB', 1, PAST, 'AAA', 'BBB', 20, 10, 3.0)])
    fresh = app._nfl_ats_sync(clean, age_hours=1.0, last_refresh='x', season=2026)
    stale = app._nfl_ats_sync(clean, age_hours=1000.0, last_refresh='x', season=2026)
    issues = []
    if not fresh['synchronized']:
        issues.append(f'fresh clean source not synchronized: {fresh}')
    if stale['synchronized'] or 'freshness budget' not in (stale['reason'] or ''):
        issues.append(f'stale source not failed closed: {stale}')
    return issues


def qc_push_interrupts():
    """W,W,P,W -> current cover streak 1 (push breaks the strict cover streak), ordered by kickoff."""
    rows = [_g('2026_01_T_O1', 1, '2026-09-13', 'T', 'O1', 20, 10, 3.0),   # W
            _g('2026_02_T_O2', 2, '2026-09-20', 'T', 'O2', 20, 10, 3.0),   # W
            _g('2026_03_T_O3', 3, '2026-09-27', 'T', 'O3', 13, 10, 3.0),   # P (margin 3 == spread)
            _g('2026_04_T_O4', 4, '2026-10-04', 'T', 'O4', 20, 10, 3.0)]   # W
    dec = _dec(rows)
    rec = dec['per'].get('T', {})
    issues = []
    if rec.get('results') != [1, 1, 0, 1]:
        issues.append(f'sequence wrong (order/signs): {rec.get("results")}')
    if rec.get('cover_streak') != 1:
        issues.append(f'push did not interrupt: cover_streak={rec.get("cover_streak")} want 1')
    return issues


def qc_end_to_end_membership_and_order():
    """Through the real loader path (a published generation in a temp store, fresh checked_at):
    membership = cover streak >= 3, order is streak-desc then team-asc, and nothing model-derived can
    alter it (no model input exists)."""
    import fetch_nfl_games as fg
    from datetime import datetime, timezone
    issues = []
    rows = []
    # BIG (5 covers), MID (3 covers), TIE (3 covers), LOW (2 covers -> excluded)
    plan = {'BIG': [1, 1, 1, 1, 1], 'MID': [1, 1, 1], 'TIE': [1, 1, 1], 'LOW': [1, 1]}
    for team, signs in plan.items():
        for i, _s in enumerate(signs, 1):
            # home win by 10 vs spread 3 => cover (+1)
            rows.append(_g(f'2026_0{i}_{team}_OP{i}', i, f'2026-09-{10+i:02d}', team, f'OP{team}{i}', 20, 10, 3.0))
    with tempfile.TemporaryDirectory() as root:
        now = datetime.now(timezone.utc)
        fg.publish_generation(pd.DataFrame(rows), now, '(qc)', None, None,
                              {'current_season': 2026, 'current_season_rows': len(rows),
                               'completed_games': len(rows), 'distinct_teams': 32, 'max_week': 18},
                              root=root, now_utc=now)
        res = app.build_nfl_ats_wave(now_et=NOW, games_root=root)
    sync = res['sync']
    if not sync['synchronized']:
        return [f'controlled fresh fixture not synchronized: {sync.get("reason")}']
    teams = [m['team'] for m in res['members']]
    if set(teams) != {'BIG', 'MID', 'TIE'}:
        issues.append(f'membership not cover-streak>=3: {teams}')
    streaks = [m['streak'] for m in res['members']]
    if streaks != sorted(streaks, reverse=True):
        issues.append(f'not streak-desc: {streaks}')
    tie = [m['team'] for m in res['members'] if m['streak'] == 3]
    if tie != sorted(tie):
        issues.append(f'tie not broken by team-asc (deterministic, model-independent): {tie}')
    if res['members'] and res['members'][0]['team'] != 'BIG':
        issues.append('highest streak not on top')
    return issues


CHECKS = [('season_gate_and_unavailable', qc_season_gate_and_unavailable),
          ('recorded_spread_signs', qc_recorded_spread_signs), ('reciprocity', qc_reciprocity),
          ('event_completeness', qc_event_completeness),
          ('duplicate_and_malformed', qc_duplicate_and_malformed), ('stale_source', qc_stale_source),
          ('push_interrupts', qc_push_interrupts),
          ('end_to_end_membership_and_order', qc_end_to_end_membership_and_order)]


def main() -> int:
    print('=' * 60)
    print('BANKROLL KINGS NFL ACTIVE ATS WAVE QC')
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
    print(f'FAIL: {failed}' if failed else 'NFL Active ATS Wave verified.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
