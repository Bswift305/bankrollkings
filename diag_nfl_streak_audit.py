"""READ-ONLY diagnostic + fail-closed health report for NFL milestone / matchup streaks.

Stop-the-line integrity tool for the Nico Collins case. Computes streaks from AUTHORITATIVE game
statistics (nflverse weekly player logs) -- NOT from sportsbook-line grades -- with ROBUST identity
resolution (the 2025 build stores short forms like 'N.Collins'; a literal full-name match silently
drops a player's whole season and under-counts streaks). Nothing here writes or publishes.

Separates the two streak PRODUCTS the UI must never conflate:
  * MILESTONE streak  -- reached a fixed factual threshold (e.g. 100+ receiving yards). Needs game
                         stats only. Can be season-wide OR opponent-specific (vs one team).
  * MARKET-LINE streak -- went Over/Under the actual posted sportsbook line. Needs captured lines +
                         grading (data/tracking/NFL_AllPropResults.csv). Reported here only for
                         freshness/health; this script never grades lines.

Run on prod via SSM (where the weekly parquet is current):
    sudo -u ubuntu python3 /opt/bankrollkings/diag_nfl_streak_audit.py --season 2026 --player "Nico Collins"
Exit code: 0 healthy; 2 current-season game-stat record absent/stale/incomplete (fail closed).
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from datetime import datetime, timezone

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')

THRESHOLDS = {
    'receiving_yards': [50, 75, 100, 125],
    'receptions': [5, 7, 10],
    'rushing_yards': [50, 75, 100],
    'passing_yards': [200, 250, 300],
}
STALE_BUDGET_H = 72.0  # in-season weekly parquet freshness budget


def name_key(n):
    """First-initial + last-name key: 'Nico Collins' and 'N.Collins' both -> 'n.collins'."""
    n = str(n or '').strip()
    t = n.replace('.', ' ').split()
    return (t[0][:1] + '.' + t[-1]).lower() if len(t) >= 2 else n.lower()


def _sources():
    srcs = []
    csv_seasons = set()
    for f in sorted(glob.glob(os.path.join(DATA, 'historical', 'NFL_PlayerStats_202*.csv'))):
        digits = ''.join(c for c in os.path.basename(f) if c.isdigit())[:4]
        s = int(digits) if digits else None
        srcs.append((f, 'csv', s))
        if s:
            csv_seasons.add(s)
    season_files = {}
    for pf in sorted(glob.glob(os.path.join(DATA, 'tracking', '_nflverse_stats_20*.parquet'))):
        digits = ''.join(c for c in os.path.basename(pf) if c.isdigit())[:4]
        if digits:
            season_files[int(digits)] = pf
    legacy = os.path.join(BASE, 'jw26.parquet')
    if 2026 not in season_files and os.path.exists(legacy):
        season_files[2026] = legacy
    for s, pf in sorted(season_files.items()):
        if s not in csv_seasons:
            srcs.append((pf, 'parquet', s))
    return srcs


def load_logs():
    frames, manifest = [], []
    for path, kind, season in _sources():
        try:
            d = pd.read_csv(path, low_memory=False) if kind == 'csv' else pd.read_parquet(path)
        except Exception as e:
            manifest.append((os.path.relpath(path, BASE), kind, season, f'READ-ERROR {e}', 0))
            continue
        d['__season'] = season
        try:
            mt = os.path.getmtime(path)
        except OSError:
            mt = 0
        manifest.append((os.path.relpath(path, BASE), kind, season, len(d), mt))
        frames.append(d)
    if not frames:
        return pd.DataFrame(), manifest
    df = pd.concat(frames, ignore_index=True)
    disp = 'player_display_name' if 'player_display_name' in df.columns else None
    alt = 'player_name' if 'player_name' in df.columns else None
    names = disp or alt
    df['__name'] = df[names].astype(str) if names else ''
    # resolve a short form to a full name when its key maps to exactly one full ('Jalen Hurts')
    df['__k'] = df['__name'].map(name_key)
    if alt and disp:
        df['__k2'] = df[alt].astype(str).map(name_key)
    else:
        df['__k2'] = df['__k']
    fulls = df.loc[df['__name'].str.contains(' ', na=False), '__name']
    key2full = {}
    for fn in fulls.unique():
        key2full.setdefault(name_key(fn), set()).add(fn)
    resolve = {k: next(iter(v)) for k, v in key2full.items() if len(v) == 1}
    df['__full'] = [resolve.get(k, n) for n, k in zip(df['__name'], df['__k'])]
    df['__week'] = pd.to_numeric(df.get('week'), errors='coerce')
    if 'season_type' in df.columns:
        df = df[df['season_type'].astype(str).str.upper().isin(['REG', ''])]
    return df, manifest


def trailing_run(values, thr):
    run = 0
    for v in reversed(values):
        if v is not None and not pd.isna(v) and float(v) >= thr:
            run += 1
        else:
            break
    return run


def player_rows(df, player):
    k = name_key(player)
    d = df[(df['__k'] == k) | (df['__k2'] == k)].copy()
    return d.sort_values(['__season', '__week'])


def trace_player(df, player, opponent=None):
    d = player_rows(df, player)
    if opponent:
        d = d[d['opponent_team'].astype(str).str.upper().isin([opponent.upper(), {'JAX': 'JAC', 'JAC': 'JAX'}.get(opponent.upper(), '')])]
    cols = [c for c in ['__season', '__week', 'opponent_team', 'receptions', 'receiving_yards',
                        'rushing_yards', 'passing_yards', 'receiving_tds'] if c in d.columns]
    return d, cols


def health(manifest, season):
    """Fail-closed health: is the resolved current season present and fresh in the game-stat logs?"""
    rows = [m for m in manifest if m[2] == season and isinstance(m[3], int) and m[3] > 0]
    if not rows:
        return 2, f'current-season ({season}) game-stat record ABSENT'
    newest = max(m[4] for m in rows)
    age_h = (datetime.now(timezone.utc).timestamp() - newest) / 3600.0 if newest else 1e9
    et = datetime.fromtimestamp(newest, tz=timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M %Z') if newest else '?'
    if age_h > STALE_BUDGET_H:
        return 2, f'current-season game-stat record STALE (updated {et}, {age_h:.0f}h > {STALE_BUDGET_H:.0f}h budget)'
    return 0, f'current-season game-stat record present + fresh (updated {et}, {age_h:.0f}h old)'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=None, help='resolved current season (default: infer)')
    ap.add_argument('--player', default='Nico Collins')
    ap.add_argument('--opponent', default='JAX')
    ap.add_argument('--min-run', type=int, default=3)
    ap.add_argument('--require-market-line', action='store_true',
                    help='also FAIL CLOSED (exit 3) when the market-line prop record (NFL_AllPropResults) '
                         'is behind the current season -- use this in the prop-grader monitor.')
    args = ap.parse_args()
    market_stale = False

    df, manifest = load_logs()
    print('=' * 72)
    print('NFL MILESTONE / MATCHUP STREAK DIAGNOSTIC (read-only)')
    print('=' * 72)
    print('\n[SOURCES]')
    for rel, kind, s, n, mt in manifest:
        et = datetime.fromtimestamp(mt, tz=timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M') if mt else '-'
        print(f'  {rel:52} {kind:7} season={s} rows={n} updated={et}')
    if df.empty:
        print('\nNO game-stat logs found -> FAIL CLOSED')
        return 2
    today = datetime.now().date()
    season = args.season or (today.year if today.month >= 3 else today.year - 1)
    code, msg = health(manifest, season)
    print(f'\n[HEALTH] resolved season={season}: {msg}')

    # market-line record freshness (NOT graded here -- health only)
    apr = os.path.join(DATA, 'tracking', 'NFL_AllPropResults.csv')
    if os.path.exists(apr):
        try:
            ad = pd.read_csv(apr, low_memory=False)
            amax = pd.to_numeric(ad.get('Season'), errors='coerce').max()
            amt = datetime.fromtimestamp(os.path.getmtime(apr), tz=timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')
            market_stale = bool(pd.notna(amax) and amax < season)
            verdict = ('STALE -- max Season %s < current %s (prop-grading lane not advancing)'
                       % (int(amax) if pd.notna(amax) else '?', season)) if market_stale else 'current'
            print(f'[MARKET-LINE] NFL_AllPropResults.csv max Season={amax} updated={amt} -> {verdict}')
            print('              (market-line streaks are a SEPARATE product from milestone streaks; '
                  'game-stat milestone streaks are unaffected by this)')
        except Exception as e:
            market_stale = True
            print(f'[MARKET-LINE] NFL_AllPropResults.csv unreadable: {e}')
    else:
        market_stale = True
        print('[MARKET-LINE] NFL_AllPropResults.csv absent')

    # ---- Nico (or --player) MATCHUP trace: milestone streak vs one opponent, across seasons -------
    print(f'\n[MATCHUP TRACE] {args.player} vs {args.opponent} (milestone, game-stats; identity key-resolved)')
    d, cols = trace_player(df, args.player, opponent=args.opponent)
    if d.empty:
        print('  no games on record vs that opponent (check identity / data completeness)')
    else:
        print(d[cols].to_string(index=False))
        ry = d['receiving_yards'].tolist() if 'receiving_yards' in d.columns else []
        for thr in (125, 100, 75, 50):
            print(f'  trailing {thr}+ receiving-yd streak vs {args.opponent}: {trailing_run(ry, thr)}')

    # ---- current-season threshold audit from the COMPLETE eligible player-event universe ----------
    cur = df[df['__season'] == season]
    print(f'\n[THRESHOLD AUDIT] current season {season} -- milestone streaks from ALL players (min run {args.min_run})')
    if cur.empty:
        print('  current-season universe EMPTY -> nothing to audit (see HEALTH)')
    for stat, thrs in THRESHOLDS.items():
        if stat not in cur.columns:
            continue
        for thr in thrs:
            members = []
            for full, g in cur.groupby('__full'):
                g = g.sort_values('__week')
                run = trailing_run(g[stat].tolist(), thr)
                if run >= args.min_run:
                    members.append((full, run, int(g['__week'].max())))
            members.sort(key=lambda x: -x[1])
            head = ', '.join(f'{n}({r}, thru wk{w})' for n, r, w in members[:8])
            print(f'  {stat} {thr}+ : {len(members)} active -> {head}')

    # Market-line staleness is a SEPARATE fail-closed signal (opt-in), so the prop-grader monitor can
    # exit non-zero on the stuck record without conflating it with the game-stat milestone health.
    if args.require_market_line and market_stale and code == 0:
        code, msg = 3, 'market-line prop record (NFL_AllPropResults) behind the current season'
    print('\n[EXIT]', 'HEALTHY (0)' if code == 0 else f'FAIL-CLOSED ({code}) -- {msg}')
    return code


if __name__ == '__main__':
    sys.exit(main())
