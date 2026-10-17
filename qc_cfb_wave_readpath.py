"""QC: CFB Active ATS Wave READ-PATH validation (docs/cfb_runtime_data_corrective.md).

Companion to qc_cfb_ats_wave_admission.py. That suite proves the admission math on injected frames; THIS
suite proves the on-disk READ path is hardened: the runtime manifest (cfb_line_moves.json) and graded
results (NCAAF_GameLineResults.csv) are validated AGAIN when read, so a post-publication corruption --
invalid GameID / side / date / conference / team name, a duplicate identity, a mixed-schema frame, or a
truncated JSON/CSV -- produces the existing UNAVAILABLE state, never a 500 and never partial membership.

Each fixture is written to a private temp tree; app.DATA_DIR + BK_RUNTIME_DIR are pointed at it and the
module caches cleared, so the real app functions read the fixture exactly as production would. The
overlay (rankings / matchup form) is neutralized to no-ops because, by contract, it can change neither
membership nor ordering -- that keeps the valid-fixture byte-equivalence assertion deterministic.

Reads must NOT rewrite / repair / refetch / mutate: every fixture verifies the graded file's bytes are
untouched by a full read cycle. Controlled fixtures; exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from pathlib import Path

import pandas as pd

import app
import bk_runtime
import report_cfb_wave_sync as rep


# ---- production-shaped fixture builders -------------------------------------------------------------

def grow(gid, side, team, opp, state, wk, date, conf='SEC', line=-3.5):
    return {'Sport': 'NCAAF', 'Season': 2026, 'GameID': gid, 'TeamSide': side, 'Team': team,
            'Opponent': opp, 'Conf': conf, 'OppConf': 'Big Sky', 'Week': wk, 'GameDate': date,
            'MarketType': 'SPREAD', 'OutcomeState': state, 'Line': line}


def mgame(gid, home, away, wk, home_conf='SEC', away_conf='Big Sky', spread_now=-3.5, completed=True):
    return {'game_id': gid, 'home': home, 'away': away, 'week': wk, 'home_conf': home_conf,
            'away_conf': away_conf, 'spread_now': spread_now, 'completed': completed}


def _lm(games, season=2026, updated='2026-10-17 01:00 UTC'):
    return {'season': season, 'updated': updated, 'games': games}


_DATES = {1: '2026-09-05', 2: '2026-09-12', 3: '2026-09-19'}


def valid_three_cover(team, conf, gid0):
    """Three graded covers (weeks 1-3) for `team` vs an FCS opponent -> one FBS decision per game."""
    rows = [grow(str(gid0 + k), 'HOME', team, f'FCS{gid0 + k}', 'Hit', k, _DATES[k], conf=conf)
            for k in (1, 2, 3)]
    games = [mgame(str(gid0 + k), team, f'FCS{gid0 + k}', k, home_conf=conf, away_conf='Big Sky')
             for k in (1, 2, 3)]
    return rows, games


def valid_fixture():
    """Two FBS teams each on a 3-cover streak vs FCS opponents, plus a week-4 upcoming game that sets the
    slate week (so completed_week == 3). Golden ordering: ['Georgia', 'Oregon'] (streak 3 each, team asc)."""
    r1, g1 = valid_three_cover('Georgia', 'SEC', 400100)
    r2, g2 = valid_three_cover('Oregon', 'Big Ten', 400200)
    upcoming = mgame('400900', 'Georgia', 'Oregon', 4, home_conf='SEC', away_conf='Big Ten',
                     spread_now=-2.5, completed=False)
    return r1 + r2, _lm(g1 + g2 + [upcoming])


# ---- harness: point the real app functions at a temp tree -------------------------------------------

@contextlib.contextmanager
def _env(graded, manifest):
    """Materialize `graded` (list[dict] | raw str) + `manifest` (dict | raw str) into a temp tree, point
    app.DATA_DIR + BK_RUNTIME_DIR at it, neutralize the overlay, and clear caches. Restores everything."""
    import cfb_current_form as cff
    tmp = Path(tempfile.mkdtemp(prefix='bk_cfb_readpath_'))
    (tmp / 'tracking').mkdir(parents=True, exist_ok=True)
    (tmp / 'scenarios').mkdir(parents=True, exist_ok=True)
    gpath = tmp / 'tracking' / 'NCAAF_GameLineResults.csv'
    if isinstance(graded, str):
        gpath.write_text(graded, encoding='utf-8')
    elif isinstance(graded, (bytes, bytearray)):
        gpath.write_bytes(graded)
    else:
        pd.DataFrame(graded).to_csv(gpath, index=False)
    mpath = tmp / 'scenarios' / 'cfb_line_moves.json'
    if isinstance(manifest, str):
        mpath.write_text(manifest, encoding='utf-8')
    else:
        mpath.write_text(json.dumps(manifest), encoding='utf-8')

    saved = {'DATA_DIR': app.DATA_DIR, 'BK': os.environ.get('BK_RUNTIME_DIR'),
             'ranks': app._cfb_rankings, 'clear': cff.clear_cache,
             'matchup': getattr(cff, 'matchup_read', None), 'total': getattr(cff, 'total_read', None)}
    app.DATA_DIR = tmp
    os.environ['BK_RUNTIME_DIR'] = str(tmp)
    app._cfb_rankings = lambda: {}
    cff.clear_cache = lambda: None
    cff.matchup_read = lambda *a, **k: {}
    cff.total_read = lambda *a, **k: {}
    app._CFB_ATS_STREAK_CACHE.clear()
    app._CFB_WAVE_CACHE.clear()
    try:
        yield tmp, gpath
    finally:
        app.DATA_DIR = saved['DATA_DIR']
        if saved['BK'] is None:
            os.environ.pop('BK_RUNTIME_DIR', None)
        else:
            os.environ['BK_RUNTIME_DIR'] = saved['BK']
        app._cfb_rankings = saved['ranks']
        cff.clear_cache = saved['clear']
        if saved['matchup'] is not None:
            cff.matchup_read = saved['matchup']
        if saved['total'] is not None:
            cff.total_read = saved['total']
        app._CFB_ATS_STREAK_CACHE.clear()
        app._CFB_WAVE_CACHE.clear()


def _sync_like_reporter():
    """Reproduce the reporter's read -> sync, from whatever is on disk now."""
    lm = bk_runtime.read_json('cfb_line_moves.json', {})
    streak = app._cfb_active_cover_streaks(2026)
    games = lm.get('games') if isinstance(lm.get('games'), list) else []
    moves = [g for g in games if not g.get('completed') and g.get('spread_now') is not None]
    slate_week = min((g['week'] for g in moves), default=None)
    completed_week = (slate_week - 1) if slate_week else None
    return app._cfb_ats_sync(streak, lm, completed_week, 2026)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---- corruption fixtures ----------------------------------------------------------------------------

def _corruption_case(label, mutate_graded=None, mutate_manifest=None, graded_override=None,
                     manifest_override=None, expect_counter=None, expect_read_error=False):
    """Start from the single-team valid base (Georgia 3-0 vs FCS, slate wk4), apply one corruption, and
    assert the FULL fail-closed invariant on the REAL read path."""
    rows, games = valid_three_cover('Georgia', 'SEC', 400100)
    manifest = _lm(games + [mgame('400900', 'Georgia', 'Tenn', 4, away_conf='SEC', spread_now=-2.5,
                                  completed=False)])
    if mutate_graded is not None:
        mutate_graded(rows)
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    graded = graded_override if graded_override is not None else rows
    manifest = manifest_override if manifest_override is not None else manifest
    issues = []
    with _env(graded, manifest) as (_tmp, gpath):
        before = _digest(gpath)
        # 1) the read path must not raise (no 500) at any layer
        try:
            sync = _sync_like_reporter()
            ctx = app.build_cfb_wave_context()
        except Exception as exc:                       # pragma: no cover - this IS the failure we guard
            return [f'{label}: read path raised {type(exc).__name__}: {exc}']
        # 2) fail closed, never synchronized
        if sync.get('synchronized'):
            issues.append(f'{label}: synchronized True on corrupt data')
        # 3) reporter exits nonzero
        rc, _bad = rep.evaluate_closure(sync, (0 if sync.get('synchronized') else None), False)
        if rc == 0:
            issues.append(f'{label}: reporter evaluate_closure returned 0')
        # 4) never partial membership
        if not ctx.get('wave_unsynced') or ctx.get('wave_members'):
            issues.append(f'{label}: context not fail-closed (unsynced={ctx.get("wave_unsynced")}, '
                          f'members={len(ctx.get("wave_members") or [])})')
        # 5) targeted counter / read_error, where deterministic
        if expect_counter and not sync.get(expect_counter):
            issues.append(f'{label}: expected counter {expect_counter} > 0, sync={sync.get(expect_counter)}')
        if expect_read_error and not sync.get('read_error'):
            issues.append(f'{label}: expected read_error to be set, got None')
        # 6) no rewrite/repair/refetch/mutation during reads
        if _digest(gpath) != before:
            issues.append(f'{label}: graded file MUTATED during read')
    return issues


def qc_invalid_gameid():
    return _corruption_case('invalid_gameid',
                            mutate_graded=lambda rows: rows[1].__setitem__('GameID', 'not-an-id'),
                            expect_counter='malformed_rows')


def qc_invalid_side():
    return _corruption_case('invalid_side',
                            mutate_graded=lambda rows: rows[1].__setitem__('TeamSide', 'MIDDLE'),
                            expect_counter='ineligible')


def qc_invalid_date():
    # Exercises the NEW read-path date gate: a present-but-unparseable date -> malformed, not silently kept.
    return _corruption_case('invalid_date',
                            mutate_graded=lambda rows: rows[1].__setitem__('GameDate', 'not-a-date'),
                            expect_counter='malformed_rows')


def qc_invalid_conference():
    return _corruption_case('invalid_conference',
                            mutate_manifest=lambda m: m['games'][0].__setitem__('home_conf', 'Narnia'),
                            expect_counter='unknown_conference')


def qc_invalid_team_name():
    return _corruption_case('invalid_team_name',
                            mutate_graded=lambda rows: rows[1].__setitem__('Team', ''),
                            expect_counter='ineligible')


def qc_duplicate_identity():
    # A second graded row for the same (GameID, HOME) with a conflicting result -> conflicting duplicate.
    def _dup(rows):
        rows.append(grow(rows[0]['GameID'], 'HOME', 'Georgia', rows[0]['Opponent'], 'Miss',
                         rows[0]['Week'], rows[0]['GameDate']))
    return _corruption_case('duplicate_identity', mutate_graded=_dup,
                            expect_counter='conflicting_duplicates')


def qc_mixed_schema_csv():
    # Valid CSV, but missing required columns -> schema gate fails closed (NOT a KeyError/500).
    return _corruption_case('mixed_schema_csv', graded_override='foo,bar\n1,2\n3,4\n',
                            expect_read_error=True)


def qc_truncated_csv():
    # Null-byte / garbage payload: pd.read_csv raises -> contained -> read_error, never a 500.
    return _corruption_case('truncated_csv', graded_override=b'\x00\x00\x00\x00bad,data\n"unterminated',
                            expect_read_error=True)


def qc_truncated_json_manifest():
    # Truncated JSON -> read_json returns {} -> manifest schema invalid -> read_error, fail closed.
    return _corruption_case('truncated_json', manifest_override='{"season": 2026, "games": [ {"gam',
                            expect_read_error=True)


def qc_missing_graded_file():
    # Absent graded file (a 'missing runtime data' case) -> unavailable, not a 500.
    rows, games = valid_three_cover('Georgia', 'SEC', 400100)
    manifest = _lm(games + [mgame('400900', 'Georgia', 'Tenn', 4, away_conf='SEC', spread_now=-2.5,
                                  completed=False)])
    issues = []
    with _env([], manifest) as (tmp, gpath):
        os.remove(gpath)                               # genuinely absent
        app._CFB_ATS_STREAK_CACHE.clear()
        try:
            sync = _sync_like_reporter()
            ctx = app.build_cfb_wave_context()
        except Exception as exc:
            return [f'missing_graded_file: read path raised {type(exc).__name__}: {exc}']
    if sync.get('synchronized') or not sync.get('read_error'):
        issues.append(f'missing_graded_file: not fail-closed with read_error: {sync.get("read_error")}')
    if not ctx.get('wave_unsynced') or ctx.get('wave_members'):
        issues.append('missing_graded_file: context not fail-closed')
    return issues


# ---- valid fixture: byte-equivalent membership + ordering, and no mutation --------------------------

def qc_valid_membership_byte_equivalent():
    graded, manifest = valid_fixture()
    issues = []
    with _env(graded, manifest) as (_tmp, gpath):
        before = _digest(gpath)
        ctx1 = app.build_cfb_wave_context()
        app._CFB_ATS_STREAK_CACHE.clear()
        app._CFB_WAVE_CACHE.clear()
        ctx2 = app.build_cfb_wave_context()
        after = _digest(gpath)
    if ctx1.get('wave_unsynced') or ctx2.get('wave_unsynced'):
        return [f'valid fixture did not synchronize: {ctx1.get("wave_sync", {}).get("reason")}']
    m1 = ctx1.get('wave_members') or []
    m2 = ctx2.get('wave_members') or []
    order1 = [m['team'] for m in m1]
    if order1 != ['Georgia', 'Oregon']:
        issues.append(f'golden ordering wrong: {order1}')
    if order1 != [m['team'] for m in m2]:
        issues.append(f'non-deterministic ordering across reads: {order1} vs {[m["team"] for m in m2]}')
    if m1 != m2:
        issues.append('member records not byte-equivalent across identical reads')
    for m in m1:
        if m.get('cover_streak') != 3:
            issues.append(f'{m.get("team")}: cover_streak {m.get("cover_streak")} != 3')
    if before != after:
        issues.append('valid read cycle MUTATED the graded file')
    return issues


CHECKS = [
    ('invalid_gameid', qc_invalid_gameid),
    ('invalid_side', qc_invalid_side),
    ('invalid_date', qc_invalid_date),
    ('invalid_conference', qc_invalid_conference),
    ('invalid_team_name', qc_invalid_team_name),
    ('duplicate_identity', qc_duplicate_identity),
    ('mixed_schema_csv', qc_mixed_schema_csv),
    ('truncated_csv', qc_truncated_csv),
    ('truncated_json_manifest', qc_truncated_json_manifest),
    ('missing_graded_file', qc_missing_graded_file),
    ('valid_membership_byte_equivalent', qc_valid_membership_byte_equivalent),
]


def main():
    print('=' * 60)
    print('BANKROLL KINGS CFB ATS WAVE READ-PATH QC')
    print('=' * 60)
    failed = 0
    for name, fn in CHECKS:
        try:
            issues = fn()
        except Exception as exc:
            issues = [f'{name} raised during QC harness: {type(exc).__name__}: {exc}']
        if issues:
            failed += 1
            print(f'[FAIL] {name}')
            for i in issues:
                print(f'       - {i}')
        else:
            print(f'[PASS] {name}')
    print('-' * 60)
    if failed:
        print(f'{failed} read-path check(s) FAILED.')
        return 1
    print('CFB ATS Wave read-path hardening verified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
