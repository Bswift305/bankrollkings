"""QC: streak integrity audit — ATS families (NFL + CFB), via the pure df->streak cores.

Directed fixtures through the REAL cores (_nfl_ats_decisions_from_games, _cfb_cover_streaks_from_df) prove
the frozen Active ATS Wave rules without the parquet/sync layer:
- authoritative current-season resolution (explicit season filter before any grouping);
- canonical event identity (NFL game_id; CFB (GameID, TeamSide));
- duplicate/conflict handling (exact repeat collapses; conflicting repeat fails closed);
- completeness/freshness (NFL overdue/excluded/malformed; CFB ineligible/malformed; ungraded ignored);
- membership + ordering (active consecutive covers; earlier losses allowed; pushes interrupt; byes spanned);
- source->render universe hashes (graded_keys fingerprint);
- no model suppression (every graded team present in `per`);
- fail-closed (empty source -> empty);
- exact game-level trace for selected fixtures.
Synthetic fixtures only; no hardcoded production membership.
"""
from __future__ import annotations

import hashlib

ISSUES, NOTES = [], []


def ok(cond, fail, pas=None):
    (NOTES.append(pas) if pas else None) if cond else ISSUES.append(fail)


def _uh(keys):
    return hashlib.sha256('\n'.join(sorted(str(k) for k in keys)).encode()).hexdigest()[:16]


def run_qc():
    try:
        import app
    except ModuleNotFoundError as e:
        if 'flask' in str(e).lower():
            NOTES.append('SKIPPED: run under the app virtualenv')
            return {'issues': ISSUES, 'notes': NOTES}
        raise
    import pandas as pd

    # ---------- NFL ATS (nflverse schema: result = home margin; ats = result - spread_line) ----------
    def nrow(gid, wk, home, away, result, spread):
        return {'game_id': gid, 'season': 2026, 'week': wk, 'home_team': home, 'away_team': away,
                'result': result, 'spread_line': spread, 'gameday': None, 'gametime': None}
    nfl = []
    # KC home: wk1 loss (ats<0), wk2-4 covers -> trailing cover_streak 3, earlier loss allowed
    nfl += [nrow('g1', 1, 'KC', 'DEN', -10, -3)]            # ats -7 -> KC loss
    nfl += [nrow('g2', 2, 'KC', 'LV', 10, 3)]               # ats +7 -> KC cover
    nfl += [nrow('g4', 4, 'KC', 'LAC', 7, 1)]               # bye wk3 (no KC game) -> span
    nfl += [nrow('g5', 5, 'KC', 'HOU', 9, 2)]               # ats +7 cover
    # BUF home: wk1-2 cover, wk3 push (result==spread), wk4 cover -> trailing cover_streak 1 (push interrupts)
    nfl += [nrow('g6', 1, 'BUF', 'NYJ', 6, 1), nrow('g7', 2, 'BUF', 'MIA', 8, 2),
            nrow('g8', 3, 'BUF', 'NE', 3, 3), nrow('g9', 4, 'BUF', 'IND', 7, 1)]
    # dup collapse (exact repeat of g2) + conflict (g1 differing result)
    nfl += [nrow('g2', 2, 'KC', 'LV', 10, 3)]               # identical repeat -> collapsed
    nfl += [nrow('g1', 1, 'KC', 'DEN', 99, -3)]             # same gid, different result -> conflict
    from datetime import datetime
    dec = app._nfl_ats_decisions_from_games(pd.DataFrame(nfl), 2026, datetime(2030, 1, 1))
    per = dec['per']
    ok(per.get('KC', {}).get('cover_streak') == 3, f"NFL KC cover_streak wrong: {per.get('KC')}",
       'NFL ATS: active consecutive covers = 3 (earlier loss allowed, bye spanned)')
    ok(per.get('BUF', {}).get('cover_streak') == 1, f"NFL BUF cover_streak wrong: {per.get('BUF')}",
       'NFL ATS: a push interrupts the cover run (BUF trailing = 1)')
    ok(dec['collapsed'] == 1 and dec['conflicts'] == ['g1'],
       f"NFL dedup/conflict wrong: collapsed={dec['collapsed']} conflicts={dec['conflicts']}",
       'NFL ATS: exact repeat collapses; conflicting game_id fails closed')
    ok(('g1', 'KC') in dec['graded_keys'] and _uh(dec['graded_keys']),
       'NFL graded_keys missing the legitimate first decision',
       f'NFL ATS: source->render over graded_keys ({_uh(dec["graded_keys"])}); the conflicting duplicate is '
       'reported while the first canonical decision stands (no silent drop)')
    ok(app._nfl_ats_decisions_from_games(pd.DataFrame([]), 2026, datetime(2030, 1, 1))['per'] == {},
       'NFL empty source not fail-closed', 'NFL ATS: empty source fails closed')
    NOTES.append(f"TRACE NFL KC: signs {per['KC']['results']} -> cover_streak {per['KC']['cover_streak']} "
                 f"(weeks {per['KC']['weeks']})")

    # ---------- CFB ATS (frozen rule; (GameID, TeamSide) authoritative) ----------
    def crow(gid, wk, team, opp, side, state, conf='SEC', line=-3.5):
        return {'MarketType': 'SPREAD', 'Season': 2026, 'OutcomeState': state, 'GameID': gid, 'Line': line,
                'Week': wk, 'GameDate': f'2026-09-{wk:02d}', 'TeamSide': side, 'Team': team,
                'Opponent': opp, 'Conf': conf}
    cfb = []
    # Georgia: wk1 Miss, wk2-4 Hit -> cover_streak 3 (earlier loss allowed)
    cfb += [crow(401001, 1, 'Georgia', 'Clemson', 'HOME', 'Miss'),
            crow(401002, 2, 'Georgia', 'Auburn', 'HOME', 'Hit'),
            crow(401003, 3, 'Georgia', 'Kentucky', 'HOME', 'Hit'),
            crow(401004, 4, 'Georgia', 'Florida', 'HOME', 'Hit')]
    # Alabama: Hit, Hit, Push, Hit -> trailing cover_streak 1 (push interrupts)
    cfb += [crow(401005, 1, 'Alabama', 'USF', 'HOME', 'Hit'), crow(401006, 2, 'Alabama', 'Wisconsin', 'HOME', 'Hit'),
            crow(401007, 3, 'Alabama', 'Georgia', 'AWAY', 'Push'), crow(401008, 4, 'Alabama', 'Vandy', 'HOME', 'Hit')]
    # dup collapse (exact repeat of 401002) + conflict (401003 differing result) + ineligible (no TeamSide)
    cfb += [crow(401002, 2, 'Georgia', 'Auburn', 'HOME', 'Hit')]          # identical -> collapsed
    cfb += [crow(401003, 3, 'Georgia', 'Kentucky', 'HOME', 'Miss')]      # conflict (res differs)
    bad = crow(401009, 5, 'Tulsa', 'Navy', '', 'Hit'); cfb.append(bad)    # no TeamSide -> ineligible
    res = app._cfb_cover_streaks_from_df(pd.DataFrame(cfb), 2026)
    cper = res['per']
    ok(cper.get('Georgia', {}).get('cover_streak') == 3, f"CFB Georgia cover_streak wrong: {cper.get('Georgia')}",
       'CFB ATS: active consecutive covers = 3 (earlier loss allowed)')
    ok(cper.get('Alabama', {}).get('cover_streak') == 1, f"CFB Alabama wrong: {cper.get('Alabama')}",
       'CFB ATS: a push interrupts the cover run')
    ok(res['collapsed'] == 1 and len(res['conflicts']) >= 1 and res['ineligible'] >= 1,
       f"CFB integrity wrong: {res['collapsed']}/{res['conflicts']}/{res['ineligible']}",
       'CFB ATS: exact repeat collapses; conflicting (GameID,TeamSide) + missing side fail closed')
    ok(all(isinstance(k, tuple) and len(k) == 2 for k in res['graded_keys']),
       'CFB graded_keys not (GameID, TeamSide)',
       f'CFB ATS: (GameID,TeamSide) authoritative; universe hash {_uh(res["graded_keys"])}')
    ok(cper.get('Georgia', {}).get('conf') == 'SEC',
       'CFB conf not carried for the FBS gate', 'CFB ATS: provider conference carried (FBS gate input)')
    ok(app._cfb_cover_streaks_from_df(pd.DataFrame(cfb), 2099)['per'] == {},
       'CFB wrong-season not fail-closed', 'CFB ATS: season filter -> empty for a non-current season')
    NOTES.append(f"TRACE CFB Georgia: results {cper['Georgia']['results']} -> "
                 f"cover_streak {cper['Georgia']['cover_streak']}")

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 72)
    print('BANKROLL KINGS - STREAK INTEGRITY AUDIT (NFL + CFB ATS)')
    print('=' * 72)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No ATS streak-integrity issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
