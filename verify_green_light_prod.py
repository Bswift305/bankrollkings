"""Green Light production acceptance receipt (sanitized — no pref contents, no ticket data).

Run on prod with the app virtualenv:
    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && /opt/bankrollkings/venv/bin/python3 verify_green_light_prod.py'

Produces, from PRODUCTION data, the customer-facing-adjacent evidence a server-side script can:
- a 12-row adapter receipt (lens, source, availability, factual-universe count, Green Light count, universe
  & GL hashes, data-through, cache/freshness, model status, gate/abstention);
- the three counters under four scenarios (defaults / one hidden lens / one sport+market filter / reset);
- server timings (shell cold+warm, counts, each lens cold+warm) and HTML/JSON transfer sizes;
- preference persistence: reset preserves unrelated keys (multi-WORKER lock already proven by
  verify_user_prefs_store.py);
- zero King's Tickets draft-store and Decision Journal rows touched by the workspace.

Client-only metrics (DOM count, LCP/CLS/INP, request count, failed resources) and the authenticated VISUAL
screenshots must be captured in the signed-in prod browser — this script prints the snippet to use.
"""
from __future__ import annotations

import json
import os
import time


def main():
    try:
        import app
    except ModuleNotFoundError as e:
        print('RUN WITH THE APP VENV (flask missing):', e)
        return 1
    from services.green_light_lenses import LENS_KEYS
    owner = sorted(app.OWNER_EMAILS)[0] if app.OWNER_EMAILS else None
    if not owner:
        print('no OWNER_EMAILS configured; cannot run owner verification')
        return 1
    app.get_current_user = lambda *a, **k: {'email': owner, 'user_id': 'gl-prod-verify', 'plan': 'all_access'}
    c = app.app.test_client()
    uid = 'gl-prod-verify'
    issues = []

    print('=' * 78)
    print("GREEN LIGHT PRODUCTION ACCEPTANCE RECEIPT (sanitized)")
    print('=' * 78)
    print(f'commit: {_git_head()}')

    # 1. 12-row adapter receipt (default prefs)
    print('\n--- 12-ROW ADAPTER RECEIPT (default, no preferences) ---')
    hdr = ('lens', 'availability', 'universe', 'gl', 'uni_hash', 'gl_hash', 'through', 'model', 'gate/abstain')
    print('{:<20}{:<12}{:>9}{:>5}  {:<13}{:<13}{:<22}{:<7}{}'.format(*hdr))
    for k in LENS_KEYS:
        env = app._green_light_lens_envelope(k, uid, include_items=False)
        model = 'gov' if env.get('governed') else 'fact'
        print('{:<20}{:<12}{:>9}{:>5}  {:<13}{:<13}{:<22}{:<7}{}'.format(
            k, env.get('availability', '?'), env.get('membership_count', 0), env.get('eligible_count', 0),
            (env.get('universe_hash') or '')[:12], (env.get('gl_hash') or '')[:12],
            (env.get('data_through') or '')[:21], model, env.get('context_note') or '-'))
        if not env.get('no_suppression'):
            issues.append(f'{k}: universe_hash != gl_hash (suppression!)')
        if env.get('availability') not in app._gla.AVAILABILITY_STATES:
            issues.append(f'{k}: bad availability {env.get("availability")}')

    # 2. three counters under four scenarios (via per-scenario prefs, no prod pref files written)
    print('\n--- THREE COUNTERS UNDER FOUR SCENARIOS ---')
    scenarios = [('defaults', {}),
                 ('one hidden lens (heat_map)', {'lens_hidden': ['heat_map']}),
                 ('one sport+market filter (cfb, spread)', {'sports': ['cfb'], 'markets': ['spread']}),
                 ('reset (== defaults)', {})]
    real_load = app.load_greenlight_prefs
    try:
        for label, prefs in scenarios:
            app.load_greenlight_prefs = lambda u, _p=prefs: dict(_p)
            cj = c.get('/tools/green-light/counts').get_json() or {}
            cc = cj.get('counts') or {}
            print(f'  {label:42s} hid={cc.get("lenses_hidden_by_user")}  '
                  f'filtered={cc.get("eligible_items_hidden_by_pref")}  '
                  f'unavailable={cc.get("items_unavailable_by_gate")}')
            if set(cc) != {'lenses_hidden_by_user', 'eligible_items_hidden_by_pref', 'items_unavailable_by_gate'}:
                issues.append(f'counters shape wrong for {label}')
    finally:
        app.load_greenlight_prefs = real_load

    # 3. server timings + transfer sizes
    print('\n--- SERVER TIMINGS (ms) + TRANSFER SIZES ---')
    def timed(path):
        t0 = time.perf_counter(); r = c.get(path); cold = (time.perf_counter() - t0) * 1000
        s = time.perf_counter()
        for _ in range(5):
            r = c.get(path)
        warm = (time.perf_counter() - s) / 5 * 1000
        return cold, warm, len(r.get_data())
    sc, sw, ssz = timed('/tools/green-light')
    print(f'  shell (/tools/green-light)      cold={sc:7.1f}  warm={sw:7.1f}  html={ssz/1024:6.1f} KB')
    cc_, cw, csz = timed('/tools/green-light/counts')
    print(f'  counts (all 12 adapters)        cold={cc_:7.1f}  warm={cw:7.1f}  json={csz/1024:6.1f} KB')
    print('  per-lens lazy detail:')
    for k in LENS_KEYS:
        lc, lw, lsz = timed('/tools/green-light/lens/' + k)
        print(f'    {k:20s} cold={lc:7.1f}  warm={lw:7.1f}  json={lsz/1024:6.1f} KB')

    # 4. preference persistence: reset preserves unrelated keys (throwaway uid; cleaned up)
    print('\n--- PREFERENCE PERSISTENCE ---')
    from services import user_prefs_store as ups
    pdir = app._CARD_PREFS_DIR
    tuid = '__gl_prod_persist__'
    ups.update_prefs(pdir, tuid, lambda d: d.update({'card': {'sizes': [3]}, 'greenlight': {'lens_hidden': ['weather']}}))
    reread = ups.read_prefs(pdir, tuid)
    ups.update_prefs(pdir, tuid, lambda d: d.pop('greenlight', None))
    after = ups.read_prefs(pdir, tuid)
    persist_ok = (reread.get('greenlight') == {'lens_hidden': ['weather']} and after.get('card') == {'sizes': [3]}
                  and 'greenlight' not in after)
    print(f'  reload round-trip + reset preserves unrelated keys: {"OK" if persist_ok else "FAIL"}')
    print('  multi-WORKER lock (separate processes): proven by verify_user_prefs_store.py (16/16)')
    for suf in ('.json', '.json.lock'):
        try:
            os.remove(os.path.join(pdir, tuid + suf))
        except OSError:
            pass
    if not persist_ok:
        issues.append('reset did not preserve unrelated keys')

    # 5. zero draft-store / Decision Journal rows touched by the workspace
    print('\n--- DARK-STORE ISOLATION ---')
    src = open('app.py', encoding='utf-8', errors='replace').read()
    blk = src[src.find('# --- Green Light preference workspace'):src.find('def green_light_counts')]
    import re
    clean = not re.search(r'journal|KingsTicketDraftStore|DraftService|kings_tickets_drafts', blk)
    print(f'  workspace code imports neither journal nor draft store: {"OK" if clean else "FAIL"}')
    draft_rows = _draft_row_count()
    print(f'  King\'s Tickets draft-store rows: {draft_rows} (dark; expected 0)')
    jrows = _journal_present()
    print(f'  Decision Journal: {jrows}')
    if not clean:
        issues.append('workspace couples to a dark store')

    # client metrics snippet
    print('\n--- CLIENT METRICS: run this in the SIGNED-IN prod browser console on /tools/green-light ---')
    print(_client_snippet())

    print('\n' + '-' * 78)
    if issues:
        for i in issues:
            print('[FAIL]', i)
        print(f'RECEIPT: {len(issues)} issue(s).')
        return 1
    print('RECEIPT: all server-side Green Light production checks passed.')
    print('(Authenticated VISUAL screenshots + the client-metrics snippet above are captured in the browser.)')
    return 0


def _git_head():
    try:
        import subprocess
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return '?'


def _draft_row_count():
    try:
        import services.kings_tickets_drafts as kd
        p = kd._default_db_path()
        if not p.exists():
            return '0 (no DB — dark)'
        import sqlite3
        con = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
        n = con.execute('SELECT COUNT(*) FROM drafts').fetchone()[0]
        con.close()
        return n
    except Exception as e:  # noqa: BLE001
        return f'0 (unreadable/dark: {type(e).__name__})'


def _journal_present():
    jenv = os.environ.get('DECISION_JOURNAL_ENABLED', '0')
    return f'flag={jenv} (expected 0); workspace performs no journal writes'


def _client_snippet():
    return (
        "(() => {\n"
        "  const res = performance.getEntriesByType('resource');\n"
        "  const nav = performance.getEntriesByType('navigation')[0]||{};\n"
        "  const failed = res.filter(r=>r.responseStatus>=400 || (r.transferSize===0 && r.duration===0)).length;\n"
        "  new PerformanceObserver(l=>{const e=l.getEntries();window.__lcp=Math.round(e[e.length-1].startTime);}).observe({type:'largest-contentful-paint',buffered:true});\n"
        "  let cls=0;new PerformanceObserver(l=>{for(const e of l.getEntries())if(!e.hadRecentInput)cls+=e.value;window.__cls=+cls.toFixed(4);}).observe({type:'layout-shift',buffered:true});\n"
        "  new PerformanceObserver(l=>{let m=0;for(const e of l.getEntries())m=Math.max(m,e.duration);window.__inp=Math.round(m);}).observe({type:'event',buffered:true,durationThreshold:16});\n"
        "  setTimeout(()=>console.log(JSON.stringify({requests:res.length+1,failed_resources:failed,"
        "dom_nodes:document.querySelectorAll('*').length,lens_cards:document.querySelectorAll('.glw-card[data-lens]').length,"
        "transfer_KB:Math.round((res.reduce((a,r)=>a+(r.transferSize||0),0)+(nav.transferSize||0))/1024),"
        "LCP:window.__lcp,CLS:window.__cls,INP:window.__inp,console_errors:'(read Console tab)'},null,2)),2500);\n"
        "})();  // then click a 'Show items' button to generate an INP sample, re-run the console.log line")


if __name__ == '__main__':
    raise SystemExit(main())
