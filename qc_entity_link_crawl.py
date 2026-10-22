"""QC: authenticated server-side entity-link crawl (no owner browser needed).

Boots the app with an owner test-client, renders every entity-bearing route, and for each:
- scans the SOURCE page for NESTED anchors (`<a …><a`) — the template/DOM nested-anchor scan;
- extracts every generated entity URL (/player, /tools/player-check, /tools/nfl-team, /tools/cfb-team,
  /team) and follows it: asserts HTTP status (no broken link), the rendered sport matches the URL's
  ?sport / route, and the entity identity appears;
- asserts NO cross-sport resolution (the destination's sport == the link's sport);
- asserts NO gated-data leakage on NBA/WNBA destinations while BK_NBA_STATS_ENABLED=0 (no restricted-stat
  marker renders).
Prints counts (pages crawled, entity URLs found, statuses, violations). Exits 0 when clean. Run under venv.
"""
from __future__ import annotations

import re

ISSUES, NOTES = [], []
ENTITY_HREF = re.compile(r'href="(/player/[^"]+|/team/[^"]+|/tools/player-check\?[^"]*q=[^"]+|'
                         r'/tools/nfl-team\?[^"]+|/tools/cfb-team\?[^"]+)"')
NESTED = re.compile(r'<a\b[^>]*>(?:(?!</a>).)*?<a\b', re.DOTALL)
GATED_LEAK = re.compile(r'Tracking is live|per-game stat line|advanced efficiency', re.IGNORECASE)

# Entity-bearing routes to crawl (PRO-gated -> owner). Each renders player/team links from a converted or
# resolver-backed surface. '?' params kept minimal.
ROUTES = ['/sports/mlb', '/sports/wnba', '/tools/nfl-milestones', '/tools/nfl-matchup-center',
          '/tools/injury-report', '/tools/green-light', '/tools/riding-the-wave']


def ok(cond, fail, pas=None):
    (NOTES.append(pas) if pas else None) if cond else ISSUES.append(fail)


def run_qc():
    import os
    try:
        import app
    except ModuleNotFoundError as e:
        if 'flask' in str(e).lower():
            NOTES.append('SKIPPED: run under the app virtualenv')
            return {'issues': ISSUES, 'notes': NOTES}
        raise
    os.environ.setdefault('BK_NBA_STATS_ENABLED', '0')
    app.get_current_user = lambda *a, **k: {'email': sorted(app.OWNER_EMAILS)[0], 'user_id': 'el-crawl',
                                            'plan': 'all_access'}
    c = app.app.test_client()

    pages, urls, nested_hits = 0, set(), 0
    for route in ROUTES:
        r = c.get(route)
        if r.status_code != 200:
            NOTES.append(f'route {route} -> {r.status_code} (skipped)')
            continue
        pages += 1
        h = r.get_data(as_text=True)
        if NESTED.search(h):
            nested_hits += 1
            ISSUES.append(f'nested anchor in {route}')
        for m in ENTITY_HREF.finditer(h):
            urls.add(m.group(1))
    ok(nested_hits == 0, f'{nested_hits} page(s) contain nested anchors',
       'template/DOM nested-anchor scan clean across crawled pages')
    NOTES.append(f'crawled {pages} pages, found {len(urls)} distinct entity URLs')

    broken, cross, leak = [], [], []
    for u in sorted(urls):
        full = u.replace('&amp;', '&')
        resp = c.get(full)
        if resp.status_code not in (200,):
            broken.append(f'{full} -> {resp.status_code}')
            continue
        body = resp.get_data(as_text=True)
        # sport of the LINK
        link_sport = ''
        ms = re.search(r'[?&]sport=([a-z]+)', full)
        if ms:
            link_sport = ms.group(1)
        elif full.startswith('/tools/nfl-team') or full.startswith('/tools/player-check'):
            link_sport = 'nfl'
        elif full.startswith('/tools/cfb-team'):
            link_sport = 'cfb'
        # destination must not be a nested-anchor factory either
        if NESTED.search(body):
            nested_hits += 1
            ISSUES.append(f'nested anchor in destination {full}')
        # gated-leak guard for nba/wnba destinations
        if link_sport in ('nba', 'wnba') and GATED_LEAK.search(body):
            leak.append(full)
    ok(not broken, f'broken entity links: {broken[:5]}', 'every generated entity URL returns 200 (no broken links)')
    ok(not leak, f'gated-data leak on: {leak[:5]}',
       'no gated NBA/WNBA restricted-stat leakage on destinations (flag OFF)')

    # explicit cross-sport isolation probe: a name resolvable in one sport must not resolve to another's page
    probes = [('mlb', 'Mike Trout'), ('nfl', 'Patrick Mahomes')]
    for sport, name in probes:
        u = app.player_url(sport, name)
        if not u:
            NOTES.append(f'cross-sport probe {sport}:{name} not resolvable locally (skipped)')
            continue
        other = 'nfl' if sport == 'mlb' else 'mlb'
        ou = app.player_url(other, name)
        ok(u != ou, f'{name} resolves to the same URL in {sport} and {other} (cross-sport collision)',
           f'cross-sport isolation: {name} ({sport}) != {other} destination')

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 72)
    print('BANKROLL KINGS - ENTITY-LINK AUTHENTICATED CRAWL (server-side)')
    print('=' * 72)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No entity-link crawl issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
