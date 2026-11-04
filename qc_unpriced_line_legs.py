"""QC: a real line without a real price is incomplete information -- not a -110 bet.

Regression guard for the Daily Card fabricated-price defect (2026-11-01): `_cfb_form_legs` and
`_nfl_line_legs` attached `'price': -110` to every CFB/NFL team-line leg, so the Daily Card and
the Menu priced, paid out and ranked spread legs at a price no sportsbook was ever recorded as
offering. Also covers the second instance found by the repo scan: `grade_signals.py` graded CFB
ATS ROI at an assumed -110 (price-performance learning on a fabricated price).

Executable-leg contract (owner, 2026-11-01): a leg may be priced, paid out, ranked as bettable or put on
a ticket ONLY with a complete single-book quote -- real bookmaker identity, offered American odds,
event / market / selection identity, line value, source update time, and a passing CLOCK-A freshness
check. Missing any field => context only. A real number under an invented bookmaker is still not
executable, and no bookmaker name is ever substituted for a missing source ("Unrecorded source").

Proves, offline (Python networking is blocked in this process and its Python children):
  A. repo scans -- no tracked .py carries a -110 equivalent (int/float/string/Decimal/constant/
     default) outside `# synthetic-fixture` lines, except KNOWN_PENDING (another branch) and
     RESEARCH_ASSUMED_PRICE (offline research, disclosed); no production code/template/JS substitutes
     a bookmaker name for a missing source; both scanners catch every mutation shape;
  X. the executable gate rejects each missing/invalid quote field with its own reason code;
  B. both leg builders emit price=None / executable=False / UNAVAILABLE with the source label
     retained (CFBD consensus can never read as a book offer) and the line kept as context;
  C. no payout / implied % / card slot / swap-bench slot / bettable ranking for an unpriced leg,
     even when a stale -110 rides along on a leg marked non-executable;
  D. the Menu and Daily Card templates render the abstention text and no add-to-slip control;
  E. grade_signals CFB ATS rows carry no BetPrice and their cohort ROI abstains;
  F. the no-network guard blocks in-process + child-process network and offline mode refuses
     qc_odds_feed (the 2026-11-01 accidental live Odds API call).
Exit 0 = all pass, 1 = any failure.
"""
from __future__ import annotations

from services.qc_no_network import install as _block_network

_block_network()  # before importing app: nothing below may reach the network

import os  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import types  # noqa: E402
import json  # noqa: E402
import tempfile  # noqa: E402
import urllib.request  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from services import fabricated_price_scan as fps  # noqa: E402
from services.qc_no_network import NetworkBlocked, child_env  # noqa: E402

# Files whose fabricated -110 is removed by another, not-yet-merged branch. An entry that no
# longer matches FAILS (stale allowlist would hide a re-introduction) -- delete it at merge time.
KNOWN_PENDING: dict = {}   # emptied at integration: F7 removed fetch_ncaaf_slate_cfbd.py's -110

results: list[tuple[bool, str]] = []


def ok(cond, msg):
    results.append((bool(cond), msg))


def _has_blocked(exc) -> bool:
    while exc is not None:
        if isinstance(exc, NetworkBlocked):
            return True
        exc = exc.__cause__ or exc.__context__ or getattr(exc, 'reason', None)
        if exc is not None and not isinstance(exc, BaseException):
            return False
    return False


# --------------------------------------------------------------------------- F. network guard
def check_network_guard():
    for label, fn in (
            ('socket.create_connection', lambda: socket.create_connection(('93.184.216.34', 443), timeout=2)),
            ('socket.getaddrinfo', lambda: socket.getaddrinfo('api.the-odds-api.com', 443)),
            ('urllib urlopen', lambda: urllib.request.urlopen('https://api.the-odds-api.com/v4/sports', timeout=2)),
            ('raw socket.connect', lambda: socket.socket().connect(('1.1.1.1', 443)))):
        try:
            fn()
            ok(False, f'F: {label} reached the network under the offline guard')
        except Exception as exc:  # noqa: BLE001
            ok(_has_blocked(exc), f'F: {label} blocked by NetworkBlocked ({type(exc).__name__})')
    srv = socket.socket()
    try:
        srv.bind(('127.0.0.1', 0))
        srv.listen(1)
        cli = socket.create_connection(srv.getsockname(), timeout=2)
        cli.close()
        ok(True, 'F: loopback connection still allowed (local test servers work)')
    except Exception as exc:  # noqa: BLE001
        ok(False, f'F: loopback wrongly blocked: {exc!r}')
    finally:
        srv.close()
    child = subprocess.run([sys.executable, '-c', "import socket; socket.getaddrinfo('example.com', 80)"],
                           env=child_env(), capture_output=True, text=True, timeout=60)
    ok(child.returncode != 0 and 'NetworkBlocked' in child.stderr,
       'F: child Python process inherits the guard (DNS lookup raises NetworkBlocked)')
    import qc_offline
    ok(qc_offline.requires_network(ROOT / 'qc_odds_feed.py'), 'F: qc_odds_feed declares REQUIRES_NETWORK')
    ok(not qc_offline.requires_network(Path(__file__)), 'F: this QC is not a network QC')
    ok(qc_offline.main(['qc_odds_feed.py']) == qc_offline.NOT_RUN,
       'F: qc_offline.py refuses qc_odds_feed (NOT RUN, no process started)')
    direct = subprocess.run([sys.executable, str(ROOT / 'qc_odds_feed.py')], env=child_env(), cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    ok(direct.returncode == 3 and 'NOT RUN' in direct.stdout,
       f'F: qc_odds_feed run directly in offline mode reports NOT RUN (exit {direct.returncode})')


# --------------------------------------------------------------------------- A. repo scan
# Offline research scripts that grade ROI at an assumed -110 (not production; not imported or run by
# any unit). Disclosed, not silently passed: an entry that no longer matches FAILS (delete it), and any
# finding these produced is assumed-price / unverified (PROGRAM_LEDGER 1.5r).
RESEARCH_ASSUMED_PRICE = {
    'research/cfb_gameline/cfb_gameline_capture.py': 'every result priced at an assumed -110',
    'research/cfb_gameline/cfb_gameline_hunt.py': 'missing prices filled with -110',
    'research/nba_streak_opportunity/nba_sleeper_capture.py': 'simulate mode assumes BREAK_EVEN = -110',
}

MUTATIONS = {
    'int dict value': "leg = {'label': 'x', 'price': -110}\n",
    'any field name': "row = {'line': -110}\n",
    'float': "p = -110.0\n",
    'parenthesised': "p = -(110)\n",
    'string': "row = {'SpreadOdds': '-110'}\n",
    'string float': "p = '-110.0'\n",
    'unicode minus string': "p = '−110'\n",
    'Decimal string': "from decimal import Decimal\np = Decimal('-110')\n",
    'float() string': "p = float('-110')\n",
    'int() string': "p = int('-110')\n",
    'negated Decimal': "from decimal import Decimal\np = -Decimal(110)\n",
    'named constant': "STANDARD_JUICE = -110\n",
    'constant used later': "STANDARD_JUICE = -110\ndef f():\n    return {'price': STANDARD_JUICE}\n",
    'negated positive constant': "JUICE = 110\nprice = -JUICE\n",
    'helper default': "def make_leg(price=-110):\n    return price\n",
    'lambda default': "f = lambda price=-110: price\n",
    '.get default': "p = leg.get('price', -110)\n",
    'or fallback': "price_value = leg.get('price') or -110\n",
    'ifexp fallback': "price_value = p if p else -110\n",
}
NOT_FLAGGED = {
    'marked fixture': "leg = {'price': -110}  # synthetic-fixture\n",
    'other number': "leg = {'price': -115}\n",
    'positive 110': "leg = {'price': 110}\n",
    'mention in docstring': '"""Never default to -110."""\n',
    'absence check': "assert '-110' not in html\n",
}
BOOK_MUTATIONS = {  # the five shapes removed from production on 2026-11-01, plus variants
    'or fallback': "'book': str(market.get('book') or '').strip() or 'DraftKings',",
    'column default': "        working['Book'] = 'DraftKings'",
    '.get default': "'book': row.get('Book', 'DraftKings'),",
    'jinja or': "{{ prop.book or 'DraftKings' }}",
    'jinja default': "{{ prop.book|default('FanDuel') }}",
    'js ||': "var b = leg.book || 'BetMGM';",
    'kwarg default': "def quote(book='Caesars'):",
}
BOOK_NOT_FLAGGED = {
    'input placeholder': '<input name="book" placeholder="DraftKings">',
    'provider request param': 'DEFAULT_BOOKMAKERS = "draftkings"',
    'honest label': "'book': _clean_book(x) or UNRECORDED_SOURCE,",
}


def check_repo_scan():
    hits = fps.scan_repo(ROOT)
    unexpected = {f: h for f, h in hits.items() if f not in KNOWN_PENDING and f not in RESEARCH_ASSUMED_PRICE}
    ok(not unexpected, f'A: no -110 equivalent outside fixture lines / known-pending / research: {unexpected or "none"}')
    for f in ('app.py', 'grade_signals.py'):
        ok(f not in hits, f'A: {f} carries no -110 equivalent')
    for f, why in KNOWN_PENDING.items():
        ok(f in hits, f'A: known-pending entry still live ({f}: {why}) -- else delete the entry')
    for f, why in RESEARCH_ASSUMED_PRICE.items():
        ok(f in hits, f'A: research assumed-price entry still live ({f}: {why}) -- else delete the entry')
    prod_refs = subprocess.run(['git', 'grep', '-l', '-E', 'cfb_gameline|nba_sleeper_capture', '--', '*.py',
                                '*.sh', '*.service', '*.timer', ':!research/', ':!qc_*.py'], cwd=ROOT,
                               capture_output=True, text=True).stdout.split()
    ok(not prod_refs, f'A: no production code/unit imports or runs the assumed-price research scripts ({prod_refs or "none"})')
    book_hits = fps.scan_book_fallbacks(ROOT)
    ok(not book_hits, f'A: no production code/template/JS substitutes a bookmaker name: {book_hits or "none"}')
    for name, txt in BOOK_MUTATIONS.items():
        ok(fps.scan_book_text(txt), f'A: bookmaker-fallback scanner catches [{name}]')
    for name, txt in BOOK_NOT_FLAGGED.items():
        ok(not fps.scan_book_text(txt), f'A: bookmaker-fallback scanner does not flag [{name}]')
    for name, src in MUTATIONS.items():
        ok(fps.scan_source(src), f'A: scanner catches mutation [{name}]')
    for name, src in NOT_FLAGGED.items():
        ok(not fps.scan_source(src), f'A: scanner does not flag [{name}]')
    # Mutation of the real builder: put the fabricated price back into _cfb_form_legs.
    app_src = (ROOT / 'app.py').read_text(encoding='utf-8')
    anchor = "            'game': f\"{a} @ {h}\",\n"
    ok(app_src.count(anchor) == 1, 'A: mutation anchor found once in _cfb_form_legs')
    mutated = app_src.replace(anchor, "            'game': f\"{a} @ {h}\", 'price': -110,\n", 1)
    ok(fps.scan_source(mutated, 'app.py'), 'A: re-introducing -110 into _cfb_form_legs is caught')
    marked = mutated.replace("'price': -110,\n", "'price': -110,  # synthetic-fixture\n", 1)
    ok(not fps.scan_source(marked, 'app.py'),
       'A: fixture marker exempts only its own line')
    ok(not any(fps.FIXTURE_MARKER in (ROOT / f).read_text(encoding='utf-8')
               for f in ('app.py', 'grade_signals.py')),
       'A: no synthetic-fixture marker in production code (app.py, grade_signals.py)')


# --------------------------------------------------------------------------- B-D. leg behavior
def _fake_cff():
    m = types.ModuleType('cfb_current_form')

    def matchup_read(away, home, spread):
        # Form projects home far better than the market for both fixture games.
        return {'proj_home_margin': -float(spread) + 12.0}
    m.matchup_read = matchup_read
    return m


CFB_GAMES = [
    {'away': 'Nevada', 'home': 'UCLA', 'spread': -23.0, 'book_source': 'CFBD consensus', 'date': '2026-11-07',
     'updated_utc': '2026-11-01T10:30:00Z'},
    {'away': 'Utah', 'home': 'Iowa', 'spread': -3.5, 'book_source': None, 'date': '2026-11-07'},
]
NFL_BOARD = [
    {'play': 'BUF -3', 'game': 'MIA @ BUF', 'why': 'model margin', 'tier': 'Model', 'rank': 1,
     'flag': '', 'line_source': 'DraftKings'},
    {'play': 'KC @ DEN UNDER 41', 'game': 'KC @ DEN', 'why': 'wind', 'tier': 'Validated', 'rank': 2,
     'flag': 'WIND', 'line_source': None},
]
NOW = datetime.now(timezone.utc)
FRESH_AT = (NOW - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
STALE_AT = (NOW - timedelta(hours=9)).strftime('%Y-%m-%dT%H:%M:%SZ')
# D4 kickoff gate: an executable leg also needs a canonical kickoff strictly after the server clock.
# Fixture games kick off well in the future so this QC keeps testing the PRICE contract only
# (qc_ticket_kickoff_gate.py owns the kickoff contract).
KICKOFF_AT = (NOW + timedelta(hours=30)).strftime('%Y-%m-%dT%H:%M:%SZ')


def _quote(player, line, price, game, at=FRESH_AT, book='SynBook'):
    return {'book': book, 'price': price, 'line': line, 'event': game, 'market': 'player_reception_yds',
            'selection': f'{player} Over {line:g}', 'updated_utc': at}


def _floor(i, game, price, quote='fresh'):
    player = f'P{i}'
    q = None if quote is None else _quote(player, 40.5, price, game, FRESH_AT if quote == 'fresh' else STALE_AT)
    return {'player': player, 'stat': 'Rec Yds', 'line': 40.5, 'game': game, 'price': price, 'hit': 90 - i,
            'n': 12, 'edge': 2, 'stat_key': 'rec', 'quote': q,  # hit 90-i clears MENU_FLOOR_MIN_HIT
            'event_id': f'evt-{i}', 'kickoff_utc': KICKOFF_AT}


PROP_FLOORS = (  # synthetic priced props, distinct games: 6 fresh single-book quotes, 2 none, 1 stale
    [_floor(i, g, pr) for i, (g, pr) in enumerate([('MIA @ BUF', -150), ('KC @ DEN', -140), ('NYJ @ NE', -160),
                                                   ('SF @ LAR', -135), ('DAL @ PHI', -145), ('GB @ CHI', -155)])]
    + [_floor(6, 'LV @ LAC', -150, quote=None), _floor(7, 'SEA @ ARI', -165, quote=None),
       _floor(8, 'PIT @ CLE', -170, quote='stale')])
UNQUOTED_GAMES = {'LV @ LAC', 'SEA @ ARI', 'PIT @ CLE'}


# --------------------------------------------------------------------------- X. executable contract
def check_executable_contract():
    os.environ.setdefault('SECRET_KEY', 'qc-unpriced-legs')
    import app
    base = {'price': -150, 'line': 40.5, 'quote': _quote('P', 40.5, -150, 'A @ B'), 'kickoff_utc': KICKOFF_AT}

    def variant(leg_over=None, **q_over):
        leg = dict(base, quote=dict(base['quote']))
        leg['quote'].update(q_over)
        leg.update(leg_over or {})
        return leg
    ok(app._leg_is_executable(base), 'X: complete fresh single-book quote -> executable (control)')
    ok(app._leg_is_executable(variant(updated_utc=(NOW - timedelta(hours=5.9)).strftime('%Y-%m-%dT%H:%M:%SZ'))),
       'X: 5.9h-old quote still inside the 6h live-market window')
    no_q = dict(base)
    no_q.pop('quote')
    future = (NOW + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
    cases = [
        ('no quote at all', no_q, 'NO_QUOTE'),
        ('missing bookmaker', variant(book=''), 'MISSING_BOOK'),
        ('"Unrecorded source" as book', variant(book='Unrecorded source'), 'NOT_A_SPORTSBOOK'),
        ('CFBD consensus as book', variant(book='CFBD consensus'), 'NOT_A_SPORTSBOOK'),
        ('"nan" as book', variant(book='nan'), 'NOT_A_SPORTSBOOK'),
        ('missing offered odds', variant(price=None), 'MISSING_PRICE'),
        ('invalid offered odds', variant(price=-50), 'INVALID_PRICE'),
        ('leg price not the quote price', variant({'price': -140}), 'PRICE_NOT_FROM_QUOTE'),
        ('leg has no price', variant({'price': None}), 'PRICE_NOT_FROM_QUOTE'),
        ('missing line', variant(line=None), 'MISSING_LINE'),
        ('leg line not the quote line', variant({'line': 41.5}), 'LINE_NOT_FROM_QUOTE'),
        ('missing event identity', variant(event=''), 'MISSING_EVENT'),
        ('missing market identity', variant(market=None), 'MISSING_MARKET'),
        ('missing selection identity', variant(selection=''), 'MISSING_SELECTION'),
        ('missing update time', variant(updated_utc=None), 'MISSING_UPDATE_TIME'),
        ('unparseable update time', variant(updated_utc='not-a-time'), 'MISSING_UPDATE_TIME'),
        ('stale quote (9h)', variant(updated_utc=STALE_AT), 'STALE_QUOTE'),
        ('quote time in the future', variant(updated_utc=future), 'QUOTE_FROM_FUTURE'),
        ('marked non-executable', variant({'executable': False}), 'MARKED_NON_EXECUTABLE'),
    ]
    for name, leg, code in cases:
        why = app._leg_quote_failures(leg)
        ok(code in why and not app._leg_is_executable(leg), f'X: {name} -> context only ({code})')
    # _quote_from_row: every field from ONE source row, no defaults
    row = pd.Series({'Book': 'DraftKings', 'LastUpdated': '2026-11-01 05:30', 'MarketKey': 'player_reception_yds',
                     'Game': 'Arizona Cardinals @ Seattle Seahawks', 'Stat': 'Rec Yds'})
    q = app._quote_from_row(row, 'P', 40.5, -150)
    ok(bool(q) and q['book'] == 'DraftKings' and q['updated_utc'] == '2026-11-01T10:30:00Z'
       and q['event'] == 'Arizona Cardinals @ Seattle Seahawks' and q['selection'] == 'P Over 40.5',
       f"X: quote built from one row; zone-less ET stamp -> UTC after DST ends ({q and q['updated_utc']})")
    r_dst = row.copy()
    r_dst['LastUpdated'] = '2026-10-31 05:30'
    q2 = app._quote_from_row(r_dst, 'P', 40.5, -150)
    ok(bool(q2) and q2['updated_utc'] == '2026-10-31T09:30:00Z', 'X: ET stamp during DST -> UTC-4')
    for name, patch in (('no Book', {'Book': float('nan')}), ('consensus Book', {'Book': 'CFBD consensus'}),
                        ('no LastUpdated', {'LastUpdated': None}), ('no Game', {'Game': ''})):
        r2 = row.copy()
        for k, v in patch.items():
            r2[k] = v
        ok(app._quote_from_row(r2, 'P', 40.5, -150) is None, f'X: _quote_from_row refuses a row with {name}')


# --------------------------------------------------------------------------- bookmaker attribution
def check_book_attribution():
    import app
    nba = app._format_game_market_odds(pd.DataFrame([{'Date': '2026-11-02', 'Away': 'BOS', 'Home': 'NYK',
                                                       'Spread': -3.5}]))
    ok('Book' in nba.columns and nba['Book'].eq('').all(),
       f"BK: odds frame with no Book column -> blank, not 'DraftKings' ({list(nba.get('Book', []))})")
    look = app.build_game_market_lookup(pd.DataFrame([{'Date': '2026-11-02', 'Away': 'BOS', 'Home': 'NYK',
                                                        'Spread': -3.5, 'Book': float('nan')}]))
    books = {v.get('book') for v in look.values()} if look else set()
    ok(look and books == {''}, f"BK: game-market lookup with no book -> '' ({books})")
    odds = pd.DataFrame([{'Date': '2099-01-01', 'Time': '13:00', 'Away': 'Away Team', 'Home': 'Home Team',
                          'Spread': -3.5, 'Total': 44.5, 'Book': float('nan')}])
    games = app.build_football_live_games(odds, pd.DataFrame(), date_filter='all')
    ok(games and all(g['book'] == 'Unrecorded source' and g['book_source'] is None for g in games),
       f"BK: football live game with no book -> 'Unrecorded source' ({[g.get('book') for g in games]})")


# --------------------------------------------------------------------------- legacy scorecard ROI
def check_legacy_scorecard():
    import app
    legacy = {'totals': {'rows': 5, 'resolved': 3, 'pending': 2},
              'by_sport_kind': [{'Sport': 'CFB', 'Kind': 'buy_low', 'roi': 12.3, 'priced': 10, 'hit_rate': 60.0,
                                 'n': 5, 'resolved': 3, 'pending': 2, 'decided': 3, 'hits': 2, 'avg_move': 1.5,
                                 'read': 'too few to read'}],
              'by_sport_kind_stat': [], 'min_sample': 20, 'note': 'old'}
    current = dict(legacy, price_basis='captured_price_only',
                   by_sport_kind=[dict(legacy['by_sport_kind'][0], Sport='NFL', roi=5.0, priced=8, hit_rate=55.0)])
    saved_base = app.BASE_DIR
    try:
        for label, summary in (('legacy', legacy), ('current', current)):
            with tempfile.TemporaryDirectory() as td:
                (Path(td) / 'data' / 'tracking').mkdir(parents=True)
                (Path(td) / 'data' / 'tracking' / 'Signal_Grades_Summary.json').write_text(json.dumps(summary))
                app.BASE_DIR = td
                app._SIGNAL_REPORT_CACHE.clear()
                ctx = app.build_signal_report_context()
                coh = ctx['sr_cohorts'][0]
                if label == 'legacy':
                    ok(ctx['sr_legacy_price'] and coh['roi'] is None and coh.get('roi_legacy'),
                       'L: pre-fix summary (assumed -110) -> legacy, ROI withheld, never shown as verified')
                    ok(coh['hit_rate'] == 60.0, 'L: legacy hit rate kept (it never depended on a price)')
                    saved_user, saved_owner = app.get_current_user, app.is_owner_user
                    app.get_current_user = lambda *a, **k: {'email': 'qc@example.invalid', 'user_id': 'qc-legacy',
                                                            'plan': 'all_access'}
                    app.is_owner_user = lambda u=None: True
                    try:
                        r = app.app.test_client().get('/tools/signal-report')
                        page = r.get_data(as_text=True)
                    finally:
                        app.get_current_user, app.is_owner_user = saved_user, saved_owner
                    ok(r.status_code == 200 and 'Legacy record' in page and 'ROI withheld' in page
                       and '+12.3%' not in page,
                       f'L: Signal Report page labels the legacy record and shows no assumed ROI (HTTP {r.status_code})')
                else:
                    ok(not ctx['sr_legacy_price'] and coh['roi'] == 5.0,
                       'L: summary graded on captured prices only keeps its ROI')
    finally:
        app.BASE_DIR = saved_base
        app._SIGNAL_REPORT_CACHE.clear()


def check_leg_behavior():
    os.environ.setdefault('SECRET_KEY', 'qc-unpriced-legs')  # app enforces it at import; dummy is fine offline
    import app
    saved = {k: getattr(app, k) for k in ('build_football_live_games', 'load_ncaaf_game_market_odds',
                                          'load_ncaaf_schedule', 'build_nfl_game_board_context',
                                          'build_nfl_floor_board', '_mlb_floor_legs', '_game_date_map',
                                          'build_nfl_current_roster_lookup', '_load_cached_csv',
                                          '_mlb_hitter_rates', 'load_mlb_game_market_odds',
                                          'get_current_user', 'record_active_user')}
    saved_mod = sys.modules.get('cfb_current_form')
    try:
        sys.modules['cfb_current_form'] = _fake_cff()
        app.build_football_live_games = lambda *a, **k: [dict(g) for g in CFB_GAMES]
        app.load_ncaaf_game_market_odds = lambda *a, **k: pd.DataFrame()
        app.load_ncaaf_schedule = lambda *a, **k: pd.DataFrame()
        app.build_nfl_game_board_context = lambda: {'board': [dict(r) for r in NFL_BOARD]}
        app.build_nfl_floor_board = lambda *a, **k: {'floors': [dict(f) for f in PROP_FLOORS]}
        _teams = list(app.MLB_TEAM_NAME_TO_ABBR.items())[:2]
        app._mlb_hitter_rates = lambda: {(_teams[0][1], 'Mlb Hitter'): {'hit': 0.74, 'hrr': 0.8, 'g': 60},
                                         (_teams[1][1], 'Mlb Other'): {'hit': 0.70, 'hrr': 0.78, 'g': 55}}
        app.load_mlb_game_market_odds = lambda *a, **k: pd.DataFrame(
            [{'Date': '2099-01-01', 'Away': _teams[0][0], 'Home': _teams[1][0]}])
        app._game_date_map = lambda: {}
        app.build_nfl_current_roster_lookup = lambda: {}
        app._load_cached_csv = lambda *a, **k: pd.DataFrame()

        # ---- B: the two builders ----
        cfb = app._cfb_form_legs(10)
        nfl = app._nfl_line_legs(10)
        ok(len(cfb) == 2 and len(nfl) == 2, f'B: fixture legs built (cfb={len(cfb)}, nfl={len(nfl)})')
        for leg in cfb + nfl:
            tag = f"{leg['sport']} {leg['label']}"
            ok(leg.get('price') is None, f'B: {tag} price is None (not -110)')
            ok(leg.get('executable') is False, f'B: {tag} executable=False')
            ok(leg.get('price_status') == 'UNAVAILABLE', f'B: {tag} price_status UNAVAILABLE')
            ok(leg.get('price_note') == 'Unavailable — no verified book quote', f'B: {tag} abstention text')
            ok(not app._leg_is_executable(leg), f'B: {tag} fails the executable gate')
        by_game = {l['game']: l for l in cfb}
        ucla = by_game.get('Nevada @ UCLA', {})
        ok(ucla.get('line_source') == 'CFBD consensus — no book price',
           f"B: CFBD source label retained ({ucla.get('line_source')!r})")
        ok(ucla.get('line') == -23.0 and '-23' in ucla.get('label', ''),
           f"B: real spread kept as context ({ucla.get('label')!r})")
        ok(by_game.get('Utah @ Iowa', {}).get('line_source') == 'Unrecorded source',
           'B: missing CFB source -> "Unrecorded source" (never a substituted bookmaker)')
        nfl_src = {l['game']: l.get('line_source') for l in nfl}
        ok(nfl_src == {'MIA @ BUF': 'DraftKings', 'KC @ DEN': 'Unrecorded source'},
           f'B: NFL line source carried through ({nfl_src})')

        # ---- C: pools, cards, bench, ranking ----
        floors, swings = app._card_pools('lines')
        ok(all(l.get('market_pct') is None for l in floors + swings),
           'C: no implied probability on any unpriced line leg')
        lines_only = app.build_daily_cards(sizes=[3], legs='lines', timeframe='week')
        ok(not lines_only['cards'] and lines_only['available'] is False,
           'C: lines-only Daily Card builds NO card from unpriced legs')
        ok(len(lines_only['context_lines']) == 4 and all(
            c['price_note'] and c['line_source'] for c in lines_only['context_lines']),
           f"C: unpriced lines returned as context ({len(lines_only['context_lines'])})")
        ok(not lines_only['bench'], 'C: no unpriced leg offered on the swap bench')

        mixed = app.build_daily_cards(sizes=[3, 4, 5], risk='aggressive', legs='all', timeframe='week')
        card_legs = [l for c in mixed['cards'] for l in c['legs']]
        ok(len(mixed['cards']) == 3 and mixed['bench'], 'C: fixture builds 3 priced cards + a bench (non-vacuous)')
        ok(mixed['cards'] and all(app._leg_is_executable(l) for l in card_legs),
           f"C: every card leg carries a verified price ({len(mixed['cards'])} cards)")
        ok(all(l.get('kind') != 'line' for l in card_legs), 'C: no team-line leg on any card')
        ok(all(b.get('price') is not None for b in mixed['bench']), 'C: swap bench holds priced legs only')
        for c in mixed['cards']:
            ok((c['american'], c['decimal'], c['payout_5']) == app._card_price(c['legs']),
               f"C: {c['n']}-leg payout computed from verified prices only")
        ok(not any(l['game'] in UNQUOTED_GAMES for l in card_legs),
           'C: props with no single-book quote / a stale quote never reach a card')
        ctx_games = {c['game'] for c in mixed['context_lines']}
        ok(UNQUOTED_GAMES <= ctx_games, 'C: unquoted + stale props shown as context instead')
        mlb_ctx = [c for c in mixed['context_lines'] if c['sport'] == 'MLB']
        ok(len(mlb_ctx) == 2 and all('est' not in (c['reason'] or '') for c in mlb_ctx),
           f'C: MLB hit legs (no book quote; estimated price table removed) are context only ({len(mlb_ctx)})')
        ok(len([c for c in mixed['context_lines'] if c['kind'] == 'line']) == 4,
           'C: unpriced team lines still visible as context on the mixed card')
        quoted_price = {f['game']: f['quote']['price'] for f in PROP_FLOORS if f['quote']}
        ok(all(l['price'] == quoted_price[l['game']] and l['book'] == 'SynBook' for l in card_legs),
           'C: every card price is the quote price, with its bookmaker')

        # featured parlay: payout only from fresh single-book quotes
        fp = app.build_nfl_featured_parlay(legs=3)
        ok(fp.get('available') and all(l['game'] not in UNQUOTED_GAMES and l.get('book') == 'SynBook'
                                       for l in fp['legs']),
           'C: featured parlay built only from fresh single-book quotes')
        app.build_nfl_floor_board = lambda *a, **k: {'floors': [dict(f) for f in PROP_FLOORS
                                                                if f['game'] in UNQUOTED_GAMES]}
        ok(app.build_nfl_featured_parlay(legs=3).get('available') is False,
           'C: featured parlay abstains when no leg has a fresh single-book quote')
        app.build_nfl_floor_board = lambda *a, **k: {'floors': [dict(f) for f in PROP_FLOORS]}

        stale = {'sport': 'CFB', 'label': 'UCLA -23', 'game': 'Nevada @ UCLA', 'price': -110,  # synthetic-fixture
                 'executable': False}
        ok(not app._leg_is_executable(stale), 'C: a stale -110 on a non-executable leg is still not executable')
        try:
            app._card_price(card_legs[:2] + [stale])
            ok(False, 'C: _card_price priced a card containing an unpriced leg')
        except ValueError:
            ok(True, 'C: _card_price refuses a card containing an unpriced leg')

        menu = app.build_menu_board(legs='all', timeframe='week')
        ok(any(app._leg_is_executable(l) for gd in menu['games'] for l in gd['legs']),
           'C: menu fixture contains priced legs (ordering checks are non-vacuous)')
        for gd in menu['games']:
            ex = [app._leg_is_executable(l) for l in gd['legs']]
            ok(ex == sorted(ex, reverse=True), f"C: menu {gd['game']}: priced legs before unpriced context")
        line_only_games = [gd for gd in menu['games'] if not any(app._leg_is_executable(l) for l in gd['legs'])]
        ok(all(menu['games'].index(gd) >= len(menu['games']) - len(line_only_games) for gd in line_only_games),
           'C: games with only unpriced lines never outrank a game with a priced leg')

        # ---- D: the real routes render (owner session stubbed; no prefs file -> house default) ----
        owner = sorted(app.OWNER_EMAILS)[0] if app.OWNER_EMAILS else 'qc@example.invalid'
        app.get_current_user = lambda *a, **k: {'email': owner, 'user_id': 'qc-unpriced-legs',
                                                'plan': 'all_access'}
        app.record_active_user = lambda *a, **k: None
        c = app.app.test_client()
        r = c.get('/tools/menu?timeframe=week')
        html = r.get_data(as_text=True)
        ok(r.status_code == 200, f'D: /tools/menu renders with unpriced legs (HTTP {r.status_code})')
        ok('Unavailable — no verified book quote' in html, 'D: Menu shows the abstention text')
        ok('CFBD consensus — no book price' in html, 'D: Menu shows the CFBD source label')
        ok('-110' not in html, 'D: Menu renders no -110')
        rows = html.split('<div class="mb-leg')[1:]
        # an unpriced row holds only spans, so its first </div> closes it -- scope checks to the row
        ctx_rows = [x.split('</div>', 1)[0] for x in rows if 'data-unpriced="1"' in x.split('>', 1)[0]]
        rows = [x.split('</div>', 1)[0] for x in rows]
        n_ctx = sum(1 for gd in menu['games'] for l in gd['legs'] if not l['executable_now'])
        ok(n_ctx >= 9 and len(ctx_rows) == n_ctx and not any('mb-add' in x for x in ctx_rows),
           f'D: {len(ctx_rows)} context Menu rows (= {n_ctx} non-executable legs), none with add-to-slip')
        ok('Quote not current' in html, 'D: a stale quote is labelled not current, not priced')
        ok('No fresh executable prices available' not in html, 'D: no empty-state banner while priced legs exist')
        stale_at_et = app._updated_label(STALE_AT)
        ok(stale_at_et in html, f'D: stale quote shows its own book update time ({stale_at_et})')
        lh = c.get('/tools/menu?timeframe=week&legs=lines').get_data(as_text=True)
        ok('No fresh executable prices available' in lh and 'class="mb-add"' not in lh,
           'D: lines-only Menu (nothing executable) shows the honest empty state, no slip buttons')
        ok('SynBook' in html and app._updated_label(FRESH_AT) in html,
           'D: priced Menu rows name the bookmaker and its updated-at time')
        ok(any('mb-add' in x for x in rows if x not in ctx_rows), 'D: priced Menu rows keep add-to-slip')
        for path in ('/tools/daily-card?legs=lines&timeframe=week', '/tools/kings-tickets?legs=lines&timeframe=week'):
            r = c.get(path)
            dhtml = r.get_data(as_text=True)
            ok(r.status_code == 200 and 'not on any card' in dhtml
               and 'No fresh executable prices available' in dhtml
               and 'updated 2026-11-01 05:30 ET' in dhtml and 'update time not recorded' in dhtml
               and 'CFBD consensus — no book price' in dhtml,
               f'D: {path.split("?")[0]}: honest empty state + context with real source and updated-at (HTTP {r.status_code})')
            ok('-110' not in dhtml, f'D: {path.split("?")[0]} renders no -110')
        r = c.get('/tools/daily-card?legs=all&timeframe=week')
        dh = r.get_data(as_text=True)
        ok(r.status_code == 200 and 'odnum' in dh, f'D: mixed Daily Card still renders priced cards (HTTP {r.status_code})')
        ok('no book or capture time recorded' not in dh and 'SynBook' in dh,
           'D: card leg prices carry their bookmaker + capture time (old "no book" copy gone)')

        # image endpoint: never prices what the browser sends
        import re as _re
        from marketing.generators import weekly_cards as _wc
        from PIL import Image as _Image
        token = _re.search(r'CSRF="([^"]+)"', html).group(1)
        captured = {}
        orig_render = _wc.render_daily_card

        def _fake_render(card):
            captured['card'] = card
            return _Image.new('RGB', (2, 2))
        _wc.render_daily_card = _fake_render
        try:
            forged = [dict(sport=l['sport'], label=l['label'], game=l['game'], tier=l['tier'], price=900)
                      for l in mixed['cards'][0]['legs']]
            r = c.post('/tools/daily-card.png', json={'legs': forged}, headers={'X-CSRFToken': token})
            got = captured.get('card', {}).get('legs', [])
            ok(r.status_code == 200 and len(got) == len(forged)
               and all(g['price'] == quoted_price[g['game']] for g in got),
               f'D: image endpoint reprices from the server quote, ignoring a forged +900 (HTTP {r.status_code})')
            captured.clear()
            unpriced = [dict(sport='CFB', label='UCLA -23', game='Nevada @ UCLA', tier='swing', price=-105)]
            r = c.post('/tools/daily-card.png', json={'legs': forged[:2] + unpriced}, headers={'X-CSRFToken': token})
            j = r.get_json(silent=True) or {}
            bad = [e for e in (j.get('legs') or []) if not e.get('executable')]
            ok(r.status_code == 409 and not captured and len(j.get('legs') or []) == 3
               and [e.get('position') for e in bad] == [3],
               f'D: image endpoint REJECTS (never drops) a ticket carrying an unpriced leg '
               f'(HTTP {r.status_code}, blocked positions {[e.get("position") for e in bad]})')
        finally:
            _wc.render_daily_card = orig_render
    finally:
        for k, v in saved.items():
            setattr(app, k, v)
        if saved_mod is not None:
            sys.modules['cfb_current_form'] = saved_mod
        else:
            sys.modules.pop('cfb_current_form', None)


# --------------------------------------------------------------------------- E. grade_signals
def check_grade_signals():
    import grade_signals as gs
    m = types.ModuleType('cfb_current_form')
    m._resolve = lambda s: str(s).strip().lower()
    m.team_games = lambda team: [{'week': 6, 'opp': 'Nevada', 'margin': 30}]
    saved_mod = sys.modules.get('cfb_current_form')
    sys.modules['cfb_current_form'] = m
    try:
        row = {'Sport': 'CFB', 'Kind': 'buy_low', 'Subject': 'UCLA', 'Opponent': 'Nevada',
               'Line': -23.0, 'AsOfWeek': 5}
        res = gs.resolve_cfb_team(row)
        ok(res.get('resolved') and 'price' not in res, 'E: CFB ATS resolution carries no bet price')
        ok(res.get('price_status') == 'UNAVAILABLE', 'E: CFB ATS resolution labelled UNAVAILABLE')
        graded = gs.grade_archive(pd.DataFrame([row] * 3))
        ok(graded['BetPrice'].eq('').all() and graded['PriceStatus'].eq('UNAVAILABLE').all(),
           'E: graded rows: blank BetPrice + PriceStatus UNAVAILABLE')
        roi, priced = gs._roi(graded[graded['Hit'].isin([0, 1])])
        ok(roi is None and priced == 0, f'E: CFB ATS ROI abstains (roi={roi}, priced={priced})')
    finally:
        if saved_mod is not None:
            sys.modules['cfb_current_form'] = saved_mod
        else:
            sys.modules.pop('cfb_current_form', None)


def main() -> int:
    for fn in (check_network_guard, check_repo_scan, check_executable_contract, check_leg_behavior,
               check_book_attribution, check_grade_signals, check_legacy_scorecard):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            ok(False, f'{fn.__name__} crashed: {exc!r}')
    print('=' * 60)
    print('BANKROLL KINGS UNPRICED LINE LEGS QC')
    print('=' * 60)
    for passed, msg in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")
    n_fail = sum(1 for p, _ in results if not p)
    print(f'\n{len(results) - n_fail}/{len(results)} passed')
    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
