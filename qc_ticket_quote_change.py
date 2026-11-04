"""QC: quote-change atomicity -- a changed quote rejects the WHOLE ticket; it is never silently repriced (D4).

Owner decision 1: at the final server submission boundary the quote terms the user saw and confirmed
(sportsbook, event, market, selection, line, price) are compared -- after canonicalization -- with the
CURRENT canonical server quote. A changed book / line / price (a BETTER price too) or an event / market /
selection mismatch rejects the entire ticket (409) with per-leg reason codes and the current safe terms;
no image, no export, no handoff, no partial save, no file write. Formatting-only differences compare equal.
Owner decision 3: the executable ticket range is frozen at 2..8 legs (1 / 9+ rejected, never truncated).

Boundaries under test (synthetic pools + menus, frozen server clock, renderer patched, temp dirs, isolated
owner principal from services.qc_auth, no network, no user-store writes):
  IMG  POST /tools/daily-card.png -- the shared editor (Today's Cards / King's Tickets / Green Light ticket)
       and the Menu slip
  SGP  GET /tools/sgp-workbench export / handoff (confirmed terms = the selection id + `cf=<id>~<price>`)
Checks: worse price / better price -> PRICE_CHANGED; changed line, same price -> LINE_CHANGED; changed book
-> BOOK_CHANGED; selection mismatch -> QUOTE_MISMATCH; no terms -> QUOTE_UNCONFIRMED; equivalent numeric /
string / book-alias formatting -> accepted with identical canonical terms; stale current quote ->
QUOTE_STALE; missing current quote -> QUOTE_UNAVAILABLE; corrected resubmission with the current terms ->
accepted with exactly those legs and terms; zero artifacts on every rejection (renderer not called, no new
files under the temp DATA_DIR / repo cache / prefs / runtime dirs); the response carries the current safe
terms and no raw payload echo; the log canary is absent; 1 leg / 9 legs rejected, never truncated; a
forged client price is never used.
  M  mutations: re-enable repricing (image verdict / SGP confirmation ignored) or drop the 2..8 count gate
     -> the matching checks FAIL.
Exit 0 = all pass, 1 = any failure.
"""
from __future__ import annotations

from services.qc_no_network import install as _block_network

_block_network()  # before importing app: nothing below may reach the network

import ast  # noqa: E402
import contextlib  # noqa: E402
import copy  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SECRET_KEY', 'qc-ticket-quote-change')

import app  # noqa: E402
from services.qc_auth import isolated_owner_client  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 11, 8, 17, 0, 0, tzinfo=UTC)
LATE = NOW + timedelta(hours=4)
CANARY = 'QC-CANARY-QUOTE-9c41e2-RAW'
CSRF = 'qc-quote-change-csrf'
REJ = '[REJ]'                     # marks a rejection assertion (the mutation runs require these to FAIL)
results: list[tuple[bool, str]] = []


def ok(cond, msg):
    results.append((bool(cond), msg))
    return bool(cond)


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


# ------------------------------------------------------------------ synthetic card pool (mutable server state)
def pool_leg(i, price=-150, line=40.5, book='SynBook', upd_h=1.0, quoted=True):
    at = iso(NOW - timedelta(hours=upd_h))
    leg = {'sport': 'NFL', 'kind': 'prop', 'tier': 'floor', 'player': f'Quote Receiver {i}',
           'label': f'Quote Receiver {i} Receiving Yards {line:g}+', 'game': f'QA{i} @ QH{i}', 'line': line,
           'reason': 'qc synthetic', 'hit': 70, 'sample': 12, 'score': 100 - i,
           'event_id': f'evt-quote-{i}', 'kickoff_utc': iso(LATE)}
    if quoted:
        q = {'book': book, 'price': price, 'line': line, 'event': f'QA{i}@QH{i}',
             'market': 'player_reception_yds', 'selection': f'Quote Receiver {i} Over {line:g}', 'updated_utc': at}
        leg.update(price=price, quote=q, book=book, quote_at=at, quote_label='qc')
    else:
        leg.update(price=None, price_status='UNAVAILABLE', executable=False, line_source='Unrecorded source')
    return leg


def base_pool():
    # 1: plain; 2: plus-money (+150); 3: Caesars (alias williamhill_us); 4: plain; 10..18: extra valid legs
    return ([pool_leg(1), pool_leg(2, price=150), pool_leg(3, book='Caesars'), pool_leg(4)]
            + [pool_leg(i) for i in range(10, 19)])


STATE = {'pool': base_pool()}


def server(i):
    return next(l for l in STATE['pool'] if l['player'] == f'Quote Receiver {i}')


def set_server(i, **kw):
    STATE['pool'] = [pool_leg(i, **kw) if l['player'] == f'Quote Receiver {i}' else l for l in STATE['pool']]


def confirmed(leg, **extra):
    """What the browser sends for ONE leg: identity + display fields (+ canary) + the quote terms the user
    saw, exactly as ticket_quote_terms rendered them."""
    w = {'sport': leg['sport'], 'label': leg['label'], 'game': leg['game'], 'tier': leg['tier'],
         'reason': f'{CANARY} reason', 'note': CANARY}
    w.update(app.ticket_quote_terms(leg) or {})
    w.update(extra)
    return w


class Fixture:
    def __init__(self, td):
        self.td = Path(td)
        self.renders = []

    def __enter__(self):
        from marketing.generators import weekly_cards as _wc
        from PIL import Image as _Image
        self._wc = _wc
        names = ('DATA_DIR', '_now_utc', '_card_pools', '_game_date_map', 'record_active_user', '_CARD_PREFS_DIR',
                 '_nfl_sgp_leg_menu', 'build_nfl_matchup_context', '_nfl_line_move')
        self.saved = {n: getattr(app, n) for n in names}
        self.saved_render = _wc.render_daily_card
        self.saved_env = os.environ.get('BK_RUNTIME_DIR')
        (self.td / 'data').mkdir()
        (self.td / 'prefs').mkdir()
        (self.td / 'runtime').mkdir()
        os.environ['BK_RUNTIME_DIR'] = str(self.td / 'runtime')
        app.DATA_DIR = self.td / 'data'
        app._CARD_PREFS_DIR = str(self.td / 'prefs')
        app._now_utc = lambda: NOW
        app._card_pools = lambda legs='all', mlb_limit=12, cfb_limit=10, nfl_line_limit=8, now=None: (
            copy.deepcopy(STATE['pool']), [])
        app._game_date_map = lambda: {}
        app.record_active_user = lambda *a, **k: None
        app._nfl_sgp_leg_menu = lambda away, home: [{'cat': 'Receiving', 'legs': copy.deepcopy(SGP['legs'])}]
        app.build_nfl_matchup_context = lambda: {'mu_week': [{'away': SGP_AWAY, 'home': SGP_HOME}]}
        app._nfl_line_move = lambda a, h: None
        fx = self

        def _fake_render(card):
            fx.renders.append(copy.deepcopy(card))
            return _Image.new('RGB', (4, 4))
        _wc.render_daily_card = _fake_render
        return self

    def __exit__(self, *exc):
        for n, v in self.saved.items():
            setattr(app, n, v)
        self._wc.render_daily_card = self.saved_render
        if self.saved_env is None:
            os.environ.pop('BK_RUNTIME_DIR', None)
        else:
            os.environ['BK_RUNTIME_DIR'] = self.saved_env


def snapshot(*dirs):
    out = {}
    for d in dirs:
        d = Path(d)
        if not d.exists():
            continue
        for p in d.rglob('*'):
            if p.is_file():
                st = p.stat()
                out[str(p)] = (st.st_size, st.st_mtime_ns)
    return out


@contextlib.contextmanager
def captured_output():
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setLevel(logging.DEBUG)
    root = logging.getLogger()
    lvl_app, lvl_root = app.app.logger.level, root.level
    app.app.logger.addHandler(h)
    root.addHandler(h)
    app.app.logger.setLevel(logging.DEBUG)
    root.setLevel(logging.DEBUG)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            yield lambda: buf.getvalue() + out.getvalue() + err.getvalue()
    finally:
        app.app.logger.removeHandler(h)
        root.removeHandler(h)
        app.app.logger.setLevel(lvl_app)
        root.setLevel(lvl_root)


def post(client, legs):
    return client.post('/tools/daily-card.png', json={'legs': legs}, headers={'X-CSRFToken': CSRF})


# ------------------------------------------------------------------ canonicalization unit checks
def check_canon(rec):
    P, L, B, T = app._canon_quote_price, app._canon_quote_line, app._canon_quote_book, app._canon_quote_text
    rec(P(150) == P('+150') == P('150') == P(150.0) == P('150.0') == 150 and P(-125) == P('-125') == P('-125.0'),
        'CANON price: 150 == "+150" == "150" == 150.0 == "150.0"; -125 == "-125" == "-125.0"')
    rec(P(True) is None and P('1x0') is None and P(150.5) is None and P(float('nan')) is None and P(None) is None,
        'CANON price: bool / text / fractional / NaN / None are unreadable (malformed), never coerced')
    rec(L(-3.5) == L('-3.5') == L('-3.50') and L('+3.5') == L(3.5) == L('3.50') and L('x') is None
        and L(True) is None, 'CANON line: -3.5 == "-3.5" == "-3.50"; "+3.5" == 3.5; text / bool unreadable')
    rec(B('DraftKings') == B(' draft kings ') == B('draftkings') == B('DRAFTKINGS')
        and B('williamhill_us') == B('Caesars') and B('consensus') == '' and B(7) is None
        and B('FanDuel') != B('DraftKings'),
        'CANON book: case / whitespace / alias insensitive (williamhill_us == Caesars); non-book -> "", never a book')
    rec(T('QA1 @ QH1') == T('qa1@qh1') and T('player_reception_yds') == T('Player Reception Yds')
        and T('Quote Receiver 1 Over 40.5', drop_numbers=True) == T('quote receiver 1 OVER 42.5', drop_numbers=True)
        and T('Over 40.50') == T('over 40.5') and T('Over 40.5') != T('Over 42.5'),
        'CANON text: case / spacing / punctuation insensitive, numbers respelled; selection compare masks the line')
    src = (ROOT / 'fetch_player_props.py').read_text(encoding='utf-8')
    titles = None
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'BOOKMAKER_TITLES' for t in node.targets):
            titles = ast.literal_eval(node.value)
    rec(titles == app._TICKET_BOOK_ALIASES,
        'CANON book: the alias table is in parity with fetch_player_props.BOOKMAKER_TITLES (one book vocabulary)')
    rec(app.TICKET_SUBMIT_MIN_LEGS == 2 and app.TICKET_SUBMIT_MAX_LEGS == 8
        and app.TICKET_SUBMIT_MIN_LEGS <= app.TICKET_EDITOR_MAX_LEGS <= app.TICKET_SUBMIT_MAX_LEGS,
        'CONTRACT: the executable ticket range is the frozen shared 2..8 constant (editor cap inside it)')
    for tpl in ('_ticket_editor.html', 'menu_board.html'):
        t = (ROOT / 'templates' / tpl).read_text(encoding='utf-8')
        rec('TICKET_SUBMIT_MIN_LEGS' in t and 'ticket_quote_terms' in t and not re.search(r'MAX\s*=\s*\d', t)
            and 'slip.length>8' not in t,
            f'CONTRACT: {tpl} reads the shared range + confirmable terms (no hard-coded leg limits)')


# ------------------------------------------------------------------ image POST
def ids(legs):
    return [l.get('label') for l in legs]


def check_image(rec, client, fx):
    dirs = (fx.td, Path(fx.saved['DATA_DIR']) / 'cache', ROOT / 'data' / 'user_prefs')
    before = snapshot(*dirs)
    with captured_output() as logs:
        STATE['pool'] = base_pool()
        four = [server(i) for i in (1, 2, 3, 4)]
        sub = [confirmed(l) for l in four]

        # baseline: confirmed current terms -> accepted, priced from the server quote
        n0 = len(fx.renders)
        r = post(client, sub)
        card = fx.renders[-1] if len(fx.renders) == n0 + 1 else {}
        rec(r.status_code == 200 and r.mimetype == 'image/png' and ids(card.get('legs', [])) == ids(four),
            f'IMG baseline: confirmed current terms -> 200 image/png with exactly the 4 legs (HTTP {r.status_code})')

        def rejected(tag, r, n0, pos, codes, current=True):
            j = r.get_json(silent=True) or {}
            entries = j.get('legs') or []
            bl = [e for e in entries if not e.get('executable')]
            body = r.data.decode('utf-8', 'replace')
            rec(r.status_code == 409 and r.mimetype == 'application/json' and len(fx.renders) == n0
                and not r.data.startswith(b'\x89PNG'),
                f'{tag}: -> 409 JSON, renderer not called, no image bytes {REJ} (HTTP {r.status_code})')
            rec(len(entries) == 4 and [e.get('position') for e in bl] == [pos]
                and bl and all(c in bl[0].get('reasons', []) for c in codes),
                f'{tag}: the whole ticket is rejected; only position {pos} blocked with {codes} {REJ} '
                f'({[(e.get("position"), e.get("reasons")) for e in bl]})')
            cur = (bl[0].get('current') if bl else None) or {}
            if current:
                rec({'book', 'line', 'price', 'updated_utc', 'updated_label', 'label', 'event', 'market',
                     'selection'} <= set(cur), f'{tag}: the blocked leg carries the CURRENT safe terms {REJ}')
            else:
                rec(bl and 'current' not in bl[0], f'{tag}: a non-executable current quote offers no terms to confirm')
            rec(CANARY not in body and json.dumps(sub) not in body,
                f'{tag}: no raw payload echo (canary absent from the response)')
            return j, cur

        # worse / better price -> PRICE_CHANGED (a better price is a change too)
        for tag, new in (('IMG price worse', -170), ('IMG price better', -130)):
            set_server(1, price=new)
            n0 = len(fx.renders)
            j, cur = rejected(tag, post(client, sub), n0, 1, ['PRICE_CHANGED'])
            rec(cur.get('price') == new and cur.get('book') == 'SynBook' and cur.get('line') == 40.5
                and j.get('error') == 'quote_changed', f'{tag}: current terms show the server price {new:+d}')
        # corrected resubmission with the current terms -> accepted with exactly those legs + terms
        cur_terms = {k: cur.get(k) for k in ('book', 'event', 'market', 'selection', 'line', 'price')}
        n0 = len(fx.renders)
        r = post(client, [dict(sub[0], **cur_terms)] + sub[1:])
        card = fx.renders[-1] if len(fx.renders) == n0 + 1 else {}
        rec(r.status_code == 200 and ids(card.get('legs', [])) == ids(four)
            and [l['price'] for l in card['legs']] == [-130, 150, -150, -150]
            and card['legs'][0]['quote'] == server(1)['quote'],
            f'IMG corrected price: resubmitting the current terms -> 200 with exactly those legs and terms '
            f'(HTTP {r.status_code})')
        STATE['pool'] = base_pool()

        # changed line, same price -> LINE_CHANGED (label carries the line: resolved by event/market/selection)
        set_server(1, line=42.5)
        n0 = len(fx.renders)
        j, cur = rejected('IMG line moved', post(client, sub), n0, 1, ['LINE_CHANGED'])
        rec((j.get('legs') or [{}])[0].get('reasons') == ['LINE_CHANGED'] and cur.get('line') == 42.5 and cur.get('price') == -150
            and cur.get('label') == 'Quote Receiver 1 Receiving Yards 42.5+' and (j.get('legs') or [{}])[0].get('label') == sub[0]['label'],
            'IMG line moved: LINE_CHANGED alone (same price); current names the new line + label')
        n0 = len(fx.renders)
        fix = dict(sub[0], label=cur.get('label') or sub[0]['label'],
                   **{k: cur.get(k) for k in ('book', 'event', 'market', 'selection', 'line', 'price')})
        r = post(client, [fix] + sub[1:])
        card = fx.renders[-1] if len(fx.renders) == n0 + 1 else {}
        rec(r.status_code == 200 and ids(card.get('legs', [])) == [cur.get('label')] + ids(four)[1:]
            and card['legs'][0]['quote']['line'] == 42.5,
            f'IMG corrected line: resubmitting the current label + terms -> 200 with exactly those legs (HTTP {r.status_code})')
        # a line change on a label that does not carry it (exact identity) is LINE_CHANGED too
        STATE['pool'] = base_pool()
        lg = pool_leg(1, line=41.5)
        lg['label'] = server(1)['label']
        STATE['pool'] = [lg if l['player'] == 'Quote Receiver 1' else l for l in STATE['pool']]
        n0 = len(fx.renders)
        rejected('IMG line changed (same label)', post(client, sub), n0, 1, ['LINE_CHANGED'])
        STATE['pool'] = base_pool()

        # changed book -> BOOK_CHANGED
        set_server(1, book='OtherBook')
        n0 = len(fx.renders)
        j, cur = rejected('IMG book changed', post(client, sub), n0, 1, ['BOOK_CHANGED'])
        rec((j.get('legs') or [{}])[0].get('reasons') == ['BOOK_CHANGED'] and cur.get('book') == 'OtherBook',
            'IMG book changed: BOOK_CHANGED alone; current names the new sportsbook')
        STATE['pool'] = base_pool()

        # event / market / selection mismatch -> QUOTE_MISMATCH
        n0 = len(fx.renders)
        rejected('IMG selection mismatch', post(client, [dict(sub[0], market='player_rush_yds')] + sub[1:]),
                 n0, 1, ['QUOTE_MISMATCH'])
        # no terms at all (an older client) -> QUOTE_UNCONFIRMED (conservative), with the current terms
        old = [{k: s[k] for k in ('sport', 'label', 'game', 'tier', 'price')} for s in sub]
        n0 = len(fx.renders)
        r = post(client, [old[0]] + sub[1:])
        rejected('IMG unconfirmed', r, n0, 1, ['QUOTE_UNCONFIRMED'])
        # a forged book carrying the canary -> BOOK_CHANGED, and the canary is never echoed
        n0 = len(fx.renders)
        r = post(client, [dict(sub[0], book=CANARY)] + sub[1:])
        rejected('IMG forged book', r, n0, 1, ['BOOK_CHANGED'])
        # unreadable confirmed terms -> 422 malformed, nothing rendered
        for name, bad in (('price text', {'price': 'plus one fifty'}), ('price fractional', {'price': -150.5}),
                          ('line object', {'line': {'v': 40.5}}), ('book number', {'book': 7})):
            n0 = len(fx.renders)
            r = post(client, [dict(sub[0], **bad)] + sub[1:])
            jj = r.get_json(silent=True) or {}
            rec(r.status_code == 422 and len(fx.renders) == n0 and jj.get('error') == 'malformed_ticket',
                f'IMG unreadable terms ({name}) -> 422 malformed_ticket, nothing rendered {REJ} (HTTP {r.status_code})')

        # stale current quote -> QUOTE_STALE ; missing current quote -> QUOTE_UNAVAILABLE (no terms offered)
        set_server(1, upd_h=7.0)
        n0 = len(fx.renders)
        rejected('IMG stale current quote', post(client, sub), n0, 1, ['QUOTE_STALE'], current=False)
        STATE['pool'] = base_pool()
        set_server(1, quoted=False)
        n0 = len(fx.renders)
        rejected('IMG missing current quote', post(client, [dict(sub[0])] + sub[1:]), n0, 1,
                 ['QUOTE_UNAVAILABLE'], current=False)
        STATE['pool'] = base_pool()

        # equivalent formatting -> accepted with identical canonical terms
        fmt = [dict(sub[0], price='-150.0', line='40.50', book=' synbook ', event='qa1 @ qh1',
                    market='Player Reception Yds', selection='quote receiver 1 OVER 40.50'),
               dict(sub[1], price='+150'), dict(sub[2], book='williamhill_us'), dict(sub[3], price=-150.0)]
        for variant in (fmt, [dict(fmt[0]), dict(sub[1], price='150'), fmt[2], fmt[3]],
                        [dict(fmt[0]), dict(sub[1], price=150.0), fmt[2], fmt[3]]):
            n0 = len(fx.renders)
            r = post(client, variant)
            card = fx.renders[-1] if len(fx.renders) == n0 + 1 else {}
            rec(r.status_code == 200 and ids(card.get('legs', [])) == ids(four)
                and [l['quote'] for l in card['legs']] == [l['quote'] for l in four]
                and [l['price'] for l in card['legs']] == [-150, 150, -150, -150],
                f'IMG formatting: equivalent spellings ({variant[1]["price"]!r}, "40.50", " synbook ", '
                f'williamhill_us) -> 200 with identical canonical server terms (HTTP {r.status_code})')

        # 2..8 frozen range: 1 and 9 rejected (never truncated); 2 and 8 accepted
        extra = [confirmed(server(i)) for i in range(10, 19)]
        for n, want in ((1, 422), (9, 422), (2, 200), (8, 200)):
            legs = (sub + extra)[:n]
            n0 = len(fx.renders)
            r = post(client, legs)
            jj = r.get_json(silent=True) or {}
            if want == 422:
                rec(r.status_code == 422 and jj.get('error') == 'wrong_leg_count' and len(fx.renders) == n0
                    and (('at least 2' in jj.get('message', '')) if n == 1 else ('at most 8' in jj.get('message', ''))),
                    f'IMG count: {n} leg(s) -> 422 wrong_leg_count with a clear message, nothing rendered '
                    f'(never truncated) {REJ} (HTTP {r.status_code})')
            else:
                card = fx.renders[-1] if len(fx.renders) == n0 + 1 else {}
                rec(r.status_code == 200 and len(card.get('legs', [])) == n,
                    f'IMG count: {n} legs -> 200 with exactly {n} legs (HTTP {r.status_code})')
        log_text = logs()
    after = snapshot(*dirs)
    rec(after == before, f'IMG files: no file created / changed under the temp DATA_DIR, repo cache, prefs or '
                         f'runtime dirs across every rejection ({len(set(after) ^ set(before))} changed paths)')
    rec(CANARY not in log_text and 'Quote Receiver' not in log_text and '"legs"' not in log_text,
        'IMG log: logs / stdout / stderr carry no canary, label or raw payload')
    rec('PRICE_CHANGED' in log_text and 'LINE_CHANGED' in log_text and 'BOOK_CHANGED' in log_text,
        'IMG log: the sanitized rejection line carries the change reason codes')


# ------------------------------------------------------------------ SGP Workbench export / handoff
SGP_AWAY, SGP_HOME = 'Quote Away Hawks', 'Quote Home Bears'
SGP_GAME = f'{SGP_AWAY}@{SGP_HOME}'


def sgp_leg(i, price=-115, line=None, book='SynBook', upd_h=0.5):
    line = 40.5 + i if line is None else line
    lg = {'kind': 'player', 'category': 'Receiving', 'player': f'Quote Sgp {i}', 'team': 'BEARS', 'position': None,
          'stat': 'Rec Yds', 'direction': 'OVER', 'line': line, 'price': price, 'book': book,
          'timestamp': iso(NOW - timedelta(hours=upd_h)), 'source_updated_utc': iso(NOW - timedelta(hours=upd_h)),
          'tz': 'provider source time',
          'quote_scope': 'individual', 'lineage': 'synthetic', 'lean': None, 'inj': None,
          'label': f'Quote Sgp {i} OVER Rec Yds {line:g}', 'event_id': 'evt-quote-sgp', 'kickoff_utc': iso(LATE)}
    lg['id'] = '|'.join([book, 'player', lg['player'], 'Rec Yds', 'OVER', str(line)])
    return lg


def sgp_base():
    return [sgp_leg(1), sgp_leg(2, price=150), sgp_leg(3), sgp_leg(4)] + [sgp_leg(i) for i in range(10, 15)]


SGP = {'legs': sgp_base()}


def sgp_set(i, **kw):
    SGP['legs'] = [sgp_leg(i, **kw) if l['player'] == f'Quote Sgp {i}' else l for l in SGP['legs']]


def sgp_by(i):
    return next(l for l in SGP['legs'] if l['player'] == f'Quote Sgp {i}')


def sgp_url(sel, conf):
    return '/tools/sgp-workbench?' + urlencode([('game', SGP_GAME), ('thesis', 'custom')] + [('sel', i) for i in sel]
                                               + [('cf', f'{i}~{p}') for i, p in conf])


def sgp_get(client, sel, conf):
    r = client.get(sgp_url(sel, conf))
    return r.status_code, r.get_data(as_text=True)


def copy_lines(page):
    import html as _h
    return re.findall(r'^- (.+?) \| (.+?) \| (.+?) \| ', _h.unescape(page), re.M)


def check_sgp(rec, client, fx):
    dirs = (fx.td, Path(fx.saved['DATA_DIR']) / 'cache', ROOT / 'data' / 'user_prefs')
    before = snapshot(*dirs)
    SGP['legs'] = sgp_base()
    four = [sgp_by(i) for i in (1, 2, 3, 4)]
    sel = [l['id'] for l in four]
    conf = [(l['id'], f"{l['price']:+d}") for l in four]

    def ctx(sel_, conf_):
        return app.build_sgp_workbench_context(game=SGP_GAME, selected_ids=sel_, thesis='custom',
                                               confirmed=[f'{i}~{p}' for i, p in conf_])

    c = ctx(sel, conf)
    rec((c.get('handoff') or {}).get('status') == 'held' and c['ticket_gate']['executable'],
        'SGP baseline: a confirmed 4-leg ticket is exportable (handoff held, full-fidelity copy)')
    code, page = sgp_get(client, sel, conf)
    rec(code == 200 and [x[0] for x in copy_lines(page)] == [l['label'] for l in four]
        and [x[2] for x in copy_lines(page)] == [f"{l['price']:+d}" for l in four],
        f'SGP baseline: the export copy lists exactly the confirmed legs at their server prices (HTTP {code})')

    def rejected(tag, sel_, conf_, code_, reason):
        cx = ctx(sel_, conf_)
        h = cx.get('handoff') or {}
        bl = h.get('legs') or []
        rec(h.get('status') == 'rejected' and not cx['ticket_gate']['executable'] and len(bl) == 1
            and all(cc in bl[0].get('reasons', []) for cc in code_),
            f'{tag}: export / handoff REJECTED with {code_} on exactly one leg {REJ} '
            f'({h.get("status")}, {[b.get("reasons") for b in bl]})')
        if reason:
            rec(h.get('reason') == reason, f'{tag}: rejection reason is {reason} ({h.get("reason")})')
        st, pg = sgp_get(client, sel_, conf_)
        rec(st == 200 and 'data-sgp-rejected="1"' in pg and '| scope:' not in pg,
            f'{tag}: the rendered page shows the rejection and NO export copy {REJ} (HTTP {st})')
        return cx, bl[0] if bl else {}, pg

    # worse / better price
    for tag, new in (('SGP price worse', -140), ('SGP price better', -105)):
        sgp_set(1, price=new)
        cx, b, pg = rejected(tag, sel, conf, ['PRICE_CHANGED'], 'quote_changed')
        rec((b.get('current') or {}).get('price') == new and (b.get('confirmed') or {}).get('price') == -115
            and 'data-sgp-confirm=' in pg and 'Confirm current terms' in pg,
            f'{tag}: shows confirmed -115 -> current {new:+d} with an explicit "Confirm current terms" link')
    # corrected: follow the confirm link -> exportable with exactly those legs and the current price
    st = client.get(b.get('confirm_url') or sgp_url(sel, conf))
    pg = st.get_data(as_text=True)
    rec(st.status_code == 200 and [x[0] for x in copy_lines(pg)] == [l['label'] for l in four]
        and [x[2] for x in copy_lines(pg)][0] == '-105' and 'data-sgp-rejected' not in pg,
        'SGP corrected price: the confirm link re-confirms the current terms -> exportable with exactly those legs')
    SGP['legs'] = sgp_base()

    # changed line (same price): the id carries the line -> LINE_CHANGED with the current id / terms
    sgp_set(1, line=43.5)
    cx, b, pg = rejected('SGP line moved', sel, conf, ['LINE_CHANGED'], 'quote_changed')
    new_id = sgp_by(1)['id']
    rec(b.get('reasons') == ['LINE_CHANGED'] and (b.get('current') or {}).get('id') == new_id
        and (b.get('current') or {}).get('line') == 43.5 and (b.get('confirmed') or {}).get('line') == 41.5
        and cx['ticket_gate']['unresolved'] == [], 'SGP line moved: LINE_CHANGED alone (41.5 -> 43.5), not NOT_ON_BOARD')
    st = client.get(b.get('confirm_url') or sgp_url(sel, conf))
    pg = st.get_data(as_text=True)
    rec(st.status_code == 200 and [x[0] for x in copy_lines(pg)] == [sgp_by(1)['label']] + [l['label'] for l in four[1:]],
        'SGP corrected line: the confirm link swaps in the current leg -> exportable with exactly those legs')
    SGP['legs'] = sgp_base()

    # changed book
    sgp_set(1, book='OtherBook')
    cx, b, pg = rejected('SGP book changed', sel, conf, ['BOOK_CHANGED'], 'quote_changed')
    rec(b.get('reasons') == ['BOOK_CHANGED'] and (b.get('current') or {}).get('book') == 'OtherBook',
        'SGP book changed: BOOK_CHANGED alone; current names the new sportsbook')
    SGP['legs'] = sgp_base()

    # no confirmation (old URL state) -> QUOTE_UNCONFIRMED ; forged +900 -> PRICE_CHANGED, never exported
    rejected('SGP unconfirmed', sel, conf[1:], ['QUOTE_UNCONFIRMED'], 'quote_changed')
    cx, b, pg = rejected('SGP forged price', sel, [(sel[0], '+900')] + conf[1:], ['PRICE_CHANGED'], 'quote_changed')
    rec((b.get('current') or {}).get('price') == -115, 'SGP forged price: the current (server) price stays -115')
    # stale / missing current quote
    sgp_set(1, upd_h=7.0)
    rejected('SGP stale current quote', sel, conf, ['QUOTE_STALE'], 'quote_gate')
    SGP['legs'] = sgp_base()
    sgp_set(1, price=None)
    rejected('SGP missing current quote', sel, conf, ['QUOTE_UNAVAILABLE'], 'quote_gate')
    SGP['legs'] = sgp_base()

    # equivalent formatting: "+150" / "150" / "150.0", respelled book + line in the id -> the same legs
    respelled = 'synbook|player|Quote Sgp 1|Rec Yds|OVER|41.50'
    for p2 in ('+150', '150', '150.0'):
        cf2 = [(respelled, '-115.0'), (sel[1], p2)] + conf[2:]
        cx = ctx([respelled] + sel[1:], cf2)
        rec((cx.get('handoff') or {}).get('status') == 'held' and [l['id'] for l in cx['selected']] == sel,
            f'SGP formatting: equivalent spellings (id "synbook ... 41.50", price {p2!r}) -> exportable, '
            f'identical canonical legs')

    # 2..8 frozen range: 1 / 9 rejected (all legs kept, never truncated); 2 / 8 exportable
    every = [l for l in SGP['legs']]
    for n in (1, 9, 2, 8):
        sel_n = [l['id'] for l in every[:n]]
        conf_n = [(l['id'], f"{l['price']:+d}") for l in every[:n]]
        cx = ctx(sel_n, conf_n)
        h = cx.get('handoff') or {}
        if n in (1, 9):
            rec(h.get('status') == 'rejected' and h.get('reason') == 'leg_count' and len(cx['selected']) == n
                and h.get('leg_count_error'),
                f'SGP count: {n} leg(s) -> export REJECTED (leg_count), all {n} kept, never truncated {REJ}')
        else:
            rec(h.get('status') == 'held' and len(cx['selected']) == n,
                f'SGP count: {n} legs -> exportable with exactly {n} legs')
    after = snapshot(*dirs)
    rec(after == before, f'SGP files: no file created / changed on any rejection ({len(set(after) ^ set(before))} paths)')


# ------------------------------------------------------------------ runner + mutations
class _EqAny(int):
    """Equal to every price (formats as 0)."""
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = int.__hash__


class _AlwaysMatch(dict):
    """Mutation: every SGP confirmation 'matches' the current price -- i.e. the server reprices silently."""
    def get(self, key, default=None):
        return _EqAny()


def run_all(rec):
    with tempfile.TemporaryDirectory() as td, Fixture(td) as fx, isolated_owner_client('qc-quote-owner') as client:
        with client.session_transaction() as sess:
            sess['_csrf_token'] = CSRF
        for name, fn in (('CANON', lambda: check_canon(rec)), ('IMG', lambda: check_image(rec, client, fx)),
                         ('SGP', lambda: check_sgp(rec, client, fx))):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                rec(False, f'{name} crashed: {exc!r}')
        STATE['pool'] = base_pool()
        SGP['legs'] = sgp_base()


def mutation(label, patches, prefixes):
    saved = {k: getattr(app, k) for k in patches}
    res = []
    for k, v in patches.items():
        setattr(app, k, v)
    try:
        run_all(lambda c, m: res.append((bool(c), m)))
    finally:
        for k, v in saved.items():
            setattr(app, k, v)
    must = [m for _c, m in res if REJ in m and any(m.startswith(p) for p in prefixes)]
    failed = {m for c, m in res if not c}
    missed = [m for m in must if m not in failed]
    ok(len(must) >= 4 and not missed, f'{label} => {len(must) - len(missed)}/{len(must)} rejection checks FAIL'
       + (f' (still passing: {missed[:3]})' if missed else ''))


def main() -> int:
    run_all(ok)
    mutation('M1: image repricing re-enabled (confirmed terms ignored)',
             {'_confirmed_terms_verdict': lambda sub, srv: ([], False)},
             ('IMG price', 'IMG line moved', 'IMG line changed', 'IMG book', 'IMG selection', 'IMG unconfirmed',
              'IMG forged book'))
    mutation('M2: SGP repricing re-enabled (every confirmation matches the current price)',
             {'_sgp_parse_confirmed': lambda raw: _AlwaysMatch()},
             ('SGP price', 'SGP unconfirmed', 'SGP forged price'))
    mutation('M3: the 2..8 leg-count gate removed (truncation / 1-leg tickets possible)',
             {'_ticket_leg_count_failure': lambda n: None}, ('IMG count', 'SGP count'))

    print('=' * 60)
    print('BANKROLL KINGS QUOTE-CHANGE ATOMICITY QC (D4)')
    print('=' * 60)
    for passed, msg in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")
    n_fail = sum(1 for p, _ in results if not p)
    print(f'\n{len(results) - n_fail}/{len(results)} passed')
    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
