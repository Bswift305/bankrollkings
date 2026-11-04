"""QC: a user-submitted ticket is ATOMIC -- accepted whole or rejected whole, never silently trimmed (D4).

Residual R2 (cache audit at e1e33dc): the Daily Card image POST re-resolved the browser's legs against the
server pool, returned 409 only for STARTED legs and silently DROPPED every other non-executable leg (stale
quote, unpriced, unknown kickoff, no recorded sportsbook), rendering the rest when >= 3 remained. A user who
submitted a four-leg ticket could receive a three-leg image.

Contract under test (synthetic pools, frozen server clock, renderer patched, nothing persisted):
  POST /tools/daily-card.png  (the ONE image/export boundary for user-selected tickets: the shared ticket
       editor -- Today's Cards, King's Tickets, Green Light's proposed ticket -- and the Menu slip)
    * four legs with one stale / started / unknown-kickoff / unpriced / unrecorded-sportsbook / no-longer-
      on-the-board leg -> 409, JSON (never image/png), every submitted leg listed with position, public
      identity (sport / label / game), executable flag, reason codes from the shared vocabulary, note
    * malformed input (bad JSON, legs not a list, wrong types, wrong count, duplicate leg) -> 422
    * three valid + one invalid never becomes a three-leg image (renderer never called, no bytes)
    * no image / file created on rejection (temp DATA_DIR + the repo cache dir are unchanged)
    * the corrected all-valid resubmission -> 200 image/png with exactly the submitted legs, in order,
      priced from the server quote (each leg carries the quote terms the user confirmed; a forged price is
      rejected 409 quote_changed -- qc_ticket_quote_change.py owns that contract)
    * logs + stdout/stderr carry no raw payload / canary (sanitized counts + reason codes only)
  GET /tools/daily-card.png -- takes no client legs: forged leg/selection params never reach the image
  SGP Workbench export / handoff (/tools/sgp-workbench) -- the same atomic rule: any non-executable leg
    (kickoff, price, sportsbook, freshness, unresolved id) rejects the export with per-leg reasons; no
    full-fidelity copy renders; nothing is dropped; the all-valid ticket exports exactly its legs
  M  mutations: restoring the silent drop, or disabling the SGP quote gate, makes the checks FAIL
Exit 0 = all pass, 1 = any failure.
"""
from __future__ import annotations

from services.qc_no_network import install as _block_network

_block_network()  # before importing app: nothing below may reach the network

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
os.environ.setdefault('SECRET_KEY', 'qc-ticket-submission-atomic')

import app  # noqa: E402
from services.qc_auth import isolated_owner_client  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 11, 8, 17, 0, 0, tzinfo=UTC)
LATE = NOW + timedelta(hours=4)
CANARY = 'QC-CANARY-7f3a9d-RAW-PAYLOAD'
CSRF = 'qc-atomic-csrf-token'
results: list[tuple[bool, str]] = []


def ok(cond, msg):
    results.append((bool(cond), msg))
    return bool(cond)


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


# ------------------------------------------------------------------ synthetic card pool
def _pool_leg(i, kickoff=LATE, upd_h=1.0, book='SynBook', priced=True):
    at = iso(NOW - timedelta(hours=upd_h))
    leg = {'sport': 'NFL', 'kind': 'prop', 'tier': 'floor', 'player': f'Atomic Receiver {i}',
           'label': f'Atomic Receiver {i} Receiving Yards 40.5+', 'game': f'AT{i} @ HM{i}', 'line': 40.5,
           'reason': f'clears 7{i}% of the time (12 g)', 'hit': 70 + i, 'sample': 12, 'score': 100 - i,
           'event_id': f'evt-atomic-{i}', 'kickoff_utc': iso(kickoff) if kickoff else None}
    if priced:
        q = {'book': book, 'price': -150 - i, 'line': 40.5, 'event': f'AT{i}@HM{i}',
             'market': 'player_reception_yds', 'selection': f'Atomic Receiver {i} Over 40.5', 'updated_utc': at}
        leg.update(price=-150 - i, quote=q, book=book, quote_at=at, quote_label='qc')
    else:
        leg.update(price=None, price_status='UNAVAILABLE', executable=False, line_source='Unrecorded source')
    return leg


VALID = [_pool_leg(i) for i in (1, 2, 3, 4)]
BAD = {
    'stale': (_pool_leg(5, upd_h=7.0), 'STALE_QUOTE'),
    'started': (_pool_leg(6, kickoff=NOW - timedelta(seconds=1)), 'STARTED'),
    'unknown_kickoff': (_pool_leg(7, kickoff=None), 'MISSING_KICKOFF'),
    'unpriced': (_pool_leg(8, priced=False), 'NO_QUOTE'),
    'unrecorded_source': (_pool_leg(9, book='Unrecorded source'), 'NOT_A_SPORTSBOOK'),
}
POOL = VALID + [lg for lg, _c in BAD.values()]


def wire(leg, **extra):
    """What the browser sends: identity + display fields (+ a canary in non-identity fields) + the quote
    terms the user confirmed (book / event / market / selection / line / price, exactly as rendered)."""
    w = {'sport': leg['sport'], 'label': leg['label'], 'game': leg['game'], 'tier': leg['tier'],
         'reason': f'{CANARY} reason', 'note': CANARY}
    terms = app.ticket_quote_terms(leg)
    if terms:
        w.update(terms)
    else:
        w['price'] = -110  # synthetic-fixture
    w.update(extra)
    return w


# ------------------------------------------------------------------ fixture
class Fixture:
    def __init__(self, td):
        self.td = Path(td)
        self.renders = []

    def __enter__(self):
        from marketing.generators import weekly_cards as _wc
        from PIL import Image as _Image
        self._wc = _wc
        names = ('DATA_DIR', '_now_utc', '_card_pools', '_game_date_map', 'record_active_user')
        self.saved = {n: getattr(app, n) for n in names}
        self.saved_render = _wc.render_daily_card
        app.DATA_DIR = self.td
        app._now_utc = lambda: NOW
        app._card_pools = lambda legs='all', mlb_limit=12, cfb_limit=10, nfl_line_limit=8, now=None: (
            copy.deepcopy(POOL), [])
        app._game_date_map = lambda: {}
        app.record_active_user = lambda *a, **k: None
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
    """Capture app.logger + root logging + stdout/stderr for the duration."""
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


def post(client, body=None, raw=None):
    kw = {'headers': {'X-CSRFToken': CSRF}}
    if raw is not None:
        kw.update(data=raw, content_type='application/json')
    else:
        kw.update(json=body)
    return client.post('/tools/daily-card.png', **kw)


# ------------------------------------------------------------------ image POST / GET checks
def check_image(rec, client, fx):
    repo_cache = Path(fx.saved['DATA_DIR']) / 'cache'
    before = snapshot(fx.td, repo_cache)
    with captured_output() as logs:
        # 1. one invalid leg among four -> the WHOLE ticket is rejected (409), per kind and per position
        for kind, (bad, code) in BAD.items():
            for pos in (4, 2):
                legs = [wire(l) for l in VALID[:3]]
                legs.insert(pos - 1, wire(bad))
                body = {'legs': legs}
                n0 = len(fx.renders)
                r = post(client, body)
                j = r.get_json(silent=True) or {}
                entries = j.get('legs') or []
                blocked = [e for e in entries if not e.get('executable')]
                rec(r.status_code == 409 and r.mimetype == 'application/json' and len(fx.renders) == n0
                    and not r.data.startswith(b'\x89PNG'),
                    f'IMG {kind}@{pos}: four legs with one {kind} -> 409 JSON, renderer not called, no PNG bytes '
                    f'(HTTP {r.status_code}, {r.mimetype})')
                rec(len(entries) == 4 and [e.get('position') for e in entries] == [1, 2, 3, 4]
                    and [e.get('position') for e in blocked] == [pos] and code in blocked[0].get('reasons', [])
                    and blocked[0].get('label') == bad['label'] and blocked[0].get('note'),
                    f'IMG {kind}@{pos}: every submitted leg is listed; only position {pos} blocked with {code} '
                    f'({[(e.get("position"), e.get("reasons")) for e in blocked]})')
                rec(all(set(e) == {'position', 'sport', 'label', 'game', 'executable', 'reasons', 'note'}
                        for e in entries) and CANARY not in r.data.decode('utf-8', 'replace')
                    and json.dumps(body) not in r.data.decode('utf-8', 'replace'),
                    f'IMG {kind}@{pos}: response carries identity + reasons only (no price/quote, no raw payload echo)')
        # no-longer-on-the-board (well-formed id, unknown to the server)
        ghost = dict(wire(VALID[0]), label='Ghost Player Receiving Yards 99.5+', game='GH @ ST')
        r = post(client, {'legs': [wire(l) for l in VALID[:3]] + [ghost]})
        j = r.get_json(silent=True) or {}
        bl = [e for e in j.get('legs') or [] if not e.get('executable')]
        rec(r.status_code == 409 and [e.get('reasons') for e in bl] == [['NOT_ON_BOARD']],
            f'IMG ghost: a leg no longer on the board -> 409 NOT_ON_BOARD, never dropped (HTTP {r.status_code})')
        rec(j.get('removed_started') == [] and 'nothing was removed' in (j.get('message') or ''),
            'IMG ghost: message says nothing was removed for the user')

        # 2. malformed -> 422
        three = [wire(l) for l in VALID[:3]]
        cases = [
            ('bad JSON', None, '{"legs": [not json'),
            ('empty body', None, ''),
            ('legs not a list', {'legs': 'AT1 @ HM1'}, None),
            ('payload not an object', [wire(VALID[0])], None),
            ('wrong type (label int)', {'legs': three + [dict(wire(VALID[3]), label=12345)]}, None),
            ('missing game', {'legs': three + [{k: v for k, v in wire(VALID[3]).items() if k != 'game'}]}, None),
            ('leg not an object', {'legs': three + ['AT4 @ HM4']}, None),
            ('oversized id', {'legs': three + [dict(wire(VALID[3]), label='X' * 500)]}, None),
            ('wrong count (1)', {'legs': three[:1]}, None),
            ('wrong count (9)', {'legs': [wire(_pool_leg(i)) for i in range(10, 19)]}, None),
            ('duplicate leg', {'legs': three + [wire(VALID[0])]}, None),
        ]
        for name, body, raw in cases:
            n0 = len(fx.renders)
            r = post(client, body, raw)
            j = r.get_json(silent=True) or {}
            rec(r.status_code == 422 and len(fx.renders) == n0 and r.mimetype == 'application/json'
                and j.get('error') in ('malformed_ticket', 'wrong_leg_count'),
                f'IMG malformed ({name}) -> 422 {j.get("error")}, nothing rendered (HTTP {r.status_code})')
        r = post(client, {'legs': three + [wire(VALID[0])]})
        j = r.get_json(silent=True) or {}
        rec([e.get('reasons') for e in j.get('legs') or [] if not e.get('executable')] == [['DUPLICATE_LEG']],
            'IMG malformed: the duplicate is named per leg (DUPLICATE_LEG at position 4)')
        rec('ticket_submission_rejected' in logs(), 'LOG: rejections are logged (sanitized metadata line present)')
        log_text = logs()
    after = snapshot(fx.td, repo_cache)
    rec(after == before, f'FILE: no file created/changed under the temp DATA_DIR or the repo cache dir on rejection '
                         f'({len(set(after) ^ set(before))} changed paths)')
    rec(CANARY not in log_text and '"legs"' not in log_text and 'Atomic Receiver' not in log_text,
        'LOG: logs/stdout/stderr carry no raw payload, canary or leg label (codes + counts only)')
    rec(bool(re.search(r'reasons=[A-Z_:0-9,]+', log_text)),
        'LOG: the rejection line carries reason codes only')

    # 3. a forged +900 is REJECTED whole (409 quote_changed), never repriced; then the corrected all-valid
    #    resubmission -> 200 image/png with EXACTLY the submitted legs
    n0 = len(fx.renders)
    r = post(client, {'legs': [wire(l, price=900) for l in VALID]})
    j = r.get_json(silent=True) or {}
    rec(r.status_code == 409 and j.get('error') == 'quote_changed' and len(fx.renders) == n0
        and all('PRICE_CHANGED' in e.get('reasons', []) for e in j.get('legs') or []),
        f'IMG forged price: a forged +900 on every leg -> 409 quote_changed, nothing rendered (HTTP {r.status_code})')
    n0 = len(fx.renders)
    sub = [wire(l) for l in VALID]
    r = post(client, {'legs': sub})
    card = fx.renders[-1] if len(fx.renders) == n0 + 1 else {}
    got = [l.get('label') for l in card.get('legs', [])]
    rec(r.status_code == 200 and r.mimetype == 'image/png' and r.data.startswith(b'\x89PNG')
        and got == [l['label'] for l in VALID] and card.get('n') == 4,
        f'IMG corrected: all-valid 4-leg resubmission -> 200 image/png with exactly the 4 submitted legs in order '
        f'(HTTP {r.status_code}, {got})')
    rec([l.get('price') for l in card.get('legs', [])] == [l['price'] for l in VALID],
        'IMG corrected: prices are the server quote (the confirmed terms only confirm, never price)')
    r2 = post(client, {'legs': [wire(l) for l in VALID[:2]]})
    rec(r2.status_code == 200 and r2.mimetype == 'image/png' and len(fx.renders[-1].get('legs', [])) == 2,
        f'IMG corrected: a 2-leg editor ticket (editor MIN) renders exactly 2 legs (HTTP {r2.status_code})')

    # 4. image GET takes no client legs: forged selection params never reach the image
    forged = json.dumps([wire(b) for b, _c in BAD.values()])
    n0 = len(fx.renders)
    r = client.get('/tools/daily-card.png?' + urlencode([('n', 3), ('legs', forged), ('sel', BAD['stale'][0]['label']),
                                                          ('label', BAD['started'][0]['label'])]))
    card = fx.renders[-1] if len(fx.renders) == n0 + 1 else {}
    got = [l.get('label') for l in card.get('legs', [])]
    valid_labels = {l['label'] for l in VALID}
    rec(r.status_code == 200 and len(got) == 3 and set(got) <= valid_labels,
        f'IMG GET: forged leg/selection params are ignored; the server-built card holds only executable legs ({got})')


# ------------------------------------------------------------------ SGP Workbench export / handoff
SGP_AWAY, SGP_HOME = 'Atomic Away Hawks', 'Atomic Home Bears'
SGP_GAME = f'{SGP_AWAY}@{SGP_HOME}'


def _sgp_leg(i, kickoff=LATE, upd_h=0.5, book='SynBook', price=-110):  # synthetic-fixture
    ts = iso(NOW - timedelta(hours=upd_h))
    lg = {'kind': 'player', 'category': 'Receiving', 'player': f'Sgp Player {i}', 'team': 'BEARS',
          'position': None, 'stat': 'Rec Yds', 'direction': 'OVER', 'line': 40.5 + i, 'price': price,
          'book': book, 'timestamp': ts, 'tz': 'provider time; tz unverified', 'quote_scope': 'individual',
          'lineage': 'synthetic', 'lean': None, 'inj': None, 'label': f'Sgp Player {i} OVER Rec Yds {40.5 + i:g}',
          'event_id': 'evt-sgp', 'kickoff_utc': iso(kickoff) if kickoff else None}
    lg['id'] = '|'.join([book, 'player', lg['player'], 'Rec Yds', 'OVER', str(lg['line'])])
    return lg


SGP_VALID = [_sgp_leg(i) for i in (1, 2, 3, 4)]
SGP_BAD = {
    'stale': (_sgp_leg(5, upd_h=7.0), 'STALE_QUOTE'),
    'started': (_sgp_leg(6, kickoff=NOW - timedelta(seconds=1)), 'STARTED'),
    'unknown_kickoff': (_sgp_leg(7, kickoff=None), 'MISSING_KICKOFF'),
    'unpriced': (_sgp_leg(8, price=None), 'MISSING_PRICE'),
    'unrecorded_source': (_sgp_leg(9, book='book'), 'MISSING_BOOK'),
}


def _sgp_menu(away, home):
    return [{'cat': 'Receiving', 'legs': copy.deepcopy(SGP_VALID + [b for b, _c in SGP_BAD.values()])}]


class SgpFixture:
    def __enter__(self):
        names = ('_nfl_sgp_leg_menu', 'build_nfl_matchup_context', '_nfl_line_move', '_now_utc', 'record_active_user')
        self.saved = {n: getattr(app, n) for n in names}
        app._nfl_sgp_leg_menu = _sgp_menu
        app.build_nfl_matchup_context = lambda: {'mu_week': [{'away': SGP_AWAY, 'home': SGP_HOME}]}
        app._nfl_line_move = lambda a, h: None
        app._now_utc = lambda: NOW
        app.record_active_user = lambda *a, **k: None
        return self

    def __exit__(self, *exc):
        for n, v in self.saved.items():
            setattr(app, n, v)


def sgp_conf(ids):
    """{id: price} the user confirmed when adding each leg (quote-change atomicity)."""
    every = SGP_VALID + [b for b, _c in SGP_BAD.values()]
    return {lg['id']: lg['price'] for lg in every if lg['id'] in ids and lg['price'] is not None}


def sgp_page(client, ids):
    r = client.get('/tools/sgp-workbench?' + urlencode([('game', SGP_GAME), ('thesis', 'custom')]
                                                         + [('sel', i) for i in ids]
                                                         + [('cf', f'{i}~{p:+d}') for i, p in sgp_conf(ids).items()]))
    return r.status_code, r.get_data(as_text=True)


def check_sgp(rec, client):
    import html as _h
    with SgpFixture():
        v3 = [lg['id'] for lg in SGP_VALID[:3]]
        for kind, (bad, code) in SGP_BAD.items():
            ids = v3 + [bad['id']]
            ctx = app.build_sgp_workbench_context(game=SGP_GAME, selected_ids=ids, thesis='custom',
                                                  confirmed=sgp_conf(ids))
            h = ctx.get('handoff') or {}
            bl = h.get('legs') or []
            rec(h.get('status') == 'rejected' and [b.get('id') for b in bl] == [bad['id']]
                and code in bl[0].get('reasons', []) and [lg['id'] for lg in ctx['selected']] == ids,
                f'SGP {kind}: four legs with one {kind} -> export REJECTED, that leg named with {code}, '
                f'all 4 legs kept on the ticket ({h.get("status")}, {[b.get("reasons") for b in bl]})')
            code_, page = sgp_page(client, ids)
            un = _h.unescape(page)
            rec(code_ == 200 and 'data-sgp-rejected="1"' in page and '| scope:' not in page
                and f'data-sgp-blocked="{bad["id"]}"' in un and code in un,
                f'SGP {kind}: rendered page shows the per-leg reason and NO full-fidelity export copy (HTTP {code_})')
        ids = v3 + ['not-a-real|leg|id']
        ctx = app.build_sgp_workbench_context(game=SGP_GAME, selected_ids=ids, thesis='custom',
                                              confirmed=sgp_conf(ids))
        h = ctx.get('handoff') or {}
        rec(h.get('status') == 'rejected' and [b.get('reasons') for b in h.get('legs') or []] == [['NOT_ON_BOARD']]
            and [u['id'] for u in ctx['unresolved_selected']] == ['not-a-real|leg|id'],
            'SGP malformed id: an unknown leg id is listed NOT_ON_BOARD and blocks export (never dropped)')
        ids = [lg['id'] for lg in SGP_VALID]
        ctx = app.build_sgp_workbench_context(game=SGP_GAME, selected_ids=ids, thesis='custom',
                                              confirmed=sgp_conf(ids))
        rec((ctx.get('handoff') or {}).get('status') == 'held' and ctx['ticket_gate']['executable'],
            'SGP corrected: the all-valid 4-leg ticket is exportable (handoff held with full-fidelity copy)')
        code_, page = sgp_page(client, ids)
        copy_lines = re.findall(r'^- (.+?) \| ', _h.unescape(page), re.M)
        rec(code_ == 200 and copy_lines == [lg['label'] for lg in SGP_VALID] and 'data-sgp-rejected' not in page,
            f'SGP corrected: the export copy lists exactly the 4 submitted legs ({copy_lines})')


# ------------------------------------------------------------------ mutations
def _old_silent_drop_judge(payload, now, pool_legs):
    """The pre-fix behaviour: reject only STARTED, silently drop every other non-executable leg."""
    raw = (payload or {}).get('legs') or [] if isinstance(payload, dict) else []
    live, started = {}, set()
    for l in pool_legs:
        k = (l.get('sport'), l.get('label'), l.get('game'))
        why = app._leg_quote_failures(l, now)
        if not why:
            live[k] = l
        elif 'STARTED' in why:
            started.add(k)
    raw = [l for l in raw[:8] if isinstance(l, dict)]
    if any((l.get('sport'), l.get('label'), l.get('game')) in started for l in raw):
        return 409, None, {'error': 'started', 'legs': []}
    legs = []
    for l in raw:
        srv = live.get((l.get('sport'), l.get('label'), l.get('game')))
        if srv is not None:
            legs.append({'label': srv['label'], 'price': int(srv['price']), 'quote': srv['quote'],
                         'line': srv.get('line'), 'tier': 'floor', 'sport': srv['sport'], 'game': srv['game'],
                         'reason': '', 'kickoff_utc': srv.get('kickoff_utc')})
    if len(legs) < 3:
        return 422, None, {'error': 'x', 'legs': []}
    return 200, legs, None


def run_all(rec):
    with tempfile.TemporaryDirectory() as td, Fixture(td) as fx, isolated_owner_client('qc-atomic-owner') as client:
        with client.session_transaction() as sess:
            sess['_csrf_token'] = CSRF
        for name, fn in (('IMG', lambda: check_image(rec, client, fx)), ('SGP', lambda: check_sgp(rec, client))):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                rec(False, f'{name} crashed: {exc!r}')


def main() -> int:
    run_all(ok)

    # M1: restore the silent drop -> the atomic checks must FAIL
    real = app._judge_submitted_ticket
    m1 = []
    app._judge_submitted_ticket = _old_silent_drop_judge
    try:
        run_all(lambda c, m: m1.append((bool(c), m)))
    finally:
        app._judge_submitted_ticket = real
    must = [m for c, m in m1 if m.startswith('IMG ') and ('-> 409' in m)
            and any(k in m for k in ('stale', 'unknown_kickoff', 'unpriced', 'unrecorded_source', 'ghost'))]
    failed = {m for c, m in m1 if not c}
    missed = [m for m in must if m not in failed]
    ok(len(must) >= 9 and not missed, f'M1: silent drop restored => {len(must) - len(missed)}/{len(must)} non-started '
                            f'rejection checks FAIL' + (f' (still passing: {missed[:3]})' if missed else ''))

    # M2: SGP quote gate disabled -> the stale / unpriced / unrecorded-book SGP checks must FAIL
    real_q = app._sgp_leg_quote_failures
    m2 = []
    app._sgp_leg_quote_failures = lambda lg, now: []
    try:
        run_all(lambda c, m: m2.append((bool(c), m)))
    finally:
        app._sgp_leg_quote_failures = real_q
    must2 = [m for c, m in m2 if m.startswith('SGP ') and any(f'SGP {k}:' in m for k in ('stale', 'unpriced',
                                                                                         'unrecorded_source'))]
    failed2 = {m for c, m in m2 if not c}
    missed2 = [m for m in must2 if m not in failed2]
    ok(len(must2) == 6 and not missed2, f'M2: SGP quote gate disabled => {len(must2) - len(missed2)}/{len(must2)} '
                                        f'stale/unpriced/unrecorded SGP checks FAIL')

    print('=' * 60)
    print('BANKROLL KINGS ATOMIC TICKET SUBMISSION QC (D4 / R2)')
    print('=' * 60)
    for passed, msg in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")
    n_fail = sum(1 for p, _ in results if not p)
    print(f'\n{len(results) - n_fail}/{len(results)} passed')
    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
