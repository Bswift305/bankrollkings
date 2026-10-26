"""QC: NBA Command Center gated-stub licensed market facts (Decision 2 — Data-Pulse contradiction fix).

While BK_NBA_STATS_ENABLED=0 the Command Center must keep every restricted statistic gated, but must NOT
deny the ungated licensed market board. The gated stub carries `nba_market_facts` — honest Odds-API quote
counts from the SAME feed as market_only_board. Honest counting contract (reviewer Rev):
  * quote_rows = raw displayed-row count (a row may have only one side);
  * player_stat_markets = distinct (game, player, stat) FAMILIES (NOT a prop-LINE count, NOT the quote
    count); books differing on the same stat collapse to one family;
  * every derived count is published only when its required fields are COMPLETE across displayed rows,
    else None ('Unavailable') — never a partial count as complete;
  * books counted from DISPLAYED rows, not feed metadata.
Proves all of the above + agreement with the board + gate-ON untouched + the template contract.
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


COLS = ['Player', 'Game', 'Book', 'Stat', 'Line', 'OverOdds', 'UnderOdds']
# 8 quote rows · 4 player-stat families · 2 games · 4 teams · 2 books.
# NOTE: Ausar PTS has DIFFERENT lines across books (11.5 vs 10.5) -> still ONE (game,player,stat) family.
FEED_ROWS = [
    ('Ausar Thompson', 'DET@PHI', 'DraftKings', 'AST', 4.5, 111, -147),
    ('Ausar Thompson', 'DET@PHI', 'FanDuel', 'AST', 4.5, 118, -158),
    ('Ausar Thompson', 'DET@PHI', 'DraftKings', 'PTS', 11.5, -111, -115),
    ('Ausar Thompson', 'DET@PHI', 'FanDuel', 'PTS', 10.5, -128, -104),
    ('Cade Cunningham', 'DET@PHI', 'DraftKings', '3PM', 2.5, 129, -170),
    ('Cade Cunningham', 'DET@PHI', 'FanDuel', '3PM', 2.5, 132, -178),
    ('Franz Wagner', 'ORL@NYK', 'DraftKings', 'STL', 1.5, 120, -150),
    ('Franz Wagner', 'ORL@NYK', 'FanDuel', 'STL', 1.5, 118, -158),
]


def _feed(rows, meta=None):
    df = pd.DataFrame([dict(zip(COLS, r)) for r in rows])
    if not df.empty:
        df['LastUpdated'] = '2026-10-25 13:05'
    return lambda require_fresh=False: (df, (meta or {}))


def _with_feed(rows, fn, meta=None):
    orig = app.load_live_props_feed
    app.load_live_props_feed = _feed(rows, meta)
    try:
        return fn()
    finally:
        app.load_live_props_feed = orig


def _facts(rows, meta=None):
    return _with_feed(rows, app._nba_gated_market_facts, meta)


def test_restricted_absent_in_stub():
    print("\n[A] gated stub keeps restricted statistics absent; only market COUNTS added")
    stub = _with_feed(FEED_ROWS, lambda: app._nba_command_center_gated_stub(False))
    check(stub['nba_gated'] is True, "nba_gated True")
    check(stub['total_props'] == 0 and stub['teams'] == [] and stub['top_plays'] == []
          and stub['role_changes'] == [] and stub['best_by_series'] == [],
          "stats-derived fields stay empty")
    mf = stub['nba_market_facts']
    check(set(mf) <= {'available', 'quote_rows', 'player_stat_markets', 'games', 'teams', 'books', 'as_of'},
          "nba_market_facts has ONLY count/label keys (%r)" % sorted(mf))
    blob = repr(mf).lower()
    check(all(bad not in blob for bad in ('avg', 'average', 'boost', 'proj', 'model', 'pct', 'odds')),
          "no averages/boost/projection/model/odds fields in the market facts")


def test_counts_agree_with_board():
    print("\n[B] counts AGREE with build_market_only_board (same feed); families, not quotes")
    def go():
        mf = app._nba_gated_market_facts()
        board = app.build_market_only_board(app.load_live_props_feed)
        rows = board['rows']
        games = {r['game'] for r in rows}
        fams = {(r['game'], r['player'], r['stat']) for r in rows}
        teams = set()
        for g in games:
            teams.update(p.strip() for p in g.split('@'))
        books = {r['book'] for r in rows}
        return mf, len(rows), len(games), len(fams), len(teams), len(books)
    mf, n_rows, n_games, n_fams, n_teams, n_books = _with_feed(FEED_ROWS, go)
    check(mf['available'] is True, "facts available with a populated feed")
    check(mf['quote_rows'] == n_rows == 8, "quote_rows == board rows (%s)" % mf['quote_rows'])
    check(mf['games'] == n_games == 2, "games agree (%s)" % mf['games'])
    check(mf['player_stat_markets'] == n_fams == 4,
          "player_stat_markets == distinct (game,player,stat) families (%s)" % mf['player_stat_markets'])
    check(mf['teams'] == n_teams == 4, "teams agree (%s)" % mf['teams'])
    check(mf['books'] == n_books == 2, "books agree (from rows) (%s)" % mf['books'])


def test_quotes_distinguished_and_lines_collapse():
    print("\n[C] quote rows != player-stat markets; different lines for one stat collapse to one family")
    mf = _facts(FEED_ROWS)
    check(mf['quote_rows'] > mf['player_stat_markets'],
          "quote_rows (%s) > player_stat_markets (%s) — quotes not mislabeled as markets"
          % (mf['quote_rows'], mf['player_stat_markets']))
    # Ausar PTS appears at 2 different lines (11.5, 10.5) across 2 books -> 4 quote rows for Ausar
    # (AST x2, PTS x2) but Ausar contributes exactly 2 families (AST, PTS): the differing PTS lines
    # DID NOT inflate the family count.
    check(mf['player_stat_markets'] == 4, "4 families despite a stat posted at two different lines")


def test_empty_feed_honest():
    print("\n[D] empty feed -> available False (template keeps its honest empty state)")
    check(_facts([]) == {'available': False}, "empty feed -> {'available': False}")


def test_completeness_unavailable_not_zero():
    print("\n[E] a required field missing on ANY displayed row -> that count is None ('Unavailable')")
    # blank GAME -> games / player_stat_markets / teams all None; quote_rows + books still derivable
    bg = _facts([('P1', '', 'DK', 'PTS', 10.5, -110, -110), ('P2', 'DET@PHI', 'DK', 'AST', 4.5, 110, -130)])
    check(bg['games'] is None and bg['player_stat_markets'] is None and bg['teams'] is None,
          "blank game -> games/player_stat_markets/teams = None")
    check(bg['quote_rows'] == 2 and bg['books'] == 1, "quote_rows + books still correct with a blank game")
    # blank STAT -> player_stat_markets None; games/teams/books fine
    bs = _facts([('P1', 'DET@PHI', 'DK', '', 10.5, -110, -110), ('P2', 'DET@PHI', 'DK', 'AST', 4.5, 110, -130)])
    check(bs['player_stat_markets'] is None, "blank stat -> player_stat_markets = None")
    check(bs['games'] == 1 and bs['teams'] == 2 and bs['books'] == 1, "blank stat leaves games/teams/books intact")
    # blank BOOK -> books None; others fine
    bb = _facts([('P1', 'DET@PHI', '', 'PTS', 10.5, -110, -110), ('P2', 'DET@PHI', 'DK', 'AST', 4.5, 110, -130)])
    check(bb['books'] is None, "blank book -> books = None (not a partial count)")
    check(bb['games'] == 1 and bb['player_stat_markets'] == 2 and bb['teams'] == 2, "blank book leaves the rest intact")


def test_missing_side_still_counted():
    print("\n[F] a quote with a missing side is still a displayed row (quote_rows counts it)")
    ms = _facts([('P1', 'DET@PHI', 'DK', 'PTS', 10.5, -110, None)])
    check(ms['quote_rows'] == 1, "row with only an over side still counts as a quote row")
    check(ms['player_stat_markets'] == 1 and ms['games'] == 1, "other counts derive normally")


def test_books_from_rows_not_metadata():
    print("\n[G] books counted from DISPLAYED rows, not feed metadata")
    mf = _facts(FEED_ROWS, meta={'books': ['DraftKings', 'FanDuel', 'PhantomBook']})
    check(mf['books'] == 2, "a metadata-only book (no surviving rows) is excluded -> books == 2 (%s)" % mf['books'])


def test_gate_on_untouched():
    print("\n[H] gate-on path untouched — market facts only when gated; routes guarded; no network")
    src = open(os.path.join(HERE, 'app.py'), encoding='utf-8').read()
    check(src.count("'nba_market_facts':") == 3, "nba_market_facts set in 3 gated places (stub + 2 routes)")
    check(src.count("'nba_market_facts': _nba_gated_market_facts()") == 3, "all assignments use the helper")
    check(src.count("if nba_context.get('nba_gated'):") == 2, "the 2 route recomputes are guarded by nba_gated")
    check(src.count("'nba_gated': True") == 1, "nba_gated True set only in the gated stub")
    body = src.split('def _nba_gated_market_facts', 1)[1].split('def _nba_command_center_gated_stub', 1)[0]
    check('build_market_only_board(load_live_props_feed)' in body, "uses the licensed market feed only")
    for bad in ('load_gamelogs', 'load_player', 'requests.', 'urlopen', 'nba_api', 'stats.nba.com'):
        check(bad not in body, "no network / NBA.com-stats call in the helper (%s)" % bad)


def test_template_contract():
    print("\n[I] dashboard.html: Player-stat markets label, Unavailable guards, no two-sided implication")
    t = open(os.path.join(HERE, 'templates', 'dashboard.html'), encoding='utf-8').read()
    check('nba_gated and nba_market_facts and nba_market_facts.available' in t, "gated blocks guarded")
    check('nba_market_facts.player_stat_markets' in t and 'Player-stat markets' in t,
          "tile renamed to Player-stat markets (field player_stat_markets)")
    check('prop_markets' not in t and 'Prop markets' not in t, "old 'Prop markets' label/field gone")
    for metric in ('games', 'player_stat_markets', 'teams'):
        check(("nba_market_facts.%s is not none" % metric) in t, "Unavailable guard on %s" % metric)
    check('nba_market_facts.books is not none' in t, "books clause guarded (only shown when derivable)")
    check('two-sided' not in t, "copy does not imply every quote is two-sided")
    check('a quote may list only one side' in t, "copy acknowledges a quote may be one-sided")
    check('Licensed sportsbook market quotes' in t and 'not' in t and 'projections' in t,
          "copy says licensed market quotes, not plays/projections/model")
    check('licensed market quotes on the board' in t, "empty-state points at the live board when gated")
    check(t.count('Total Games') == 1 and t.count('No plays loaded') == 1,
          "original stats tiles + 'No plays loaded' preserved for gate-on / empty-feed")


if __name__ == '__main__':
    print("=" * 72)
    print("NBA GATED COMMAND-CENTER LICENSED MARKET FACTS QC (Decision 2, Rev)")
    print("=" * 72)
    test_restricted_absent_in_stub()
    test_counts_agree_with_board()
    test_quotes_distinguished_and_lines_collapse()
    test_empty_feed_honest()
    test_completeness_unavailable_not_zero()
    test_missing_side_still_counted()
    test_books_from_rows_not_metadata()
    test_gate_on_untouched()
    test_template_contract()
    print("\nClean:", not fails)
    sys.exit(1 if fails else 0)
