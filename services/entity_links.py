"""Pure, data-free construction of Bankroll Kings entity-page URLs.

ONE place that knows the URL shape for each (kind, sport) entity destination and performs ALL
percent-encoding. No app import, no data access -- it shapes a URL string (or returns None for a
sport/kind that has no targetable per-entity page). WHETHER an entity actually exists / resolves is
a separate data question answered in app.py (`player_url` / `team_url`); this module only shapes the
link. Centralizing it here means no template ever hand-builds an entity href or lowercases a
displayed name into a URL.

Per-sport destinations (decided with the owner, 2026-10-18):
  player  nba / wnba / mlb -> /player/<name>?sport=<sport>   (shared route, scoped so identical
                              names across these datasets cannot collide on one inferred page)
          nfl              -> /tools/player-check?q=<name>    (canonical NFL player page, resolver-
                              backed; renders the intended entity)
          cfb              -> None  (no CFB player page -> caller renders plain text)
  team    nba              -> /team/<team>?sport=nba
          cfb              -> /tools/cfb-team?team=<team>
          nfl              -> /tools/nfl-team?team=<abbr>   (profile pre-selected to that team)
          mlb              -> /tools/mlb-team?team=<team>   (minimal cleared market/schedule page)
          wnba             -> /tools/wnba-team?team=<team>  (minimal cleared market/schedule page;
                              licensed Odds schedule renders even while the NBA/WNBA stats gate is
                              off -- restricted statistics abstain visibly, they are never shown)
"""
from __future__ import annotations

from urllib.parse import quote, urlencode

# Sports recognized by the resolver. Identical names in different sports NEVER share a URL because
# the sport is part of resolution and (for the shared /player route) an explicit query scope.
PLAYER_SPORTS = frozenset({'nba', 'wnba', 'mlb', 'nfl'})   # cfb has no player page -> None
TEAM_SPORTS = frozenset({'nba', 'cfb', 'nfl', 'mlb', 'wnba'})   # mlb + wnba now have minimal cleared team pages
KNOWN_SPORTS = frozenset({'nba', 'wnba', 'mlb', 'nfl', 'cfb'})


def canonical_sport(sport):
    """Normalize a sport token to its canonical key, or '' if unrecognized. Accepts common aliases
    (ncaaf -> cfb) so callers can pass whatever their surface calls the league."""
    s = str(sport or '').strip().lower()
    if s in ('ncaaf', 'college-football', 'cfb'):
        return 'cfb'
    return s if s in KNOWN_SPORTS else ''


def _seg(value):
    """Encode a path segment -- the single chokepoint for path encoding. Never lowercases."""
    return quote(str(value), safe='')


def player_path(sport, name, sample=None, stat=None):
    """URL for a single player's page in `sport`, or None if that sport has no player page. `name`
    is the canonical display identity; it is percent-encoded here, never lowercased or slugified."""
    sport = canonical_sport(sport)
    name = str(name or '').strip()
    if not name or sport not in PLAYER_SPORTS:
        return None
    if sport == 'nfl':
        return '/tools/player-check?' + urlencode({'q': name})
    params = {'sport': sport}
    if sample:
        params['sample'] = sample
    if stat:
        params['stat'] = stat
    return f'/player/{_seg(name)}?' + urlencode(params)


# Market-only destinations (additive). While the NBA.com stats gate is OFF, NBA/WNBA entity links
# point here instead of the rich stats pages: identity resolves from the LICENSED Odds feed and the
# page shows cleared market/schedule facts only. app.py chooses rich-vs-market by the gate; this
# module only owns the URL shapes. Kept separate from team_path/player_path so the frozen /team and
# /player routes are never touched.
MARKET_PLAYER_SPORTS = frozenset({'nba', 'wnba'})


def market_player_path(sport, name):
    """URL for the minimal, cleared market-only player page for `sport` (nba|wnba), or None. Identity
    is percent-encoded here, never lowercased. The destination (`/tools/<sport>-player`) renders
    licensed Odds markets only and abstains on stats.nba.com statistics."""
    sport = canonical_sport(sport)
    name = str(name or '').strip()
    if not name or sport not in MARKET_PLAYER_SPORTS:
        return None
    return f'/tools/{sport}-player?' + urlencode({'q': name})


def nba_market_team_path(team):
    """URL for the minimal, cleared market-only NBA team page, or None. Licensed Odds schedule/lines
    only; abstains on stats.nba.com statistics. Additive -- never the frozen /team route."""
    team = str(team or '').strip()
    if not team:
        return None
    return '/tools/nba-team?' + urlencode({'team': team})


def team_path(sport, team, postseason=False):
    """URL for a single team's page in `sport`, or None if that sport has no targetable per-team
    page (-> caller renders plain text)."""
    sport = canonical_sport(sport)
    team = str(team or '').strip()
    if not team or sport not in TEAM_SPORTS:
        return None
    if sport == 'cfb':
        return '/tools/cfb-team?' + urlencode({'team': team})
    if sport == 'nfl':
        return '/tools/nfl-team?' + urlencode({'team': team})
    if sport == 'mlb':
        return '/tools/mlb-team?' + urlencode({'team': team})
    if sport == 'wnba':
        return '/tools/wnba-team?' + urlencode({'team': team})
    params = {'sport': 'nba'}
    if postseason:
        params['postseason'] = '1'
    return f'/team/{_seg(team)}?' + urlencode(params)
