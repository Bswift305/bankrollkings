"""QC: NBA/WNBA market-only board while the NBA.com data-rights gate is OFF (docs/legal_ip_audit.md).

Proves the stats-free Odds-API-only fallback: (1) market rows render while every NBA-stat loader is
gated; (2) no NBA-derived statistic or cached snapshot appears; (3) every quote carries book + capture
time + source; (4) no authority fields/ordering; (5) the market-only record is independent of the
NBA-stats gate (enabling stats later does not change it); (6) NBA and WNBA are tested independently.

Access + containment (2026-11, self-contained -- no user store, no untracked data, no network):
  (7) signed-out requests are refused (401 access gate, no board rows);
  (8) the plan gate is enforced: a synthetic FREE (unpaid) member is refused (403) on both paid boards,
      per get_required_plan_for_endpoint, and a synthetic ALL_ACCESS member (non-owner) is admitted;
  (9) no user-store writes: every file under data/tracking, data/user_prefs and data/live_scores (the
      user store NBA_Users.csv, per-user files, the activity heartbeat) is byte/mtime identical before and
      after, the account writers are tripwired, and the heartbeat path is redirected to a temp dir;
  (10) stale still bites: a > 6h (LIVE_LINES_MAX_AGE_HOURS) NBA lines fixture renders /game-lines as
      STALE / not executable with NO price; a stale NBA AND WNBA props feed puts ZERO rows on the
      market-only BOARD and its rendered page (actual update time shown), through the REAL central loader
      -- v3 fixes v2's contradiction, which tested the loader with require_fresh=True while the board
      called require_fresh=False. Future-dated / timestamp-less feeds and injected loaders are withheld too.
Principals come from services.qc_auth (in-memory one-row store), never a real account.

Uses controlled fixtures (no production data). Exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

os.environ.setdefault("SECRET_KEY", "qc-nba-market-only")  # app import needs one; synthetic QC

import app  # noqa: E402
from services.nba_source_gate import nba_stats_enabled  # noqa: E402
from services.qc_auth import isolated_member_client, isolated_owner_client, unauth_client  # noqa: E402

BOARD_PATHS = (('/sports/nba/props', 'NBA'), ('/sports/wnba/props', 'WNBA'))
# Directories that hold the user store and per-user state; none may change during this QC.
USER_STATE_DIRS = ('tracking', 'user_prefs', 'live_scores')
# The REAL feed loader (run_qc swaps app.load_live_props_feed for a fixture lambda during the body).
_REAL_LOAD_LIVE_PROPS_FEED = app.load_live_props_feed
_REAL_LOAD_WNBA_LIVE_PROPS_FEED = app.load_wnba_live_props_feed

AUTHORITY = ['>Confidence<', '>Tier<', '>Edge<', '>EV<', '>Fair<', '>Model<', 'PropScore', 'Hit Rate',
             'Recommend', 'Best Over', 'Best Under']
APPROVED_HEADERS = ['Matchup', 'Player', 'Prop', 'Line', 'Book', 'Over', 'Under', 'Book Updated']


def qc_source_parser_no_merge():
    """Source-pipeline proof: drive the ACTUAL Odds API parser (fetch_player_props.parse_market_rows)
    with two books quoting the same player at different lines, different Over/Under prices, one missing
    side, and different bookmaker update times. Prove each board row preserves one book + one exact line
    + its own two sides + its own book-update time, with NO cross-book or cross-line merging."""
    import fetch_player_props as fpp
    issues = []
    mk = 'player_points'
    # v3: book update times are RELATIVE (fresh) -- the board now re-verifies the 6h executable rule, so a
    # far-future stamp (formerly 2099) would correctly be withheld as unverifiable.
    now = datetime.now(timezone.utc).replace(microsecond=0)
    z = lambda dt: dt.strftime('%Y-%m-%dT%H:%M:%SZ')  # noqa: E731
    event = {'id': 'evt1', 'home_team': 'Celtics', 'away_team': 'Lakers',
             'commence_time': z(now + timedelta(days=1))}
    book_a = {'key': 'draftkings', 'title': 'DraftKings', 'last_update': z(now - timedelta(minutes=60)),
              'markets': [{'key': mk, 'outcomes': [
                  {'name': 'Over', 'description': 'A. Player', 'point': 24.5, 'price': -110},  # synthetic-fixture
                  {'name': 'Under', 'description': 'A. Player', 'point': 24.5, 'price': -108}]}]}
    book_b = {'key': 'fanduel', 'title': 'FanDuel', 'last_update': z(now - timedelta(minutes=53)),
              'markets': [{'key': mk, 'outcomes': [
                  {'name': 'Over', 'description': 'A. Player', 'point': 25.5, 'price': -120}]}]}  # no Under
    src = fpp.parse_market_rows(event, book_a, [mk]) + fpp.parse_market_rows(event, book_b, [mk])
    feed = pd.DataFrame(src)
    board = app.build_market_only_board(lambda **k: (feed.copy(), {'books': ['DraftKings', 'FanDuel']}))
    rows = board['rows']
    by_book = {r['book']: r for r in rows}
    if len(rows) != 2 or set(by_book) != {'DraftKings', 'FanDuel'}:
        return ['source parser produced wrong per-book rows: ' + str([(r['book'], r['line']) for r in rows])]
    a, b = by_book['DraftKings'], by_book['FanDuel']
    # each row keeps its OWN line + OWN two sides (no cross-book/cross-line merge)
    if a['line'] != 24.5 or a['over_odds'] != -110 or a['under_odds'] != -108:  # synthetic-fixture
        issues.append(f'DraftKings row merged/incorrect: {a}')
    if b['line'] != 25.5 or b['over_odds'] != -120 or b['under_odds'] is not None:
        issues.append(f'FanDuel row merged/incorrect (missing side must stay None): {b}')
    # different bookmaker update times preserved (not collapsed)
    if not a['book_updated_at'] or not b['book_updated_at'] or a['book_updated_at'] == b['book_updated_at']:
        issues.append(f'bookmaker update times not preserved distinctly: {a["book_updated_at"]} / {b["book_updated_at"]}')
    return issues


def _et(dt):
    from services.timeutils import DISPLAY_TZ
    return dt.astimezone(DISPLAY_TZ).strftime('%Y-%m-%d %H:%M')


def _fixture(sport, age_hours=1.0):
    """Two quotes whose freshest LastUpdated (Eastern wall clock, as the fetcher writes it) is age_hours old.
    v3: relative times -- the old fixed 2099 stamps are future-dated, which the central gate now withholds."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    base = {c: '' for c in ['Player', 'Team', 'Stat', 'MarketKey', 'Line', 'Game', 'Book', 'LastUpdated',
                            'OverOdds', 'UnderOdds']}
    r1 = dict(base, Player=f'{sport} PLAYER ONE', Team='LAL', Stat='Points', Line=24.5, Game='LAL @ BOS',
              Book='DraftKings', OverOdds=-110, UnderOdds=-110,  # synthetic-fixture
              LastUpdated=_et(now - timedelta(hours=age_hours, minutes=5)))
    r2 = dict(base, Player=f'{sport} GUARD TWO', Team='MIA', Stat='Assists', Line=6.5, Game='MIA @ NYK',
              Book='FanDuel', OverOdds=-115, UnderOdds='',
              LastUpdated=_et(now - timedelta(hours=age_hours)))  # missing under
    return pd.DataFrame([r1, r2])


def _user_state_snapshot():
    """{relative path: (size, mtime_ns, sha256)} for every file in the user-state dirs (absent dirs -> {})."""
    snap = {}
    for sub in USER_STATE_DIRS:
        root = Path(app.DATA_DIR) / sub
        if not root.exists():
            continue
        for p in sorted(root.rglob('*')):
            if p.is_file():
                st = p.stat()
                snap[str(p.relative_to(app.DATA_DIR))] = (st.st_size, st.st_mtime_ns,
                                                          hashlib.sha256(p.read_bytes()).hexdigest())
    return snap


@contextlib.contextmanager
def _user_write_guard(calls):
    """Tripwire every account writer and redirect the activity heartbeat into a temp dir."""
    names = [n for n in ('save_user', 'update_user_membership', 'record_active_user') if hasattr(app, n)]
    saved = {n: getattr(app, n) for n in names}
    saved_hb = app.ACTIVE_USER_HEARTBEAT_PATH
    tmp = tempfile.TemporaryDirectory(prefix='qc_nba_market_only_')
    try:
        app.ACTIVE_USER_HEARTBEAT_PATH = Path(tmp.name) / 'active_user_heartbeat.txt'
        for n in ('save_user', 'update_user_membership'):
            if n in saved:
                setattr(app, n, lambda *a, _n=n, **k: calls.append(_n))
        yield
    finally:
        for n, fn in saved.items():
            setattr(app, n, fn)
        app.ACTIVE_USER_HEARTBEAT_PATH = saved_hb
        tmp.cleanup()


def _stale_lines_frames(now, lu_age_h):
    """Synthetic NBA lines (legacy layout, upcoming games) whose freshest LastUpdated is lu_age_h old."""
    from services.timeutils import DISPLAY_TZ

    def et(dt):
        return dt.astimezone(DISPLAY_TZ).strftime('%Y-%m-%d %H:%M')
    lu = et(now - timedelta(hours=lu_age_h))
    rows = []
    for gid, away, home, kick in (('q1', 'Boston Celtics', 'New York Knicks', now + timedelta(hours=3)),
                                  ('q2', 'Denver Nuggets', 'Phoenix Suns', now + timedelta(days=1))):
        d, t = et(kick).split(' ')
        rows.append(dict(Date=d, Time=t, Away=away, Home=home, AwayFull=away, HomeFull=home, AwayML=137,
                         HomeML=-163, Spread=-3.5, SpreadOdds=-112, Total=219.5, OverOdds=-108, UnderOdds=-114,
                         Book='DraftKings', GameID=gid, LastUpdated=lu))
    return pd.DataFrame(rows)


def qc_stale_bites(issues, notes):
    """(10) stale lines render the unavailable state with no executable price; stale props are withheld."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    saved = (app.load_game_market_odds, app.load_schedule, app.load_props)
    price_tokens = ('+137', '-163', '219.5')
    try:
        results = {}
        for label, age in (('stale', app.LIVE_LINES_MAX_AGE_HOURS + 4), ('fresh', 1)):
            frame = _stale_lines_frames(now, age)
            app.load_game_market_odds = lambda f=frame: app._format_nba_game_market_odds(f.copy())
            app.load_schedule = lambda f=frame: app._format_schedule(f.copy())
            with isolated_member_client(plan='all_access') as c:
                r = c.get('/game-lines?postseason=0')
            results[label] = (r.status_code, r.get_data(as_text=True))
        st_s, html_s = results['stale']
        st_f, html_f = results['fresh']
        if st_s != 200 or st_f != 200:
            issues.append(f'/game-lines did not render 200 for the paid member (stale={st_s}, fresh={st_f})')
        else:
            n0 = len(issues)
            if not ('data-lines-executable="0"' in html_s and 'data-lines-state="stale"' in html_s
                    and 'Prices are withheld' in html_s and not any(t in html_s for t in price_tokens)):
                issues.append('stale NBA lines fixture: /game-lines did not render STALE / non-executable '
                              'with every price withheld')
            # control: the same fixture, fresh, DOES price -- so the absence above is the stale gate biting
            if not ('data-lines-executable="1"' in html_f and '+137' in html_f):
                issues.append('fresh NBA lines control did not render an executable price (stale proof is vacuous)')
            if len(issues) == n0:
                notes.append(f'stale bites: lines > {app.LIVE_LINES_MAX_AGE_HOURS}h -> /game-lines STALE, '
                             'not executable, no price rendered; fresh control prices normally')
    finally:
        app.load_game_market_odds, app.load_schedule, app.load_props = saved
    qc_stale_props_board(issues, notes)


def qc_stale_props_board(issues, notes):
    """v3 contradiction fix. v2 asserted 'stale props -> require_fresh returns zero rows' by calling the
    LOADER with require_fresh=True, while build_market_only_board called it with require_fresh=False -- so
    the QC passed while the board rendered stale rows. Now the BOARD and the rendered PAGE are tested,
    through the REAL central loaders (only the raw file read is swapped), with the board's own call."""
    saved = (app._load_props_raw, app._load_wnba_props_raw, app.load_live_props_feed, app.load_wnba_live_props_feed)
    stale_h = app.LIVE_LINES_MAX_AGE_HOURS + 4
    try:
        app.load_live_props_feed, app.load_wnba_live_props_feed = _REAL_LOAD_LIVE_PROPS_FEED, _REAL_LOAD_WNBA_LIVE_PROPS_FEED
        for sport, label, raw_name, path in (('nba', 'NBA', '_load_props_raw', '/sports/nba/props'),
                                             ('wnba', 'WNBA', '_load_wnba_props_raw', '/sports/wnba/props')):
            loader = app.load_live_props_feed if sport == 'nba' else app.load_wnba_live_props_feed
            for state, age in (('stale', stale_h), ('fresh', 1.0)):
                fx = _fixture(label, age_hours=age)
                setattr(app, raw_name, lambda f=fx: f.copy())
                board = app.build_market_only_board(loader)   # the board's OWN loader call
                df_default, meta = loader()                   # default arguments (formerly stale-leaking)
                with isolated_member_client(plan='all_access') as c:
                    r = c.get(path)
                h = r.get_data(as_text=True)
                st = board.get('props_status') or {}
                if state == 'stale':
                    ok = (not board['rows'] and df_default.empty and st.get('prices_withheld')
                          and st.get('unavailable_reason') == 'stale' and not st.get('executable')
                          and r.status_code == 200 and f'{label} PLAYER ONE' not in h and '-110' not in h  # synthetic-fixture
                          and 'data-props-executable="0"' in h and 'data-props-state="stale"' in h
                          and str(meta.get('last_updated')) in h and meta.get('last_updated') != 'Unknown')
                    if ok:
                        notes.append(f'{label} stale props (> {app.LIVE_LINES_MAX_AGE_HOURS}h): board 0 rows, loader '
                                     f'default call 0 rows, {path} shows NO quote/price + actual update time '
                                     f'{meta.get("last_updated")} ({meta.get("age_hours")}h, UTC-aware)')
                    else:
                        issues.append(f'{label} stale props leaked or state dishonest: rows={len(board["rows"])} '
                                      f'loader_rows={len(df_default)} status={st} http={r.status_code}')
                else:
                    ok = (len(board['rows']) == 2 and st.get('executable') and r.status_code == 200
                          and f'{label} PLAYER ONE' in h and 'data-props-executable="0"' not in h)
                    if ok:
                        notes.append(f'{label} fresh props control: board renders 2 rows (the stale result above is the gate biting)')
                    else:
                        issues.append(f'{label} fresh props control did not render (stale proof vacuous): {st}')
        # future-dated / no-timestamp feeds are unverifiable -> withheld (never treated as current)
        fx = _fixture('NBA')
        fx['LastUpdated'] = '2099-01-01 12:00'
        app._load_props_raw = lambda f=fx: f.copy()
        b_future = app.build_market_only_board(app.load_live_props_feed)
        fx2 = _fixture('NBA')
        fx2['LastUpdated'] = ''
        app._load_props_raw = lambda f=fx2: f.copy()
        b_none = app.build_market_only_board(app.load_live_props_feed)
        if b_future['rows'] or b_none['rows'] or b_future['props_status'].get('unavailable_reason') != 'future_timestamp' \
                or b_none['props_status'].get('unavailable_reason') != 'no_timestamp':
            issues.append('a future-dated or timestamp-less props feed was not withheld')
        else:
            notes.append('future-dated and timestamp-less props feeds are withheld (unverifiable, never current)')
        # an injected loader that ignores require_fresh cannot smuggle stale rows onto the board
        stale = _fixture('NBA', age_hours=stale_h)
        b_inj = app.build_market_only_board(lambda **k: (stale.copy(), {'books': ['DraftKings']}))
        if b_inj['rows']:
            issues.append('an injected stale-returning loader put rows on the market-only board')
        else:
            notes.append('defense in depth: the board re-verifies the frame an injected loader returns (0 rows)')
    finally:
        app._load_props_raw, app._load_wnba_props_raw, app.load_live_props_feed, app.load_wnba_live_props_feed = saved


def run_qc():
    issues, notes = [], []
    os.environ.pop('BK_NBA_STATS_ENABLED', None)  # gate OFF
    if nba_stats_enabled():
        return {'issues': ['NBA gate is ON; market-only path not exercised'], 'notes': notes}

    before = _user_state_snapshot()
    writer_calls = []
    saved_feeds = (app.load_live_props_feed, app.load_wnba_live_props_feed)
    try:
        with _user_write_guard(writer_calls):
            _run_qc_body(issues, notes)
    finally:
        app.load_live_props_feed, app.load_wnba_live_props_feed = saved_feeds
    after = _user_state_snapshot()
    # (9) no user-store / user-file writes
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if changed or writer_calls:
        issues.append(f'user state changed during the QC: files={changed} writers={writer_calls}')
    else:
        users_csv = 'present' if 'tracking' + os.sep + 'NBA_Users.csv' in before else 'absent'
        notes.append(f'no user-store writes: {len(before)} user-state file(s) byte/mtime identical '
                     f'(NBA_Users.csv {users_csv} before and after); account writers never called')
    if not issues:
        notes.append('market-only board verified: licensed Odds facts only, no NBA.com stats or authority')
    return {'issues': issues, 'notes': notes}


def _run_qc_body(issues, notes):
    nba_fx, wnba_fx = _fixture('NBA'), _fixture('WNBA')
    app.load_live_props_feed = lambda **k: (nba_fx.copy(), {'books': ['DraftKings', 'FanDuel'], 'as_of': 'fixture'})
    app.load_wnba_live_props_feed = lambda **k: (wnba_fx.copy(), {'books': ['DraftKings'], 'as_of': 'fixture'})

    # (1) + (3) + (4) build-level: rows render; each carries book/capture/source; neutral order; approved fields only
    board = app.build_market_only_board(app.load_live_props_feed)
    rows = board['rows']
    if len(rows) != 2:
        issues.append(f'market-only build produced {len(rows)} rows (want 2)')
    for r in rows:
        if not r.get('book') or not r.get('book_updated_at') or r.get('source') != 'Odds API (licensed)':
            issues.append(f'row missing book/book-updated/source lineage: {r.get("player")}')
        extra = set(r.keys()) - {'player', 'game', 'book', 'stat', 'line', 'over_odds', 'under_odds',
                                 'book_updated_at', 'book_updated_tz_known', 'source'}
        if extra:
            issues.append(f'row carries non-approved fields: {extra}')
    # source-pipeline proof: real parser, two books, no cross-book/cross-line merge, distinct book times
    issues += qc_source_parser_no_merge()
    if not any('source parser' in i or 'merged' in i or 'update times' in i for i in issues):
        notes.append('source parser (parse_market_rows): per-book, per-line two-sided quotes preserved; '
                     'missing side kept None; distinct bookmaker update times; no merging')
    # missing side preserved as None (not synthesized)
    g2 = [r for r in rows if 'GUARD TWO' in r['player']]
    if g2 and g2[0]['under_odds'] is not None:
        issues.append('missing Under side was synthesized instead of left None')
    # neutral order: (game, player, stat)
    if [r['game'] for r in rows] != sorted(r['game'] for r in rows):
        issues.append('rows not in neutral (matchup) order')
    notes.append('market-only build: 2 rows, lineage present, missing side preserved, neutral order')

    # (1 render) + (2) + (4 render): gate the stat loaders, render the page, check no stats/authority
    for name in ('load_gamelogs', 'load_player_tracking', 'load_player_advanced', 'load_player_snapshot'):
        df = getattr(app, name)()
        if df is None or not df.empty:
            issues.append(f'{name} not gated empty while market-only active')
    if app.load_runtime_snapshot('nba_props_postseason_today_current') is not None:
        issues.append('an NBA runtime snapshot served while gated (bypass)')

    import re
    # (7) signed-out: refused by the access gate, no board rows leak
    for path, label in BOARD_PATHS:
        r = unauth_client().get(path)
        h = r.get_data(as_text=True)
        if r.status_code != 401 or f'{label} PLAYER ONE' in h:
            issues.append(f'{path} signed-out: expected 401 with no rows, got {r.status_code}')
    # (8) plan gating: both boards require the paid plan; a FREE member is refused (403, upgrade gate)
    for path, _label in BOARD_PATHS:
        endpoint = app.app.url_map.bind('localhost').match(path)[0]
        with app.app.test_request_context(path):  # the resolver reads request.path for sport routes
            required = app.get_required_plan_for_endpoint(endpoint)
        if required != 'all_access':
            issues.append(f'{path} ({endpoint}) required plan is {required!r}, want all_access')
    with isolated_member_client(plan='free') as c:
        for path, label in BOARD_PATHS:
            r = c.get(path)
            h = r.get_data(as_text=True)
            if r.status_code != 403 or f'{label} PLAYER ONE' in h or 'upgrade_required' not in h:
                issues.append(f'{path} free member: expected 403 upgrade gate with no rows, got {r.status_code}')
    n_access = len(issues)
    # (c) + (1 render) + (2) + (4 render) + (6): the paid (non-owner) member AND the owner both get the
    # market-only board; NBA and WNBA are checked independently.
    for who, ctx in (('all_access member', lambda: isolated_member_client(plan='all_access')),
                     ('owner', isolated_owner_client)):
        with ctx() as c:
            for path, label in BOARD_PATHS:
                r = c.get(path)
                h = r.get_data(as_text=True)
                if r.status_code != 200:
                    issues.append(f'{path} returned {r.status_code} for the {who}')
                    continue
                if f'{label} statistical context is temporarily unavailable' not in h:
                    issues.append(f'{path} missing the required market-only label')
                if f'{label} PLAYER ONE' not in h:
                    issues.append(f'{path} did not render the fixture market rows')
                if 'are not recommendations' not in h:
                    issues.append(f'{path} missing the "not recommendations" statement')
                # Board-scoped proof (2 & 4): the ONLY table on this page is the market-only board; its
                # column headers must be EXACTLY the approved market facts -- no stat or authority columns.
                # (The shared shell nav contains unrelated tool names like "Heat Map", not board columns.)
                headers = [m.strip() for m in re.findall(r'<th(?:\s[^>]*)?>(.*?)</th>', h, re.S | re.I)]
                if headers != APPROVED_HEADERS:
                    issues.append(f'{path} table headers are not the approved market-only set: {headers}')
    if len(issues) == n_access:
        notes.append('access: signed-out -> 401, free member -> 403 upgrade gate (required plan all_access), '
                     'no rows leaked to either')
        notes.append('NBA + WNBA market-only pages render rows for the paid member and the owner; table '
                     'columns are exactly the approved market facts (no stat/authority columns), with the '
                     'required label')

    # (5) independence of the market-only record from the NBA-stats gate
    os.environ['BK_NBA_STATS_ENABLED'] = '1'
    board_on = app.build_market_only_board(app.load_live_props_feed)
    os.environ.pop('BK_NBA_STATS_ENABLED', None)
    if board_on['rows'] != rows:
        issues.append('market-only record changed when the stats gate flipped (should be independent)')
    else:
        notes.append('market-only record is identical regardless of the NBA-stats gate state (test 5)')

    # (10) stale still bites
    qc_stale_bites(issues, notes)


def main() -> int:
    report = run_qc()
    print('=' * 60)
    print('BANKROLL KINGS NBA/WNBA MARKET-ONLY BOARD QC')
    print('=' * 60)
    for n in report['notes']:
        print(f'[NOTE] {n}')
    if report['notes']:
        print()
    if not report['issues']:
        print('Market-only board verified.')
        return 0
    for m in report['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
