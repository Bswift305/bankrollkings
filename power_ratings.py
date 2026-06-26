# -*- coding: utf-8 -*-
"""
Market-INDEPENDENT power ratings (Elo) from actual game results.
================================================================

The point of this module: produce a team-strength estimate that owes NOTHING to
the betting market, so we can honestly compare our model to the market and call
the difference an edge. (The old Team_Strength_Priors were partly built FROM the
market line, which makes model-vs-market circular — we do not use them here.)

Inputs are final scores only:
  - NFL   : data/historical/NFL_Games_nfldata.csv      (1999-now, explicit scores)
  - NCAAF : data/historical/NCAAF_CFBD_Games_2025.csv  (completed games, scores)
  - WNBA  : data/gamelogs/WNBA_GameLogs.csv            (team score = sum of PTS)
  - MLB   : data/gamelogs/MLB_GameLogs.csv             (team runs = sum of R)

Output (written to data/tracking/):
  - Power_Ratings.csv       Sport, Team, Elo, Games
  - Power_Ratings_Meta.csv  Sport, HFAelo, HomeWinRate, NGames, SUAccuracy, Brier

The web app reads those and derives a model win probability per matchup, then
compares it to the market's no-vig implied probability. Win probability needs no
points-per-Elo scale, so we avoid that calibration risk entirely.
"""
import math
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / 'data'
RATINGS_PATH = DATA_DIR / 'tracking' / 'Power_Ratings.csv'
META_PATH = DATA_DIR / 'tracking' / 'Power_Ratings_Meta.csv'

BASE_ELO = 1500.0

# A sport's model is only surfaced as an edge if its out-of-sample straight-up
# accuracy clears this bar. Baseball (~.508, a coin flip) fails on purpose — we do
# not show a "model edge" we cannot actually back up.
MIN_SKILL_ACCURACY = 0.55

# WNBA game logs use abbreviations; the board uses full names. Map so ratings join.
_WNBA_ABBR_TO_FULL = {
    'ATL': 'Atlanta Dream', 'CHI': 'Chicago Sky', 'CON': 'Connecticut Sun',
    'DAL': 'Dallas Wings', 'GSV': 'Golden State Valkyries', 'IND': 'Indiana Fever',
    'LAS': 'Los Angeles Sparks', 'LVA': 'Las Vegas Aces', 'MIN': 'Minnesota Lynx',
    'NYL': 'New York Liberty', 'PDX': 'Portland Fire', 'PHX': 'Phoenix Mercury',
    'SEA': 'Seattle Storm', 'TOR': 'Toronto Tempo', 'WAS': 'Washington Mystics',
}

# FBS conferences — Elo across all NCAA divisions inflates isolated D-II/D-III teams
# that never play FBS opponents, so we restrict to FBS-vs-FBS games.
_FBS_CONFERENCES = {
    'ACC', 'American Athletic', 'Big 12', 'Big Ten', 'Conference USA',
    'FBS Independents', 'Mid-American', 'Mountain West', 'Pac-12', 'Sun Belt', 'SEC',
}

# Per-sport Elo settings. K = responsiveness; regress = season-to-season pull back
# toward the mean (only matters for the multi-season NFL file).
_SPORT_CFG = {
    'nfl':   {'k': 20.0, 'regress': 0.33, 'seasons': 6},
    'ncaaf': {'k': 32.0, 'regress': 0.0,  'seasons': 1},
    'wnba':  {'k': 24.0, 'regress': 0.0,  'seasons': 1},
    'mlb':   {'k': 6.0,  'regress': 0.0,  'seasons': 1},
}


# --------------------------------------------------------------------------- #
# Results loaders — each returns a tidy frame: date, away, home, ascore, hscore
# (teams left in their native format; the app normalizes on join).
# --------------------------------------------------------------------------- #
def _results_nfl():
    path = DATA_DIR / 'historical' / 'NFL_Games_nfldata.csv'
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df = df.dropna(subset=['away_score', 'home_score', 'home_team', 'away_team'])
    keep = max(df['season']) - _SPORT_CFG['nfl']['seasons'] + 1
    df = df[df['season'] >= keep]
    return pd.DataFrame({
        'date': df['gameday'].astype(str), 'season': df['season'],
        'away': df['away_team'].astype(str), 'home': df['home_team'].astype(str),
        'ascore': pd.to_numeric(df['away_score'], errors='coerce'),
        'hscore': pd.to_numeric(df['home_score'], errors='coerce'),
    }).dropna(subset=['ascore', 'hscore'])


def _results_ncaaf():
    path = DATA_DIR / 'historical' / 'NCAAF_CFBD_Games_2025.csv'
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if 'Completed' in df.columns:
        df = df[df['Completed'].astype(str).str.lower().isin(['true', '1', 'yes'])]
    if {'AwayConference', 'HomeConference'}.issubset(df.columns):
        df = df[df['AwayConference'].isin(_FBS_CONFERENCES) & df['HomeConference'].isin(_FBS_CONFERENCES)]
    df = df.dropna(subset=['AwayScore', 'HomeScore', 'Away', 'Home'])
    return pd.DataFrame({
        'date': df['Date'].astype(str), 'season': df.get('Season', 2025),
        'away': df['Away'].astype(str), 'home': df['Home'].astype(str),
        'ascore': pd.to_numeric(df['AwayScore'], errors='coerce'),
        'hscore': pd.to_numeric(df['HomeScore'], errors='coerce'),
    }).dropna(subset=['ascore', 'hscore'])


def _results_from_gamelogs(path, gid_col, stat_col):
    """Build team-level final scores by summing a per-player stat (PTS / R) within
    each (game, team), then pairing the two teams of each game by home/away."""
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    needed = {gid_col, 'Team', 'Date', stat_col, 'Matchup'}
    if not needed.issubset(df.columns):
        return pd.DataFrame()
    df[stat_col] = pd.to_numeric(df[stat_col], errors='coerce').fillna(0)
    team_score = df.groupby([gid_col, 'Team', 'Date'], as_index=False)[stat_col].sum()
    # Home/away: a "vs" matchup means the listed Team is home; "@" means away.
    matchup = df.groupby([gid_col, 'Team'])['Matchup'].first().reset_index()
    team_score = team_score.merge(matchup, on=[gid_col, 'Team'], how='left')
    team_score['is_home'] = team_score['Matchup'].astype(str).str.contains('vs', case=False)
    rows = []
    for gid, g in team_score.groupby(gid_col):
        if len(g) != 2:
            continue
        home = g[g['is_home']]
        away = g[~g['is_home']]
        if len(home) != 1 or len(away) != 1:
            continue
        h, a = home.iloc[0], away.iloc[0]
        rows.append({'date': str(h['Date']), 'season': 1,
                     'away': str(a['Team']), 'home': str(h['Team']),
                     'ascore': float(a[stat_col]), 'hscore': float(h[stat_col])})
    return pd.DataFrame(rows)


def _results_wnba():
    df = _results_from_gamelogs(DATA_DIR / 'gamelogs' / 'WNBA_GameLogs.csv', 'GAME_ID', 'PTS')
    if not df.empty:  # store ratings under full names so they join the board
        df['away'] = df['away'].map(lambda t: _WNBA_ABBR_TO_FULL.get(t, t))
        df['home'] = df['home'].map(lambda t: _WNBA_ABBR_TO_FULL.get(t, t))
    return df


def _results_mlb():
    return _results_from_gamelogs(DATA_DIR / 'gamelogs' / 'MLB_GameLogs.csv', 'GameID', 'R')


_LOADERS = {'nfl': _results_nfl, 'ncaaf': _results_ncaaf, 'wnba': _results_wnba, 'mlb': _results_mlb}


# --------------------------------------------------------------------------- #
# Elo core
# --------------------------------------------------------------------------- #
def _expected(elo_a, elo_b):
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def _mov_mult(margin):
    return math.log(abs(margin) + 1.0)


def _home_win_rate(df):
    played = df[df['hscore'] != df['ascore']]
    if played.empty:
        return 0.5
    return float((played['hscore'] > played['ascore']).mean())


def _hfa_elo_from_rate(hwr):
    hwr = min(max(hwr, 0.5), 0.75)  # clamp; home edge is real but bounded
    return 400.0 * math.log10(hwr / (1.0 - hwr))


def compute_elo(sport):
    """Return (ratings dict, meta dict) for one sport from real results."""
    loader = _LOADERS.get(sport)
    if not loader:
        return {}, {}
    df = loader()
    if df is None or df.empty:
        return {}, {}
    df = df.copy()
    df['_d'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['_d']).sort_values(['season', '_d'])
    cfg = _SPORT_CFG[sport]
    k, regress = cfg['k'], cfg['regress']
    hfa = _hfa_elo_from_rate(_home_win_rate(df))

    elo, last_season = {}, None
    correct = total = 0
    brier_sum = 0.0
    for _, g in df.iterrows():
        if regress and last_season is not None and g['season'] != last_season:
            for t in elo:  # pull every team a third of the way back to the mean
                elo[t] = BASE_ELO + (elo[t] - BASE_ELO) * (1 - regress)
        last_season = g['season']
        a, h = g['away'], g['home']
        ra = elo.get(a, BASE_ELO)
        rh = elo.get(h, BASE_ELO)
        exp_h = _expected(rh + hfa, ra)
        margin = g['hscore'] - g['ascore']
        if margin == 0:
            continue
        actual_h = 1.0 if margin > 0 else 0.0
        # backtest (graded before the update = out-of-sample for this game)
        if (a in elo) and (h in elo):
            total += 1
            correct += 1 if (exp_h >= 0.5) == (actual_h == 1.0) else 0
            brier_sum += (exp_h - actual_h) ** 2
        change = k * _mov_mult(margin) * (actual_h - exp_h)
        elo[h] = rh + change
        elo[a] = ra - change

    games_count = {}
    for _, g in df.iterrows():
        games_count[g['away']] = games_count.get(g['away'], 0) + 1
        games_count[g['home']] = games_count.get(g['home'], 0) + 1

    ratings = {t: {'elo': round(r, 1), 'games': games_count.get(t, 0)} for t, r in elo.items()}
    acc = round(correct / total, 3) if total else None
    meta = {'hfa_elo': round(hfa, 1), 'home_win_rate': round(_home_win_rate(df), 3),
            'n_games': int(len(df)),
            'su_accuracy': acc,
            'brier': round(brier_sum / total, 4) if total else None,
            'surfaced': bool(acc is not None and acc >= MIN_SKILL_ACCURACY)}
    return ratings, meta


def build_power_ratings():
    """Compute every sport and persist. Returns the meta dict for logging."""
    rating_rows, meta_rows = [], []
    for sport in _LOADERS:
        ratings, meta = compute_elo(sport)
        for team, r in ratings.items():
            rating_rows.append({'Sport': sport, 'Team': team, 'Elo': r['elo'], 'Games': r['games']})
        if meta:
            meta_rows.append({'Sport': sport, 'HFAelo': meta['hfa_elo'],
                              'HomeWinRate': meta['home_win_rate'], 'NGames': meta['n_games'],
                              'SUAccuracy': meta['su_accuracy'], 'Brier': meta['brier'],
                              'Surfaced': meta['surfaced']})
    RATINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rating_rows).to_csv(RATINGS_PATH, index=False)
    pd.DataFrame(meta_rows).to_csv(META_PATH, index=False)
    return {m['Sport']: m for m in meta_rows}


def win_probability(home_elo, away_elo, hfa_elo):
    return _expected(home_elo + hfa_elo, away_elo)


if __name__ == '__main__':
    meta = build_power_ratings()
    rat = pd.read_csv(RATINGS_PATH)
    for sport in _LOADERS:
        m = meta.get(sport)
        if not m:
            print(f"{sport.upper()}: no data")
            continue
        top = rat[rat['Sport'] == sport].sort_values('Elo', ascending=False).head(5)
        print(f"\n{sport.upper()}  games={m['NGames']}  HFA={m['HFAelo']}elo  "
              f"homeWR={m['HomeWinRate']}  SU-acc={m['SUAccuracy']}  Brier={m['Brier']}")
        for _, r in top.iterrows():
            print(f"   {r['Team']:<26} {r['Elo']}")
