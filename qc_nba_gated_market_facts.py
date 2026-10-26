"""QC: NBA Command Center gated-stub licensed market facts (Decision 2 — Data-Pulse contradiction fix).

While BK_NBA_STATS_ENABLED=0 the Command Center must keep every restricted statistic gated, but must NOT
deny the ungated licensed market board. The gated stub now carries `nba_market_facts` — honest Odds-API
quote counts from the SAME feed as market_only_board, with quote rows distinguished from prop markets and
'Unavailable' (not zero) where a count can't be derived. Proves: (1) restricted data absent; (2) counts
AGREE with the market-only board; (3) quotes != props; (4) empty feed -> honest empty state; (5)
Unavailable-not-zero; (6) gate-on path untouched; (7) no zero-filled contradiction in the template; and
that no provider/paid fetch is used.
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "qc-only-not-a-real-secret")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd  # noqa: E402
import app  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


# Synthetic licensed feed: 8 quote rows, 4 prop markets, 2 games, 4 teams, 2 books.
FEED_ROWS = [
    # DET@PHI
    ('Ausar Thompson', 'DET@PHI', 'DraftKings', 'AST', 4.5, 111, -147),
    ('Ausar Thompson', 'DET@PHI', 'FanDuel', 'AST', 4.5, 118, -158),
    ('Ausar Thompson', 'DET@PHI', 'DraftKings', 'PTS', 11.5, -111, -115),
    ('Ausar Thompson', 'DET@PHI', 'FanDuel', 'PTS', 10.5, -128, -104),
    ('Cade Cunningham', 'DET@PHI', 'DraftKings', '3PM', 2.5, 129, -170),
    ('Cade Cunningham', 'DET@PHI', 'FanDuel', '3PM', 2.5, 132, -178),
    # ORL@NYK
    ('Franz Wagner', 'ORL@NYK', 'DraftKings', 'STL', 1.5, 120, -150),
    ('Franz Wagner', 'ORL@NYK', 'FanDuel', 'STL', 1.5, 118, -158),
]
COLS = ['Player', 'Game', 'Book', 'Stat', 'Line', 'OverOdds', 'UnderOdds']


def _feed(rows):
    df = pd.DataFrame([dict(zip(COLS, r)) for r in rows])
    if not df.empty:
        df['LastUpdated'] = '2026-10-25 13:05'
    return lambda require_fresh=False: (df, {})   # meta has no 'books' -> exercises the row-derived fallback


def _with_feed(rows, fn):
    orig = app.load_live_props_feed
    app.load_live_props_feed = _feed(rows)
    try:
        return fn()
    finally:
        app.load_live_props_feed = orig


def test_restricted_absent_in_stub():
    print("\n[A] gated stub keeps restricted statistics absent; only market COUNTS added")
    stub = _with_feed(FEED_ROWS, lambda: app._nba_command_center_gated_stub(False))
    check(stub['nba_gated'] is True, "nba_gated True")
    check(stub['total_props'] == 0 and stub['teams'] == [] and stub['top_plays'] == []
          and stub['role_changes'] == [] and stub['best_by_series'] == [],
          "stats-derived fields stay empty (total_props/teams/top_plays/role_changes/best_by_series)")
    mf = stub['nba_market_facts']
    check(set(mf) <= {'available', 'quote_rows', 'prop_markets', 'games', 'teams', 'books', 'as_of'},
          "nba_market_facts has ONLY count/label keys (%r)" % sorted(mf))
    # no statistics/averages/model/boost leaked into the facts
    blob = repr(mf).lower()
    check(all(bad not in blob for bad in ('avg', 'average', 'boost', 'proj', 'model', 'pct', 'odds')),
          "no averages/boost/projection/model/odds fields in the market facts")


def test_counts_agree_with_board():
    print("\n[B] licensed market counts AGREE with build_market_only_board (same feed)")
    def go():
        mf = app._nba_gated_market_facts()
        board = app.build_market_only_board(app.load_live_props_feed)
        rows = board['rows']
        games = {r['game'] for r in rows if r['game']}
        props = {(r['game'], r['player'], r['stat']) for r in rows if r['player'] and r['stat']}
        teams = set()
        for g in games:
            teams.update(p.strip() for p in g.split('@'))
        return mf, len(rows), len(games), len(props), len(teams)
    mf, n_rows, n_games, n_props, n_teams = _with_feed(FEED_ROWS, go)
    check(mf['available'] is True, "facts available with a populated feed")
    check(mf['quote_rows'] == n_rows == 8, "quote_rows == board rows (%s)" % mf['quote_rows'])
    check(mf['games'] == n_games == 2, "games agree (%s)" % mf['games'])
    check(mf['prop_markets'] == n_props == 4, "prop_markets == distinct (game,player,stat) (%s)" % mf['prop_markets'])
    check(mf['teams'] == n_teams == 4, "teams agree (%s)" % mf['teams'])
    check(mf['books'] == 2, "books derived from rows when meta lacks them (%s)" % mf['books'])


def test_quotes_not_props():
    print("\n[C] quote rows are DISTINGUISHED from prop markets (never '728 props')")
    mf = _with_feed(FEED_ROWS, app._nba_gated_market_facts)
    check(mf['quote_rows'] > mf['prop_markets'],
          "quote_rows (%s) > prop_markets (%s) — quotes are not mislabeled as props"
          % (mf['quote_rows'], mf['prop_markets']))


def test_empty_feed_honest():
    print("\n[D] empty feed -> available False (template keeps its honest empty state)")
    mf = _with_feed([], app._nba_gated_market_facts)
    check(mf == {'available': False}, "empty feed -> {'available': False} (%r)" % mf)


def test_unavailable_not_zero():
    print("\n[E] a count that can't be derived reliably -> None ('Unavailable'), not 0")
    # a game string with no clean 2-team '@' split -> teams Unavailable
    bad = [('P1', 'TBD', 'DraftKings', 'PTS', 10.5, -110, -110)]
    mf = _with_feed(bad, app._nba_gated_market_facts)
    check(mf['available'] is True and mf['teams'] is None, "teams is None (Unavailable), not 0 (%r)" % mf['teams'])
    check(mf['games'] == 1 and mf['quote_rows'] == 1, "other derivable counts still correct")


def test_gate_on_untouched():
    print("\n[F] gate-on path untouched — nba_gated/nba_market_facts only come from the gated stub")
    src = open(os.path.join(HERE, 'app.py'), encoding='utf-8').read()
    # nba_market_facts is populated only while gated: once in the stub, and recomputed LIVE in the two
    # authed routes — each guarded by `if nba_context.get('nba_gated'):` so gate-ON never gets it.
    check(src.count("'nba_market_facts':") == 3, "nba_market_facts set in 3 gated places (stub + 2 route recomputes)")
    check(src.count("'nba_market_facts': _nba_gated_market_facts()") == 3,
          "every nba_market_facts assignment uses the licensed-feed helper (stub + 2 routes)")
    check(src.count("if nba_context.get('nba_gated'):") == 2,
          "the 2 live route recomputes are each guarded by nba_gated (gate-ON never gets market facts)")
    check(src.count("'nba_gated': True") == 1, "nba_gated True set only in the gated stub")
    # the helper reads ONLY the licensed feed/board — no gamelog/tracking/network
    body = src.split('def _nba_gated_market_facts', 1)[1].split('def _nba_command_center_gated_stub', 1)[0]
    check('build_market_only_board(load_live_props_feed)' in body, "uses the licensed market feed only")
    for bad in ('load_gamelogs', 'load_player', 'requests.', 'urlopen', 'nba_api', 'stats.nba.com'):
        check(bad not in body, "no network / NBA.com-stats call in the helper (%s)" % bad)


def test_template_no_zero_contradiction():
    print("\n[G] dashboard.html: gated shows labeled market facts; no '0/No plays' contradiction; gate-on intact")
    t = open(os.path.join(HERE, 'templates', 'dashboard.html'), encoding='utf-8').read()
    check('nba_gated and nba_market_facts and nba_market_facts.available' in t,
          "licensed-market blocks guarded by nba_gated + available")
    check('nba_market_facts.quote_rows' in t and 'nba_market_facts.prop_markets' in t
          and 'Market quotes' in t and 'Prop markets' in t,
          "gated metric tiles render quote_rows + prop_markets, labeled distinctly")
    check('Licensed sportsbook market quotes' in t and 'not' in t and 'projections' in t,
          "copy says 'licensed sportsbook market quotes', not plays/projections/model")
    check("{% if nba_market_facts.teams is not none %}" in t and 'Unavailable' in t,
          "teams shows 'Unavailable' when None, not 0")
    check('licensed market quotes on the board' in t, "empty-state points at the live licensed board when gated")
    # gate-on (and gated-but-empty) still render the original tiles + 'No plays loaded'
    check(t.count('Total Games') == 1 and t.count('No plays loaded') == 1,
          "original stats tiles + 'No plays loaded' preserved for gate-on / empty-feed")


if __name__ == '__main__':
    print("=" * 72)
    print("NBA GATED COMMAND-CENTER LICENSED MARKET FACTS QC (Decision 2)")
    print("=" * 72)
    test_restricted_absent_in_stub()
    test_counts_agree_with_board()
    test_quotes_not_props()
    test_empty_feed_honest()
    test_unavailable_not_zero()
    test_gate_on_untouched()
    test_template_no_zero_contradiction()
    print("\nClean:", not fails)
    sys.exit(1 if fails else 0)
