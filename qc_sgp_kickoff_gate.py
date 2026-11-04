"""QC: the NFL SGP Workbench obeys the D4 kickoff gate (owner decisions A + B + C).

The SGP Workbench (/tools/sgp-workbench) is a ticket-construction surface even though the user assembles
it, so it takes the SAME canonical server-side kickoff rule as every other proposed-ticket surface:
`app._kickoff_gate_failure` (strict kickoff > now; unknown / naive / unparseable => MISSING_KICKOFF),
reached through `app._leg_kickoff_failure`, against ONE injectable server clock (`app._now_utc`, frozen
here). The browser's clock / any request value is never trusted.

The REAL builders run (`_nfl_sgp_leg_menu` reading a temp NFL_Props / NFL_Odds / NFL_FirstHalf, then
`build_sgp_workbench_context` and the `/tools/sgp-workbench` route + template) on synthetic data.
  SEL  selection: started legs are never offered by the picker (kickoff = now-1s and kickoff == now are
       not addable; kickoff = now+1s is); a started market stays browsable, labelled live/historical,
       with no price and no Add control
  HELD stale-held ticket: a selected leg that crosses kickoff while held stays on the ticket (never
       deleted), is marked "Started — remove or rebuild", loses its price, and makes the ticket
       non-executable; a held leg whose rows vanish from the feed is listed (not dropped) and blocks
  EXP  final submission / export / handoff: a ticket carrying a started, unknown-kickoff or vanished leg
       is REJECTED server-side (no full-fidelity copy, no King's Tickets build); request params that
       look like a client clock are ignored; a forged "ok" annotation on a leg is re-judged
  UNK  unknown kickoff (missing column, blank, naive) fails closed: "Kickoff unavailable — context only"
  OFS  offset-equivalent kickoffs ('Z' vs '-05:00') canonicalize to one instant and one decision
  CTX  game-line / spread / team-total legs (no governed kickoff in their feeds) render exactly
       "Kickoff unavailable — context only", carry no price, cannot be added, and block an export
  ONE  no second predicate: the SGP code reaches the kickoff rule only via _leg_kickoff_failure
  M    mutation: kickoff gate disabled => the SEL / HELD / EXP / UNK / CTX checks FAIL; picker annotation
       bypassed => the server-side export gate still rejects (defence in depth)
Python networking blocked; writes only inside a temp dir. Exit 0 = all pass, 1 = any failure.
"""
from __future__ import annotations

from services.qc_no_network import install as _block_network

_block_network()  # before importing app: nothing below may reach the network

import inspect  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SECRET_KEY', 'qc-sgp-kickoff-gate')

import app  # noqa: E402

UTC = timezone.utc
KICK = datetime(2026, 11, 8, 18, 0, 0, tzinfo=UTC)      # the game's kickoff (13:00 ET)
PRE = KICK - timedelta(hours=1)
S1 = timedelta(seconds=1)
CLOCK = {'now': PRE}
AWAY, HOME = 'Syn Away Hawks', 'Syn Home Bears'
GAME = f'{AWAY}@{HOME}'
KNA = 'Kickoff unavailable — context only'
results: list[tuple[bool, str]] = []


def ok(cond, msg):
    results.append((bool(cond), msg))
    return bool(cond)


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


# ------------------------------------------------------------------ synthetic feeds
QB, WR, RB, TE = 'Syn QB', 'Syn WR', 'Syn RB', 'Syn TE'


def props_frame(drop_players=(), commence_col=True):
    """NFL_Props rows for ONE game. QB has two books spelling the SAME instant as 'Z' and '-05:00'; RB has a
    blank commence time; TE a naive (zone-less) one -- both must fail closed."""
    kz = iso(KICK)
    k5 = (KICK - timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M:%S-05:00')
    spec = [(QB, 'Pass Yds', 250.5, 'SynBook', kz), (QB, 'Pass Yds', 250.5, 'OtherBook', k5),
            (WR, 'Rec Yds', 60.5, 'SynBook', kz), (RB, 'Rush Yds', 50.5, 'SynBook', ''),
            (TE, 'Rec Yds', 35.5, 'SynBook', '2026-11-08 18:00:00')]
    rows = []
    for pl, st, line, book, kick in spec:
        if pl in drop_players:
            continue
        r = {'Player': pl, 'Team': 'BEARS', 'Stat': st, 'MarketKey': 'player_x', 'Line': line, 'Game': GAME,
             'Book': book, 'LastUpdated': '2026-11-08 11:30', 'EventId': 'evt-syn-1',
             'SourceUpdatedAtUTC': '2026-11-08T16:30:00Z', 'OverOdds': -110, 'UnderOdds': -110}  # synthetic-fixture
        if commence_col:
            r['EventCommenceAtUTC'] = kick
        rows.append(r)
    # a second, unrelated row so the frame is never a single row (the loader drops 1-row frames)
    rows.append({**rows[-1], 'Game': 'Other Team@Elsewhere Team', 'Player': 'Elsewhere Guy'})
    return pd.DataFrame(rows)


def write_feeds(td, **kw):
    td = Path(td)
    (td / 'props').mkdir(parents=True, exist_ok=True)
    (td / 'odds').mkdir(parents=True, exist_ok=True)
    path = td / 'props' / 'NFL_Props.csv'
    props_frame(**kw).to_csv(path, index=False)
    t = time.time() + CLOCK.setdefault('bump', 0)
    CLOCK['bump'] += 5                                    # force a new mtime -> loader cache refresh
    os.utime(path, (t, t))
    pd.DataFrame([{'Date': '2026-11-08', 'Time': '13:00', 'Away': AWAY, 'Home': HOME, 'AwayFull': AWAY,
                   'HomeFull': HOME, 'AwayML': 150, 'HomeML': -170, 'Spread': -3.5, 'SpreadOdds': -112,
                   'Total': 44.5, 'OverOdds': -108, 'UnderOdds': -112, 'Book': 'SynBook', 'GameID': 'evt-syn-1',
                   'LastUpdated': '2026-11-08 11:30'},
                  {'Date': '2026-11-08', 'Time': '16:25', 'Away': 'Other Team', 'Home': 'Elsewhere Team',
                   'AwayFull': 'x', 'HomeFull': 'y', 'AwayML': 100, 'HomeML': -120, 'Spread': -1.5,
                   'SpreadOdds': -110, 'Total': 40.5, 'OverOdds': -110, 'UnderOdds': -110, 'Book': 'SynBook',  # synthetic-fixture
                   'GameID': 'evt-other', 'LastUpdated': '2026-11-08 11:30'}]).to_csv(
        td / 'odds' / 'NFL_Odds.csv', index=False)
    pd.DataFrame([{'Date': '2026-11-08', 'Time': '1:00 PM', 'Away': AWAY, 'Home': HOME, 'SpreadH1': -1.5,
                   'TotalH1': 22.5, 'SpreadQ1': -0.5, 'TotalQ1': 7.5, 'TeamTotalAway': 20.5, 'TeamTotalHome': 24.5,
                   'Books': 'SynBook', 'GameID': 'evt-syn-1', 'LastUpdated': '2026-11-08T16:30:00Z'},
                  {'Date': '2026-11-08', 'Time': '4:25 PM', 'Away': 'Other Team', 'Home': 'Elsewhere Team',
                   'SpreadH1': -0.5, 'TotalH1': 20.5, 'SpreadQ1': 0, 'TotalQ1': 6.5, 'TeamTotalAway': 19.5,
                   'TeamTotalHome': 21.5, 'Books': 'SynBook', 'GameID': 'evt-other',
                   'LastUpdated': '2026-11-08T16:30:00Z'}]).to_csv(td / 'odds' / 'NFL_FirstHalf.csv', index=False)


class Fixture:
    def __init__(self, td):
        self.td = Path(td)

    def __enter__(self):
        write_feeds(self.td)
        names = ('DATA_DIR', '_now_utc', '_nfl_player_team_pos', 'build_nfl_matchup_context', '_nfl_line_move',
                 'get_current_user', 'is_owner_user', 'record_active_user')
        self.saved = {n: getattr(app, n) for n in names}
        app.DATA_DIR = self.td
        app._now_utc = lambda: CLOCK['now']
        app._nfl_player_team_pos = lambda: {}
        app.build_nfl_matchup_context = lambda: {'mu_week': [{'away': AWAY, 'home': HOME}]}
        app._nfl_line_move = lambda a, h: None
        owner = sorted(app.OWNER_EMAILS)[0] if app.OWNER_EMAILS else 'qc@example.invalid'
        app.get_current_user = lambda *a, **k: {'email': owner, 'user_id': 'qc-sgp-kickoff', 'plan': 'all_access'}
        app.is_owner_user = lambda *a, **k: True
        app.record_active_user = lambda *a, **k: None
        return self

    def __exit__(self, *exc):
        for n, v in self.saved.items():
            setattr(app, n, v)


def ctx_at(now, sel=(), conf=None):
    CLOCK['now'] = now
    return app.build_sgp_workbench_context(game=GAME, selected_ids=list(sel), thesis='custom', confirmed=conf)


def confirm_map(ctx, ids):
    """{id: price} -- the quote terms the user confirmed when adding each leg (quote-change atomicity:
    an export carries only confirmed terms; the D4 contract also needs 2..8 legs)."""
    return {lg['id']: lg['price'] for lg in legs(ctx) if lg['id'] in ids and lg['price'] is not None}


def legs(ctx):
    return [lg for grp in ctx['menu'] for lg in grp['legs']]


def leg_id(ctx, **m):
    for lg in legs(ctx):
        if all(lg.get(k) == v for k, v in m.items()):
            return lg['id']
    raise KeyError(m)


def page(client, now, sel=(), extra=(), conf=None):
    CLOCK['now'] = now
    q = urlencode([('game', GAME), ('thesis', 'custom')] + [('sel', i) for i in sel] + list(extra)
                  + [('cf', f'{i}~{p:+d}') for i, p in (conf or {}).items()])
    r = client.get('/tools/sgp-workbench?' + q)
    return r.status_code, r.get_data(as_text=True)


def blocks(html, attr):
    """{id: html block} for every `<div class="sgp-leg ..." {attr}="id"` row (cut before the next section)."""
    out = {}
    for part in html.split('<div class="sgp-leg')[1:]:
        m = re.search(attr + r'="([^"]*)"', part[:400])
        if m:
            import html as _h
            out[_h.unescape(m.group(1))] = part.split('<h2>')[0].split('<div class="sgp-sec')[0]
    return out


PRICED = 'class="sgp-price">'     # a rendered price span (unavailable prices use class="sgp-price na")


# ------------------------------------------------------------------ the checks (rec = result sink)
def check_selection(rec, client):
    for now, offered, tag in ((KICK + S1, False, 'kickoff = now-1s'), (KICK, False, 'kickoff == now'),
                              (KICK - S1, True, 'kickoff = now+1s')):
        c = ctx_at(now)
        for pl in (QB, WR):
            ls = [lg for lg in legs(c) if lg.get('player') == pl]
            rec(ls and all(bool(lg['ticket_ok']) == offered and bool(lg['toggle_url']) == offered for lg in ls),
                f'SEL {tag}: {pl} legs {"offered [control]" if offered else "NOT offered"} by the picker '
                f'({[(lg["kickoff_status"], bool(lg["toggle_url"])) for lg in ls]})')
            if not offered:
                rec(all(lg['kickoff_status'] == 'STARTED' and lg['kickoff_note'] == app.SGP_STARTED_MENU_NOTE
                        for lg in ls), f'SEL {tag}: {pl} stays browsable, labelled "{app.SGP_STARTED_MENU_NOTE}"')
        code, html = page(client, now)
        b = blocks(html, 'data-leg-id')
        qid = leg_id(c, player=QB, direction='OVER', book='SynBook')
        blk = b.get(qid, '')
        has_add = 'class="sgp-btn add"' in blk
        rec(code == 200 and blk and has_add == offered and ((PRICED in blk) == offered),
            f'SEL {tag}: rendered row {"has [control]" if offered else "has NO"} Add control / price '
            f'(HTTP {code}, add={has_add}, priced={PRICED in blk})')
        if not offered:
            rec(app.SGP_STARTED_MENU_NOTE in blk, f'SEL {tag}: rendered row shows the started label')


def check_held(rec, client):
    c0 = ctx_at(PRE)
    q, w = leg_id(c0, player=QB, direction='OVER', book='SynBook'), leg_id(c0, player=WR, direction='OVER')
    held = [q, w]
    cf = confirm_map(c0, held)
    pre = ctx_at(PRE, held, cf)
    rec([l['id'] for l in pre['selected']] == held and pre['handoff']['status'] == 'held'
        and pre['ticket_gate']['executable'], 'HELD control: before kickoff the 2-leg ticket is executable (handoff held)')
    code, html = page(client, PRE, held, conf=cf)
    rec('Parlay Builder transfer held' in html and '| scope: individual' in html,
        'HELD control: before kickoff the full-fidelity copy renders')

    post = ctx_at(KICK + S1, held, cf)
    rec([l['id'] for l in post['selected']] == held, 'HELD: legs that crossed kickoff are NOT deleted from the ticket [structural]')
    rec(all(l['kickoff_status'] == 'STARTED' and l['held_note'] == 'Started — remove or rebuild' and l.get('remove_url')
            for l in post['selected']), 'HELD: each is marked "Started — remove or rebuild" with a remove control')
    rec(post['ticket_gate'] and not post['ticket_gate']['executable']
        and sorted(post['ticket_gate']['started']) == sorted(l['label'] for l in post['selected'])
        and post['handoff']['status'] == 'rejected', 'HELD: the held ticket is non-executable (handoff rejected)')
    code, html = page(client, KICK + S1, held, conf=cf)
    sb = blocks(html, 'data-selected-id')
    rec(code == 200 and all(i in sb and 'Started — remove or rebuild' in sb[i] and PRICED not in sb[i] for i in held),
        'HELD: rendered selected legs are marked and show no price')
    rec('data-sgp-rejected="1"' in html and 'Parlay Builder transfer held' not in html and '| scope:' not in html,
        'HELD: no full-fidelity copy / handoff renders for the stale ticket')

    # the feed drops the started game's QB rows: the held id must be LISTED (not silently dropped)
    write_feeds(app.DATA_DIR, drop_players=(QB,))
    try:
        gone = ctx_at(KICK - timedelta(minutes=5), held, cf)
        un = [u['id'] for u in gone['unresolved_selected']]
        rec(un == [q] and [l['id'] for l in gone['selected']] == [w],
            f'HELD: a held leg that vanished from the feed is listed as unresolved, not deleted ({un}) [structural]')
        rec(gone['handoff']['status'] == 'rejected' and gone['ticket_gate']['unresolved'] == [q],
            'HELD: a vanished held leg blocks export (fail closed) [structural]')
        other = next(lg for lg in legs(gone) if lg.get('toggle_url') and lg['id'] != w)
        rec(urlencode([('sel', q)]) in other['toggle_url'],
            'HELD: the next click keeps the vanished id in the ticket state (only an explicit remove drops it) [structural]')
        rec(urlencode([('sel', q)]) not in gone['unresolved_selected'][0]['remove_url'],
            'HELD: the vanished leg has its own explicit remove control [structural]')
        code, html = page(client, KICK - timedelta(minutes=5), held, conf=cf)
        ub = blocks(html, 'data-unresolved')
        rec(q in ub and app.SGP_UNRESOLVED_NOTE in ub[q] and 'data-sgp-rejected="1"' in html,
            'HELD: rendered page lists the vanished leg with its note and rejects export [structural]')
    finally:
        write_feeds(app.DATA_DIR)


def check_export(rec, client):
    c0 = ctx_at(PRE)
    q = leg_id(c0, player=QB, direction='OVER', book='SynBook')
    w = leg_id(c0, player=WR, direction='OVER')
    cf = confirm_map(c0, [q, w])                 # a confirmed 2-leg ticket: only the kickoff gate can reject it
    # forged client clock params are ignored -- the server clock decides
    forged = [('now', iso(PRE)), ('server_now_utc', iso(PRE)), ('kickoff_utc', iso(KICK + timedelta(days=1)))]
    code, html = page(client, KICK, [q, w], forged, conf=cf)
    rec(code == 200 and 'data-sgp-rejected="1"' in html and '| scope:' not in html,
        'EXP: GET with a forged pre-kickoff client clock is still rejected at kickoff == server now')
    started = [lg for lg in legs(ctx_at(KICK + S1)) if lg.get('player') == QB]   # CLOCK now KICK+1s
    h = app._sgp_handoff_state(started[:1])                       # no gate passed: computed on server clock
    rec(h['status'] == 'rejected' and h['reason'] == 'kickoff_gate',
        'EXP: _sgp_handoff_state with a started leg and no gate -> rejected (computed server-side)')
    forged_leg = dict(started[0], kickoff_status=None, ticket_ok=True, kickoff_note=None)
    g = app._sgp_ticket_gate([forged_leg], [], KICK + S1)
    rec(not g['executable'] and g['started'] == [forged_leg['label']],
        'EXP: a forged "ticket_ok" annotation is re-judged by the server gate (rejected)')
    CLOCK['now'] = PRE
    ok_legs = [lg for lg in legs(ctx_at(PRE)) if lg['id'] in (q, w)]
    rec(len(ok_legs) == 2 and app._sgp_handoff_state(ok_legs, confirmed=cf)['status'] == 'held',
        'EXP control: a not-started, confirmed 2-leg ticket is not rejected')
    for pl in (RB, TE):
        lid = leg_id(c0, player=pl, direction='OVER')
        cx = ctx_at(PRE, [lid])
        rec(cx['handoff']['status'] == 'rejected' and cx['ticket_gate']['missing_kickoff'],
            f'EXP: a ticket carrying an unknown-kickoff leg ({pl}) is rejected')


def check_unknown(rec, client):
    c = ctx_at(PRE)
    for pl, why in ((RB, 'blank commence time'), (TE, 'naive commence time')):
        ls = [lg for lg in legs(c) if lg.get('player') == pl]
        rec(ls and all(lg['kickoff_utc'] is None and lg['kickoff_status'] == 'MISSING_KICKOFF' and not lg['ticket_ok']
                       and lg['toggle_url'] is None and lg['kickoff_note'] == KNA for lg in ls),
            f'UNK: {pl} ({why}) -> MISSING_KICKOFF, not addable, labelled "{KNA}"')
        lid = leg_id(c, player=pl, direction='OVER')
        sel = ctx_at(PRE, [lid])['selected']
        rec(sel and sel[0]['held_note'] == KNA, f'UNK: a crafted selection of {pl} shows "{KNA}" (not dropped)')
    write_feeds(app.DATA_DIR, commence_col=False)
    try:
        c2 = ctx_at(PRE)
        pls = [lg for lg in legs(c2) if lg['kind'] == 'player']
        rec(pls and all(lg['kickoff_status'] == 'MISSING_KICKOFF' and lg['toggle_url'] is None for lg in pls),
            f'UNK: props feed with no EventCommenceAtUTC column -> every player leg fails closed ({len(pls)})')
    finally:
        write_feeds(app.DATA_DIR)


def check_offset(rec, client):
    for now in (KICK - S1, KICK, KICK + S1):
        c = ctx_at(now)
        qb = [lg for lg in legs(c) if lg.get('player') == QB]
        books = {lg['book'] for lg in qb}
        rec(books == {'SynBook', 'OtherBook'} and {lg['kickoff_utc'] for lg in qb} == {iso(KICK)}
            and len({lg['kickoff_status'] for lg in qb}) == 1,
            f"OFS now={iso(now)}: 'Z' and '-05:00' rows canonicalize to one instant with one decision "
            f"({sorted({str(lg['kickoff_status']) for lg in qb})})")


def check_context_lines(rec, client):
    c = ctx_at(PRE)
    team = [lg for lg in legs(c) if lg['kind'] in ('game', 'team_total')]
    stats = {lg['stat'] for lg in team}
    rec({'Game Total', 'Spread', 'Team Total'} <= stats, f'CTX: fixture yields game-line + team-total legs ({sorted(stats)})')
    rec(all(lg['kickoff_status'] == 'MISSING_KICKOFF' and lg['kickoff_note'] == KNA and lg['toggle_url'] is None
            for lg in team), f'CTX: every game-line / team-total leg is "{KNA}" and not addable')
    code, html = page(client, PRE)
    b = blocks(html, 'data-leg-id')
    rec(team and all(KNA in b.get(lg['id'], '') and PRICED not in b.get(lg['id'], '')
                     and 'class="sgp-btn add"' not in b.get(lg['id'], '') for lg in team),
        'CTX: rendered game-line / team-total rows carry the exact label, no price, no Add control')
    gt = next(lg for lg in team if lg['stat'] == 'Game Total' and lg['direction'] == 'OVER')
    rec(gt['price'] == -108 and '-108' not in b.get(gt['id'], ''),
        'CTX: a captured game-total price (-108) is withheld from the context-only row')
    cx = ctx_at(PRE, [gt['id']])
    rec(cx['handoff']['status'] == 'rejected' and cx['ticket_gate']['missing_kickoff'] == [gt['label']]
        and cx['selected'][0]['held_note'] == KNA,
        'CTX: a crafted selection of a context-only game line is shown labelled and blocks export')


def check_one_predicate(rec):
    src = (ROOT / 'app.py').read_text(encoding='utf-8')
    rec(len(re.findall(r'_kickoff_gate_failure\(', src)) == 2, 'ONE: app.py defines the kickoff predicate once, one call site')
    for fn in (app._sgp_apply_kickoff_gate, app._sgp_ticket_gate):
        s = inspect.getsource(fn)
        rec('_leg_kickoff_failure(' in s and '_canonical_kickoff_utc(' not in s
            and not re.search(r'[<>]=?\s*now\b', s), f'ONE: {fn.__name__} uses only the shared rule (no own comparison)')
    s = inspect.getsource(app.build_sgp_workbench_context)
    rec('_sgp_apply_kickoff_gate(' in s and '_now_utc()' in s and not re.search(r'[<>]=?\s*now\b', s)
        and 'request.' not in s, 'ONE: the workbench context judges on the server clock, no request-supplied time')


GROUPS = (('SEL', check_selection), ('HELD', check_held), ('EXP', check_export), ('UNK', check_unknown),
          ('OFS', check_offset), ('CTX', check_context_lines))


def run_groups(rec):
    client = app.app.test_client()
    for name, fn in GROUPS:
        try:
            fn(rec, client)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            rec(False, f'{name} crashed: {exc!r}')


def main() -> int:
    with tempfile.TemporaryDirectory() as td, Fixture(td):
        run_groups(ok)
        check_one_predicate(ok)

        # M1: disable the kickoff predicate -> the gate checks must FAIL
        real = app._kickoff_gate_failure
        mres = []
        app._kickoff_gate_failure = lambda k, now: None
        try:
            run_groups(lambda c, m: mres.append((bool(c), m)))
        finally:
            app._kickoff_gate_failure = real
        failed = {m for c, m in mres if not c}
        # every gate-dependent assertion must flip; positive controls, fixture sanity, offset
        # canonicalization and the vanished-leg path (independent of the predicate) are excluded
        must = [m for _c, m in mres if not m.startswith('OFS') and 'control' not in m
                and '[structural]' not in m and not m.startswith('CTX: fixture')]
        missed = [m for m in must if m not in failed]
        ok(not missed and len(must) >= 20,
           f'M1: kickoff gate disabled => {len(must) - len(missed)}/{len(must)} SEL/HELD/EXP/UNK/CTX checks FAIL'
           + (f' (still passing: {missed[:4]})' if missed else ''))

        # M2: bypass the picker annotation (every leg marked ok) -> the server export gate still rejects
        real_apply = app._sgp_apply_kickoff_gate

        def _mut(lg, now):
            lg.update(kickoff_status=None, ticket_ok=True, kickoff_note=None, held_note=None)
            return None
        app._sgp_apply_kickoff_gate = _mut
        try:
            c0 = ctx_at(PRE)
            q = leg_id(c0, player=QB, direction='OVER', book='SynBook')
            post = ctx_at(KICK + S1, [q])
            rec_ok = post['handoff']['status'] == 'rejected' and post['ticket_gate']['started']
            picker_leak = any(lg['toggle_url'] for lg in legs(post) if lg.get('player') == QB and not lg['selected'])
        finally:
            app._sgp_apply_kickoff_gate = real_apply
        ok(picker_leak, 'M2: picker annotation bypassed => started legs ARE offered (selection checks can see it)')
        ok(rec_ok, 'M2: ...yet the server-side export gate still REJECTS the started ticket (defence in depth)')

    print('=' * 60)
    print('BANKROLL KINGS SGP WORKBENCH KICKOFF GATE QC (D4)')
    print('=' * 60)
    for passed, msg in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")
    n_fail = sum(1 for p, _ in results if not p)
    print(f'\n{len(results) - n_fail}/{len(results)} passed')
    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
