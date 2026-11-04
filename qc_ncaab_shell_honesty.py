"""QC: college-basketball (NCAAB -- men's ncaamb / women's ncaawb) truthfulness safeguard B.

No CBB data pipeline exists. Before this guard the themed shells rendered fabricated confidence
values (60-71) on real team names (DUKE, UNC, ...), the sidebar said "Live Board & Lines", and the
All Access copy claimed "Full prop boards ... college hoops". Every CBB surface must now render the
exact honest sentence and nothing that reads as evidence or coverage.

Offline, Flask test client, portable in-memory principals (services/qc_auth) -- no user store.
Checks:
  1. Route inventory: every app.url_map rule naming ncaamb/ncaawb is covered by this sweep (a new,
     unswept CBB route fails the QC instead of slipping past it).
  2. Every CBB page (command center, props [+filter], market-edge, trends, parlay, free preview)
     returns 200 for an owner AND a paid member, carries the exact honest text inside its honest
     section, and that section shows no digits, no confidence/lock/pick/simulation/projected/
     injury/live-board/example/sample wording and no real team names.
  3. Gating preserved: signed-out and free-plan requests to the paid CBB sections are not 200.
  4. Nav: the CBB sidebar groups show no count and no "Live Board & Lines"; on CBB pages the
     workflow toolbar offers only the CBB shell sections (no Injuries/Review/Hot Streaks/...).
  5. Hubs / data contexts: method hubs, Today and Matchup Lens hubs mark CBB 'unavailable' with the
     honest note; the cross-sport snapshot and free preview carry no CBB rows, prop, or features.
  6. Coverage copy: PRICING_TIERS / pricing page no longer claim college hoops; the fabricated
     example-row builder is gone from app.py.
  7. Mutation proof: re-inserting a fake row, a "Live Board & Lines" label, a sample hub note, a
     coverage claim, or removing the honest sentence each makes the audit FAIL.
  8. Season Markets (/tools/season-markets): NCAAMB/NCAAWB are never under "Leagues at launch", never
     counted, listed in filters or shown as rows (even when a synthetic fixture holds CBB rows); they
     appear only in a separate Planned section with the exact text "Data pipeline not yet available"
     and no link, count, live badge or launch claim. Mutation proof for each.
Exit 0 = all pass.
"""
from __future__ import annotations

import os
import re
from html import unescape

os.environ.setdefault('SECRET_KEY', 'qc-ncaab-shell-honesty')

import app  # noqa: E402
from services.qc_auth import isolated_owner_client, isolated_user_client, unauth_client  # noqa: E402

HONEST = 'NCAAB data pipeline is not yet available'
SPORTS = ('ncaamb', 'ncaawb')

# Paid (gated) CBB sections, keyed by the route rule they exercise.
GATED_PAGES = {
    '/sports/<league>': ['/sports/{s}'],
    '/sports/{s}/props': ['/sports/{s}/props'],
    '/sports/{s}/props/<filter_type>': ['/sports/{s}/props/top'],
    '/sports/{s}/market-edge': ['/sports/{s}/market-edge'],
    '/sports/{s}/trends': ['/sports/{s}/trends'],
    '/parlay': ['/parlay?sport={s}', '/parlay?sport={s}&sample=current'],
}
FREE_PAGES = ['/free/{s}']

ALLOWED_TOOLBAR_LABELS = {'Command Center', 'Props', 'Parlay Builder', 'Market Edge', 'Streak Patterns'}

FORBIDDEN_WORDS = re.compile(
    r'\b(confidence|confident|locks?|picks?|simulat\w*|projected|projections?|injur\w*|'
    r'example|sample|tips? off|live board|full prop boards?|season prep|pre-season preview|'
    r'model read|edge score|hit rate|over rate)\b',
    re.IGNORECASE,
)
# Real programs used (or likely to be used) as sample "evidence". Abbreviations are matched
# case-sensitively as whole tokens; full names case-insensitively.
TEAM_ABBR = re.compile(r'\b(DUKE|UNC|KAN|KU|UCLA|GONZ|BAY|UCONN|SC|STAN|IOWA|LSU|TEX|UK|MSU|ARIZ|PUR|HOU|VILL|NOVA)\b')
TEAM_NAMES = re.compile(
    r'\b(Duke|North Carolina|Tar Heels|Kansas|Jayhawks|Gonzaga|Baylor|UConn|Connecticut|South Carolina|'
    r'Stanford|Iowa|Hawkeyes|LSU|Texas|Longhorns|Kentucky|Michigan State|Arizona|Purdue|Houston|Villanova)\b',
    re.IGNORECASE,
)
FABRICATED_MARKERS = ('Example Guard', 'Example Wing', 'Example Forward', 'Example Center',
                      'Pre-season example', 'Example row', 'example plays')

results: list[tuple[bool, str]] = []


def ok(cond, msg):
    results.append((bool(cond), msg))


def _visible(html: str) -> str:
    html = re.sub(r'(?is)<(script|style)\b.*?</\1>', ' ', html)
    html = re.sub(r'(?s)<!--.*?-->', ' ', html)
    text = re.sub(r'(?s)<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', unescape(text)).strip()


def _honest_section(html: str) -> str | None:
    m = re.search(r'<!-- ncaab-honest:start -->(.*?)<!-- ncaab-honest:end -->', html, re.S)
    return m.group(1) if m else None


def _sidebar_group(html: str, sport: str) -> str:
    m = re.search(r'<div class="bk-sport-group" data-sport="%s">(.*?)</div>\s*</div>' % sport, html, re.S)
    return m.group(1) if m else ''


def _toolbar_labels(html: str) -> list[str]:
    m = re.search(r'<div class="bk-toolbar bk-command-toolbar bk-workflow-toolbar">(.*?)</div>', html, re.S)
    if not m:
        return []
    return [_visible(a) for a in re.findall(r'<a\b[^>]*>(.*?)</a>', m.group(1), re.S)]


def audit_page(path: str, html: str, *, gated: bool) -> list[str]:
    """Pure audit of one rendered CBB page. Returns failure strings (empty = honest)."""
    fails: list[str] = []
    section = _honest_section(html)
    if section is None:
        return [f'{path}: no ncaab-honest section rendered']
    text = _visible(section)
    if HONEST not in text:
        fails.append(f'{path}: exact honest text missing from the CBB section')
    numeric = re.findall(r'[^ ]*\d[^ ]*', text)
    if numeric:
        fails.append(f'{path}: numeric value in CBB section: {numeric[:5]}')
    for rx, label in ((FORBIDDEN_WORDS, 'forbidden claim word'), (TEAM_ABBR, 'team abbreviation'),
                      (TEAM_NAMES, 'real team name')):
        hits = sorted({h if isinstance(h, str) else h[0] for h in rx.findall(text)})
        if hits:
            fails.append(f'{path}: {label} in CBB section: {hits}')
    for marker in FABRICATED_MARKERS:
        if marker.lower() in html.lower():
            fails.append(f'{path}: fabricated sample marker on page: {marker!r}')
    if re.search(r'<table\b', section, re.I):
        fails.append(f'{path}: table rendered inside the CBB honest section')
    for sport in SPORTS:
        grp = _sidebar_group(html, sport)
        if grp:
            if 'si-count' in grp:
                fails.append(f'{path}: {sport} sidebar group shows a count')
            if re.search(r'live board|lines|live\b', _visible(grp), re.I):
                fails.append(f'{path}: {sport} sidebar label claims live data: {_visible(grp)!r}')
    if gated:
        labels = _toolbar_labels(html)
        extra = [lb for lb in labels if lb not in ALLOWED_TOOLBAR_LABELS]
        if not labels:
            fails.append(f'{path}: workflow toolbar missing (navigation not preserved)')
        if extra:
            fails.append(f'{path}: toolbar links imply CBB coverage: {extra}')
    return fails


def _expand(templates):
    return [t.format(s=s) for t in templates for s in SPORTS]


def sweep_pages() -> tuple[list[str], dict]:
    """Render every CBB page for an owner and a paid member; returns (failures, status_codes)."""
    fails: list[str] = []
    codes: dict = {}
    gated_paths = _expand([p for ps in GATED_PAGES.values() for p in ps])
    free_paths = _expand(FREE_PAGES)
    for principal, ctx in (('owner', isolated_owner_client), ('member', lambda: isolated_user_client('all_access'))):
        with ctx() as c:
            for path in gated_paths + free_paths:
                r = c.get(path)
                codes[(principal, path)] = r.status_code
                if r.status_code != 200:
                    fails.append(f'{principal} {path}: HTTP {r.status_code}')
                    continue
                if (r.mimetype or '').endswith('json'):
                    fails.append(f'{principal} {path}: JSON response from a CBB page')
                fails += [f'{principal} {f}' for f in audit_page(path, r.get_data(as_text=True),
                                                                  gated=path in gated_paths)]
    return fails, codes


def audit_hubs() -> list[str]:
    fails: list[str] = []
    want = f'{HONEST}.'
    for method in ('props', 'market-edge', 'parlay', 'injuries', 'trends'):
        for card in app.build_method_hub_context(method).get('cards', []):
            if card.get('sport_key') in SPORTS:
                if card.get('status') != 'unavailable' or card.get('note') != want:
                    fails.append(f'hub {method}/{card["sport_key"]}: status={card.get("status")!r} note={card.get("note")!r}')
    for name, ctx in (('today', app.build_today_hub_context()), ('matchup-lens', app.build_matchup_lens_hub_context())):
        for card in ctx.get('cards', []):
            if card.get('sport_key') in SPORTS:
                if card.get('status') != 'unavailable' or card.get('note') != want or int(card.get('game_count') or 0):
                    fails.append(f'hub {name}/{card["sport_key"]}: status={card.get("status")!r} note={card.get("note")!r}')
    for sport in SPORTS:
        cfg = app.SPORTS_LAUNCH_PAGES.get(sport, {})
        if HONEST not in cfg.get('summary', '') or cfg.get('highlights'):
            fails.append(f'SPORTS_LAUNCH_PAGES[{sport}] not honest: {cfg}')
        pv = app.FREE_SPORT_PREVIEW_CONFIG.get(sport, {})
        if HONEST not in pv.get('summary', '') or pv.get('drivers') or not pv.get('pipeline_unavailable'):
            fails.append(f'FREE_SPORT_PREVIEW_CONFIG[{sport}] not honest: {pv}')
        if app.get_free_sport_locked_features(sport):
            fails.append(f'free locked features still promise CBB tools: {sport}')
        if app.build_free_sport_prop_rows(sport):
            fails.append(f'free preview sample rows for {sport}')
    for snap in app.build_cross_sport_dashboard_snapshots(postseason_only=False):
        if snap.get('key') in SPORTS:
            if (snap.get('props_rows') or snap.get('today_games') or snap.get('best_prop')
                    or snap.get('best_over') or snap.get('best_under') or snap.get('matchups')
                    or snap.get('is_live') or HONEST not in str(snap.get('note'))):
                fails.append(f'dashboard snapshot for {snap.get("key")} not honest: '
                             f'{ {k: snap.get(k) for k in ("status", "note", "props_rows", "best_prop")} }')
    for sport in SPORTS:
        nav = app.build_sport_workflow_nav(sport, 'props', can_see_missed=True, can_see_calibration=True)
        extra = [it['label'] for it in nav if it['label'] not in ALLOWED_TOOLBAR_LABELS]
        if extra:
            fails.append(f'workflow nav for {sport} implies coverage: {extra}')
    return fails


CLAIM_RX = re.compile(r'college hoops|college basketball|\bCBB\b|NCAAB|NCAAMB|NCAAWB', re.I)


def audit_copy(pricing_html: str | None = None) -> list[str]:
    fails: list[str] = []
    for tier in app.PRICING_TIERS:
        for line in [tier.get('summary', '')] + list(tier.get('features', [])):
            if CLAIM_RX.search(str(line)):
                fails.append(f'PRICING_TIERS[{tier.get("key")}] claims college hoops: {line!r}')
    if pricing_html is not None and CLAIM_RX.search(_visible(pricing_html)):
        fails.append(f'/pricing page claims college hoops: {CLAIM_RX.findall(_visible(pricing_html))}')
    src = open(app.__file__, encoding='utf-8').read()
    for needle in ('_college_hoops_example_props', 'college hoops\',', 'Example Guard'):
        if needle in src:
            fails.append(f'app.py still contains {needle!r}')
    return fails


PLANNED_TEXT = 'Data pipeline not yet available'
CBB_CODE_RX = re.compile(r'NCAAMB|NCAAWB|college basketball|college hoops|\bCBB\b', re.I)


def audit_season_markets(html: str, label: str) -> list[str]:
    """Season Markets: NCAAMB/NCAAWB appear ONLY in the separate Planned section, each with the exact
    'Data pipeline not yet available' text, and with no link, count, live badge or launch claim."""
    fails: list[str] = []
    m = re.search(r'<!-- season-planned:start -->(.*?)<!-- season-planned:end -->', html, re.S)
    if not m:
        return [f'{label}: separate Planned section missing']
    planned = m.group(1)
    outside = html.replace(m.group(0), '')
    content = outside.split('<div class="bk-compat-content">', 1)[-1].split('<footer', 1)[0]
    hits = CBB_CODE_RX.findall(content)
    if hits:
        fails.append(f'{label}: college basketball outside the Planned section: {sorted(set(hits))}')
    launch = re.search(r'Leagues at launch</div>(.*?)</div>\s*</div>', content, re.S)
    if launch and CBB_CODE_RX.search(launch.group(1)):
        fails.append(f'{label}: college basketball listed under "Leagues at launch"')
    ptext = _visible(planned)
    for name in ("Men's College Basketball", "Women's College Basketball"):
        if f'{name} — {PLANNED_TEXT}' not in ptext:
            fails.append(f'{label}: Planned entry missing exact text for {name}: {ptext!r}')
    if re.search(r'<a\b|<button\b|<select\b|<option\b', planned, re.I):
        fails.append(f'{label}: Planned section carries an action/link')
    if re.search(r'\d', ptext):
        fails.append(f'{label}: Planned section carries a count/number: {ptext!r}')
    if re.search(r'\b(live|launch\w*|active|coming soon)\b', ptext, re.I) or 'badge' in planned:
        fails.append(f'{label}: Planned section carries a live/launch badge or claim: {ptext!r}')
    return fails


def _season_fixture(tmp) -> None:
    """Synthetic season-market rows incl. NCAAMB/NCAAWB (as an ingest could write them)."""
    import pandas as pd
    from services import season_markets as sm
    d = tmp / 'data' / 'season_markets'
    d.mkdir(parents=True)
    rows = []
    for sport, team in (('NFL', 'QC Team A'), ('NBA', 'QC Team B'), ('NCAAMB', 'QC Hoops M'), ('NCAAWB', 'QC Hoops W')):
        for book, line in (('Book A', 9.5), ('Book B', 10.5)):
            rows.append({'SnapshotAt': '2026-11-01T00:00:00Z', 'Sport': sport, 'Season': '2026', 'EntityType': 'team',
                         'Entity': team, 'Team': team, 'Market': 'Wins', 'Line': line, 'OverOdds': -115,  # synthetic-fixture
                         'UnderOdds': -105,  # synthetic-fixture
                         'Book': book, 'Source': 'qc-fixture', 'SourceUpdatedAt': ''})
    pd.DataFrame(rows, columns=sm.MARKET_COLUMNS).to_csv(d / 'Season_Markets.csv', index=False)


def sweep_season_markets() -> list[str]:
    """Render /tools/season-markets for the awaiting-feed state AND a live state fed by a synthetic
    fixture that includes college-basketball rows; audit both plus the builder context."""
    import tempfile
    from pathlib import Path
    from services import season_markets as sm
    fails: list[str] = []
    real_builder = app.build_season_market_context
    with tempfile.TemporaryDirectory() as td:
        empty, live = Path(td) / 'empty', Path(td) / 'live'
        empty.mkdir()
        _season_fixture(live)
        for label, base in (('season-markets[awaiting feed]', empty), ('season-markets[live fixture]', live)):
            ctx = sm.build_season_market_context(base)
            leaked = [s for s in ctx.get('sports', []) if s in sm.PLANNED_SPORTS]
            leaked += [r['sport'] for r in ctx.get('rows', []) if r.get('sport') in sm.PLANNED_SPORTS]
            if leaked:
                fails.append(f'{label}: context lists/counts planned sports: {sorted(set(leaked))}')
            if base is live and ctx.get('market_rows') != 2:
                fails.append(f'{label}: market_rows={ctx.get("market_rows")} (expected 2: NFL+NBA only)')
            if [p.get('code') for p in ctx.get('planned_sports', [])] != ['NCAAMB', 'NCAAWB']:
                fails.append(f'{label}: planned_sports missing from context')
            app.build_season_market_context = lambda _base, _b=base, **kw: real_builder(_b, **kw)
            try:
                with isolated_owner_client() as c:
                    r = c.get('/tools/season-markets')
                if r.status_code != 200:
                    fails.append(f'{label}: HTTP {r.status_code}')
                    continue
                fails += audit_season_markets(r.get_data(as_text=True), label)
            finally:
                app.build_season_market_context = real_builder
    return fails


def route_inventory() -> list[str]:
    swept = {r.replace('{s}', s) for r in GATED_PAGES for s in SPORTS} | {p.format(s=s) for p in FREE_PAGES for s in SPORTS}
    fails = []
    for rule in app.app.url_map.iter_rules():
        rs = str(rule.rule)
        if re.search(r'ncaa[mw]b|cbb|hoops', rs, re.I) and rs not in swept:
            fails.append(f'unswept CBB route rule: {rs}')
    if not any(str(r.rule) == '/sports/<league>' for r in app.app.url_map.iter_rules()):
        fails.append('catch-all /sports/<league> rule missing')
    return fails


def main() -> int:
    ok(not (inv := route_inventory()), f'1: every CBB url_map rule is swept {inv or ""}')

    page_fails, codes = sweep_pages()
    n_pages = len(codes)
    ok(not page_fails, f'2: {n_pages} CBB page renders (owner + paid member) are 200 and honest'
       + ('' if not page_fails else f' -- {page_fails[:6]}'))

    anon = unauth_client()
    gated = _expand([p for ps in GATED_PAGES.values() for p in ps])
    anon_codes = {p: anon.get(p).status_code for p in gated}
    ok(all(c != 200 for c in anon_codes.values()), f'3: signed-out CBB sections stay gated ({sorted(set(anon_codes.values()))})')
    with isolated_user_client('free') as c:
        free_codes = {p: c.get(p).status_code for p in gated}
    ok(all(v != 200 for v in free_codes.values()), f'3: free-plan CBB sections stay gated ({sorted(set(free_codes.values()))})')

    with isolated_owner_client() as c:
        dash = c.get('/dashboard').get_data(as_text=True)
        hub_pages = {p: c.get(p) for p in ('/tools/props?sport=ncaamb', '/tools/parlay?sport=ncaawb',
                                           '/tools/today?sport=ncaamb', '/tools/matchup-lens?sport=ncaawb')}
        pricing = c.get('/pricing').get_data(as_text=True)
    nav_fails = []
    for sport in SPORTS:
        grp = _sidebar_group(dash, sport)
        if not grp:
            nav_fails.append(f'{sport} sidebar group not found on /dashboard')
        elif 'si-count' in grp or re.search(r'live board|lines', _visible(grp), re.I):
            nav_fails.append(f'{sport} sidebar claims live data: {_visible(grp)!r}')
    ok(not nav_fails, f'4: CBB sidebar groups carry no count and no live-data label {nav_fails or ""}')

    hub_render_fails = [f'{p}: {r.status_code}' for p, r in hub_pages.items()
                        if r.status_code != 200 or HONEST not in _visible(r.get_data(as_text=True))]
    hub_fails = audit_hubs()
    ok(not hub_fails and not hub_render_fails,
       f'5: hubs/snapshots/free preview mark CBB unavailable with the honest note {hub_fails[:4] + hub_render_fails}')

    copy_fails = audit_copy(pricing)
    ok(not copy_fails, f'6: coverage copy no longer claims college hoops {copy_fails or ""}')

    sm_fails = sweep_season_markets()
    ok(not sm_fails, '8: Season Markets lists NCAAMB/NCAAWB only under a separate Planned section '
       f'("{PLANNED_TEXT}"), never counted/launched -- awaiting-feed and live-fixture states {sm_fails[:4] or ""}')

    # 8 mutation proof: each re-introduced Season Markets defect must FAIL.
    from services import season_markets as sm
    saved_gov = sm.GOVERNED_SPORTS
    sm.GOVERNED_SPORTS = sm.SPORTS
    try:
        ok(bool(sweep_season_markets()), '8: mutation [NCAAMB/NCAAWB rows counted/listed as governed] is caught')
    finally:
        sm.GOVERNED_SPORTS = saved_gov
    with isolated_owner_client() as c:
        sm_good = c.get('/tools/season-markets').get_data(as_text=True)
    sm_mutants = {
        '"Leagues at launch" NCAAMB badge': sm_good.replace('<span class="badge">MLB</span>',
                                                             '<span class="badge">MLB</span><span class="badge">NCAAMB</span>', 1),
        'Planned entry with action link': sm_good.replace('<!-- season-planned:end -->',
                                                          '<a href="/sports/ncaamb">Open</a><!-- season-planned:end -->', 1),
        'Planned entry with live badge': sm_good.replace('<!-- season-planned:end -->',
                                                         '<span class="badge">Live</span><!-- season-planned:end -->', 1),
        'Planned entry with count': sm_good.replace(f'{PLANNED_TEXT}</li>', f'{PLANNED_TEXT} (12 markets)</li>', 1),
        'Planned exact text removed': sm_good.replace(PLANNED_TEXT, 'Launching soon'),
    }
    for name, mutated in sm_mutants.items():
        ok(mutated != sm_good and bool(audit_season_markets(mutated, name)), f'8: mutation [{name}] is caught')

    # ---- 7. Mutation proof: each re-introduced defect must make the audit FAIL. ----
    fake_row = ('<table><tr><td>Example Guard</td><td>DUKE</td><td>PTS OVER 17.5</td>'
                '<td>71% confidence</td></tr></table>')
    orig_render = getattr(app, '_render_ncaab_unavailable', None)
    ok(orig_render is not None, '7: honest renderer _render_ncaab_unavailable exists (mutation target)')
    if orig_render is None:
        return _report()

    def mutant_row(sport_key, section_key):
        resp = orig_render(sport_key, section_key)
        if hasattr(resp, 'get_data'):
            resp.set_data(resp.get_data(as_text=True).replace('<!-- ncaab-honest:end -->', fake_row + '<!-- ncaab-honest:end -->'))
            return resp
        return str(resp).replace('<!-- ncaab-honest:end -->', fake_row + '<!-- ncaab-honest:end -->')

    def mutant_no_text(sport_key, section_key):
        resp = orig_render(sport_key, section_key)
        body = resp.get_data(as_text=True) if hasattr(resp, 'get_data') else str(resp)
        body = body.replace(HONEST, 'Live board opens when the season tips off')
        if hasattr(resp, 'set_data'):
            resp.set_data(body)
            return resp
        return body

    for name, mutant in (('fake confidence row on real team', mutant_row), ('honest sentence removed', mutant_no_text)):
        app._render_ncaab_unavailable = mutant
        try:
            mf, _ = sweep_pages()
        finally:
            app._render_ncaab_unavailable = orig_render
        ok(bool(mf), f'7: mutation [{name}] is caught ({len(mf)} failures)')

    with isolated_owner_client() as c:
        good = c.get('/sports/ncaamb/props').get_data(as_text=True)
    live_label = good.replace('<span class="si-name">Data Pipeline Status</span>',
                              '<span class="si-name">Live Board &amp; Lines</span>', 1)
    ok(live_label != good and bool(audit_page('/sports/ncaamb/props', live_label, gated=True)),
       '7: mutation [sidebar "Live Board & Lines"] is caught')
    counted = good.replace('<span class="si-name">Men\'s CBB</span>',
                           '<span class="si-name">Men\'s CBB</span><span class="si-count">0</span>', 1)
    ok(counted != good and bool(audit_page('/sports/ncaamb/props', counted, gated=True)),
       '7: mutation [sidebar CBB count] is caught')
    injected_nav = good.replace('<div class="bk-toolbar bk-command-toolbar bk-workflow-toolbar">',
                                '<div class="bk-toolbar bk-command-toolbar bk-workflow-toolbar"><a class="bk-btn" href="/injuries?sport=NCAAMB">Injuries</a>', 1)
    ok(injected_nav != good and bool(audit_page('/sports/ncaamb/props', injected_nav, gated=True)),
       '7: mutation [CBB toolbar Injuries link] is caught')

    card = next(c for c in app.METHOD_HUB_CONFIG['props']['cards'] if c.get('sport_key') == 'ncaamb')
    saved = dict(card)
    card.update(status='watch', note='Pre-season preview with example plays.')
    try:
        ok(bool(audit_hubs()), '7: mutation [hub card sample note] is caught')
    finally:
        card.clear()
        card.update(saved)

    tier = app.PRICING_TIERS[-1]
    saved_features = list(tier['features'])
    tier['features'] = ['Full prop boards across NBA, MLB, WNBA, NFL, CFB, and college hoops'] + saved_features[1:]
    try:
        ok(bool(audit_copy()), '7: mutation [All Access "college hoops" coverage claim] is caught')
    finally:
        tier['features'] = saved_features
    ok(not audit_copy() and not audit_hubs(), '7: state restored after mutations')
    return _report()


def _report() -> int:
    print('=' * 64)
    print('BANKROLL KINGS NCAAB SHELL HONESTY (safeguard B)')
    print('=' * 64)
    for passed, msg in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")
    n_fail = sum(1 for p, _ in results if not p)
    print(f'\n{len(results) - n_fail}/{len(results)} passed')
    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
