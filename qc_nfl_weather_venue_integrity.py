"""QC: NFL weather / venue integrity (defect D1, 2026-11-03).

Incident: live NE @ MIA (open-air Hard Rock Stadium, storms + 13-14 mph wind forecast) rendered
"indoor/calm" on /sports/nfl and "dome" on /tools/nfl-totals-today. The venue table was right; the
templates turned MISSING weather into an affirmative condition, and three home-team-only joins could
attach a weeks-old forecast to a different game (and default missing wind to 0 mph).

Contract enforced here (synthetic fixtures; no network, no live data files read or written). Every
assertion prints one [PASS]/[FAIL] line; a final count follows; exit 1 on any failure.
  1. VENUE TABLE   all 32 full team names in NFL_STADIUMS; roof set == an explicit truth table.
  2. UNAVAILABLE   every weather-bearing surface -- rendered /sports/nfl, /sports/ncaaf,
                   /tools/nfl-totals-today, /tools/nfl-matchup-center, /tools/nfl-board (Top board),
                   /tools/nfl-game-board (Game board), plus their builder rows -- with missing weather says
                   only "Weather unavailable" / "No forecast available"; never indoor / calm / dome / 0 mph /
                   no wind; unknown wind is None (never 0) with no WIND tier / flag / tag.
  3. NO VENUE GUESS missing weather never implies indoor or dome: an open-air home keeps roof='outdoor'.
  4. ROOF SEPARATE  a known roof (dome DET, open-air MIA) stays its own field (roof / roof_label) next to
                   the weather fields, with or without a forecast.
  5. KNOWN VALID   a licensed, dated, matching forecast (17 mph) renders its real value on every surface.
  6. DATE + HOME   forecasts for the same home on another date, for a different home on the same date, or
                   for the AWAY team's stadium never attach to the game.
  7. GATE ON READ  BK_WEATHER_SOURCE_LICENSED off => no surface shows a stored wind even when the CSV has a
                   matching row; on => it does. Same for CFB weather (_cfb_weather + CFB Top board).
  8. MUTATION      restoring the pre-D1 template text, a home-only join, or an always-on licence makes the
                   corresponding assertions fail (proves the QC has teeth).
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import pandas as pd

os.environ.setdefault('SECRET_KEY', 'qc-nfl-weather-venue-integrity')  # app import needs one; synthetic QC

import app  # noqa: E402
import cfb_current_form  # noqa: E402
import nfl_totals  # noqa: E402
from services.nfl_stadiums import NFL_STADIUMS  # noqa: E402

UNAVAILABLE = 'Weather unavailable'
MC_UNAVAILABLE = 'No forecast available'

# Explicit roof truth table (owner-verified 2026-11-03). 'dome' = fixed roof (SoFi: fixed canopy).
ROOF_TRUTH = {
    'Arizona Cardinals': 'retractable', 'Atlanta Falcons': 'retractable', 'Dallas Cowboys': 'retractable',
    'Houston Texans': 'retractable', 'Indianapolis Colts': 'retractable',
    'Detroit Lions': 'dome', 'Las Vegas Raiders': 'dome', 'Minnesota Vikings': 'dome',
    'New Orleans Saints': 'dome', 'Los Angeles Rams': 'dome', 'Los Angeles Chargers': 'dome',
    'Baltimore Ravens': 'outdoor', 'Buffalo Bills': 'outdoor', 'Carolina Panthers': 'outdoor',
    'Chicago Bears': 'outdoor', 'Cincinnati Bengals': 'outdoor', 'Cleveland Browns': 'outdoor',
    'Denver Broncos': 'outdoor', 'Green Bay Packers': 'outdoor', 'Jacksonville Jaguars': 'outdoor',
    'Kansas City Chiefs': 'outdoor', 'Miami Dolphins': 'outdoor', 'New England Patriots': 'outdoor',
    'New York Giants': 'outdoor', 'New York Jets': 'outdoor', 'Philadelphia Eagles': 'outdoor',
    'Pittsburgh Steelers': 'outdoor', 'San Francisco 49ers': 'outdoor', 'Seattle Seahawks': 'outdoor',
    'Tampa Bay Buccaneers': 'outdoor', 'Tennessee Titans': 'outdoor', 'Washington Commanders': 'outdoor',
}

# Affirmative conditions that missing weather must never produce.
FORBIDDEN_OUTDOOR = re.compile(
    r'indoor|\bcalm\b|\bdome\b|\b0\s*mph\b|\bzero[ -]wind\b|\bno wind\b|\bclosed\b', re.I)
FORBIDDEN_DOME = re.compile(r'\bcalm\b|\b0\s*mph\b|\bzero[ -]wind\b|\bno wind\b|\bclosed\b', re.I)
# A weather LABEL (not the roof field) must never assert a venue condition.
VENUE_WORDS = re.compile(r'indoor|\bdome\b|\broof\b|\bclosed\b|\bcalm\b', re.I)

TODAY = app.sports_today_date()
D_GAME = (TODAY + timedelta(days=2)).isoformat()       # the game (D2)
D_OLD = (TODAY - timedelta(days=12)).isoformat()       # a weeks-old forecast row (D1)
D_NEXT = (TODAY + timedelta(days=9)).isoformat()       # the same home team's NEXT game
NFL_SCORES = {'games': []}
AWAY, HOME = 'New England Patriots', 'Miami Dolphins'   # the incident game (open-air home)


def _game(away, home, date, total=44.5, spread=-3.0):
    return {'away': away, 'home': home, 'matchup': f'{away} @ {home}', 'date': date, 'time': '1:00 PM',
            'spread': spread, 'total': total, 'away_ml': None, 'home_ml': None, 'book': 'DraftKings',
            'slug': f'{away}@{home}', 'summary': ''}


def _wx_row(date, home, wind, gust=None):
    return {'Date': date, 'HomeTeam': home, 'WindMph': wind, 'GustMph': gust, 'PrecipMm': 0, 'TempF': 70,
            'Roof': NFL_STADIUMS.get(home, (None, None, ''))[2], 'Updated': f'{TODAY.isoformat()} 06:00'}


class Recorder:
    """One line per assertion; `echo=False` collects silently (used by the mutation runs)."""

    def __init__(self, echo=True):
        self.echo = echo
        self.results = []

    def check(self, name, ok, detail=''):
        ok = bool(ok)
        self.results.append((name, ok, detail))
        if self.echo:
            print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ('' if ok or not detail else f"  -- {detail}"))
        return ok

    @property
    def failed(self):
        return [r for r in self.results if not r[1]]


class Fixture:
    """Installs synthetic loaders on `app` (restored by `restore`). No file under the repo is written:
    the weather CSV and scores JSON live in a temp dir; disk caches are bypassed."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.saved = {}
        self.nfl_games, self.cfb_games = [], []
        self.weather_csv = tmp / 'NFL_GameWeather.csv'
        self.scores = tmp / 'nfl_scores.json'
        self.scores.write_text(json.dumps(NFL_SCORES), encoding='utf-8')
        self.set_weather([])

    def set_weather(self, rows):
        pd.DataFrame(rows, columns=['Date', 'HomeTeam', 'WindMph', 'GustMph', 'PrecipMm', 'TempF', 'Roof',
                                    'Updated']).to_csv(self.weather_csv, index=False)
        # bump mtime so mtime-keyed caches (DATAFRAME_CACHE, board sigs) see the change
        st = os.stat(self.weather_csv)
        bump = getattr(self, '_bump', 0) + 1
        self._bump = bump
        os.utime(self.weather_csv, (st.st_atime + bump, st.st_mtime + bump))
        self.clear_caches()

    def clear_caches(self):
        for name in ('_NFL_BOARD_CACHE', '_NFL_GAME_BOARD_CACHE', '_NFL_MATCHUP_CENTER_CACHE'):
            getattr(app, name).clear()

    def _patch(self, obj, name, value):
        self.saved.setdefault((obj, name), getattr(obj, name))
        setattr(obj, name, value)

    def install(self):
        nfl_odds = pd.DataFrame()
        nfl_odds.attrs['qc_sport'] = 'nfl'
        cfb_odds = pd.DataFrame()
        cfb_odds.attrs['qc_sport'] = 'ncaaf'

        def live_games(odds_df, schedule_df, date_filter='all', day_filter=''):
            sport = getattr(odds_df, 'attrs', {}).get('qc_sport', 'nfl')
            return [dict(g) for g in (self.cfb_games if sport == 'ncaaf' else self.nfl_games)]

        p = self._patch
        p(app, 'load_nfl_game_market_odds', lambda *a, **k: nfl_odds)
        p(app, 'load_ncaaf_game_market_odds', lambda *a, **k: cfb_odds)
        p(app, 'build_football_live_games', live_games)
        p(app, 'get_lines_refresh_meta', lambda *a, **k: {'is_stale': False})
        p(app, '_nfl_weather_path', lambda: self.weather_csv)
        p(app, '_nfl_scenario_path', lambda name: str(self.scores) if name == 'nfl_scores.json'
          else self.saved[(app, '_nfl_scenario_path')](name))
        p(app, '_nfl_disk_cache_load', lambda *a, **k: None)
        p(app, '_nfl_disk_cache_store', lambda *a, **k: None)
        p(app, '_get_disk_ttl_cached_value', lambda cache_key, ttl_seconds, builder, version=None: builder())
        # in-season: the dashboard slate (and its weather column) renders only when live props exist
        real_status = app.build_football_live_status
        p(app, 'build_football_live_status', lambda *a, **k: {**(real_status(*a, **k) or {}), 'has_live_props': True})
        p(app, 'get_current_user', lambda: {'user_id': 'qc', 'email': 'qc@bk.test', 'plan': 'all_access'})
        p(app, 'is_owner_user', lambda u=None: True)
        # totals model: every game leans UNDER so the wind tier/tag path is exercised
        p(nfl_totals, 'clear_cache', lambda: None)
        p(nfl_totals, '_ratings', lambda: ({}, {}, 22.0))
        p(nfl_totals, 'total_read', lambda a, h, line=None: {
            'proj_total': 38.0, 'edge': -6.5, 'lean': 'UNDER', 'away_qb_out': None, 'home_qb_out': None})
        p(nfl_totals, 'projected_margin', lambda a, h: None)

    def restore(self):
        for (obj, name), value in self.saved.items():
            setattr(obj, name, value)
        self.saved.clear()


def _set_gate(on: bool):
    app.BK_WEATHER_SOURCE_LICENSED = bool(on)


def _gate_tag():
    return f"gate {'ON' if app.BK_WEATHER_SOURCE_LICENSED else 'OFF'}"


# ---------------------------------------------------------------------------------------------
# surface extraction: only the weather-bearing region of each page is inspected (page chrome has
# unrelated words, e.g. a "calm, readable crawl" comment in bk_base.html).
# ---------------------------------------------------------------------------------------------
def _strip(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.replace('&mdash;', '-'))).strip()


def _region_dashboard(html):
    m = re.search(r'<table class="bk-slate">(.*?)</table>', html, re.S)
    return m.group(1) if m else None


def _region_totals(html):
    m = re.search(r'<tbody>(.*?)</tbody>', html, re.S)
    return m.group(1) if m else None


def _region_mc(html):
    m = re.search(r'<div class="mc-label">Weather(.*?)<div class="mc-label">', html, re.S)
    return m.group(1) if m else None


def _region_board(html):
    subs = re.findall(r'<div class="nb-sub">(.*?)</div>', html, re.S)
    return ' | '.join(subs) if subs else None


# label -> (url, region extractor, unavailable wording, rendered value for the 17 mph positive control)
SURFACES = {
    'nfl_dashboard (/sports/nfl)': ('/sports/nfl?qc=1', _region_dashboard, UNAVAILABLE, '17 mph'),
    'ncaaf dashboard (/sports/ncaaf)': ('/sports/ncaaf', _region_dashboard, UNAVAILABLE, None),
    'totals-today (/tools/nfl-totals-today)': ('/tools/nfl-totals-today', _region_totals, UNAVAILABLE, '17'),
    'matchup center (/tools/nfl-matchup-center)': ('/tools/nfl-matchup-center', _region_mc, MC_UNAVAILABLE, '17 mph'),
    'NFL Top board (/tools/nfl-board)': ('/tools/nfl-board', _region_board, UNAVAILABLE, 'wind 17'),
    'NFL Game board (/tools/nfl-game-board)': ('/tools/nfl-game-board', _region_board, UNAVAILABLE, 'wind 17'),
}
NFL_SURFACES = [label for label in SURFACES if not label.startswith('ncaaf')]


def render_regions(client, fx=None):
    out = {}
    for label, (url, region, _, _) in SURFACES.items():
        if fx is not None:
            fx.clear_caches()
        r = client.get(url)
        html = r.get_data(as_text=True)
        out[label] = (r.status_code, region(html) if r.status_code == 200 else None)
    return out


def _total_rows(builder, fx):
    fx.clear_caches()
    return [c for c in builder().get('board', []) if c.get('market') == 'Total']


BOARD_BUILDERS = (('NFL Top board', 'build_nfl_board_context'), ('NFL Game board', 'build_nfl_game_board_context'))
WIND_TIERS = ('Validated', 'Backtest ~55% (not yet governed)')


# ---------------------------------------------------------------------------------------------
# 1. venue table
# ---------------------------------------------------------------------------------------------
def check_venue_table(R):
    missing = sorted(set(ROOF_TRUTH) - set(NFL_STADIUMS))
    extra = sorted(set(NFL_STADIUMS) - set(ROOF_TRUTH))
    R.check('venue table: exactly the 32 NFL teams', len(ROOF_TRUTH) == 32 and not missing and not extra,
            f'missing={missing} extra={extra}')
    for team, roof in ROOF_TRUTH.items():
        info = NFL_STADIUMS.get(team)
        R.check(f'venue table: {team} roof={roof!r}, wind_exposed consistent',
                bool(info) and info[2] == roof and info[3] == (roof == 'outdoor'),
                f'got {info[2:4] if info else None}')


# ---------------------------------------------------------------------------------------------
# 2-4. missing weather (rendered + builder rows), under the current gate state
# ---------------------------------------------------------------------------------------------
def check_missing(client, fx, R, home_kind, away, home):
    """Missing weather for one game: unavailable wording, no affirmative condition, roof separate."""
    tag = f'[{_gate_tag()}][missing wx, {home_kind} {home}]'
    forbidden = FORBIDDEN_OUTDOOR if home_kind == 'outdoor' else FORBIDDEN_DOME
    fx.nfl_games = [_game(away, home, D_GAME)]
    fx.cfb_games = [_game('Georgia Tech', 'Miami', D_GAME)]   # open-air college venue, no wind source
    fx.set_weather([])
    for label, (status, region) in render_regions(client, fx).items():
        if label.startswith('ncaaf') and home_kind != 'outdoor':
            continue  # the CFB fixture is the same either way; checked once on the outdoor pass
        want = SURFACES[label][2]
        if not R.check(f'{tag} {label}: HTTP 200, weather region rendered', status == 200 and region is not None,
                       f'HTTP {status}'):
            continue
        text = _strip(region)
        hit = forbidden.search(text)
        R.check(f'{tag} {label}: no affirmative condition (indoor/calm/dome/0 mph/no wind)', not hit,
                f'{hit.group(0) if hit else ""!r} in {text[:140]!r}')
        R.check(f'{tag} {label}: says {want!r}', want in text, text[:140])
        R.check(f'{tag} {label}: no wind value shown', 'mph' not in text.lower() and not re.search(r'\bwind \d', text),
                text[:140])
        if label.startswith('matchup'):
            roof_label = app.NFL_ROOF_LABELS[ROOF_TRUTH[home]]
            R.check(f'{tag} {label}: known roof shown as its own field ({roof_label!r})', roof_label in text, text[:160])
    # builder rows
    for label, name in BOARD_BUILDERS:
        rows = _total_rows(getattr(app, name), fx)
        if not R.check(f'{tag} {label} builder: produced a Total candidate', bool(rows)):
            continue
        c = rows[0]
        R.check(f'{tag} {label} builder: wind is None (never 0)', c.get('wind') is None, f"wind={c.get('wind')!r}")
        why = c.get('why', '')
        hit = forbidden.search(why)
        R.check(f'{tag} {label} builder: why says {UNAVAILABLE!r}, nothing affirmative', UNAVAILABLE in why and not hit, why)
        R.check(f'{tag} {label} builder: no WIND flag / wind tier',
                c.get('flag') != 'WIND' and c.get('tier') not in WIND_TIERS and 'wind' not in str(c.get('tier', '')).lower(),
                f"tier={c.get('tier')!r} flag={c.get('flag')!r}")
        R.check(f'{tag} {label} builder: roof is a separate field == {ROOF_TRUTH[home]!r}',
                c.get('roof') == ROOF_TRUTH[home] and VENUE_WORDS.search(str(c.get('weather_label'))) is None,
                f"roof={c.get('roof')!r} weather_label={c.get('weather_label')!r}")
    slate = app.build_football_home_slate('nfl')
    tot = app.build_nfl_totals_board_context('week')['nt_rows']
    fx.clear_caches()
    mc = app.build_nfl_matchup_center_context()['games']
    for label, rows, wind_key in (('home slate (nfl)', slate, 'wind'), ('totals board', tot, 'wind')):
        if not R.check(f'{tag} {label} rows: present', bool(rows)):
            continue
        r = rows[0]
        R.check(f'{tag} {label} rows: wind None (never 0), no high-wind flag',
                r.get(wind_key) is None and not r.get('high_wind') and r.get('read') != 'wind_under',
                f"wind={r.get(wind_key)!r} high_wind={r.get('high_wind')!r} read={r.get('read')!r}")
        R.check(f'{tag} {label} rows: weather_label == {UNAVAILABLE!r}', r.get('weather_label') == UNAVAILABLE,
                repr(r.get('weather_label')))
        R.check(f'{tag} {label} rows: roof stays the venue fact {ROOF_TRUTH[home]!r} (not inferred from weather)',
                r.get('roof') == ROOF_TRUTH[home], repr(r.get('roof')))
    if R.check(f'{tag} matchup center rows: present', bool(mc)):
        w = mc[0]['weather']
        R.check(f'{tag} matchup center rows: unavailable, wind_mph None, no high wind',
                not w.get('available') and w.get('wind_mph') is None and not w.get('high_wind'),
                f"available={w.get('available')} wind_mph={w.get('wind_mph')!r}")
        R.check(f'{tag} matchup center rows: roof separate == {ROOF_TRUTH[home]!r}; note not a venue claim',
                w.get('roof') == ROOF_TRUTH[home] and VENUE_WORDS.search(str(w.get('note'))) is None,
                f"roof={w.get('roof')!r} note={w.get('note')!r}")
    pm = [r for r in app.build_football_preseason_markets('nfl').get('game_totals', []) if r.get('home') == home]
    if R.check(f'{tag} preseason markets rows: present', bool(pm)):
        R.check(f'{tag} preseason markets rows: no wind_mph (never 0), no high_wind',
                not pm[0].get('wind_mph') and pm[0].get('wind_mph') != 0 and not pm[0].get('high_wind'),
                f"wind_mph={pm[0].get('wind_mph')!r}")
    if home_kind == 'outdoor':
        for r in app.build_football_home_slate('ncaaf'):
            R.check(f'{tag} home slate (ncaaf) rows: wind None, label unavailable, no NFL roof applied',
                    r.get('wind') is None and r.get('weather_label') == UNAVAILABLE and r.get('roof') is None,
                    f"wind={r.get('wind')!r} label={r.get('weather_label')!r} roof={r.get('roof')!r}")


# ---------------------------------------------------------------------------------------------
# 5. known valid weather, 6. date + home join, 7. licence gate on read
# ---------------------------------------------------------------------------------------------
def check_known_valid(client, fx, R):
    """Gate ON, a licensed, dated, matching forecast (17 mph, gust 26) for NE @ MIA."""
    tag = '[gate ON][valid 17 mph forecast, MIA]'
    _set_gate(True)
    fx.nfl_games = [_game(AWAY, HOME, D_GAME)]
    fx.cfb_games = [_game('Georgia Tech', 'Miami', D_GAME)]
    fx.set_weather([_wx_row(D_GAME, HOME, 17.0, 26.0)])
    for label, (status, region) in render_regions(client, fx).items():
        text = _strip(region or '')
        want = SURFACES[label][3]
        if want is None:  # CFB never borrows an NFL stadium forecast
            R.check(f'{tag} {label}: still {UNAVAILABLE!r} (no NFL forecast leaks to CFB)',
                    status == 200 and UNAVAILABLE in text and 'mph' not in text.lower(), text[:140])
            continue
        R.check(f'{tag} {label}: renders the real wind {want!r}', status == 200 and want in text, text[:160])
        R.check(f'{tag} {label}: no unavailable wording when a forecast exists',
                SURFACES[label][2] not in text, text[:160])
        if label.startswith('matchup'):
            R.check(f'{tag} {label}: roof shown separately as {"Open-air"!r}', 'Open-air' in text, text[:160])
    for label, name in BOARD_BUILDERS:
        rows = _total_rows(getattr(app, name), fx)
        c = rows[0] if rows else {}
        want_tier = 'Validated' if 'Game' in label else 'Backtest ~55% (not yet governed)'
        R.check(f'{tag} {label} builder: wind == 17, why "wind 17", tier {want_tier!r}',
                c.get('wind') == 17 and 'wind 17' in c.get('why', '') and c.get('tier') == want_tier,
                f"wind={c.get('wind')!r} why={c.get('why')!r} tier={c.get('tier')!r}")
        R.check(f'{tag} {label} builder: roof separate == outdoor', c.get('roof') == 'outdoor', repr(c.get('roof')))
    gb = _total_rows(app.build_nfl_game_board_context, fx)
    R.check(f'{tag} NFL Game board builder: WIND flag on the under', bool(gb) and gb[0].get('flag') == 'WIND',
            repr(gb[0].get('flag') if gb else None))
    s = (app.build_football_home_slate('nfl') or [{}])[0]
    R.check(f'{tag} home slate (nfl) row: wind 17, available, label "17 mph wind", high_wind, roof outdoor',
            s.get('wind') == 17 and s.get('weather_available') and s.get('weather_label') == '17 mph wind'
            and s.get('high_wind') and s.get('roof') == 'outdoor', repr({k: s.get(k) for k in
                                                                         ('wind', 'weather_label', 'roof')}))
    t = (app.build_nfl_totals_board_context('week')['nt_rows'] or [{}])[0]
    R.check(f'{tag} totals board row: wind 17, high_wind, read wind_under, roof outdoor',
            t.get('wind') == 17 and t.get('high_wind') and t.get('read') == 'wind_under' and t.get('roof') == 'outdoor',
            repr({k: t.get(k) for k in ('wind', 'high_wind', 'read', 'roof')}))
    fx.clear_caches()
    m = (app.build_nfl_matchup_center_context()['games'] or [{'weather': {}}])[0]['weather']
    R.check(f'{tag} matchup center row: available, wind_mph 17, high_wind, dated as_of, roof outdoor',
            m.get('available') and m.get('wind_mph') == 17 and m.get('high_wind') and m.get('as_of')
            and m.get('roof') == 'outdoor', repr(m))
    pm = [r for r in app.build_football_preseason_markets('nfl').get('game_totals', []) if r.get('home') == HOME]
    R.check(f'{tag} preseason markets row: wind_mph 17, high_wind',
            bool(pm) and pm[0].get('wind_mph') == 17 and pm[0].get('high_wind'), repr(pm[:1]))


def check_date_join(client, fx, R):
    """Gate ON. Four forecasts that are NOT this game's: same home on another date (past + next game), a
    different home on the same date, and the AWAY team's stadium on the same date. None may attach."""
    tag = '[gate ON][date+home join]'
    _set_gate(True)
    fx.nfl_games = [_game(AWAY, HOME, D_GAME)]
    fx.set_weather([_wx_row(D_OLD, HOME, 23.0), _wx_row(D_NEXT, HOME, 24.0),
                    _wx_row(D_GAME, 'Buffalo Bills', 25.0), _wx_row(D_GAME, AWAY, 26.0)])
    decoys = re.compile(r'\b2[3-6]\b')
    for label, (status, region) in render_regions(client, fx).items():
        if label.startswith('ncaaf'):
            continue
        text = _strip(region or '')
        R.check(f'{tag} {label}: no other-date / other-home forecast (23/24/25/26 mph) attached',
                status == 200 and not decoys.search(text) and SURFACES[label][2] in text, text[:160])
    for label, name in BOARD_BUILDERS:
        rows = _total_rows(getattr(app, name), fx)
        R.check(f'{tag} {label} builder: wind None, no WIND flag',
                bool(rows) and all(c.get('wind') is None and c.get('flag') != 'WIND' for c in rows),
                repr([(c.get('wind'), c.get('flag')) for c in rows]))
    R.check(f'{tag} home slate (nfl): wind None',
            all(r.get('wind') is None for r in app.build_football_home_slate('nfl')))
    R.check(f'{tag} totals board: wind None',
            all(r.get('wind') is None for r in app.build_nfl_totals_board_context('week')['nt_rows']))
    fx.clear_caches()
    R.check(f'{tag} matchup center: unavailable',
            all(not g['weather'].get('available') for g in app.build_nfl_matchup_center_context()['games']))
    R.check(f'{tag} preseason markets: no wind_mph',
            all(not r.get('wind_mph') for r in app.build_football_preseason_markets('nfl').get('game_totals', [])))
    wm = app._nfl_game_wind_map()
    R.check(f'{tag} nfl_game_wind: (date, home) lookup exact -- other date None, this date/home only',
            app.nfl_game_wind(wm, D_GAME, HOME) is None and app.nfl_game_wind(wm, D_OLD, HOME) is not None
            and app.nfl_game_wind(wm, D_GAME, 'Buffalo Bills') is not None, repr(sorted(wm)))


def check_gate_off(client, fx, R):
    """Gate OFF with a matching, valid row on disk: nothing is shown anywhere."""
    tag = '[gate OFF][matching 17 mph row on disk]'
    _set_gate(False)
    fx.nfl_games = [_game(AWAY, HOME, D_GAME)]
    fx.set_weather([_wx_row(D_GAME, HOME, 17.0, 26.0)])
    for label, (status, region) in render_regions(client, fx).items():
        if label.startswith('ncaaf'):
            continue
        text = _strip(region or '')
        R.check(f'{tag} {label}: stored wind withheld, says {SURFACES[label][2]!r}',
                status == 200 and '17' not in text and 'mph' not in text.lower() and SURFACES[label][2] in text,
                text[:160])
    for label, name in BOARD_BUILDERS:
        rows = _total_rows(getattr(app, name), fx)
        R.check(f'{tag} {label} builder: wind None, no WIND flag, no "wind 17"',
                bool(rows) and all(c.get('wind') is None and c.get('flag') != 'WIND' and 'wind 17' not in c.get('why', '')
                                   for c in rows), repr([(c.get('wind'), c.get('why')) for c in rows]))
    R.check(f'{tag} home slate + totals rows: wind None',
            all(r.get('wind') is None for r in app.build_football_home_slate('nfl')
                + app.build_nfl_totals_board_context('week')['nt_rows']))
    fx.clear_caches()
    R.check(f'{tag} matchup center: unavailable',
            all(not g['weather'].get('available') for g in app.build_nfl_matchup_center_context()['games']))
    R.check(f'{tag} preseason markets: no wind_mph',
            all(not r.get('wind_mph') for r in app.build_football_preseason_markets('nfl').get('game_totals', [])))
    R.check(f'{tag} _nfl_game_wind_map() is empty', app._nfl_game_wind_map() == {})


def check_cfb_weather_gate(client, fx, R):
    """CFB weather (cfb_weather.json, Open-Meteo-derived) is gated on read: _cfb_weather and the CFB Top
    board (/tools/cfb-board) show the 18 mph wind only while the licence is on."""
    tmp = fx.tmp
    (tmp / 'cfb_weather.json').write_text(json.dumps({'wind_flag_mph': 15, 'games': [
        {'home': 'Miami', 'away': 'Georgia Tech', 'wind': 18, 'precip': 0.0, 'temp': 75, 'dome': False}]}),
        encoding='utf-8')
    (tmp / 'cfb_line_moves.json').write_text(json.dumps({'games': [
        {'home': 'Miami', 'away': 'Georgia Tech', 'week': 11, 'completed': False, 'spread_now': -7.0,
         'spread_open': -7.0, 'total_now': 52.5}]}), encoding='utf-8')
    real_read = app.bk_runtime.scenario_read_path
    redirect = {'cfb_weather.json', 'cfb_line_moves.json'}
    fx._patch(app.bk_runtime, 'scenario_read_path',
              lambda name: (tmp / name) if name in redirect else real_read(name))
    fx._patch(cfb_current_form, 'clear_cache', lambda: None)
    fx._patch(cfb_current_form, '_fbs_teams', lambda: frozenset({'Miami', 'Georgia Tech'}))
    fx._patch(cfb_current_form, '_resolve', lambda team: team)
    fx._patch(cfb_current_form, 'matchup_read', lambda a, h, sp=None: {'proj_home_margin': None})
    fx._patch(cfb_current_form, 'total_read', lambda a, h, line=None: {
        'lean': 'UNDER', 'edge': -4.0, 'proj_total': 48.5})
    for gate in (False, True):
        _set_gate(gate)
        tag = f'[{_gate_tag()}][CFB weather, 18 mph on disk]'
        app._CFB_WX_CACHE.clear()
        app._CFB_BOARD_CACHE.clear()
        wx = app._cfb_weather('Georgia Tech', 'Miami')
        rows = [c for c in app.build_cfb_board_context().get('board', []) if c.get('market') == 'Total']
        app._CFB_BOARD_CACHE.clear()
        resp = client.get('/tools/cfb-board')
        text = _strip(_region_board(resp.get_data(as_text=True)) or '') if resp.status_code == 200 else ''
        if gate:
            R.check(f'{tag} _cfb_weather: returns the licensed 18 mph wind', bool(wx) and wx.get('wind') == 18, repr(wx))
            R.check(f'{tag} CFB Top board builder: "wind 18" + WIND flag',
                    bool(rows) and 'wind 18' in rows[0].get('why', '') and rows[0].get('flag') == 'WIND', repr(rows[:1]))
            R.check(f'{tag} /tools/cfb-board: renders "wind 18"', 'wind 18' in text, text[:160])
        else:
            R.check(f'{tag} _cfb_weather: withheld (None)', wx is None, repr(wx))
            R.check(f'{tag} CFB Top board builder: no wind in why, no WIND flag',
                    bool(rows) and 'wind' not in rows[0].get('why', '') and rows[0].get('flag') != 'WIND', repr(rows[:1]))
            R.check(f'{tag} /tools/cfb-board: no wind rendered', resp.status_code == 200 and 'wind' not in text.lower()
                    and 'Georgia Tech' in _strip(resp.get_data(as_text=True)), text[:160])
    app._CFB_WX_CACHE.clear()
    app._CFB_BOARD_CACHE.clear()


# ---------------------------------------------------------------------------------------------
# 8. mutations (the QC must fail when the D1 behaviour is reverted)
# ---------------------------------------------------------------------------------------------
def check_mutation_templates(client, fx, R):
    """Restore the pre-D1 `else` text in both templates (in memory only) and prove this QC catches it."""
    import jinja2
    env = app.app.jinja_env
    mutated = {}
    for name, new, old in (
            ('nfl_dashboard.html', '<span class="dim">Weather unavailable</span>',
             '<span class="dim">&mdash; indoor/calm</span>'),
            ('nfl_totals_today.html', '<span class="nt-wind-c">Weather unavailable</span>',
             '<span class="nt-wind-c">dome</span>')):
        src = env.loader.get_source(env, name)[0]
        if not R.check(f'mutation setup: fixed text present in {name}', new in src):
            return
        mutated[name] = src.replace(new, old)
    orig_loader = env.loader
    env.loader = jinja2.ChoiceLoader([jinja2.DictLoader(mutated), orig_loader])
    env.cache.clear() if env.cache is not None else None
    M = Recorder(echo=False)
    try:
        _set_gate(False)
        check_missing(client, fx, M, 'outdoor', AWAY, HOME)
    finally:
        env.loader = orig_loader
        env.cache.clear() if env.cache is not None else None
    R.check("mutation: pre-D1 dashboard '&mdash; indoor/calm' text is caught",
            any('nfl_dashboard' in n and 'affirmative' in n for n, _, _ in M.failed))
    R.check("mutation: pre-D1 totals-today 'dome' text is caught",
            any('totals-today' in n and 'affirmative' in n for n, _, _ in M.failed))


def check_mutation_home_only_join(client, fx, R):
    """Swap the (date, home) join for the old home-only join: the date-join assertions must fail."""
    real = app.nfl_game_wind
    app.nfl_game_wind = lambda wm, date, home: next(
        (v for (d, h), v in (wm or {}).items() if h == str(home or '').strip().lower()), None)
    M = Recorder(echo=False)
    try:
        check_date_join(client, fx, M)
    finally:
        app.nfl_game_wind = real
        fx.clear_caches()
    R.check('mutation: a home-only forecast join is caught by the date+home assertions',
            len([n for n, _, _ in M.failed if 'date+home' in n]) >= 3, f'{len(M.failed)} failed')


def check_mutation_gate_ignored(client, fx, R):
    """Make the licence gate always-on: the gate-off assertions must fail."""
    real = app._nfl_weather_licensed
    app._nfl_weather_licensed = lambda: True
    M = Recorder(echo=False)
    try:
        check_gate_off(client, fx, M)
    finally:
        app._nfl_weather_licensed = real
        fx.clear_caches()
    R.check('mutation: ignoring the licence gate is caught by the gate-off assertions',
            len([n for n, _, _ in M.failed if 'gate OFF' in n]) >= 3, f'{len(M.failed)} failed')


def run_qc(R=None):
    R = R or Recorder()
    check_venue_table(R)
    gate_before = app.BK_WEATHER_SOURCE_LICENSED
    with tempfile.TemporaryDirectory(prefix='qc_wx_') as tmp:
        fx = Fixture(Path(tmp))
        fx.install()
        try:
            client = app.app.test_client()
            for gate in (False, True):          # missing weather under BOTH gate states
                _set_gate(gate)
                check_missing(client, fx, R, 'outdoor', AWAY, HOME)
                check_missing(client, fx, R, 'dome', 'Chicago Bears', 'Detroit Lions')
            check_known_valid(client, fx, R)
            check_date_join(client, fx, R)
            check_gate_off(client, fx, R)
            check_cfb_weather_gate(client, fx, R)
            check_mutation_templates(client, fx, R)
            check_mutation_home_only_join(client, fx, R)
            check_mutation_gate_ignored(client, fx, R)
        finally:
            fx.restore()
            app.BK_WEATHER_SOURCE_LICENSED = gate_before
            for name in ('_NFL_BOARD_CACHE', '_NFL_GAME_BOARD_CACHE', '_NFL_MATCHUP_CENTER_CACHE',
                         '_CFB_BOARD_CACHE', '_CFB_WX_CACHE'):
                getattr(app, name).clear()
    return R


def main():
    print('=' * 64)
    print('BANKROLL KINGS NFL WEATHER / VENUE INTEGRITY QC')
    print('=' * 64)
    R = run_qc()
    total, failed = len(R.results), len(R.failed)
    print('-' * 64)
    print(f'RESULT: {total} assertions, {total - failed} passed, {failed} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
