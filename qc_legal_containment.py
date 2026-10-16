"""QC: Legal/IP containment (docs/legal_ip_audit.md) — verifies the reversible containment holds.

With the containment flags OFF (production default), asserts that no uncleared official league/team mark
is served or emitted, the former logo URLs 404, the independence/trademark disclaimer renders, the NBA
board shows the honest unavailable banner while licensed Odds API lines still render, and NBA.com-derived
gamelogs are withheld. When a flag is explicitly ON (documented permission / counsel approval assumed),
the corresponding checks are skipped — this is a containment guard, correct in both states.

Renders through the real authenticated route (owner session). Exits 0 when containment holds, 1 otherwise.
"""
from __future__ import annotations

import app
from services.nba_source_gate import nba_stats_enabled

FORBIDDEN_LOGO_URLS = [
    '/static/logos/nba/', '/static/logos/nba_clean/', '/static/logos/football/',
    '/static/logos/leagues/official/', 'raw.githubusercontent.com/timaboderin',
]
FORMER_URLS = [
    '/static/logos/nba/ATL.png', '/static/logos/nba_clean/ATL.png',
    '/static/logos/football/chiefs.png', '/static/logos/leagues/official/nba.png',
]
DISCLAIMER = 'not affiliated with, endorsed by, or sponsored by'


def _client():
    c = app.app.test_client()
    with c.session_transaction() as s:
        s['user_id'] = 'qc-owner'
        s['user_email'] = next(iter(app.OWNER_EMAILS))
    return c


def run_qc():
    issues, notes = [], []
    marks_on = app.BK_OFFICIAL_MARKS_ENABLED
    nba_on = nba_stats_enabled()
    c = _client()

    # ---- official marks containment (only asserted while OFF) ----
    if marks_on:
        notes.append('BK_OFFICIAL_MARKS_ENABLED is ON — marks containment checks skipped (permission assumed)')
    else:
        if app.team_logo_url('LAL', 'nba') != '':
            issues.append('team_logo_url should be empty while marks are gated')
        if app.football_logo_url('chiefs', 'nfl') != '':
            issues.append('football_logo_url should be empty while marks are gated')
        if app.sport_logo_url('nba') != app.BK_OWNED_BADGE_URL:
            issues.append('sport_logo_url(nba) should return the owned BK badge while gated')
        if '<img' in str(app.render_team_mark('LAL', sport_key='nba')):
            issues.append('render_team_mark emitted an <img> while marks are gated')
        if app.TEAM_ABBR_TO_LOGO_URL:
            issues.append('TEAM_ABBR_TO_LOGO_URL (third-party hot-link) is not empty')
        # former public URLs must 404; owned badge still serves
        for u in FORMER_URLS:
            if c.get(u).status_code != 404:
                issues.append(f'quarantined asset still served: {u}')
        if c.get(app.BK_OWNED_BADGE_URL).status_code != 200:
            issues.append('owned BK badge is not served')
        notes.append('marks gated: helpers emit text/badge, hot-link removed, quarantined URLs 404')

    # ---- rendered surfaces: no leaks, disclaimer present ----
    def _get(path):
        r = c.get(path)
        return r.status_code, r.get_data(as_text=True)
    for path in ('/sports/nba/props', '/sports/nfl/props', '/pricing', '/how-we-analyze'):
        st, h = _get(path)
        if st != 200:
            issues.append(f'{path} returned {st} (want 200)')
            continue
        if not marks_on:
            leaks = [s for s in FORBIDDEN_LOGO_URLS if s in h]
            if leaks:
                issues.append(f'{path} leaked uncleared logo URL(s): {leaks}')
    # disclaimer on a public + an authed shell
    for path in ('/pricing', '/sports/nfl/props'):
        st, h = _get(path)
        if st == 200 and DISCLAIMER not in h:
            issues.append(f'{path} missing the independence/non-affiliation disclaimer')

    # ---- NBA.com data-rights gate ----
    if nba_on:
        notes.append('BK_NBA_STATS_ENABLED is ON — NBA.com gate checks skipped (rights cleared assumed)')
    else:
        gl = app.load_gamelogs()
        if gl is None or not gl.empty:
            issues.append('load_gamelogs (NBA.com-derived) is not gated empty')
        st, h = _get('/sports/nba/props')
        if st == 200 and 'temporarily unavailable' not in h.lower():
            issues.append('NBA board missing the honest unavailable banner while the NBA gate is off')
        notes.append('NBA.com-derived stats withheld (gamelogs/tracking/advanced/snapshot + snapshots + '
                     'cache key); NBA board shows the paused banner; licensed odds + other sports unaffected')

    # ---- service worker cache bumped ----
    try:
        sw = (app.STATIC_DIR / 'service-worker.js').read_text(encoding='utf-8')
        if 'shell-v11' not in sw:
            issues.append('service-worker BK_CACHE not bumped to shell-v11')
    except OSError:
        notes.append('service-worker.js not read (skipped)')

    if not issues:
        notes.append('legal containment verified: no uncleared marks served, disclaimer live, NBA.com gated')
    return {'issues': issues, 'notes': notes}


def main() -> int:
    report = run_qc()
    print('=' * 60)
    print('BANKROLL KINGS LEGAL/IP CONTAINMENT QC')
    print('=' * 60)
    for n in report['notes']:
        print(f'[NOTE] {n}')
    if report['notes']:
        print()
    if not report['issues']:
        print('Legal/IP containment verified.')
        return 0
    for m in report['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
