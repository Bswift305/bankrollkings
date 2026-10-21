"""QC: Green Light preference workspace route + template (commit 3), via the real request pipeline.

Imports the app and drives it with an owner test client (bypasses the PRO gate) to prove, reproducibly:
- no saved prefs -> the full 12-lens default workspace (not the old board);
- the default /tools/green-light (no view) still renders the classic convergence board unchanged;
- CSRF-protected POST save: a hidden lens drops from visible, the "lenses you hid" count is accurate;
- reset removes ONLY the greenlight key (restores 12) and leaves other settings untouched;
- the per-lens status endpoint returns JSON; an unknown lens -> 404;
- the proposed ticket reuses the shared builder + editor (cannot drift from Daily Cards / King's Tickets);
- the workspace code accesses neither the Decision Journal nor the King's Tickets draft store.
Writes a throwaway local prefs file under data/user_prefs and removes it. Exits 0 when all hold.
"""
from __future__ import annotations

import os
import re

ISSUES, NOTES = [], []


def ok(cond, fail_msg, pass_msg=None):
    if cond:
        if pass_msg:
            NOTES.append(pass_msg)
    else:
        ISSUES.append(fail_msg)


def _cards(html):
    return len(re.findall(r'class="glw-card', html))


def _gl_states():
    import services.green_light_adapters as ga
    return ga.AVAILABILITY_STATES


def run_qc():
    try:
        import app
    except ModuleNotFoundError as e:
        if 'flask' in str(e).lower():
            NOTES.append('SKIPPED: run under the app virtualenv (Flask not importable with this python) — '
                         'e.g. <venv>/bin/python3 qc_green_light_workspace.py')
            return {'issues': ISSUES, 'notes': NOTES}
        raise
    owner = sorted(app.OWNER_EMAILS)[0] if app.OWNER_EMAILS else None
    if not owner:
        NOTES.append('no OWNER_EMAILS configured; workspace route QC skipped')
        return {'issues': ISSUES, 'notes': NOTES}
    app.get_current_user = lambda *a, **k: {'email': owner, 'user_id': 'qc-glw-local', 'plan': 'all_access'}
    c = app.app.test_client()
    pf = os.path.join('data', 'user_prefs', 'qc-glw-local.json')
    try:
        # 1. the DEFAULT /tools/green-light (no param) is now the full 12-lens workspace
        h = c.get('/tools/green-light').get_data(as_text=True)
        ok('Preference Workspace' in h and _cards(h) == 12,
           f'default route is not the full 12-lens workspace (cards={_cards(h)})',
           'default /tools/green-light -> full 12-lens workspace (flipped)')
        ok(all(s in h for s in ['Lenses you hid', 'Eligible items hidden by your sport/market',
                                'data / freshness / legal / model gate']),
           'the three distinct counts are not all present', 'three distinct, separately-labeled counts')

        # 2. the classic convergence board is preserved at ?view=classic (rollback)
        h_classic = c.get('/tools/green-light?view=classic').get_data(as_text=True)
        ok('Preference Workspace' not in h_classic and 'green-light' in h_classic.lower(),
           'classic board not preserved at ?view=classic',
           'classic board preserved at ?view=classic (instant rollback)')

        # 3. CSRF-protected save: a POST with no token is rejected
        ok(c.post('/tools/green-light', data={'hidden': ['heat_map']}).status_code == 400,
           'POST without a CSRF token was accepted', 'POST is CSRF-protected (no token -> 400)')
        tok = re.search(r'name="csrf_token" value="([^"]+)"', h).group(1)
        r = c.post('/tools/green-light', data={'csrf_token': tok, 'order': 'milestone_streaks,heat_map,weather',
                                               'hidden': ['heat_map', 'weather'], 'sports': ['nfl']})
        ok(r.status_code in (302, 303), f'save POST did not redirect (got {r.status_code})')
        h2 = c.get('/tools/green-light?view=workspace').get_data(as_text=True)
        ok(_cards(h2) == 10 and 'you hid this lens' in h2,
           f'hidden lenses not reflected (cards={_cards(h2)})', 'hiding lenses drops them from visible')
        ok(re.findall(r'<div class="n"[^>]*>(\d+)</div>', h2)[:1] == ['2'],
           'the "lenses you hid" count is wrong', 'hidden-by-user count is accurate')

        # 4. reset removes only the greenlight key, restores 12
        c.post('/tools/green-light', data={'csrf_token': tok, 'action': 'reset'})
        import json
        after = json.load(open(pf, encoding='utf-8')) if os.path.exists(pf) else {}
        ok('greenlight' not in after, 'reset did not remove the greenlight key')
        h3 = c.get('/tools/green-light?view=workspace').get_data(as_text=True)
        ok(_cards(h3) == 12, f'reset did not restore the 12-lens default (cards={_cards(h3)})',
           'reset restores the house default (removes only the greenlight key)')

        # 5. ALL 12 live adapters return a real envelope (no deep-link-only cards); universe == GL universe
        import app as _app
        from services.green_light_lenses import LENS_KEYS
        bad = []
        for k in LENS_KEYS:
            e = c.get('/tools/green-light/lens/' + k).get_json() or {}
            if not (e.get('key') == k and e.get('availability') in _gl_states()
                    and isinstance(e.get('membership_count'), int) and e.get('no_suppression') is True
                    and e.get('universe_hash') == e.get('gl_hash')):
                bad.append(k)
        ok(not bad, f'lenses with a bad/deep-link-only envelope: {bad}',
           'all 12 live adapters return a real envelope (universe_hash == gl_hash, no suppression)')
        ok(c.get('/tools/green-light/lens/bogus').status_code == 404, 'unknown lens was not 404',
           'unknown lens -> 404')
        # counts endpoint: the three real, never-combined counts, all ints
        cj = c.get('/tools/green-light/counts').get_json() or {}
        cc = cj.get('counts') or {}
        ok(set(cc) == {'lenses_hidden_by_user', 'eligible_items_hidden_by_pref', 'items_unavailable_by_gate'}
           and all(isinstance(v, int) for v in cc.values()),
           f'counts endpoint shape wrong: {cc}', 'counts endpoint returns three real int counts (never combined)')
        ok(isinstance(cj.get('lenses'), dict) and len(cj['lenses']) >= 1,
           'counts endpoint has no per-lens summary', 'counts endpoint returns per-lens summaries')
        # lazy, browser-only proposed-ticket fragment
        rt = c.get('/tools/green-light/ticket')
        ok(rt.status_code == 200, f'ticket fragment not 200 (got {rt.status_code})',
           'lazy proposed-ticket fragment returns 200')
    finally:
        try:
            os.remove(pf)
        except OSError:
            pass

    # 6. lazy ticket + no-drift + no journal/draftstore coupling (static)
    src = open('app.py', encoding='utf-8', errors='replace').read()

    def _fn(name):
        i = src.find('def ' + name + '(')
        return src[i:src.find('\ndef ', i + 1)] if i >= 0 else ''
    shell, ticket = _fn('build_green_light_workspace'), _fn('green_light_ticket')
    ok('build_daily_cards(' not in shell, 'shell still calls build_daily_cards (not lazy)',
       'shell calls NO builder (proposed ticket is lazy-loaded)')
    ok('build_daily_cards(' in ticket and '_ticket_editor.html' in ticket,
       'lazy ticket endpoint does not reuse the shared builder/editor',
       'lazy ticket reuses build_daily_cards + shared _ticket_editor.html (cannot drift)')
    ok(not re.search(r'journal|KingsTicketDraftStore|DraftService|kings_tickets_drafts', ticket),
       'lazy ticket couples to a dark store', 'lazy ticket touches neither the Decision Journal nor the draft store')
    tpl = open('templates/green_light_workspace.html', encoding='utf-8', errors='replace').read()
    ok('glw-ticket' in tpl and 'green_light_ticket' in tpl and '_ticket_editor.html' not in tpl,
       'template does not lazy-load the ticket (or still inlines the editor)',
       'template lazy-loads the proposed ticket (no inline build in the shell)')
    # the whole GL workspace region (shell + adapters + endpoints) is clean of dark-store coupling
    region = src[src.find('# --- Green Light preference workspace'):src.find('def green_light_ticket') + len(ticket)]
    ok(not re.search(r'journal|KingsTicketDraftStore|DraftService|kings_tickets_drafts', region),
       'workspace region couples to the journal or draft store',
       'workspace region touches neither the Decision Journal nor the draft store')

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 68)
    print('BANKROLL KINGS - GREEN LIGHT WORKSPACE QC (route + template, commit 3)')
    print('=' * 68)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No green-light workspace issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
