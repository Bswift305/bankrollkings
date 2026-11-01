"""QC: a real line without a real price is incomplete information -- not a -110 bet.

Regression guard for the Daily Card fabricated-price defect (2026-11-01): `_cfb_form_legs` and
`_nfl_line_legs` attached `'price': -110` to every CFB/NFL team-line leg, so the Daily Card and
the Menu priced, paid out and ranked spread legs at a price no sportsbook was ever recorded as
offering. Also covers the second instance found by the repo scan: `grade_signals.py` graded CFB
ATS ROI at an assumed -110 (price-performance learning on a fabricated price).

Proves, offline (the network is blocked for this whole process):
  A. repo scan -- no tracked .py assigns a literal -110 to a price/odds field outside lines marked
     `# synthetic-fixture`, except KNOWN_PENDING files removed by another branch; the scanner
     catches every mutation shape (dict, subscript, name, keyword, .get default, `or` fallback);
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
import urllib.request  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from services import fabricated_price_scan as fps  # noqa: E402
from services.qc_no_network import NetworkBlocked, child_env  # noqa: E402

# Files whose fabricated -110 is removed by another, not-yet-merged branch. An entry that no
# longer matches FAILS (stale allowlist would hide a re-introduction) -- delete it at merge time.
KNOWN_PENDING = {
    'fetch_ncaaf_slate_cfbd.py': 'removed by fix/f7-cfbd-no-fabricated-prices (bdc06c4)',
}

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
MUTATIONS = {
    'dict price': "leg = {'label': 'x', 'price': -110}\n",
    'dict odds key': "row = {'SpreadOdds': -110}\n",
    'subscript': "leg['price'] = -110\n",
    'name': "price = -110\n",
    'attribute': "self.price = -110\n",
    'keyword': "make_leg(label='x', price=-110)\n",
    '.get default': "p = leg.get('price', -110)\n",
    'or fallback': "price_value = leg.get('price') or -110\n",
    'ifexp fallback': "price_value = p if p else -110\n",
}
NOT_FLAGGED = {
    'line value': "leg = {'line': -110}\n",
    'marked fixture': "leg = {'price': -110}  # synthetic-fixture\n",
    'other number': "leg = {'price': -115}\n",
}


def check_repo_scan():
    hits = fps.scan_repo(ROOT)
    unexpected = {f: h for f, h in hits.items() if f not in KNOWN_PENDING}
    ok(not unexpected, f'A: no fabricated -110 price outside known-pending files: {unexpected or "none"}')
    ok('app.py' not in hits, 'A: app.py has no literal -110 price (both leg builders clean)')
    for f, why in KNOWN_PENDING.items():
        ok(f in hits, f'A: known-pending entry still live ({f}: {why}) -- else delete the entry')
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
    {'away': 'Nevada', 'home': 'UCLA', 'spread': -23.0, 'book_source': 'CFBD consensus', 'date': '2026-11-07'},
    {'away': 'Utah', 'home': 'Iowa', 'spread': -3.5, 'book_source': None, 'date': '2026-11-07'},
]
NFL_BOARD = [
    {'play': 'BUF -3', 'game': 'MIA @ BUF', 'why': 'model margin', 'tier': 'Model', 'rank': 1,
     'flag': '', 'line_source': 'DraftKings'},
    {'play': 'KC @ DEN UNDER 41', 'game': 'KC @ DEN', 'why': 'wind', 'tier': 'Validated', 'rank': 2,
     'flag': 'WIND', 'line_source': None},
]
PROP_FLOORS = [  # synthetic priced props, distinct games
    {'player': f'P{i}', 'stat': 'Rec Yds', 'line': 40.5, 'game': g, 'price': pr, 'hit': 90 - i, 'n': 12,
     'edge': 2, 'stat_key': 'rec'}  # hit 90-i clears MENU_FLOOR_MIN_HIT
    for i, (g, pr) in enumerate([('MIA @ BUF', -150), ('KC @ DEN', -140), ('NYJ @ NE', -160),
                                 ('SF @ LAR', -135), ('DAL @ PHI', -145), ('GB @ CHI', -155)])
]


def check_leg_behavior():
    os.environ.setdefault('SECRET_KEY', 'qc-unpriced-legs')  # app enforces it at import; dummy is fine offline
    import app
    saved = {k: getattr(app, k) for k in ('build_football_live_games', 'load_ncaaf_game_market_odds',
                                          'load_ncaaf_schedule', 'build_nfl_game_board_context',
                                          'build_nfl_floor_board', '_mlb_floor_legs', '_game_date_map',
                                          'build_nfl_current_roster_lookup', '_load_cached_csv')}
    saved_mod = sys.modules.get('cfb_current_form')
    try:
        sys.modules['cfb_current_form'] = _fake_cff()
        app.build_football_live_games = lambda *a, **k: [dict(g) for g in CFB_GAMES]
        app.load_ncaaf_game_market_odds = lambda *a, **k: pd.DataFrame()
        app.load_ncaaf_schedule = lambda *a, **k: pd.DataFrame()
        app.build_nfl_game_board_context = lambda: {'board': [dict(r) for r in NFL_BOARD]}
        app.build_nfl_floor_board = lambda *a, **k: {'floors': [dict(f) for f in PROP_FLOORS]}
        app._mlb_floor_legs = lambda *a, **k: []
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
        ok(by_game.get('Utah @ Iowa', {}).get('line_source') == 'unrecorded source',
           'B: missing CFB source -> "unrecorded source" (never the DraftKings display default)')
        nfl_src = {l['game']: l.get('line_source') for l in nfl}
        ok(nfl_src == {'MIA @ BUF': 'DraftKings', 'KC @ DEN': 'unrecorded source'},
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
        ok(len(mixed['context_lines']) == 4, 'C: unpriced lines still visible as context on mixed card')

        stale = {'sport': 'CFB', 'label': 'UCLA -23', 'game': 'Nevada @ UCLA', 'price': -110,
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
        ok(len(ctx_rows) == 4 and not any('mb-add' in x for x in ctx_rows),
           f'D: {len(ctx_rows)} unpriced Menu rows, none with an add-to-slip control')
        ok(any('mb-add' in x for x in rows if x not in ctx_rows), 'D: priced Menu rows keep add-to-slip')
        for path in ('/tools/daily-card?legs=lines&timeframe=week', '/tools/kings-tickets?legs=lines&timeframe=week'):
            r = c.get(path)
            dhtml = r.get_data(as_text=True)
            ok(r.status_code == 200 and 'context only, not on any card' in dhtml
               and 'CFBD consensus — no book price' in dhtml,
               f'D: {path.split("?")[0]} shows unpriced lines as labelled context (HTTP {r.status_code})')
            ok('-110' not in dhtml, f'D: {path.split("?")[0]} renders no -110')
        r = c.get('/tools/daily-card?legs=all&timeframe=week')
        ok(r.status_code == 200 and 'odnum' in r.get_data(as_text=True),
           f'D: mixed Daily Card still renders priced cards (HTTP {r.status_code})')
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
    for fn in (check_network_guard, check_repo_scan, check_leg_behavior, check_grade_signals):
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
