"""QC: no proposed ticket ever carries a leg whose game has kicked off (D4, P0 authority).

Defect (2026-11): Green Light's proposed ticket offered Lamar Jackson / Javonte Williams legs after
their games had started. Nothing on the ticket path compared kickoff to the clock: the floor board
dropped EventCommenceAtUTC, `_passes_timeframe` compares Eastern calendar DATES only, and the floor
board is cached on file mtimes (a pre-kickoff build is served after kickoff).

Contract under test (owner): ONE kickoff predicate (`app._kickoff_gate_failure`) reached through the
executable-leg contract (`_leg_quote_failures` -> reason STARTED / MISSING_KICKOFF), evaluated against
ONE injectable server clock (`app._now_utc`, frozen here) at the FINAL ticket-construction boundary --
after every cache. kickoff_utc > now strictly; kickoff == now is started; unknown / unparseable / naive
kickoff fails closed; offset-equivalent timestamps are one instant. A started leg is never silently
substituted: a server-built card that would have carried it is REBUILT from not-yet-started games and
says so ("N leg(s) removed — game started"); a client-held ticket carrying it is REJECTED (409). Bench /
swap / add / reroll exclude it. It gets no price math.

Synthetic fixtures + frozen clock; Python networking blocked; writes nothing outside a temp dir.
  1-3  boundary: kickoff one second before / exactly at / one second after now
  4    stale cache: board built pre-kickoff, clock advanced, board served FROM CACHE -> leg excluded
  5    mixed ticket: rebuilt-with-disclosure (server) / rejected (client POST); never a silent substitute
  6    unknown / unparseable / naive kickoff -> fail closed
  7    offset-equivalent kickoff -> same instant, same decision
  S    the gate is reached from every proposed-ticket surface (Green Light ticket, Daily Card, King's
       Tickets, Menu, image GET + POST, Featured Parlay) and the started leg appears on none
  B    context-only legs with no governed kickoff (NFL / CFB team lines, MLB hit floors, a prop row with
       no commence time) never silently disappear: Daily Card, King's Tickets, Green Light ticket, Menu
       and Featured Parlay show them with exactly "Kickoff unavailable — context only", unpriced, on no
       card / bench / slip
  M    mutation: gate disabled => the surface checks FAIL and the context-only labels vanish (the QC can
       see the defect); the predicate has ONE definition and ONE caller (_leg_kickoff_failure), whose
       callers are exactly the executable-leg contract and the SGP Workbench gate
Exit 0 = all pass, 1 = any failure.
"""
from __future__ import annotations

from services.qc_no_network import install as _block_network

_block_network()  # before importing app: nothing below may reach the network

import ast  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SECRET_KEY', 'qc-ticket-kickoff-gate')

import app  # noqa: E402

UTC = timezone.utc
KICK = datetime(2026, 11, 8, 18, 0, 0, tzinfo=UTC)          # the early game's kickoff (13:00 ET)
LATE = KICK + timedelta(hours=3, minutes=25)                 # every other game
PRE = KICK - timedelta(hours=1)                              # board + pages built here
POST = KICK + timedelta(seconds=1)                           # ...then the clock passes kickoff
CLOCK = {'now': PRE}
S1 = timedelta(seconds=1)

results: list[tuple[bool, str]] = []


def ok(cond, msg):
    results.append((bool(cond), msg))
    return bool(cond)


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _leg(kickoff, now, **over):
    """A complete, fresh single-book NFL prop leg (executable but for its kickoff)."""
    at = iso(now - timedelta(hours=1))
    q = {'book': 'SynBook', 'price': -150, 'line': 40.5, 'event': 'G9A Away@G9H Home',
         'market': 'player_reception_yds', 'selection': 'P Over 40.5', 'updated_utc': at}
    leg = {'sport': 'NFL', 'kind': 'prop', 'label': 'P Receiving Yards 40.5+', 'game': 'G9A @ G9H',
           'price': -150, 'line': 40.5, 'quote': q, 'kickoff_utc': kickoff}
    leg.update(over)
    return leg


# --------------------------------------------------------------------------- 1-3, 6, 7: predicate
def check_predicate():
    now = KICK
    gate = app._kickoff_gate_failure
    ok(gate(iso(now - S1), now) == 'STARTED', '1: kickoff one second BEFORE now -> STARTED (excluded)')
    ok(gate(iso(now), now) == 'STARTED', '2: kickoff EXACTLY at now -> STARTED (excluded; strict >)')
    ok(gate(iso(now + S1), now) is None, '3: kickoff one second AFTER now -> eligible')
    ok(not app._leg_is_executable(_leg(iso(now - S1), now), now)
       and 'STARTED' in app._leg_quote_failures(_leg(iso(now - S1), now), now),
       '1: started leg fails the executable contract with reason STARTED')
    ok(not app._leg_is_executable(_leg(iso(now), now), now), '2: kickoff==now leg is not executable')
    ok(app._leg_is_executable(_leg(iso(now + S1), now), now), '3: kickoff+1s leg is executable (control)')
    # started legs get no price math
    good = [_leg(iso(LATE), now, game=f'G{i}', label=f'L{i}') for i in range(2)]
    try:
        app._card_price(good + [_leg(iso(now - S1), now, game='GX', label='LX')], now)
        ok(False, '1: _card_price priced a ticket containing a started leg')
    except ValueError:
        ok(True, '1: _card_price refuses a ticket containing a started leg (no payout math)')
    ok(app._card_price(good, now)[0] is not None, '3: _card_price prices an all-eligible ticket (control)')
    # the default clock is the injectable server clock (no `now` passed -> app._now_utc)
    saved = app._now_utc
    try:
        app._now_utc = lambda: KICK + timedelta(hours=10)
        ok('STARTED' in app._leg_quote_failures(_leg(iso(LATE), KICK)),
           'clock: _leg_quote_failures with no `now` reads app._now_utc (single injectable clock)')
    finally:
        app._now_utc = saved

    # 6: unknown / unparseable / naive -> fail closed
    for name, val in (('None', None), ('empty', ''), ('whitespace', '   '), ('garbage', 'kickoff-ish'),
                      ('NaN float', float('nan')), ('pd.NA', pd.NA), ('NaT', pd.NaT),
                      ('naive ISO', '2026-11-08T18:00:00'), ('naive datetime', datetime(2026, 11, 8, 18)),
                      ('naive Timestamp', pd.Timestamp('2026-11-08 18:00')),
                      ('date only', '2026-11-08'), ('impossible', '2026-13-45T99:00:00Z')):
        why = app._leg_quote_failures(_leg(val, PRE), PRE)
        ok(app._kickoff_gate_failure(val, PRE) == 'MISSING_KICKOFF' and 'MISSING_KICKOFF' in why
           and not app._leg_is_executable(_leg(val, PRE), PRE),
           f'6: {name} kickoff -> MISSING_KICKOFF, fail closed')
    no_field = _leg(None, PRE)
    no_field.pop('kickoff_utc')
    ok('MISSING_KICKOFF' in app._leg_quote_failures(no_field, PRE), '6: leg with NO kickoff field -> fail closed')

    # 7: offset-equivalent spellings are one instant with one decision
    forms = ['2026-11-08T18:00:00Z', '2026-11-08T18:00:00+00:00', '2026-11-08T13:00:00-05:00',
             '2026-11-08T19:00:00+01:00', '2026-11-08 18:00:00z', KICK, pd.Timestamp('2026-11-08T13:00:00-05:00')]
    canon = {app._canonical_kickoff_utc(f) for f in forms}
    ok(canon == {KICK}, f'7: offset-equivalent kickoffs canonicalize to one UTC instant ({canon})')
    for now, want in ((KICK - S1, None), (KICK, 'STARTED'), (KICK + S1, 'STARTED')):
        got = {app._kickoff_gate_failure(f, now) for f in forms}
        ok(got == {want}, f'7: every offset form gets the same decision at now={iso(now)} ({got})')


# --------------------------------------------------------------------------- floor-board fixture
GAMES = [(f'G{i}a Away', f'G{i}h Home') for i in range(7)]
PLAYERS = [f'Syn Receiver {i}' for i in range(7)]
EARLY_PLAYER = PLAYERS[0]          # game 0 kicks off at KICK; the rest at LATE
EARLY_LABEL = f'{EARLY_PLAYER} Receiving Yards 40.5+'


def _props_frame():
    rows = []
    upd = '2026-11-08 11:30'      # zone-less Eastern = 16:30Z: fresh at PRE (0.5h) and at POST (1.5h)
    for i, (p, (a, h)) in enumerate(zip(PLAYERS, GAMES)):
        k = KICK if i == 0 else LATE
        # game 0's rows spell the SAME instant two ways (Z and -05:00): must canonicalize to one
        kforms = ([iso(k), (k - timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M:%S-05:00')] if i == 0 else [iso(k)])
        for j, kf in enumerate(kforms):
            rows.append({'Player': p, 'Team': '', 'Stat': 'Rec Yds', 'MarketKey': 'player_reception_yds',
                         'Line': 40.5, 'Game': f'{a}@{h}', 'Book': 'SynBook' if j == 0 else 'OtherBook',
                         'LastUpdated': upd, 'EventId': f'evt{i}', 'EventCommenceAtUTC': kf,
                         'SourceUpdatedAtUTC': '2026-11-08T16:30:00Z', 'OverOdds': -150 - i, 'UnderOdds': 120})
    return pd.DataFrame(rows)


class Fixture:
    """Patches app so the REAL build_nfl_floor_board (+ its caches) runs on a temp props file."""

    def __init__(self, td):
        self.td = Path(td)
        self.index_calls = 0
        self.disk = {}

    def __enter__(self):
        (self.td / 'props').mkdir(parents=True, exist_ok=True)
        _props_frame().to_csv(self.td / 'props' / 'NFL_Props.csv', index=False)
        gl = pd.DataFrame({'season': [2026] * 12, 'receiving_yards': [70] * 12})
        idx = {p.lower(): gl.copy() for p in PLAYERS}
        fx = self

        def _index():
            fx.index_calls += 1
            return idx
        names = ('DATA_DIR', '_now_utc', '_nfl_player_index', '_nfl_player_week_data', '_nfl_player_log_signature',
                 '_nfl_disk_cache_load', '_nfl_disk_cache_store', '_mlb_floor_legs', '_cfb_form_legs',
                 '_nfl_line_legs', '_game_date_map', 'build_nfl_current_roster_lookup', 'get_current_user',
                 'is_owner_user', 'record_active_user', 'load_card_prefs')
        self.saved = {n: getattr(app, n) for n in names}
        app.DATA_DIR = self.td
        app._now_utc = lambda: CLOCK['now']
        app._nfl_player_index = _index
        app._nfl_player_week_data = lambda: gl
        app._nfl_player_log_signature = lambda: ('qc-kickoff',)
        app._nfl_disk_cache_load = lambda key, version, ttl_seconds=86400: (
            fx.disk[key][1] if key in fx.disk and fx.disk[key][0] == version else None)
        app._nfl_disk_cache_store = lambda key, version, value, ttl_seconds=86400: fx.disk.__setitem__(key, (version, value))
        app._mlb_floor_legs = lambda *a, **k: []
        app._cfb_form_legs = lambda *a, **k: []
        app._nfl_line_legs = lambda *a, **k: []
        app._game_date_map = lambda: {}
        app.build_nfl_current_roster_lookup = lambda: {}
        owner = sorted(app.OWNER_EMAILS)[0] if app.OWNER_EMAILS else 'qc@example.invalid'
        app.get_current_user = lambda *a, **k: {'email': owner, 'user_id': 'qc-kickoff-gate', 'plan': 'all_access'}
        app.is_owner_user = lambda *a, **k: True
        app.record_active_user = lambda *a, **k: None
        app.load_card_prefs = lambda uid: {'sizes': [3, 4, 5], 'risk': 'balanced', 'legs': 'all', 'timeframe': 'week'}
        app._NFL_FLOOR_BOARD_CACHE.clear()
        return self

    def __exit__(self, *exc):
        for n, v in self.saved.items():
            setattr(app, n, v)
        app._NFL_FLOOR_BOARD_CACHE.clear()


def _card_labels(dc):
    return [[l['label'] for l in c['legs']] for c in dc['cards']]


# --------------------------------------------------------------------------- 4, 5: cache + mixed ticket
def check_board_and_tickets():
    with tempfile.TemporaryDirectory() as td, Fixture(td) as fx:
        CLOCK['now'] = PRE
        board = app.build_nfl_floor_board(limit=90, min_hit=52)
        rows = {r['player']: r for r in board['floors']}
        ok(len(rows) == len(PLAYERS), f'4: fixture floor board built ({len(rows)} rows, real builder)')
        r0 = rows.get(EARLY_PLAYER, {})
        ok(r0.get('kickoff_utc') == iso(KICK) and r0.get('event_id') == 'evt0',
           f"4: floor row carries event_id + canonical kickoff_utc from the props rows ({r0.get('event_id')}, "
           f"{r0.get('kickoff_utc')}; rows spelled it as Z and -05:00)")
        ok(all(r.get('kickoff_utc') for r in rows.values()), '4: every floor row carries kickoff_utc')
        # identity helper: ambiguity / missing -> fail closed
        g = _props_frame()
        mixed = pd.concat([g[g['Player'] == PLAYERS[0]], g[g['Player'] == PLAYERS[1]]])
        ok(app._nfl_props_event_identity(mixed)['kickoff_utc'] is None, '6: two different instants in one group -> None')
        gap = g[g['Player'] == PLAYERS[1]].copy()
        gap = pd.concat([gap, gap.assign(EventCommenceAtUTC=None)])
        ok(app._nfl_props_event_identity(gap)['kickoff_utc'] is None, '6: one row missing its kickoff -> None')
        ok(app._nfl_props_event_identity(g.drop(columns=['EventCommenceAtUTC']))['kickoff_utc'] is None,
           '6: props file without EventCommenceAtUTC -> None (fail closed)')
        naive = g[g['Player'] == PLAYERS[1]].assign(EventCommenceAtUTC='2026-11-08 21:25:00')
        ok(app._nfl_props_event_identity(naive)['kickoff_utc'] is None, '6: naive commence time -> None')

        pre = app.build_daily_cards(sizes=[3, 4, 5], risk='balanced', legs='all', timeframe='week')
        pre_labels = _card_labels(pre)
        ok(pre['cards'] and any(EARLY_LABEL in c for c in pre_labels),
           f'4: pre-kickoff the early leg IS on a card (fixture non-vacuous; {len(pre["cards"])} cards)')
        ok(all(not c['removed_started'] for c in pre['cards']), '4: pre-kickoff no card reports a removal')
        fp_pre = app.build_nfl_featured_parlay(legs=3)
        ok(fp_pre.get('available') and any(l['player'] == EARLY_PLAYER for l in fp_pre['legs']),
           '4: pre-kickoff the featured parlay carries the early leg (non-vacuous)')

        # ---- the clock passes kickoff; nothing on disk changes ----
        CLOCK['now'] = POST
        calls_before = fx.index_calls
        board2 = app.build_nfl_floor_board(limit=90, min_hit=52)
        ok(board2 is board and fx.index_calls == calls_before,
           '4: the floor board is served FROM CACHE after kickoff (stale pre-kickoff build, no rebuild)')
        post = app.build_daily_cards(sizes=[3, 4, 5], risk='balanced', legs='all', timeframe='week')
        ok(fx.index_calls == calls_before, '4: Daily Card post-kickoff reused the cached board')
        post_labels = _card_labels(post)
        ok(post['cards'] and not any(EARLY_LABEL in c for c in post_labels),
           '4: stale cached candidate is EXCLUDED from every card at final construction')
        ok(not any(b['label'] == EARLY_LABEL for b in post['bench']), '4/5: started leg is not on the swap bench')
        ok(all(b.get('kickoff_utc') and app._kickoff_gate_failure(b['kickoff_utc'], POST) is None
               for b in post['bench']), '5: every bench entry carries a kickoff strictly after the server clock')
        ctx = [c for c in post['context_lines'] if c['label'] == EARLY_LABEL]
        ok(len(ctx) == 1 and ctx[0]['price_note'] == app.STARTED_LEG_NOTE,
           '5: started leg is shown as context only, labelled "Game started"')
        ok(post['kickoff_gate']['n_started_excluded'] == 1 and post['server_now_utc'] == iso(POST),
           f"5: build reports 1 started exclusion against the SERVER clock ({post['server_now_utc']})")

        # 5: never a silent substitute -- any card whose legs changed across kickoff discloses the removal
        for c_pre, c_post in zip(pre['cards'], post['cards']):
            lp, lq = [l['label'] for l in c_pre['legs']], [l['label'] for l in c_post['legs']]
            if EARLY_LABEL in lp:
                ok(c_post['removed_started'] == [EARLY_LABEL],
                   f"5: {c_post['n']}-leg card rebuilt WITH disclosure ({c_post['removed_started']})")
            else:
                ok(lp == lq and not c_post['removed_started'],
                   f"5: {c_post['n']}-leg card without the started leg is unchanged, no removal claimed")
        for c in post['cards']:
            ok((c['american'], c['decimal'], c['payout_5']) == app._card_price(c['legs'], POST),
               f"5: {c['n']}-leg payout is computed only over not-started legs")

        fp = app.build_nfl_featured_parlay(legs=3)
        ok(fp.get('available') and not any(l['player'] == EARLY_PLAYER for l in fp['legs'])
           and fp.get('removed_started') == [EARLY_LABEL],
           f"5: featured parlay rebuilt without the started leg and says so ({fp.get('removed_started')})")

        # 5: rejection path -- not enough not-started games for the card -> rejected, and disclosed
        CLOCK['now'] = LATE + S1                       # every game has started
        allgone = app.build_daily_cards(sizes=[3], risk='safe', legs='all', timeframe='week')
        ok(not allgone['cards'] and not allgone['bench'] and allgone['kickoff_gate']['rejected_started'],
           '5: every game started -> no card, empty bench, rejection recorded (never a substitute)')
        ok(app.build_nfl_featured_parlay(legs=3).get('available') is False,
           '5: featured parlay abstains when every game has started')
        CLOCK['now'] = POST


# --------------------------------------------------------------------------- S + M: every surface
SURFACES = ('green_light_ticket', 'daily_card', 'kings_tickets', 'menu', 'image_get', 'image_post_started',
            'image_post_clean', 'featured_parlay')


def surface_checks(fx_label=''):
    """Exercise every proposed-ticket surface at POST (clock past the early kickoff). Returns
    {surface: (gate_calls, started_leg_absent, detail)}."""
    calls = {'n': 0}
    real_gate = app._kickoff_gate_failure

    def counting(k, now):
        calls['n'] += 1
        return real_gate(k, now)
    app._kickoff_gate_failure = counting
    out = {}
    from marketing.generators import weekly_cards as _wc
    from PIL import Image as _Image
    captured = {}
    orig_render = _wc.render_daily_card

    def _fake_render(card):
        captured['card'] = card
        return _Image.new('RGB', (2, 2))
    _wc.render_daily_card = _fake_render
    try:
        c = app.app.test_client()

        def page(path):
            calls['n'] = 0
            r = c.get(path)
            return r.status_code, r.get_data(as_text=True), calls['n']

        def priced_legs(html):
            # the started leg may appear as context; it must never be a priced ticket / slip leg
            legs = re.findall(r'class="dc-leg"[^>]*data-label="([^"]*)"', html)
            legs += re.findall(r'class="mb-leg"[^>]*data-label="([^"]*)"', html)
            return legs
        for name, path in (('green_light_ticket', '/tools/green-light/ticket'),
                           ('daily_card', '/tools/daily-card?timeframe=week'),
                           ('kings_tickets', '/tools/kings-tickets?timeframe=week'),
                           ('menu', '/tools/menu?timeframe=week')):
            code, html, n = page(path)
            legs = priced_legs(html)
            out[name] = (n, code == 200 and bool(legs) and EARLY_LABEL not in legs,
                         f'HTTP {code}, {len(legs)} priced legs, gate calls {n}')
            if name in ('daily_card', 'kings_tickets', 'green_light_ticket'):
                out[name + '_disclosed'] = (n, 'removed &mdash; game started' in html,
                                            'card shows "N leg removed — game started"')
                out[name + '_clock'] = (n, f'Date.parse("{iso(POST)}")' in html,
                                        'editor anchors to the server clock, not the browser clock')
            if name == 'menu':
                out['menu_context'] = (n, app.STARTED_LEG_NOTE in html, 'Menu labels the started leg as context')
        calls['n'] = 0
        captured.clear()
        r = c.get('/tools/daily-card.png?n=3&legs=all')
        got = [l['label'] for l in captured.get('card', {}).get('legs', [])]
        out['image_get'] = (calls['n'], r.status_code == 200 and len(got) == 3 and EARLY_LABEL not in got,
                            f'HTTP {r.status_code}, legs {len(got)}')
        # POST: a client-held ticket built before kickoff (carries the started leg) -> rejected whole
        code, html, _ = page('/tools/daily-card?timeframe=week')
        token = re.search(r'CSRF="([^"]+)"', html).group(1)
        CLOCK['now'] = PRE
        held = app.build_daily_cards(sizes=[3], risk='safe', legs='all', timeframe='week')['cards'][0]['legs']
        CLOCK['now'] = POST
        body = [dict(sport=l['sport'], label=l['label'], game=l['game'], tier=l['tier'], price=l['price']) for l in held]
        calls['n'] = 0
        captured.clear()
        r = c.post('/tools/daily-card.png', json={'legs': body}, headers={'X-CSRFToken': token})
        j = r.get_json(silent=True) or {}
        out['image_post_started'] = (calls['n'], EARLY_LABEL in [l['label'] for l in held] and r.status_code == 409
                                     and not captured and j.get('removed_started') == [EARLY_LABEL]
                                     and 'removed — game started' in (j.get('message') or ''),
                                     f'HTTP {r.status_code}, rendered={bool(captured)}, {j.get("message")}')
        clean = [b for b in body if b['label'] != EARLY_LABEL]
        clean += [dict(sport='NFL', label=f'{PLAYERS[5]} Receiving Yards 40.5+', game='G5A @ G5H', tier='floor',
                       price=-155)]
        calls['n'] = 0
        captured.clear()
        r = c.post('/tools/daily-card.png', json={'legs': clean}, headers={'X-CSRFToken': token})
        got = captured.get('card', {}).get('legs', [])
        out['image_post_clean'] = (calls['n'], r.status_code == 200 and len(got) == 3
                                   and all(l.get('kickoff_utc') for l in got),
                                   f'HTTP {r.status_code}, legs {len(got)} (not-started ticket still renders)')
        calls['n'] = 0
        fp = app.build_nfl_featured_parlay(legs=3)
        out['featured_parlay'] = (calls['n'], fp.get('available') and EARLY_PLAYER not in [l['player'] for l in fp['legs']],
                                  f"legs {[l['player'] for l in fp.get('legs', [])]}")
        # the Featured Parlay disclosure renders on its own surface template
        tpl = (ROOT / 'templates' / 'nfl_featured.html').read_text(encoding='utf-8')
        block = re.search(r'\{% if parlay\.removed_started %\}.*?\{% endif %\}', tpl, re.S)
        from flask import render_template_string
        with app.app.test_request_context('/'):
            html = render_template_string(block.group(0), parlay=fp) if block else ''
        tpl = (ROOT / 'templates' / 'nfl_featured.html').read_text(encoding='utf-8')
        out['featured_parlay_disclosed'] = (calls['n'], 'removed &mdash; game started' in html
                                            and 'parlay.removed_started' in tpl,
                                            'Featured Parlay template discloses the removal')
    finally:
        _wc.render_daily_card = orig_render
        app._kickoff_gate_failure = real_gate
    return out


def check_surfaces():
    with tempfile.TemporaryDirectory() as td, Fixture(td):
        CLOCK['now'] = POST
        res = surface_checks()
        for name, (n, good, detail) in res.items():
            ok(n > 0 and good, f'S: {name}: reaches the shared kickoff gate and carries no started leg ({detail})')
        # client-side mirror in the shared editor + Menu: bench/swap/add/reroll filter on the predicate
        ed = (ROOT / 'templates' / '_ticket_editor.html').read_text(encoding='utf-8')
        ok(re.search(r'function eligibleSwaps[\s\S]*?notStarted\(b\.kickoff_utc\)', ed) is not None,
           'S: editor eligibleSwaps excludes started / unknown-kickoff bench legs')
        ok(re.search(r'function eligibleAdds[\s\S]*?notStarted\(b\.kickoff_utc\)', ed) is not None,
           'S: editor eligibleAdds excludes started / unknown-kickoff bench legs')
        ok(re.search(r'function doReroll[\s\S]*?o\.length && notStarted\(o\[0\]\.kickoff_utc\)', ed) is not None,
           'S: Reroll never auto-inserts eligibleSwaps()[0] unless it passes the kickoff predicate')
        ok('t>nowMs()' in ed and 'SERVER_NOW+' in ed and 'isNaN(t)' in ed,
           'S: client predicate is strict (>), server-anchored, and fails closed on unparseable kickoff')
        menu = (ROOT / 'templates' / 'menu_board.html').read_text(encoding='utf-8')
        ok('!notStarted(l.kickoff)' in menu and 'data-kickoff=' in menu,
           'S: Menu slip refuses / blocks saving a started leg (server re-checks with 409)')


def check_mutation():
    """Disable the shared gate: the surface checks must now FAIL (the started leg reaches tickets)."""
    with tempfile.TemporaryDirectory() as td, Fixture(td):
        CLOCK['now'] = PRE
        app.build_nfl_floor_board(limit=90, min_hit=52)
        CLOCK['now'] = POST
        real = app._kickoff_gate_failure
        app._kickoff_gate_failure = lambda k, now: None          # MUTANT: no kickoff gate
        try:
            post = app.build_daily_cards(sizes=[3, 4, 5], risk='balanced', legs='all', timeframe='week')
            leaked = any(EARLY_LABEL in c for c in _card_labels(post))
            fp = app.build_nfl_featured_parlay(legs=3)
            leaked_fp = any(l['player'] == EARLY_PLAYER for l in fp.get('legs', []))
        finally:
            app._kickoff_gate_failure = real
        ok(leaked and leaked_fp, 'M: with the gate disabled the started leg DOES reach the cards + featured parlay '
                                 '(so the checks above are not vacuous)')
        # mutate the REAL function body the surfaces call through: _leg_quote_failures without the gate
        src = (ROOT / 'app.py').read_text(encoding='utf-8')
        anchor = "    _kick = _leg_kickoff_failure(leg, now)\n"
        ok(src.count(anchor) == 1, 'M: _leg_quote_failures reaches the gate exactly once (via _leg_kickoff_failure)')
        ok(len(re.findall(r'_kickoff_gate_failure\(', src)) == 2,
           'M: app.py has ONE kickoff predicate (definition + its single call site)')
        callers = _callers(src)
        ok(callers.get('_kickoff_gate_failure') == {'_leg_kickoff_failure'},
           f"M: the predicate's only caller is _leg_kickoff_failure ({callers.get('_kickoff_gate_failure')})")
        ok(callers.get('_leg_kickoff_failure') == {'_leg_quote_failures', '_sgp_apply_kickoff_gate', '_sgp_ticket_gate'},
           f"M: _leg_kickoff_failure is called only by the executable-leg contract + the SGP Workbench gate "
           f"({sorted(callers.get('_leg_kickoff_failure') or [])})")
        app._kickoff_gate_failure = lambda k, now: None
        try:
            res = surface_checks()
        finally:
            app._kickoff_gate_failure = real
        failed = [n for n, (_c, good, _d) in res.items() if not good]
        ok({'daily_card', 'kings_tickets', 'green_light_ticket', 'image_get', 'image_post_started',
            'featured_parlay'} <= set(failed),
           f'M: gate disabled => surface checks fail ({sorted(failed)})')
    # B under the mutant: with no kickoff gate the unknown-kickoff legs lose their label -> checks FAIL
    real = app._kickoff_gate_failure
    mres = []
    app._kickoff_gate_failure = lambda k, now: None
    try:
        check_context_only(rec=lambda c, m: mres.append((bool(c), m)))
    finally:
        app._kickoff_gate_failure = real
    mfail = {m for c, m in mres if not c}
    want = [m for _c, m in mres if m.startswith('B: ') and ('exact label' in m or 'MISSING_KICKOFF' in m
                                                            or 'kickoff_unavailable' in m)]
    hit = [m for m in want if m in mfail]
    ok(want and len(hit) == len(want),
       f'M: gate disabled => every context-only LABEL / fail-closed check fails ({len(hit)}/{len(want)})')


def _callers(src):
    """{callee_name: {enclosing top-level function names}} for every call in app.py source."""
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    out.setdefault(sub.func.id, set()).add(node.name)
    return out


# --------------------------------------------------------------------------- B: context-only labels
KNA = 'Kickoff unavailable — context only'
CTX_NFL = 'CTXN Bears -3.5'
CTX_CFB = 'CTXC Owls +7'
CTX_MLB = 'Syn Batter to record a hit'


def _ctx_line_legs():
    f = app._unpriced_line_fields
    nfl = [{'sport': 'NFL', 'kind': 'line', 'tier': 'edge', 'label': CTX_NFL, 'game': 'CTXN Away @ CTXN Bears',
            'reason': 'synthetic team-line context', 'score': 70, **f('SynLineSource', iso(PRE))}]
    cfb = [{'sport': 'CFB', 'kind': 'line', 'tier': 'edge', 'label': CTX_CFB, 'pick': 'CTXC Owls', 'line': 7.0,
            'game': 'CTXC Owls @ CTXC Home', 'reason': 'synthetic CFB form context', 'score': 66,
            **f('SynCfbSource', iso(PRE))}]
    mlb = [{'sport': 'MLB', 'kind': 'prop', 'tier': 'floor', 'label': CTX_MLB, 'game': 'SYA @ SYH', 'date': '',
            'hit': 81, 'sample': 40, 'reason': 'records a hit 81% of games (synthetic)', 'score': 81, **f(None)}]
    return nfl, cfb, mlb


def check_context_only(rec=ok):
    """B: legs with NO governed kickoff (team lines, MLB, a prop row without a commence time) are
    context only and are SHOWN with the exact label on every proposed-ticket surface -- never priced,
    never on a card / bench / slip, never silently dropped."""
    nfl, cfb, mlb = _ctx_line_legs()
    labels = (CTX_NFL, CTX_CFB, CTX_MLB)
    with tempfile.TemporaryDirectory() as td, Fixture(td):
        app._nfl_line_legs = lambda *a, **k: [dict(x) for x in nfl]
        app._cfb_form_legs = lambda *a, **k: [dict(x) for x in cfb]
        app._mlb_floor_legs = lambda *a, **k: [dict(x) for x in mlb]
        CLOCK['now'] = PRE
        for lg in nfl + cfb + mlb:
            rec(app._leg_kickoff_failure(lg, PRE) == 'MISSING_KICKOFF' and lg.get('kickoff_utc') is None,
                f"B: {lg['sport']} {lg['kind']} leg has no governed kickoff -> MISSING_KICKOFF (fail closed)")
        dc = app.build_daily_cards(sizes=[3, 4, 5], risk='balanced', legs='all', timeframe='week')
        ctx = {c['label']: c for c in dc['context_lines']}
        on_cards = {l['label'] for c in dc['cards'] for l in c['legs']}
        bench = {b['label'] for b in dc['bench']}
        for lab in labels:
            c = ctx.get(lab) or {}
            rec(c.get('kickoff_note') == KNA,
                f'B: Daily Card build: {lab!r} is a context line with the exact label ({c.get("kickoff_note")!r})')
            rec(bool(c) and lab not in on_cards and lab not in bench and c.get('price') is None,
                f'B: Daily Card build: {lab!r} is on no card / bench and carries no price')
        rec(dc['cards'] and all(app._card_price(c['legs'], PRE) == (c['american'], c['decimal'], c['payout_5'])
                                for c in dc['cards']),
            'B: payouts are computed only over the priced, not-started card legs (control)')

        cl = app.app.test_client()
        for name, path in (('daily_card', '/tools/daily-card?timeframe=week'),
                           ('kings_tickets', '/tools/kings-tickets?timeframe=week'),
                           ('green_light_ticket', '/tools/green-light/ticket')):
            r = cl.get(path)
            html = r.get_data(as_text=True)
            priced = re.findall(r'class="dc-leg"[^>]*data-label="([^"]*)"', html)
            for lab in labels:
                li = re.search(r'<li data-context-leg="' + re.escape(lab) + r'">(.*?)</li>', html, re.S)
                rec(r.status_code == 200 and li is not None and KNA in li.group(1),
                    f'B: {name}: {lab!r} is listed with the exact label "{KNA}"')
                rec(li is not None and lab not in priced and re.search(r'[+-]\d{3}\b', li.group(1)) is None,
                    f'B: {name}: {lab!r} has no price / ticket slot')
        r = cl.get('/tools/menu?timeframe=week')
        html = r.get_data(as_text=True)
        rows = html.split('<div class="mb-leg')
        for lab in labels:
            row = next((x for x in rows if f'<span class="mb-tp">{lab}<' in x), '')
            rec(r.status_code == 200 and 'mb-ctx' in row[:40] and KNA in row,
                f'B: menu: {lab!r} is a context row with the exact label "{KNA}"')
            rec(bool(row) and 'data-price' not in row[:300] and '>n/a<' in row,
                f'B: menu: {lab!r} carries no price and no slip control')

        # Featured Parlay: a floor prop whose rows carry no commence time is listed, not silently dropped
        board = app.build_nfl_floor_board(limit=60)
        top = board['floors'][0]
        nk_label = f"{top['player']} {top['stat']} {top['line']:g}+"
        real_board = app.build_nfl_floor_board
        app.build_nfl_floor_board = lambda *a, **k: dict(
            board, floors=[dict(board['floors'][0], kickoff_utc=None)] + [dict(f) for f in board['floors'][1:]])
        try:
            fp = app.build_nfl_featured_parlay(legs=3)
        finally:
            app.build_nfl_floor_board = real_board
        rec(nk_label in (fp.get('kickoff_unavailable') or [])
            and top['player'] not in [l['player'] for l in fp.get('legs', [])],
            f"B: featured parlay: the unknown-kickoff leg is listed in kickoff_unavailable, not on the parlay "
            f"({fp.get('kickoff_unavailable')})")
        from flask import render_template_string
        for tname, pat in (('nfl_featured.html', r'\{% if parlay and parlay\.available %\}.*?\{% endif %\}(?=\s*\{% if not available %\})'),
                           ('nfl_hub.html', r'\{% if parlay and parlay\.available %\}.*?props are in\..*?\{% endif %\}</div>\{% endif %\}')):
            tpl = (ROOT / 'templates' / tname).read_text(encoding='utf-8')
            blk = re.search(pat, tpl, re.S)
            src_blk = blk.group(0) if blk else ''
            with app.app.test_request_context('/'):
                out_html = render_template_string(src_blk, parlay=fp) if src_blk else ''
                none_html = render_template_string(src_blk, parlay=dict(
                    available=False, kickoff_unavailable=[nk_label], removed_started=[])) if src_blk else ''
            rec(bool(src_blk) and KNA in out_html and nk_label in out_html,
                f'B: {tname}: featured parlay renders the exact label for the kickoff_unavailable leg')
            rec(bool(src_blk) and KNA in none_html and nk_label in none_html,
                f'B: {tname}: the label still renders when no featured parlay could be built')


def main() -> int:
    for fn in (check_predicate, check_board_and_tickets, check_surfaces, check_context_only, check_mutation):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            ok(False, f'{fn.__name__} crashed: {exc!r}')
    print('=' * 60)
    print('BANKROLL KINGS TICKET KICKOFF GATE QC (D4)')
    print('=' * 60)
    for passed, msg in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")
    n_fail = sum(1 for p, _ in results if not p)
    print(f'\n{len(results) - n_fail}/{len(results)} passed')
    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
