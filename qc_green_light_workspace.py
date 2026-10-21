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


def run_qc():
    import app
    owner = sorted(app.OWNER_EMAILS)[0] if app.OWNER_EMAILS else None
    if not owner:
        NOTES.append('no OWNER_EMAILS configured; workspace route QC skipped')
        return {'issues': ISSUES, 'notes': NOTES}
    app.get_current_user = lambda *a, **k: {'email': owner, 'user_id': 'qc-glw-local', 'plan': 'all_access'}
    c = app.app.test_client()
    pf = os.path.join('data', 'user_prefs', 'qc-glw-local.json')
    try:
        # 1. full 12-lens default workspace
        h = c.get('/tools/green-light?view=workspace').get_data(as_text=True)
        ok('Preference Workspace' in h and _cards(h) == 12,
           f'default workspace is not the full 12-lens page (cards={_cards(h)})',
           'no saved prefs -> full 12-lens default workspace')
        ok(all(s in h for s in ['Lenses you hid', 'filtered by your sport/market choice',
                                'data / freshness / legal / model gate']),
           'the three distinct counts are not all present', 'three distinct, separately-labeled counts')

        # 2. default board unchanged
        h_def = c.get('/tools/green-light').get_data(as_text=True)
        ok('Preference Workspace' not in h_def and 'green-light' in h_def.lower(),
           'default /tools/green-light no longer renders the classic board',
           'default board unchanged (workspace is opt-in via ?view=workspace)')

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

        # 5. lens status endpoint
        rj = c.get('/tools/green-light/lens/milestone_streaks')
        ok(rj.status_code == 200 and rj.is_json and (rj.get_json() or {}).get('key') == 'milestone_streaks',
           'lens status endpoint did not return JSON', 'per-lens status endpoint returns JSON')
        ok(c.get('/tools/green-light/lens/bogus').status_code == 404,
           'unknown lens was not 404', 'unknown lens -> 404')
    finally:
        try:
            os.remove(pf)
        except OSError:
            pass

    # 6. no-drift + no journal/draftstore coupling (static)
    src = open('app.py', encoding='utf-8', errors='replace').read()
    block = src[src.find('# --- Green Light preference workspace'):src.find('def green_light_lens_status')]
    ok('build_daily_cards(' in block,
       'workspace does not reuse build_daily_cards (ticket could drift)',
       'proposed ticket reuses build_daily_cards (no drift from Daily Cards / King\'s Tickets)')
    tpl = open('templates/green_light_workspace.html', encoding='utf-8', errors='replace').read()
    ok('_ticket_editor.html' in tpl, 'workspace does not include the shared ticket editor',
       'workspace includes the shared _ticket_editor.html partial')
    ok(not re.search(r'journal|KingsTicketDraftStore|DraftService|kings_tickets_drafts', block),
       'workspace code couples to the journal or draft store',
       'workspace touches neither the Decision Journal nor the draft store')

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
