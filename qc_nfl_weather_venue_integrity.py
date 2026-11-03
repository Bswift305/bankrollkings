"""QC: NFL weather / venue integrity (defect D1, 2026-11-03).

Incident: live NE @ MIA (open-air Hard Rock Stadium, storms + 13-14 mph wind forecast) rendered
"indoor/calm" on /sports/nfl and "dome" on /tools/nfl-totals-today. The venue table was right; the
templates turned MISSING weather into an affirmative condition, and three home-team-only joins could
attach a weeks-old forecast to a different game (and default missing wind to 0 mph).

Contract enforced here (synthetic fixtures; no network, no live data files read or written):
  1. VENUE TABLE   all 32 full team names in NFL_STADIUMS; roof set == an explicit truth table.
  2. UNAVAILABLE   every weather-bearing surface (/sports/nfl, /sports/ncaaf, /tools/nfl-totals-today,
                   /tools/nfl-matchup-center, the NFL Top board + Game board contexts), with missing weather
                   for an OUTDOOR home, never says indoor / calm / dome / 0 mph / no wind, and does say the
                   unavailable wording. A DOME home with missing weather never asserts calm / 0 mph either
                   (its roof may be shown, as a separate field).
  3. DATE JOIN     a forecast dated D1 never attaches to the same home team's game on D2.
  4. GATE ON READ  BK_WEATHER_SOURCE_LICENSED off => no surface shows a wind value even when the CSV has a
                   matching row (positive control: gate on => the same row IS shown).
  5. NONE NOT 0    builder rows carry wind=None (never 0) when unknown.
  6. MUTATION      restoring the old template `else` text ("indoor/calm" / "dome") makes this QC fail.

Exits 0 when all hold, 1 otherwise.
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
import nfl_totals  # noqa: E402
from services.nfl_stadiums import NFL_STADIUMS

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

TODAY = app.sports_today_date()
D_GAME = (TODAY + timedelta(days=2)).isoformat()       # the game (D2)
D_OLD = (TODAY - timedelta(days=12)).isoformat()       # a weeks-old forecast row (D1)
NFL_SCORES = {'games': []}


def _game(away, home, date, total=44.5, spread=-3.0):
    return {'away': away, 'home': home, 'matchup': f'{away} @ {home}', 'date': date, 'time': '1:00 PM',
            'spread': spread, 'total': total, 'away_ml': None, 'home_ml': None, 'book': 'DraftKings',
            'slug': f'{away}@{home}', 'summary': ''}


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


SURFACES = {
    'nfl_dashboard (/sports/nfl)': ('/sports/nfl?qc=1', _region_dashboard, UNAVAILABLE),
    'ncaaf dashboard (/sports/ncaaf)': ('/sports/ncaaf', _region_dashboard, UNAVAILABLE),
    'totals-today (/tools/nfl-totals-today)': ('/tools/nfl-totals-today', _region_totals, UNAVAILABLE),
    'matchup center (/tools/nfl-matchup-center)': ('/tools/nfl-matchup-center', _region_mc, MC_UNAVAILABLE),
}


def render_regions(client):
    out = {}
    for label, (url, region, _) in SURFACES.items():
        r = client.get(url)
        html = r.get_data(as_text=True)
        out[label] = (r.status_code, region(html) if r.status_code == 200 else None)
    return out


def check_missing(client, fx, issues, notes, home_kind, away, home, mutated=False):
    """Missing weather for one game: assert unavailable wording and no affirmative condition."""
    forbidden = FORBIDDEN_OUTDOOR if home_kind == 'outdoor' else FORBIDDEN_DOME
    fx.nfl_games = [_game(away, home, D_GAME)]
    fx.cfb_games = [_game('Georgia Tech', 'Miami', D_GAME)]   # open-air college venue, no wind source
    fx.clear_caches()
    bad = []
    for label, (status, region) in render_regions(client).items():
        if label.startswith('ncaaf') and home_kind != 'outdoor':
            continue  # the CFB fixture is the same either way; checked once on the outdoor pass
        want = SURFACES[label][2]
        if status != 200 or region is None:
            bad.append(f"{label}: HTTP {status} / weather region not found")
            continue
        text = _strip(region)
        hit = forbidden.search(text)
        if hit:
            bad.append(f"{label}: missing weather rendered affirmative condition {hit.group(0)!r} "
                       f"for {home_kind} home {home} -> {text[:140]!r}")
        if want not in text:
            bad.append(f"{label}: missing weather does not say {want!r} for {home} -> {text[:140]!r}")
        if home_kind == 'dome' and label.startswith('matchup') and 'Dome (fixed roof)' not in text:
            bad.append(f"{label}: known dome venue {home} lost its separate roof field")
    # builder-level contexts
    for label, builder in (('NFL Top board', app.build_nfl_board_context),
                           ('NFL Game board', app.build_nfl_game_board_context)):
        fx.clear_caches()
        rows = [c for c in builder().get('board', []) if c.get('market') == 'Total']
        if not rows:
            bad.append(f"{label}: fixture produced no Total candidate (cannot verify)")
        for c in rows:
            if c.get('wind') is not None:
                bad.append(f"{label}: missing weather carried wind={c.get('wind')!r} (must be None)")
            hit = forbidden.search(c.get('why', ''))
            if hit or UNAVAILABLE not in c.get('why', ''):
                bad.append(f"{label}: why={c.get('why')!r} (affirmative or missing '{UNAVAILABLE}')")
            if c.get('flag') == 'WIND' or 'wind' in str(c.get('tier', '')).lower() \
                    or c.get('tier') in ('Validated', 'Backtest ~55% (not yet governed)'):
                bad.append(f"{label}: unknown wind promoted to a wind tier/flag ({c.get('tier')}/{c.get('flag')})")
    if not mutated:
        if bad:
            issues.extend(bad)
        else:
            notes.append(f"[gate {'ON' if app.BK_WEATHER_SOURCE_LICENSED else 'OFF'}] missing weather, {home_kind} home "
                         f"({away} @ {home}): every surface says unavailable, "
                         f"no affirmative condition")
    return bad


def check_builders_none(fx, issues, notes):
    fx.nfl_games = [_game('New England Patriots', 'Miami Dolphins', D_GAME)]
    fx.cfb_games = [_game('Georgia Tech', 'Miami', D_GAME)]
    fx.clear_caches()
    bad = []
    for sk in ('nfl', 'ncaaf'):
        for r in app.build_football_home_slate(sk):
            if r.get('wind') is not None or r.get('weather_label') != UNAVAILABLE:
                bad.append(f"home slate {sk}: wind={r.get('wind')!r} label={r.get('weather_label')!r}")
            if sk == 'ncaaf' and r.get('roof') is not None:
                bad.append("home slate ncaaf: an NFL venue roof was applied to a college game")
    for r in app.build_nfl_totals_board_context('week')['nt_rows']:
        if r.get('wind') is not None or r.get('high_wind'):
            bad.append(f"totals board: wind={r.get('wind')!r} high_wind={r.get('high_wind')!r}")
        if r.get('roof') != 'outdoor':
            bad.append(f"totals board: roof field {r.get('roof')!r} (expected separate 'outdoor' venue fact)")
    for g in app.build_nfl_matchup_center_context()['games']:
        w = g['weather']
        if w.get('available') or w.get('wind_mph') is not None:
            bad.append(f"matchup center: weather available={w.get('available')} wind_mph={w.get('wind_mph')!r}")
    if bad:
        issues.extend(bad)
    else:
        notes.append("builder rows: unknown wind is None (never 0) across home slate (NFL+NCAAF), totals, "
                     "matchup center; roof is a separate field")


def check_date_join_and_gate(client, fx, issues, notes):
    fx.nfl_games = [_game('New England Patriots', 'Miami Dolphins', D_GAME)]
    bad = []
    # (a) weeks-old row for the SAME home team on a different date -> must not attach (gate ON)
    _set_gate(True)
    fx.set_weather([{'Date': D_OLD, 'HomeTeam': 'Miami Dolphins', 'WindMph': 23.0, 'GustMph': 30.0,
                     'PrecipMm': 0, 'TempF': 80, 'Roof': 'outdoor', 'Updated': D_OLD + ' 06:00'}])
    for label, (status, region) in render_regions(client).items():
        if label.startswith('ncaaf'):
            continue
        text = _strip(region or '')
        if '23' in text:
            bad.append(f"{label}: a {D_OLD} forecast attached to the {D_GAME} game ({text[:120]!r})")
    slate = app.build_football_home_slate('nfl')
    if any(r.get('wind') is not None for r in slate):
        bad.append("home slate: D1 forecast attached to the D2 game (home-only join)")
    for label, builder in (('Top board', app.build_nfl_board_context), ('Game board', app.build_nfl_game_board_context)):
        fx.clear_caches()
        for c in builder().get('board', []):
            if c.get('wind') is not None or c.get('flag') == 'WIND':
                bad.append(f"{label}: D1 forecast attached to the D2 game (wind={c.get('wind')})")
    if not bad:
        notes.append(f"date join: a {D_OLD} MIA forecast never attaches to the {D_GAME} MIA game")
    # (b) matching row, gate ON -> shown (positive control, proves the join works)
    fx.set_weather([{'Date': D_GAME, 'HomeTeam': 'Miami Dolphins', 'WindMph': 17.0, 'GustMph': 26.0,
                     'PrecipMm': 9, 'TempF': 79, 'Roof': 'outdoor', 'Updated': TODAY.isoformat() + ' 06:00'}])
    shown = {lbl: '17' in _strip(reg or '') for lbl, (st, reg) in render_regions(client).items()
             if not lbl.startswith('ncaaf')}
    missing = [lbl for lbl, ok in shown.items() if not ok]
    if missing:
        bad.append(f"positive control: licensed matching forecast (17 mph) not shown on {missing}")
    gb = [c for c in (fx.clear_caches() or app.build_nfl_game_board_context()).get('board', [])
          if c.get('market') == 'Total']
    if not gb or gb[0].get('wind') != 17 or gb[0].get('flag') != 'WIND':
        bad.append(f"positive control: game board did not carry the matched 17 mph wind ({gb[:1]})")
    # (c) same matching row, gate OFF -> no surface shows a wind value
    _set_gate(False)
    fx.clear_caches()
    for label, (status, region) in render_regions(client).items():
        if label.startswith('ncaaf'):
            continue
        text = _strip(region or '')
        if '17' in text or 'mph' in text.lower():
            bad.append(f"gate off: {label} still shows a stored wind value ({text[:120]!r})")
        if SURFACES[label][2] not in text:
            bad.append(f"gate off: {label} does not say {SURFACES[label][2]!r}")
    for r in app.build_football_home_slate('nfl') + app.build_nfl_totals_board_context('week')['nt_rows']:
        if r.get('wind') is not None:
            bad.append(f"gate off: builder row still carries wind={r.get('wind')}")
    for label, builder in (('Top board', app.build_nfl_board_context), ('Game board', app.build_nfl_game_board_context)):
        fx.clear_caches()
        for c in builder().get('board', []):
            if c.get('wind') is not None or c.get('flag') == 'WIND' or 'wind 17' in c.get('why', ''):
                bad.append(f"gate off: {label} still uses the stored wind ({c.get('why')!r})")
    if app._nfl_game_wind_map():
        bad.append("gate off: _nfl_game_wind_map() returned stored rows")
    if app._cfb_weather('Georgia Tech', 'Miami') is not None:
        bad.append("gate off: _cfb_weather returned stored CFB weather")
    if bad:
        issues.extend(bad)
    else:
        notes.append("licence gate on read: matching CSV row shown when ON (17 mph), withheld on every surface when OFF")
    fx.set_weather([])


def check_venue_table(issues, notes):
    bad = []
    missing = sorted(set(ROOF_TRUTH) - set(NFL_STADIUMS))
    extra = sorted(set(NFL_STADIUMS) - set(ROOF_TRUTH))
    if len(ROOF_TRUTH) != 32 or missing or extra:
        bad.append(f"venue table: missing={missing} extra={extra}")
    for team, roof in ROOF_TRUTH.items():
        info = NFL_STADIUMS.get(team)
        if info and info[2] != roof:
            bad.append(f"venue table: {team} roof {info[2]!r} != truth {roof!r}")
        if info and info[3] != (roof == 'outdoor'):
            bad.append(f"venue table: {team} wind_exposed {info[3]} inconsistent with roof {roof!r}")
    if bad:
        issues.extend(bad)
    else:
        notes.append("venue table: 32/32 teams, roof set == truth table (MIA outdoor; 5 retractable; 6 fixed roof)")


def check_mutation(client, fx, notes, issues):
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
        if new not in src:
            issues.append(f"mutation check: fixed text not found in {name} (template drifted?)")
            return
        mutated[name] = src.replace(new, old)
    orig_loader = env.loader
    env.loader = jinja2.ChoiceLoader([jinja2.DictLoader(mutated), orig_loader])
    env.cache.clear() if env.cache is not None else None
    try:
        bad = check_missing(client, fx, [], [], 'outdoor', 'New England Patriots', 'Miami Dolphins', mutated=True)
    finally:
        env.loader = orig_loader
        env.cache.clear() if env.cache is not None else None
    caught_dash = any('nfl_dashboard' in b and 'indoor' in b for b in bad)
    caught_tot = any('totals-today' in b and 'dome' in b for b in bad)
    if caught_dash and caught_tot:
        notes.append("mutation: restoring the old '&mdash; indoor/calm' and 'dome' else-branches makes this QC FAIL (caught)")
    else:
        issues.append(f"mutation NOT caught (dashboard={caught_dash}, totals={caught_tot}) -- QC is toothless")


def run_qc():
    issues, notes = [], []
    check_venue_table(issues, notes)
    gate_before = app.BK_WEATHER_SOURCE_LICENSED
    with tempfile.TemporaryDirectory(prefix='qc_wx_') as tmp:
        fx = Fixture(Path(tmp))
        fx.install()
        try:
            client = app.app.test_client()
            # missing weather: no forecast file rows, under BOTH gate states
            for gate in (False, True):
                _set_gate(gate)
                fx.set_weather([])
                check_missing(client, fx, issues, notes, 'outdoor', 'New England Patriots', 'Miami Dolphins')
                check_missing(client, fx, issues, notes, 'dome', 'Chicago Bears', 'Detroit Lions')
            _set_gate(True)
            check_builders_none(fx, issues, notes)
            check_date_join_and_gate(client, fx, issues, notes)
            _set_gate(False)
            check_mutation(client, fx, notes, issues)
        finally:
            fx.restore()
            app.BK_WEATHER_SOURCE_LICENSED = gate_before
            for name in ('_NFL_BOARD_CACHE', '_NFL_GAME_BOARD_CACHE', '_NFL_MATCHUP_CENTER_CACHE'):
                getattr(app, name).clear()
    return {'issues': issues, 'notes': notes}


def main():
    r = run_qc()
    print('=' * 64)
    print('BANKROLL KINGS NFL WEATHER / VENUE INTEGRITY QC')
    print('=' * 64)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No weather/venue integrity issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
