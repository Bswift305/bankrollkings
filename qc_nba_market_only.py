"""QC: NBA/WNBA market-only board while the NBA.com data-rights gate is OFF (docs/legal_ip_audit.md).

Proves the stats-free Odds-API-only fallback: (1) market rows render while every NBA-stat loader is
gated; (2) no NBA-derived statistic or cached snapshot appears; (3) every quote carries book + capture
time + source; (4) no authority fields/ordering; (5) the market-only record is independent of the
NBA-stats gate (enabling stats later does not change it); (6) NBA and WNBA are tested independently.

Uses controlled fixtures (no production data). Exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import os
import pandas as pd

import app
from services.nba_source_gate import nba_stats_enabled

AUTHORITY = ['>Confidence<', '>Tier<', '>Edge<', '>EV<', '>Fair<', '>Model<', 'PropScore', 'Hit Rate',
             'Recommend', 'Best Over', 'Best Under']
APPROVED_HEADERS = ['Matchup', 'Player', 'Prop', 'Line', 'Book', 'Over', 'Under', 'Book Updated']


def qc_source_parser_no_merge():
    """Source-pipeline proof: drive the ACTUAL Odds API parser (fetch_player_props.parse_market_rows)
    with two books quoting the same player at different lines, different Over/Under prices, one missing
    side, and different bookmaker update times. Prove each board row preserves one book + one exact line
    + its own two sides + its own book-update time, with NO cross-book or cross-line merging."""
    import fetch_player_props as fpp
    issues = []
    mk = 'player_points'
    event = {'id': 'evt1', 'home_team': 'Celtics', 'away_team': 'Lakers',
             'commence_time': '2099-01-01T23:00:00Z'}
    book_a = {'key': 'draftkings', 'title': 'DraftKings', 'last_update': '2099-01-01T12:00:00Z',
              'markets': [{'key': mk, 'outcomes': [
                  {'name': 'Over', 'description': 'A. Player', 'point': 24.5, 'price': -110},
                  {'name': 'Under', 'description': 'A. Player', 'point': 24.5, 'price': -108}]}]}
    book_b = {'key': 'fanduel', 'title': 'FanDuel', 'last_update': '2099-01-01T12:07:00Z',
              'markets': [{'key': mk, 'outcomes': [
                  {'name': 'Over', 'description': 'A. Player', 'point': 25.5, 'price': -120}]}]}  # no Under
    src = fpp.parse_market_rows(event, book_a, [mk]) + fpp.parse_market_rows(event, book_b, [mk])
    feed = pd.DataFrame(src)
    board = app.build_market_only_board(lambda **k: (feed.copy(), {'books': ['DraftKings', 'FanDuel']}))
    rows = board['rows']
    by_book = {r['book']: r for r in rows}
    if len(rows) != 2 or set(by_book) != {'DraftKings', 'FanDuel'}:
        return ['source parser produced wrong per-book rows: ' + str([(r['book'], r['line']) for r in rows])]
    a, b = by_book['DraftKings'], by_book['FanDuel']
    # each row keeps its OWN line + OWN two sides (no cross-book/cross-line merge)
    if a['line'] != 24.5 or a['over_odds'] != -110 or a['under_odds'] != -108:
        issues.append(f'DraftKings row merged/incorrect: {a}')
    if b['line'] != 25.5 or b['over_odds'] != -120 or b['under_odds'] is not None:
        issues.append(f'FanDuel row merged/incorrect (missing side must stay None): {b}')
    # different bookmaker update times preserved (not collapsed)
    if not a['book_updated_at'] or not b['book_updated_at'] or a['book_updated_at'] == b['book_updated_at']:
        issues.append(f'bookmaker update times not preserved distinctly: {a["book_updated_at"]} / {b["book_updated_at"]}')
    return issues


def _fixture(sport):
    base = {c: '' for c in ['Player', 'Team', 'Stat', 'MarketKey', 'Line', 'Game', 'Book', 'LastUpdated',
                            'OverOdds', 'UnderOdds']}
    r1 = dict(base, Player=f'{sport} PLAYER ONE', Team='LAL', Stat='Points', Line=24.5, Game='LAL @ BOS',
              Book='DraftKings', OverOdds=-110, UnderOdds=-110, LastUpdated='2099-01-01 12:00')
    r2 = dict(base, Player=f'{sport} GUARD TWO', Team='MIA', Stat='Assists', Line=6.5, Game='MIA @ NYK',
              Book='FanDuel', OverOdds=-115, UnderOdds='', LastUpdated='2099-01-01 12:05')  # missing under
    return pd.DataFrame([r1, r2])


def _owner_client():
    c = app.app.test_client()
    with c.session_transaction() as s:
        s['user_id'] = 'qc-owner'
        s['user_email'] = next(iter(app.OWNER_EMAILS))
    return c


def run_qc():
    issues, notes = [], []
    os.environ.pop('BK_NBA_STATS_ENABLED', None)  # gate OFF
    if nba_stats_enabled():
        return {'issues': ['NBA gate is ON; market-only path not exercised'], 'notes': notes}

    nba_fx, wnba_fx = _fixture('NBA'), _fixture('WNBA')
    app.load_live_props_feed = lambda **k: (nba_fx.copy(), {'books': ['DraftKings', 'FanDuel'], 'as_of': 'fixture'})
    app.load_wnba_live_props_feed = lambda **k: (wnba_fx.copy(), {'books': ['DraftKings'], 'as_of': 'fixture'})

    # (1) + (3) + (4) build-level: rows render; each carries book/capture/source; neutral order; approved fields only
    board = app.build_market_only_board(app.load_live_props_feed)
    rows = board['rows']
    if len(rows) != 2:
        issues.append(f'market-only build produced {len(rows)} rows (want 2)')
    for r in rows:
        if not r.get('book') or not r.get('book_updated_at') or r.get('source') != 'Odds API (licensed)':
            issues.append(f'row missing book/book-updated/source lineage: {r.get("player")}')
        extra = set(r.keys()) - {'player', 'game', 'book', 'stat', 'line', 'over_odds', 'under_odds',
                                 'book_updated_at', 'book_updated_tz_known', 'source'}
        if extra:
            issues.append(f'row carries non-approved fields: {extra}')
    # source-pipeline proof: real parser, two books, no cross-book/cross-line merge, distinct book times
    issues += qc_source_parser_no_merge()
    if not any('source parser' in i or 'merged' in i or 'update times' in i for i in issues):
        notes.append('source parser (parse_market_rows): per-book, per-line two-sided quotes preserved; '
                     'missing side kept None; distinct bookmaker update times; no merging')
    # missing side preserved as None (not synthesized)
    g2 = [r for r in rows if 'GUARD TWO' in r['player']]
    if g2 and g2[0]['under_odds'] is not None:
        issues.append('missing Under side was synthesized instead of left None')
    # neutral order: (game, player, stat)
    if [r['game'] for r in rows] != sorted(r['game'] for r in rows):
        issues.append('rows not in neutral (matchup) order')
    notes.append('market-only build: 2 rows, lineage present, missing side preserved, neutral order')

    # (1 render) + (2) + (4 render): gate the stat loaders, render the page, check no stats/authority
    for name in ('load_gamelogs', 'load_player_tracking', 'load_player_advanced', 'load_player_snapshot'):
        df = getattr(app, name)()
        if df is None or not df.empty:
            issues.append(f'{name} not gated empty while market-only active')
    if app.load_runtime_snapshot('nba_props_postseason_today_current') is not None:
        issues.append('an NBA runtime snapshot served while gated (bypass)')

    import re
    c = _owner_client()
    for path, label in (('/sports/nba/props', 'NBA'), ('/sports/wnba/props', 'WNBA')):  # (6) independent
        r = c.get(path)
        h = r.get_data(as_text=True)
        if r.status_code != 200:
            issues.append(f'{path} returned {r.status_code}')
            continue
        if f'{label} statistical context is temporarily unavailable' not in h:
            issues.append(f'{path} missing the required market-only label')
        if f'{label} PLAYER ONE' not in h:
            issues.append(f'{path} did not render the fixture market rows')
        if 'are not recommendations' not in h:
            issues.append(f'{path} missing the "not recommendations" statement')
        # Board-scoped proof (2 & 4): the ONLY table on this page is the market-only board; its column
        # headers must be EXACTLY the approved market facts -- no stat or authority columns. (The shared
        # shell nav contains unrelated tool names like "Heat Map", which are not board columns.)
        headers = [m.strip() for m in re.findall(r'<th(?:\s[^>]*)?>(.*?)</th>', h, re.S | re.I)]
        if headers != APPROVED_HEADERS:
            issues.append(f'{path} table headers are not the approved market-only set: {headers}')
    notes.append('NBA + WNBA market-only pages render rows; table columns are exactly the approved '
                 'market facts (no stat/authority columns), with the required label')

    # (5) independence of the market-only record from the NBA-stats gate
    os.environ['BK_NBA_STATS_ENABLED'] = '1'
    board_on = app.build_market_only_board(app.load_live_props_feed)
    os.environ.pop('BK_NBA_STATS_ENABLED', None)
    if board_on['rows'] != rows:
        issues.append('market-only record changed when the stats gate flipped (should be independent)')
    else:
        notes.append('market-only record is identical regardless of the NBA-stats gate state (test 5)')

    if not issues:
        notes.append('market-only board verified: licensed Odds facts only, no NBA.com stats or authority')
    return {'issues': issues, 'notes': notes}


def main() -> int:
    report = run_qc()
    print('=' * 60)
    print('BANKROLL KINGS NBA/WNBA MARKET-ONLY BOARD QC')
    print('=' * 60)
    for n in report['notes']:
        print(f'[NOTE] {n}')
    if report['notes']:
        print()
    if not report['issues']:
        print('Market-only board verified.')
        return 0
    for m in report['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
