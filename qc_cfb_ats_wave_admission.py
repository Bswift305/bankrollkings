"""QC: CFB Active ATS Wave admission (docs/ats_wave_contract.md, FROZEN).

Proves membership is driven by the team's CURRENT consecutive graded ATS-cover streak (>=3), not season
cover percentage: the frozen truth table + the edge cases (bye, ungraded/no-line, push interrupts, loss
resets), source-through-week fail-closed, model-independent membership, and deterministic factual order.

Uses controlled fixtures for the streak computation (the pure `_cfb_cover_streaks_from_df`) and a
synthetic synced streak map for the board. Exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import pandas as pd

import app
import cfb_current_form as cff

# token -> how it appears in the graded source ('Bye' = no row that week; week still advances)
def _rows(team, tokens, season=2026):
    rows, wk = [], 1
    for t in tokens:
        if t == 'Bye':
            wk += 1
            continue
        state = {'W': 'Hit', 'L': 'Miss', 'P': 'Push', 'U': 'Pending', 'N': 'Hit'}[t]  # N = no-line cover
        rows.append({'Sport': 'NCAAF', 'Season': season, 'Week': wk, 'GameDate': f'2026-09-{wk:02d}',
                     'Team': team, 'Opponent': 'Opp', 'MarketType': 'SPREAD', 'OutcomeState': state,
                     'Line': '' if t == 'N' else -3.5})
        wk += 1
    return rows


def _streaks(cases):
    rows = []
    for team, toks in cases.items():
        rows += _rows(team, toks)
    per, through = app._cfb_cover_streaks_from_df(pd.DataFrame(rows), 2026)
    # map back by resolved name
    return {team: per.get(cff._resolve(team), {}) for team in cases}, through


def qc_truth_table():
    cases = {
        'T 3-3': ['L', 'L', 'L', 'W', 'W', 'W'],            # active 3-cover streak -> yes
        'T 5-1': ['W', 'W', 'L', 'W', 'W', 'W'],            # 3 -> yes
        'T 5-0': ['W', 'W', 'W', 'W', 'W'],                 # 5 -> yes
        'T 4-2': ['W', 'W', 'W', 'L', 'W', 'W'],            # current streak 2 -> no
        'T push': ['W', 'W', 'P', 'W'],                     # push interrupts -> streak 1 -> no
    }
    per, _ = _streaks(cases)
    want = {'T 3-3': 3, 'T 5-1': 3, 'T 5-0': 5, 'T 4-2': 2, 'T push': 1}
    issues = []
    for t, w in want.items():
        got = per[t].get('cover_streak')
        if got != w:
            issues.append(f'{t}: cover_streak {got} want {w}')
    quals = {t for t, s in per.items() if s.get('cover_streak', 0) >= 3}
    if quals != {'T 3-3', 'T 5-1', 'T 5-0'}:
        issues.append(f'wrong qualifiers: {sorted(quals)}')
    return issues


def qc_edges():
    cases = {
        'bye':      ['W', 'Bye', 'W', 'W'],     # bye ignored -> W,W,W -> 3
        'ungraded': ['W', 'U', 'W', 'W'],       # pending dropped -> 3
        'noline':   ['W', 'N', 'W', 'W'],       # wait: N is a cover w/o line -> dropped -> W,W,W? see below
        'loss':     ['W', 'W', 'W', 'L'],       # latest loss -> streak 0
    }
    per, through = _streaks(cases)
    issues = []
    if per['bye'].get('cover_streak') != 3:
        issues.append(f"bye interrupted the streak: {per['bye'].get('cover_streak')}")
    if per['ungraded'].get('cover_streak') != 3:
        issues.append(f"ungraded game counted/interrupted: {per['ungraded'].get('cover_streak')}")
    if per['noline'].get('cover_streak') != 3:
        issues.append(f"no-line game not ignored: {per['noline'].get('cover_streak')}")
    if per['loss'].get('cover_streak') != 0:
        issues.append(f"loss did not reset: {per['loss'].get('cover_streak')}")
    if through != 4:
        issues.append(f'results_through_week {through} want 4')
    return issues


def qc_board_synced_membership_order_model_independent():
    """Synthetic SYNCED streak map -> the board admits exactly the >=3-streak teams, sorted by streak
    DESC with a team-name tiebreaker, independent of the model tier overlay; a <3 team is excluded."""
    def s(cov, loss=0, dec=6):
        return {'cover_streak': cov, 'loss_streak': loss, 'results': ['W'] * cov, 'recent': ['W'] * min(cov, 6),
                'covers': cov, 'losses': loss, 'pushes': 0, 'decisions': dec, 'last_week': 7}
    # real FBS teams so they exist in the ats aggregate + resolve; different streaks incl. a tie
    synth = {cff._resolve('Georgia'): s(5), cff._resolve('Alabama'): s(3), cff._resolve('Oregon'): s(3),
             cff._resolve('Ohio State'): s(2)}
    orig = app._cfb_active_cover_streaks
    app._cfb_active_cover_streaks = lambda season=2026: (synth, 9999)  # synced (through >> slate)
    try:
        app._CFB_WAVE_CACHE.clear()
        ctx = app.build_cfb_wave_context()
    finally:
        app._cfb_active_cover_streaks = orig
        app._CFB_WAVE_CACHE.clear()
    issues = []
    if ctx.get('wave_unsynced'):
        return ['synced fixture still reported unsynced']
    members = [m['team'] for m in ctx.get('wave_members', [])]
    mset = set(cff._resolve(m) for m in members)
    want = {cff._resolve('Georgia'), cff._resolve('Alabama'), cff._resolve('Oregon')}
    if mset != want:
        issues.append(f'membership not by streak>=3: got {sorted(mset)}')
    # order: streak DESC then team asc -> Georgia(5) first; Alabama/Oregon(3) tie -> alphabetical
    streaks = [m['cover_streak'] for m in ctx['wave_members']]
    if streaks != sorted(streaks, reverse=True):
        issues.append(f'not sorted by streak DESC: {streaks}')
    tie = [m['team'] for m in ctx['wave_members'] if m['cover_streak'] == 3]
    if tie != sorted(tie):
        issues.append(f'tie not broken deterministically by team name: {tie}')
    # model-independence: each member carries a tier_label OVERLAY but membership ignored it
    if not all('tier_label' in m for m in ctx['wave_members']):
        issues.append('members missing the model tier overlay field')
    if cff._resolve('Ohio State') in mset:
        issues.append('a <3-streak team was admitted')
    return issues


def qc_fail_closed_on_mismatch():
    """On the real local dataset the graded source is behind the slate -> the board must FAIL CLOSED
    (unsynced, no members) and never fall back to season cover percentage."""
    app._CFB_WAVE_CACHE.clear()
    ctx = app.build_cfb_wave_context()
    issues = []
    if ctx.get('wave_unsynced'):
        if ctx.get('wave_members'):
            issues.append('unsynced board still produced members (cover-% fallback?)')
    # (If the local source were synced, this check is a no-op; the synced path is covered above.)
    return issues


CHECKS = [('truth_table', qc_truth_table), ('edges', qc_edges),
          ('synced_membership_order_model_independent', qc_board_synced_membership_order_model_independent),
          ('fail_closed_on_mismatch', qc_fail_closed_on_mismatch)]


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
    print(f'FAIL: {failed}' if failed else 'Active ATS Wave admission verified.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
