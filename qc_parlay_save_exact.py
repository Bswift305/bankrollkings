"""QC: /parlay/save stores EXACTLY the accepted selection -- never a truncated or silently filtered record (D4).

Owner decision 2. The legacy (NBA-centric) Parlay Builder review record used to keep `picks[:20]` (silent
truncation) and silently drop any pick missing player / stat / direction. Contract under test (isolated
owner principal from services.qc_auth, save_parlay_ticket captured in memory, temp DATA_DIR, no network,
nothing written to any user store):
  * frozen range 1..20 picks (PARLAY_REVIEW_MIN/MAX_PICKS): 1 and 20 accepted; 0 -> 422; 21 / 25 -> 422
    TOO_MANY_PICKS, nothing saved, NEVER a 20-pick record
  * an accepted save stores exactly the submitted set: same picks, same order, every field of the record
    schema equal to what was submitted
  * a malformed / invalid pick at index k -> 422 INVALID_PICKS listing {index: k, reasons: [...]} (0-based,
    codes only, no payload echo), nothing saved, nothing dropped -- for every k position and kind
  * no payout from an invalid record: the 422 carries no payout / price math and the ticket analyzer is
    never reached
  M  mutations: re-enable the silent truncation, or the silent invalid-pick drop -> the checks FAIL
Exit 0 = all pass, 1 = any failure.
"""
from __future__ import annotations

from services.qc_no_network import install as _block_network

_block_network()  # before importing app: nothing below may reach the network

import copy  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SECRET_KEY', 'qc-parlay-save-exact')

import app  # noqa: E402
from services.qc_auth import isolated_owner_client  # noqa: E402

CSRF = 'qc-parlay-save-csrf'
CANARY = 'QC-CANARY-PARLAY-5b2d'
REJ = '[REJ]'
results: list[tuple[bool, str]] = []


def ok(cond, msg):
    results.append((bool(cond), msg))
    return bool(cond)


def pick(i, **kw):
    """One review pick already in the stored record schema (canonical values), so stored == submitted."""
    p = {'sport': 'NBA', 'player': f'Exact Player {i}', 'team': 'BOS', 'stat': 'PTS', 'line': 20.5 + i,
         'direction': 'OVER' if i % 2 else 'UNDER', 'confidence': 70.0 + i, 'raw_confidence': 69.0 + i,
         'matchup': f'BOS @ NY{i}', 'tier': 'Tier 1', 'method_labels': ['Floor', 'Matchup'],
         'market_calibration_note': 'qc note', 'market_calibration_tags': ['tag-a'], 'book_count': 3,
         'book': 'SynBook', 'market_price': -115, 'model_prob': 61.5, 'ev_pct': 1.25,
         'historical_reliability': 'High'}
    p.update(kw)
    return p


SCHEMA = list(pick(0).keys())


class Fixture:
    def __init__(self, td):
        self.td = Path(td)
        self.saved_tickets = []
        self.analyzed = 0

    def __enter__(self):
        names = ('DATA_DIR', 'save_parlay_ticket', 'analyze_saved_parlay_ticket', 'record_active_user')
        self.saved = {n: getattr(app, n) for n in names}
        app.DATA_DIR = self.td
        fx = self
        app.save_parlay_ticket = lambda ticket: fx.saved_tickets.append(copy.deepcopy(ticket))

        def _analyze(*a, **k):
            fx.analyzed += 1
            return self.saved['analyze_saved_parlay_ticket'](*a, **k)
        app.analyze_saved_parlay_ticket = _analyze
        app.record_active_user = lambda *a, **k: None
        return self

    def __exit__(self, *exc):
        for n, v in self.saved.items():
            setattr(app, n, v)


def save(client, picks, **extra):
    body = {'label': 'qc', 'mode': 'QC Parlay Builder', 'bankroll': 100, 'risk_pct': 2, 'slate_budget': 2,
            'picks': picks}
    body.update(extra)
    return client.post('/parlay/save', json=body, headers={'X-CSRFToken': CSRF})


def stored_picks(fx):
    return json.loads(fx.saved_tickets[-1]['PicksJson']) if fx.saved_tickets else None


def run_all(rec):
    with tempfile.TemporaryDirectory() as td, Fixture(td) as fx, isolated_owner_client('qc-parlay-owner') as client:
        with client.session_transaction() as sess:
            sess['_csrf_token'] = CSRF
        try:
            checks(rec, client, fx)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            rec(False, f'crashed: {exc!r}')


def checks(rec, client, fx):
    rec(app.PARLAY_REVIEW_MIN_PICKS == 1 and app.PARLAY_REVIEW_MAX_PICKS == 20,
        'RANGE: the review-record range is frozen at 1..20 picks')

    # accepted saves store exactly the submitted set
    for n in (1, 3, 20):
        sub = [pick(i) for i in range(n)]
        n0 = len(fx.saved_tickets)
        r = save(client, sub)
        j = r.get_json(silent=True) or {}
        got = stored_picks(fx) if len(fx.saved_tickets) == n0 + 1 else None
        rec(r.status_code == 200 and j.get('ok') and got is not None and len(got) == n
            and fx.saved_tickets[-1]['LegCount'] == n,
            f'EXACT {n}: {n} pick(s) -> 200, one record with LegCount {n} (HTTP {r.status_code})')
        rec(got == sub and all(list(g.keys()) == SCHEMA for g in (got or [])),
            f'EXACT {n}: the stored PicksJson equals the submitted picks (order + every field)')
        rec(fx.saved_tickets and fx.saved_tickets[-1].get('Payout') == 0,
            f'EXACT {n}: the review record carries no calculated payout (Payout 0)')
    # reversed order is stored reversed (order is the user's, never re-sorted)
    sub = [pick(i) for i in range(5)][::-1]
    r = save(client, sub)
    rec(r.status_code == 200 and stored_picks(fx) == sub, 'EXACT order: a reversed selection is stored in the submitted order')

    def rejected(tag, r, n0, code, invalid=None):
        j = r.get_json(silent=True) or {}
        body = r.get_data(as_text=True)
        rec(r.status_code == 422 and j.get('ok') is False and j.get('code') == code and j.get('saved') is False
            and len(fx.saved_tickets) == n0,
            f'{tag}: -> 422 {code}, nothing saved {REJ} (HTTP {r.status_code}, saved {len(fx.saved_tickets) - n0})')
        if invalid is not None:
            rec(j.get('invalid') == invalid, f'{tag}: indexed reasons {invalid} {REJ} (got {j.get("invalid")})')
        rec(CANARY not in body and 'Exact Player' not in body
            and not any(k in j for k in ('payout', 'american', 'decimal', 'price', 'ticket_id')),
            f'{tag}: no payload echo and no payout / price math in the rejection')
        return j

    # over the cap -> 422, never truncated to 20
    for n in (21, 25):
        n0 = len(fx.saved_tickets)
        j = rejected(f'CAP {n}', save(client, [pick(i, matchup=CANARY) for i in range(n)]), n0, 'TOO_MANY_PICKS')
        rec(j.get('n_submitted') == n and j.get('max_picks') == 20 and 'nothing was trimmed' in j.get('error', ''),
            f'CAP {n}: the message states the 20 maximum and that nothing was trimmed')
    n0 = len(fx.saved_tickets)
    rejected('CAP 0', save(client, []), n0, 'TOO_FEW_PICKS')
    n0 = len(fx.saved_tickets)
    rejected('MALFORMED picks not a list', save(client, {'0': pick(0)}), n0, 'MALFORMED_REQUEST')

    # an invalid pick at index k -> 422 with index k, nothing saved, nothing dropped
    bad_kinds = {
        'missing player': ({'player': ''}, ['MISSING_PLAYER']),
        'missing stat': ({'stat': None}, ['MISSING_STAT']),
        'missing direction': ({'direction': ' '}, ['MISSING_DIRECTION']),
        'bad direction': ({'direction': 'SIDEWAYS'}, ['INVALID_DIRECTION']),
        'missing line': ({'line': None}, ['MISSING_LINE']),
        'bad line': ({'line': 'twenty'}, ['INVALID_LINE']),
        'bad confidence': ({'confidence': 'high'}, ['INVALID_NUMBER_FIELD']),
        'text field object': ({'team': {'x': CANARY}}, ['INVALID_TEXT_FIELD']),
        'tags not list': ({'market_calibration_tags': CANARY}, ['INVALID_TAGS']),
    }
    for name, (patch, codes) in bad_kinds.items():
        for k in (0, 2, 4):
            sub = [pick(i) for i in range(5)]
            sub[k] = dict(sub[k], **patch)
            n0 = len(fx.saved_tickets)
            rejected(f'INVALID {name}@{k}', save(client, sub), n0, 'INVALID_PICKS', [{'index': k, 'reasons': codes}])
    sub = [pick(i) for i in range(4)] + [CANARY]
    n0 = len(fx.saved_tickets)
    rejected('INVALID not an object@4', save(client, sub), n0, 'INVALID_PICKS', [{'index': 4, 'reasons': ['PICK_NOT_OBJECT']}])
    sub = [pick(i) for i in range(4)] + [pick(1)]
    n0 = len(fx.saved_tickets)
    rejected('INVALID duplicate@4', save(client, sub), n0, 'INVALID_PICKS', [{'index': 4, 'reasons': ['DUPLICATE_PICK']}])
    sub = [pick(i) for i in range(6)]
    sub[1] = dict(sub[1], player='')
    sub[5] = dict(sub[5], line='x')
    n0 = len(fx.saved_tickets)
    rejected('INVALID two picks', save(client, sub), n0, 'INVALID_PICKS',
             [{'index': 1, 'reasons': ['MISSING_PLAYER']}, {'index': 5, 'reasons': ['INVALID_LINE']}])
    n0 = len(fx.saved_tickets)
    rejected('FIELD bankroll', save(client, [pick(0)], bankroll='lots'), n0, 'INVALID_FIELD')
    rec(fx.analyzed == 0, 'PAYOUT: no ticket analysis / payout path is reached by any save or rejection')

    # unauthenticated -> 401, nothing saved (unchanged)
    anon = app.app.test_client()
    with anon.session_transaction() as sess:
        sess['_csrf_token'] = CSRF
    n0 = len(fx.saved_tickets)
    r = anon.post('/parlay/save', json={'picks': [pick(0)]}, headers={'X-CSRFToken': CSRF})
    rec(r.status_code == 401 and len(fx.saved_tickets) == n0, f'AUTH: anonymous save -> 401, nothing saved (HTTP {r.status_code})')


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
    ok(len(must) >= 2 and not missed, f'{label} => {len(must) - len(missed)}/{len(must)} rejection checks FAIL'
       + (f' (still passing: {missed[:3]})' if missed else ''))


def main() -> int:
    run_all(ok)
    real_validate = app._validate_parlay_review_picks

    def _truncating(picks):                 # the pre-fix behaviour: keep picks[:20]
        return real_validate(picks[:20])
    mutation('M1: silent 20-pick truncation re-enabled', {'PARLAY_REVIEW_MAX_PICKS': 10 ** 6,
                                                          '_validate_parlay_review_picks': _truncating}, ('CAP 2',))

    def _dropping(picks):                   # the pre-fix behaviour: drop invalid picks, save the rest
        kept = []
        for p in picks:
            s, bad = real_validate([p])
            if not bad:
                kept += s
        return kept, []
    mutation('M2: silent invalid-pick drop re-enabled', {'_validate_parlay_review_picks': _dropping}, ('INVALID ',))

    print('=' * 60)
    print('BANKROLL KINGS PARLAY REVIEW SAVE EXACTNESS QC (D4)')
    print('=' * 60)
    for passed, msg in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")
    n_fail = sum(1 for p, _ in results if not p)
    print(f'\n{len(results) - n_fail}/{len(results)} passed')
    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
