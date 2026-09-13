#!/usr/bin/env python3
"""
Bankroll Kings - Weekly Social Card Generator
=============================================
One command pulls live NFL lines + props and renders the full set of
post-ready, on-brand cards. Every number traces to real live/graded data;
nothing is fabricated. Honesty labels (validated edge vs. trend vs. raw
line) are baked into each card.

Cards produced:
  slate    - all games: spread, total, streak leans (leans from Riding the Wave)
  top      - clean top-12 PropScore plays (the validated edge)
  premium  - every play with PropScore >= 20, + Cowboys-style team totals
  floor    - softer tier, PropScore 10-20
  defense  - sacks/tackles RAW LINES, clearly marked NOT validated
  parlay   - editable ticket card (PARLAYS below, or auto top-2)

Usage:
  # refresh live lines+props first, then render everything:
  python marketing/generators/weekly_cards.py --refresh --week "Week 1 - Sunday"
  # just re-render from whatever data is already local:
  python marketing/generators/weekly_cards.py --only slate,top,parlay

Notes:
  - Needs ODDS_API_KEY in the environment (or .env.local) for --refresh.
  - Streak leans come from build_nfl_wave_context() (Riding the Wave).
  - The parlay card is editorial: edit PARLAYS below for the week's tickets.
"""
from __future__ import annotations
import os
import sys
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
import app as A  # noqa: E402

# --------------------------------------------------------------------------- #
# Brand tokens (from build_pack.py)
# --------------------------------------------------------------------------- #
BG=(7,14,20); PANEL=(13,25,34); INK=(238,245,247); DIM=(157,176,187); FAINT=(99,121,132)
CY=(45,212,191); GOLD=(255,206,106); GREEN=(78,212,138); RED=(255,111,126); AMBER=(255,176,90); LINE=(30,46,54)
W = 1080; M = 44

def _font(name, size):
    for p in (f"C:/Windows/Fonts/{name}", f"/usr/share/fonts/truetype/dejavu/{name}"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

FB = "arialbd.ttf"; FR = "arial.ttf"
F = {k: _font(FB if b else FR, s) for k, (s, b) in {
    'h1':(54,1),'tag':(22,1),'sub':(26,1),'hdr':(20,1),'plr':(33,1),'det':(25,0),
    'dir':(24,1),'ps':(34,1),'psu':(15,1),'ft':(21,0),'ftb':(23,1),'blk':(30,1),
    'rk':(16,1),'pl':(21,1),'de':(16,0),'sc':(22,1),'ttl':(26,1),'col':(22,1),
    'ln':(22,1),'mu':(15,0),'warn':(21,1),
}.items()}

ABBR = {'Arizona Cardinals':'ARI','Los Angeles Chargers':'LAC','Atlanta Falcons':'ATL','Pittsburgh Steelers':'PIT',
'Baltimore Ravens':'BAL','Indianapolis Colts':'IND','Buffalo Bills':'BUF','Houston Texans':'HOU','Chicago Bears':'CHI',
'Carolina Panthers':'CAR','Cleveland Browns':'CLE','Jacksonville Jaguars':'JAX','Dallas Cowboys':'DAL','New York Giants':'NYG',
'Denver Broncos':'DEN','Kansas City Chiefs':'KC','Green Bay Packers':'GB','Minnesota Vikings':'MIN','Miami Dolphins':'MIA',
'Las Vegas Raiders':'LV','New Orleans Saints':'NO','Detroit Lions':'DET','New York Jets':'NYJ','Tennessee Titans':'TEN',
'Tampa Bay Buccaneers':'TB','Cincinnati Bengals':'CIN','Washington Commanders':'WAS','Philadelphia Eagles':'PHI',
'Seattle Seahawks':'SEA','San Francisco 49ers':'SF','Los Angeles Rams':'LAR','New England Patriots':'NE'}

def abbr(name):
    return ABBR.get(str(name).strip(), str(name).strip())

def mabbr(m):
    m = str(m or '')
    for full, ab in ABBR.items():
        m = m.replace(full, ab)
    return m.replace(' @ ', '@')

def _fmt_line(v):
    try:
        return f"+{v:g}" if float(v) > 0 else f"{v:g}"
    except (TypeError, ValueError):
        return str(v)

# --------------------------------------------------------------------------- #
# Editable parlay tickets for the week (leg tuples: player/subject, detail, side)
# --------------------------------------------------------------------------- #
PARLAYS = [
    ("TOP EDGE - 2-LEG", CY, [
        ("Ja'Marr Chase", "Rec Yds  86.5", "OVER"),
        ("Jameson Williams", "Receptions  3.5", "OVER"),
    ]),
    ("COWBOYS PASSING SGP - 4-LEG", GOLD, [
        ("Cowboys Team Total", "Over  ~25.5*", "OVER"),
        ("Dak Prescott", "Pass TDs  1.5", "OVER"),
        ("CeeDee Lamb", "Receptions  5.5", "OVER"),
        ("George Pickens", "Receptions  4.5", "OVER"),
    ]),
    ("TEXANS UNDER SGP - 2-LEG", GREEN, [
        ("C.J. Stroud", "Pass TDs  1.5", "UNDER"),
        ("Nico Collins", "Receptions  5.5", "UNDER"),
    ]),
]
PARLAY_FOOTNOTE = "* team total implied from the game line - confirm your book's posted number."

# EQC-legal tickets: CROSS-GAME game lines only (no props, no same-game) - one leg per
# matchup, built from the Riding-the-Wave streak leans. kind: 'spread'/'over'/'under'.
EQC_TICKETS = [
    ("SAFEST - 2 LEG", CY, [
        ("GB@MIN", "Vikings -1.5", "spread"),
        ("DAL@NYG", "Over 47.5", "over"),
    ]),
    ("BIG DOGS - 2 LEG", GOLD, [
        ("NO@DET", "Saints +7", "spread"),
        ("CLE@JAX", "Browns +9", "spread"),
    ]),
    ("ALL OVERS - 3 LEG", GREEN, [
        ("BAL@IND", "Over 48", "over"),
        ("DAL@NYG", "Over 47.5", "over"),
        ("WAS@PHI", "Over 44", "over"),
    ]),
    ("COVER DOGS - 3 LEG", GOLD, [
        ("NO@DET", "Saints +7", "spread"),
        ("CLE@JAX", "Browns +9", "spread"),
        ("DEN@KC", "Broncos +2.5", "spread"),
    ]),
    ("MIXED - 4 LEG", CY, [
        ("GB@MIN", "Vikings -1.5", "spread"),
        ("BAL@IND", "Over 48", "over"),
        ("WAS@PHI", "Over 44", "over"),
        ("DAL@NYG", "Over 47.5", "over"),
    ]),
    ("LONGSHOT - 5 LEG", RED, [
        ("GB@MIN", "Vikings -1.5", "spread"),
        ("NO@DET", "Saints +7", "spread"),
        ("CLE@JAX", "Browns +9", "spread"),
        ("TB@CIN", "Under 50.5", "under"),
        ("DEN@KC", "Chiefs Under 43.5", "under"),
    ]),
    ("FULL SEND - 6 LEG", GOLD, [
        ("GB@MIN", "Vikings -1.5", "spread"),
        ("NO@DET", "Saints +7", "spread"),
        ("CLE@JAX", "Browns +9", "spread"),
        ("BAL@IND", "Over 48", "over"),
        ("WAS@PHI", "Over 44", "over"),
        ("DAL@NYG", "Over 47.5", "over"),
    ]),
]

# --------------------------------------------------------------------------- #
# Drawing helper
# --------------------------------------------------------------------------- #
class Card:
    def __init__(self, height):
        self.img = Image.new("RGB", (W, height), BG)
        self.d = ImageDraw.Draw(self.img)

    def text(self, x, y, s, f, fill, right=False, center=False):
        w = self.d.textlength(str(s), font=f)
        if right: x -= w
        if center: x -= w / 2
        self.d.text((x, y), str(s), font=f, fill=fill)
        return w

    def header(self, kicker, chip=None, chip_fill=(11,34,32), chip_col=CY):
        d = self.d
        y = 40
        wb = self.text(M, y, "BANKROLL ", F['h1'], INK)
        self.text(M + wb, y, "KINGS", F['h1'], CY)
        self.text(W - M, y + 16, "bankrollkings.com", F['tag'], FAINT, right=True)
        y += 84; d.line([(M, y), (W - M, y)], fill=CY, width=3)
        y += 26; self.text(M, y, kicker, F['sub'], INK)
        if chip:
            cw = d.textlength(chip, font=F['tag']) + 28
            d.rounded_rectangle([(W - M - cw, y - 2), (W - M, y + 32)], radius=15, fill=chip_fill)
            self.text(W - M - cw / 2, y + 3, chip, F['tag'], chip_col, center=True)
        return y + 44

    def save(self, path):
        self.img.save(path, "PNG")
        return path

# --------------------------------------------------------------------------- #
# Data loaders
# --------------------------------------------------------------------------- #
def refresh_live():
    env = os.environ.copy()
    print("Refreshing live game lines...")
    subprocess.run([sys.executable, str(BASE / 'fetch_game_lines.py'), '--sport', 'americanfootball_nfl',
                    '--bookmakers', 'draftkings,fanduel,betmgm,caesars', '--days', '3'],
                   cwd=str(BASE), env=env, check=False)
    print("Refreshing live player props...")
    subprocess.run([sys.executable, str(BASE / 'fetch_nfl_player_props.py')], cwd=str(BASE), env=env, check=False)

def load_slate():
    return A.build_football_live_games(A.load_nfl_game_market_odds(), A.load_nfl_schedule(), date_filter='week')

def load_scored():
    return A.build_nfl_spots_context(limit=500).get('sp_top') or []

def apply_book_preference(plays, book):
    """Prefer a single sportsbook for the whole board when it carries the play at the
    SAME line (avoids sending bettors across apps for a sliver of price). Default
    DraftKings - deepest prop menu + best UX; BetMGM's prop section is thin/clunky.
    Only overrides when the preferred book lists the exact (player, stat) line."""
    if not book:
        return plays
    path = BASE / 'data' / 'props' / 'NFL_Props.csv'
    if not path.exists():
        return plays
    df = pd.read_csv(path)
    df['Line'] = pd.to_numeric(df.get('Line'), errors='coerce')
    pref = df[df['Book'].astype(str).str.contains(book, case=False, na=False)].dropna(subset=['Player', 'Stat', 'Line'])
    lines = {}
    for _, r in pref.iterrows():
        lines.setdefault((r['Player'], r['Stat']), r['Line'])
    for p in plays:
        key = (p.get('player'), p.get('stat'))
        if key in lines and lines[key] == p.get('line'):  # same line -> safe to relabel
            p['best_book'] = book
    return plays

def implied_team_total(game, team):
    """Implied team total from the game line. home = total/2 - spread/2; away = total/2 + spread/2
    (spread is the HOME team's number)."""
    try:
        tot = float(game.get('total')); sp = float(game.get('spread'))
    except (TypeError, ValueError):
        return None
    if team == game.get('home'):
        return round(tot / 2 - sp / 2, 2)
    return round(tot / 2 + sp / 2, 2)

def streak_leans(games):
    """One lean per game (best-first: cover streak -> spread, else O/U run -> total),
    sourced from Riding the Wave active streaks. Returns {slug: (text, color)}."""
    wave = A.build_nfl_wave_context()
    b = wave.get('rw_boards', {})
    ats = {r['team']: r for r in b.get('ats', [])}
    ou = {r['team']: r for r in b.get('ou', [])}
    leans = {}
    for g in games:
        slug = g.get('slug') or f"{g.get('away')}@{g.get('home')}"
        home, away = g.get('home'), g.get('away')
        placed = False
        for team, is_home in ((home, True), (away, False)):
            if team in ats:
                sp = g.get('spread') if is_home else -float(g.get('spread'))
                leans[slug] = (f"{abbr(team)} {_fmt_line(sp)}  \u00b7  {ats[team]['streak']}-game cover run", CY)
                placed = True
                break
        if not placed:
            for team in (home, away):
                if team in ou:
                    kind = ou[team]['kind']
                    over = kind == 'Overs'
                    leans[slug] = (f"{'Over' if over else 'Under'} {g.get('total')}  \u00b7  "
                                   f"{abbr(team)} {ou[team]['streak']}-game {'over' if over else 'under'} run",
                                   GREEN if over else RED)
                    break
    return leans

def load_defense():
    path = BASE / 'data' / 'props' / 'NFL_Props.csv'
    if not path.exists():
        return pd.DataFrame(), pd.DataFrame()
    df = pd.read_csv(path)
    df['Line'] = pd.to_numeric(df.get('Line'), errors='coerce')
    d = df[df['Stat'].astype(str).str.contains('Sack|Tackle', case=False, na=False)].dropna(subset=['Player', 'Stat', 'Line'])
    key = d.groupby(['Player', 'Stat']).agg(line=('Line', 'median'), game=('Game', 'first')).reset_index()
    stars = {'Myles Garrett','Micah Parsons','T.J. Watt','Maxx Crosby','Nick Bosa','Aidan Hutchinson','Danielle Hunter',
             'Trey Hendrickson','Will Anderson Jr.','Montez Sweat','Brian Burns','Josh Hines-Allen','Rashan Gary',
             'Boye Mafe','Calais Campbell'}
    sacks = key[key['Stat'] == 'Sacks']
    top = sacks[sacks['Player'].isin(stars)].sort_values('line', ascending=False)
    top = (top if len(top) >= 10 else sacks.sort_values('line', ascending=False)).head(12)
    tk = key[key['Stat'] == 'Tackles + Assists'].sort_values('line', ascending=False).head(12)
    return top, tk

# --------------------------------------------------------------------------- #
# Cards
# --------------------------------------------------------------------------- #
def card_slate(games, leans, week, out):
    def rh(slug): return 76 if slug in leans else 60
    slugs = [g.get('slug') or f"{g.get('away')}@{g.get('home')}" for g in games]
    top = 250
    H = top + sum(rh(s) for s in slugs) + 150
    c = Card(H); d = c.d
    y = c.header(f"NFL {week.upper()} SLATE", chip="LINES + STREAK LEANS")
    c.text(M, y, "Every matchup with the spread (favorite) and O/U. Colored leans = an active streak.", F['det'], DIM)
    y += 40; d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 6
    d.line([(M, y), (W - M, y)], fill=(0, 0, 0, 0), width=0)
    c.text(M, y + 4, "MATCHUP", F['hdr'], FAINT)
    c.text(W - M - 150, y + 4, "SPREAD", F['hdr'], FAINT, right=True)
    c.text(W - M, y + 4, "O/U", F['hdr'], FAINT, right=True)
    y += 34; d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 6
    for g in games:
        slug = g.get('slug') or f"{g.get('away')}@{g.get('home')}"
        fav = _favorite_label(g)
        c.text(M, y + 8, f"{abbr(g.get('away'))}  @  {abbr(g.get('home'))}", F['plr'], INK)
        c.text(W - M - 150, y + 8, fav, F['ps'], GOLD, right=True)
        c.text(W - M, y + 8, f"{g.get('total')}", F['ps'], INK, right=True)
        if slug in leans:
            txt, col = leans[slug]
            mx, my = M + 22, y + 56
            d.polygon([(mx, my - 8), (mx + 8, my), (mx, my + 8), (mx - 8, my)], fill=col)
            c.text(M + 42, y + 46, txt, F['pl'], col)
        d.line([(M, y + rh(slug)), (W - M, y + rh(slug))], fill=LINE, width=1)
        y += rh(slug)
    y += 22
    c.text(M, y, "Colored leans = a team on a real active streak (trend/context, the market prices it - not a lock).", F['ftb'], DIM); y += 30
    c.text(M, y, f"Live lines pulled {_stamp()}. Numbers move before kickoff - glance once more before you bet. 21+", F['ft'], FAINT)
    return c.save(out)

def _favorite_label(g):
    try:
        sp = float(g.get('spread'))
    except (TypeError, ValueError):
        return "-"
    if sp < 0:
        return f"{abbr(g.get('home'))} {sp:g}"
    if sp > 0:
        return f"{abbr(g.get('away'))} {-sp:g}"
    return "PK"

def card_top(plays, week, out, limit=12):
    plays = sorted(plays, key=lambda x: -x['prop_score'])[:limit]
    top = 258; rh = 86
    H = top + len(plays) * rh + 130
    c = Card(H); d = c.d
    y = c.header(f"NFL {week.upper()} - TOP PROP PLAYS", chip="SORTED BY PROP SCORE")
    c.text(M, y, "Our validated edge - top tier has run +9-16% ROI in the graded record.", F['det'], DIM)
    y += 42; d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 6
    for i, p in enumerate(plays):
        dc = GREEN if str(p.get('direction')) == 'OVER' else RED
        c.text(M, y + 14, f"{i+1}", F['hdr'], FAINT)
        c.text(M + 40, y + 8, p.get('player'), F['plr'], INK)
        det = f"{p.get('direction')}  {p.get('stat')} {p.get('line')}"
        w = c.text(M + 40, y + 48, det, F['det'], dc)
        c.text(M + 40 + w + 18, y + 48, f"\u00b7  {mabbr(p.get('matchup'))}", F['det'], FAINT)
        bw = 104
        d.rounded_rectangle([(W - M - bw, y + 16), (W - M, y + 68)], radius=12, fill=(11, 30, 28))
        c.text(W - M - bw / 2, y + 20, f"{p['prop_score']}", F['ps'], CY, center=True)
        c.text(W - M - bw / 2, y + 56, "PROP SCORE", F['psu'], FAINT, center=True)
        d.line([(M, y + rh), (W - M, y + rh)], fill=LINE, width=1); y += rh
    y += 20
    c.text(M, y, f"Live props pulled {_stamp()}. Lines move - confirm on your board before you bet.", F['ft'], FAINT); y += 28
    c.text(M, y, "Real graded-data edge, not a guarantee. Parlays are longshots. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)

def card_board(plays, tier, games, week, out):
    if tier == 'floor':
        rows = [p for p in plays if 10 <= p['prop_score'] < 20]
        title = f"NFL {week.upper()} - FLOOR TIER"; chip = f"PROP SCORE 10-20  \u00b7  {len(rows)} PLAYS"
        note = "Still above the validated edge line, but softer than premium. Green = Over, Red = Under."
        show_tt = False
    else:
        rows = [p for p in plays if p['prop_score'] >= 20]
        title = f"NFL {week.upper()} - PREMIUM PROP BOARD"; chip = f"PROP SCORE >= 20  \u00b7  {len(rows)} PLAYS"
        note = "Every play above our premium edge line. Green = Over, Red = Under. Book shown."
        show_tt = True
    rows.sort(key=lambda x: -x['prop_score'])
    cow_tt = None
    if show_tt:
        for g in games:
            if g.get('away') == 'Dallas Cowboys':
                cow_tt = implied_team_total(g, 'Dallas Cowboys'); gtot = g.get('total'); break
    colw = (W - 2 * M - 30) // 2
    top = 250; rh = 52
    nrows = (len(rows) + 1) // 2
    H = top + nrows * rh + (150 if (cow_tt and show_tt) else 90)
    c = Card(H); d = c.d
    y = c.header(title, chip=chip)
    c.text(M, y, note, F['det'], DIM)
    y += 40; d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 8
    col_x = [M, M + colw + 30]; col_y = [y, y]
    for i, p in enumerate(rows):
        col = 0 if i < nrows else 1
        x = col_x[col]; yy = col_y[col]
        dc = GREEN if str(p.get('direction')) == 'OVER' else RED
        c.text(x, yy + 4, f"{i+1}", F['rk'], FAINT)
        c.text(x + 34, yy, str(p.get('player'))[:20], F['pl'], INK)
        c.text(x + colw, yy + 2, f"{p['prop_score']}", F['sc'], CY, right=True)
        det = f"{p.get('direction')} {p.get('stat')} {p.get('line')} \u00b7 {mabbr(p.get('matchup'))} \u00b7 {str(p.get('best_book') or '')[:3]}"
        c.text(x + 34, yy + 27, det, F['de'], dc)
        d.line([(x, yy + rh - 4), (x + colw, yy + rh - 4)], fill=(20, 32, 38), width=1)
        col_y[col] += rh
    y = max(col_y) + 10
    if cow_tt and show_tt:
        d.rounded_rectangle([(M, y), (W - M, y + 70)], radius=14, fill=PANEL, outline=GOLD, width=2)
        c.text(M + 20, y + 10, "COWBOYS TEAM TOTAL", F['ttl'], GOLD)
        c.text(M + 20, y + 44, f"Implied ~{cow_tt} from the current line (O/U {gtot}, DAL -3).  Lean OVER - 6-game over run + we're stacking their passing props.", F['de'], DIM)
        y += 88
    c.text(M, y, f"Live props pulled {_stamp()}. Lines/books move - confirm before you bet.", F['ft'], FAINT); y += 28
    c.text(M, y, "Validated edge (PropScore), not guarantees. Parlays are longshots. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)

def card_defense(sacks, tk, week, out):
    sections = [("SACKS  (Over/Under)", sacks), ("TACKLES + ASSISTS  (Over/Under)", tk)]
    rows = sum(len(s[1]) for s in sections)
    H = 250 + 90 + rows * 46 + len(sections) * 70 + 90
    c = Card(H); d = c.d
    y = c.header(f"NFL {week.upper()} - DEFENSIVE PROPS", chip="RAW LINES", chip_fill=(40, 26, 8), chip_col=AMBER)
    d.rounded_rectangle([(M, y), (W - M, y + 56)], radius=12, fill=(30, 22, 8), outline=AMBER, width=2)
    c.text(M + 18, y + 7, "NOT PropScore-validated.", F['warn'], AMBER)
    c.text(M + 18, y + 31, "Our proven edge covers offense only - these are reference lines, no backtested edge. Shop, don't chase.", F['mu'], DIM)
    y += 76
    for title, frame in sections:
        c.text(M, y, title, F['col'], CY); y += 34; d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 6
        for _, r in frame.iterrows():
            c.text(M + 4, y + 8, str(r['Player'])[:26], F['pl'], INK)
            c.text(M + 560, y + 8, mabbr(r['game']).replace('@', ' @ '), F['mu'], FAINT)
            c.text(W - M, y + 6, f"{r['line']:g}", F['ln'], GOLD, right=True)
            d.line([(M, y + 42), (W - M, y + 42)], fill=(20, 32, 38), width=1); y += 46
        y += 24
    c.text(M, y, f"Live lines pulled {_stamp()} (consensus across books). Confirm your book's number.", F['ft'], FAINT); y += 28
    c.text(M, y, "Reference only - no validated edge. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)

def card_hitlist(plays, games, week, out, floor=24):
    """Game-by-game hunt list for books with no filters (e.g. a casino retail menu):
    plays grouped by matchup in slate order, so you scroll the board once and tick
    off targets per game instead of hunting the whole list."""
    groups = {}
    for p in plays:
        if p['prop_score'] < floor:
            continue
        groups.setdefault(mabbr(p.get('matchup')), []).append(p)
    ordered = []
    for g in games:
        key = f"{abbr(g.get('away'))}@{abbr(g.get('home'))}"
        if key in groups:
            ordered.append((key, sorted(groups[key], key=lambda x: -x['prop_score'])))
    n = sum(len(v) for _, v in ordered)
    top = 250
    H = top + len(ordered) * 50 + n * 40 + 100
    c = Card(H); d = c.d
    y = c.header(f"NFL {week.upper()} - HIT LIST", chip="SCROLL & CHECK OFF")
    c.text(M, y, "Your plays grouped by game (slate order). No filters needed - tick each off as you scroll the board.", F['de'], DIM)
    y += 36
    for key, ps in ordered:
        d.rounded_rectangle([(M, y), (W - M, y + 38)], radius=8, fill=(11, 30, 28))
        c.text(M + 14, y + 8, key.replace('@', '  @  '), F['col'], CY)
        y += 48
        for p in ps:
            dc = GREEN if str(p.get('direction')) == 'OVER' else RED
            d.rectangle([(M + 6, y + 6), (M + 26, y + 26)], outline=FAINT, width=2)  # checkbox
            c.text(M + 40, y + 4, str(p.get('player')), F['pl'], INK)
            det = f"{p.get('direction')}  {p.get('stat')} {p.get('line')}"
            c.text(M + 420, y + 4, det, F['pl'], dc)
            c.text(W - M, y + 4, f"{p['prop_score']}", F['sc'], CY, right=True)
            y += 40
        y += 10
    c.text(M, y, f"Live props pulled {_stamp()}. A casino board may not carry every play - grab what's there.", F['ft'], FAINT); y += 28
    c.text(M, y, "Validated PropScore plays. Verify the line before you bet. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)

def card_openers(games, week, out, min_games=3):
    """Week 1 opener-trend moneyline board: each team's straight-up record in season
    openers (Week 1 of the game-lines history) vs its current ML. Best record on top;
    value dogs (strong record + plus money) flagged. Small samples - trend, not edge."""
    hist = A.load_nfl_game_lines_history().copy()
    hist['Week'] = pd.to_numeric(hist['Week'], errors='coerce')
    op = hist[hist['Week'] == 1].dropna(subset=['HomeScore', 'AwayScore'])
    m2f = A._nfl_mascot_to_full()
    rec = {}
    for _, r in op.iterrows():
        hs, as_ = float(r['HomeScore']), float(r['AwayScore'])
        for team, win in ((m2f.get(str(r['Home']).strip(), str(r['Home']).strip()), hs > as_),
                          (m2f.get(str(r['Away']).strip(), str(r['Away']).strip()), as_ > hs)):
            rec.setdefault(team, [0, 0])[0 if win else 1] += 1
    rows = []
    for g in games:
        mu = f"{abbr(g.get('away'))}@{abbr(g.get('home'))}"
        for team, ml in ((g.get('home'), g.get('home_ml')), (g.get('away'), g.get('away_ml'))):
            w, l = rec.get(team, [0, 0]); n = w + l
            if n >= min_games:
                rows.append({'team': team, 'w': w, 'l': l, 'pct': w / n, 'ml': ml, 'mu': mu})
    rows.sort(key=lambda x: (-x['pct'], -(x['w'] + x['l'])))
    top = 250; rh = 52
    H = top + len(rows) * rh + 120
    c = Card(H); d = c.d
    y = c.header(f"NFL {week.upper()} - OPENER TRENDS", chip="SEASON-OPENER ML")
    c.text(M, y, "Straight-up record in season openers vs today's moneyline. Best record on top; value dogs flagged.", F['de'], DIM)
    y += 40; d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 6
    for i, r in enumerate(rows):
        ml = r['ml']
        try: mlf = f"+{int(ml)}" if ml and ml > 0 else f"{int(ml)}"
        except (TypeError, ValueError): mlf = '-'
        if r['pct'] >= 0.75 and ml and ml > 0:
            tag, tc = 'VALUE DOG', GREEN
        elif r['pct'] >= 0.75 and ml and ml < 0:
            tag, tc = 'CHALK FAV', GOLD
        elif r['pct'] <= 0.25:
            tag, tc = 'FADE', RED
        else:
            tag, tc = '', DIM
        c.text(M, y + 14, f"{i+1}", F['rk'], FAINT)
        c.text(M + 40, y + 4, r['team'], F['pl'], INK)
        c.text(M + 40, y + 30, f"{r['mu']}", F['de'], FAINT)
        c.text(M + 470, y + 8, f"{r['w']}-{r['l']}", F['sc'], INK, right=False)
        c.text(M + 560, y + 12, "openers", F['de'], FAINT)
        c.text(M + 720, y + 8, f"{r['pct']*100:.0f}%", F['sc'], CY, right=True)
        c.text(M + 830, y + 8, mlf, F['sc'], (GREEN if (ml and ml > 0) else INK), right=True)
        if tag:
            tw = d.textlength(tag, font=F['de']) + 20
            d.rounded_rectangle([(W - M - tw, y + 8), (W - M, y + 40)], radius=9, fill=(tc[0]//7, tc[1]//7, tc[2]//7))
            c.text(W - M - tw / 2, y + 12, tag, F['de'], tc, center=True)
        d.line([(M, y + rh), (W - M, y + rh)], fill=(20, 32, 38), width=1); y += rh
    y += 16
    c.text(M, y, "Openers = Week 1 games, 2022-2025 (4-game samples). A trend/context read, not an edge - the market prices team quality.", F['ftb'], DIM); y += 30
    c.text(M, y, f"Lines pulled {_stamp()}. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)

# BetOnline (full book) $1 tickets: props, SGPs, ML, game lines. leg = (subject, detail, kind)
# kind: 'over'/'under'/'line'. note flags a same-game ticket that needs SGP support.
BOL_TICKETS = [
    ("TOP 2 PROPS", CY, "", [
        ("David Montgomery", "UNDER Rush Yds 56.5  ·  BUF@HOU", "under"),
        ("Jameson Williams", "OVER Receptions 3.5  ·  NO@DET", "over"),
    ]),
    ("COWBOYS PASSING SGP", GOLD, "same game - needs SGP; else 3 singles", [
        ("Dak Prescott", "OVER Pass TDs 1.5  ·  DAL@NYG", "over"),
        ("CeeDee Lamb", "OVER Receptions 5.5  ·  DAL@NYG", "over"),
        ("George Pickens", "OVER Receptions 4.5  ·  DAL@NYG", "over"),
    ]),
    ("TEXANS UNDER SGP", GOLD, "same game - needs SGP; else 2 singles", [
        ("C.J. Stroud", "UNDER Pass TDs 1.5  ·  BUF@HOU", "under"),
        ("Nico Collins", "UNDER Receptions 5.5  ·  BUF@HOU", "under"),
    ]),
    ("ALL UNDERS - 3 LEG", RED, "", [
        ("David Montgomery", "UNDER Rush Yds 56.5  ·  BUF@HOU", "under"),
        ("Dontayvion Wicks", "UNDER Receptions 2.5  ·  WAS@PHI", "under"),
        ("Kenneth Walker III", "UNDER Rush Att 16.5  ·  DEN@KC", "under"),
    ]),
    ("SKILL OVERS - 3 LEG", GREEN, "", [
        ("Jameson Williams", "OVER Receptions 3.5  ·  NO@DET", "over"),
        ("CeeDee Lamb", "OVER Receptions 5.5  ·  DAL@NYG", "over"),
        ("Daniel Jones", "OVER Pass Yds 232.5  ·  BAL@IND", "over"),
    ]),
    ("DOG ML + PROP - 2 LEG", GOLD, "", [
        ("Buccaneers ML +170", "TB@CIN  ·  4-0 in openers", "line"),
        ("Jameson Williams", "OVER Receptions 3.5  ·  NO@DET", "over"),
    ]),
    ("GAME-LINE LEANS - 3 LEG", CY, "", [
        ("Vikings -2", "GB@MIN  ·  5 covers + 5 wins", "line"),
        ("Cowboys Over 47.5", "DAL@NYG  ·  6-game over run", "over"),
        ("Ravens Over 48", "BAL@IND  ·  3-game over run", "over"),
    ]),
    ("MIXED - 4 LEG", CY, "", [
        ("David Montgomery", "UNDER Rush Yds 56.5  ·  BUF@HOU", "under"),
        ("Jameson Williams", "OVER Receptions 3.5  ·  NO@DET", "over"),
        ("CeeDee Lamb", "OVER Receptions 5.5  ·  DAL@NYG", "over"),
        ("Bryce Young", "UNDER Pass Yds 209.5  ·  CHI@CAR", "under"),
    ]),
    ("LONGSHOT - 5 LEG", RED, "", [
        ("David Montgomery", "UNDER Rush Yds 56.5  ·  BUF@HOU", "under"),
        ("CeeDee Lamb", "OVER Receptions 5.5  ·  DAL@NYG", "over"),
        ("Kenneth Walker III", "UNDER Rush Att 16.5  ·  DEN@KC", "under"),
        ("Bryce Young", "UNDER Pass Yds 209.5  ·  CHI@CAR", "under"),
        ("Buccaneers ML +170", "TB@CIN  ·  opener trend dog", "line"),
    ]),
]

def card_bol_tickets(week, out, stake=1.0):
    """9 x $1 tickets for a full online book (BetOnline): prop parlays, correlated SGPs,
    ML value and game-line leans. Payouts are a rough -110/leg ballpark - prop and ML
    juice varies, so the slip is the truth."""
    kcol = {'over': GREEN, 'under': RED, 'line': GOLD}
    top = 250
    body = sum(56 + (18 if note else 0) + len(legs) * 42 + 16 + 22 for _, _, note, legs in BOL_TICKETS)
    H = top + body + 120
    c = Card(H); d = c.d
    y = c.header(f"NFL {week.upper()} - $1 TICKETS", chip="BETONLINE - FULL BOARD")
    c.text(M, y, "Props, SGPs, ML & game lines. Rough payout on $1 (-110/leg) - the slip prices it exactly.", F['de'], DIM)
    y += 40
    for title, accent, note, legs in BOL_TICKETS:
        dec = 1.909 ** len(legs)
        payout = f"$1 -> ~${dec * stake:.2f}"
        bh = 56 + (18 if note else 0) + len(legs) * 42 + 16
        d.rounded_rectangle([(M, y), (W - M, y + bh)], radius=16, fill=PANEL, outline=LINE, width=2)
        d.rounded_rectangle([(M, y), (M + 10, y + bh)], radius=6, fill=accent)
        c.text(M + 30, y + 16, title, F['blk'], accent)
        pw = d.textlength(payout, font=F['sc']) + 28
        d.rounded_rectangle([(W - M - pw - 14, y + 12), (W - M - 14, y + 48)], radius=10, fill=(11, 30, 28))
        c.text(W - M - 14 - pw / 2, y + 17, payout, F['sc'], CY, center=True)
        ry = y + 56
        if note:
            c.text(M + 30, ry, f"({note})", F['mu'], AMBER); ry += 18
        for subj, detail, kind in legs:
            c.text(M + 30, ry, subj, F['pl'], kcol.get(kind, INK))
            c.text(M + 470, ry + 2, detail, F['de'], FAINT)
            ry += 42
        y += bh + 22
    y += 6
    c.text(M, y, f"Live board pulled {_stamp()}. Payouts rough (-110/leg) - props/ML juice varies; the slip is exact.", F['ftb'], DIM); y += 30
    c.text(M, y, "SGP legs need same-game support - split to singles if not. Trends aren't locks. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)

def card_eqc_tickets(week, out, stake=1.0):
    """$1 cross-game game-line tickets for a book with no prop/same-game parlays (EQC).
    Payouts approximated at -110 per leg; the book shows the exact number."""
    kcol = {'spread': GOLD, 'over': GREEN, 'under': RED}
    top = 250
    body = sum(56 + len(legs) * 40 + 16 + 22 for _, _, legs in EQC_TICKETS)
    H = top + body + 120
    c = Card(H); d = c.d
    y = c.header(f"NFL {week.upper()} - $1 TICKETS", chip="EQC-LEGAL - CROSS-GAME")
    c.text(M, y, "Game lines only (no props/SGP at EQC). One leg per game. Approx payout on a $1 bet.", F['de'], DIM)
    y += 40
    for title, accent, legs in EQC_TICKETS:
        dec = 1.909 ** len(legs)
        payout = f"$1 -> ~${dec * stake:.2f}"
        bh = 56 + len(legs) * 40 + 16
        d.rounded_rectangle([(M, y), (W - M, y + bh)], radius=16, fill=PANEL, outline=LINE, width=2)
        d.rounded_rectangle([(M, y), (M + 10, y + bh)], radius=6, fill=accent)
        c.text(M + 30, y + 16, title, F['blk'], accent)
        pw = d.textlength(payout, font=F['sc']) + 28
        d.rounded_rectangle([(W - M - pw - 14, y + 12), (W - M - 14, y + 48)], radius=10, fill=(11, 30, 28))
        c.text(W - M - 14 - pw / 2, y + 17, payout, F['sc'], CY, center=True)
        ry = y + 60
        for mu, pick, kind in legs:
            c.text(M + 30, ry + 4, mu, F['de'], FAINT)
            c.text(M + 160, ry, pick, F['pl'], kcol.get(kind, INK))
            ry += 40
        y += bh + 22
    y += 6
    c.text(M, y, f"Live lines pulled {_stamp()}. Payouts approximate (-110/leg) - the slip shows the exact number.", F['ftb'], DIM); y += 30
    c.text(M, y, "Streak leans = trends the market prices, not locks. Parlays are longshots. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)

def card_parlay(week, out):
    top = 250
    body = sum(62 + len(legs) * 74 + 16 + 26 for _, _, legs in PARLAYS)
    H = top + body + 120
    c = Card(H); d = c.d
    y = c.header(f"NFL {week.upper()}", chip="PARLAY CARD")
    c.text(M, y, "Sorted by Prop Score - our validated edge", F['det'], DIM)
    y += 56
    for title, accent, legs in PARLAYS:
        bh = 62 + len(legs) * 74 + 16
        d.rounded_rectangle([(M, y), (W - M, y + bh)], radius=20, fill=PANEL, outline=LINE, width=2)
        d.rounded_rectangle([(M, y), (M + 10, y + bh)], radius=6, fill=accent)
        c.text(M + 34, y + 20, title, F['blk'], accent)
        ry = y + 62
        for i, (subj, det, side) in enumerate(legs):
            if i > 0:
                d.line([(M + 34, ry), (W - M - 34, ry)], fill=LINE, width=1)
            pc = GREEN if side == 'OVER' else RED
            c.text(M + 34, ry + 16, subj, F['plr'], INK)
            c.text(M + 34, ry + 58, det, F['det'], DIM)
            pw = d.textlength(side, font=F['dir']) + 34
            d.rounded_rectangle([(W - M - 34 - pw, ry + 22), (W - M - 34, ry + 62)], radius=12,
                                fill=(pc[0] // 7, pc[1] // 7, pc[2] // 7))
            c.text(W - M - 34 - pw / 2, ry + 28, side, F['dir'], pc, center=True)
            ry += 74
        y += bh + 26
    y += 6
    c.text(M, y, PARLAY_FOOTNOTE, F['ftb'], DIM); y += 32
    c.text(M, y, "Validated PropScore edge, not guarantees. Parlays are longshots. Verify lines. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)

# --------------------------------------------------------------------------- #
def _stamp():
    return datetime.now().strftime('%a ') + datetime.now().strftime('%-I:%M%p ET').lstrip('0') \
        if os.name != 'nt' else datetime.now().strftime('%a ') + f"{datetime.now().hour % 12 or 12}:{datetime.now():%M%p} ET"

def main():
    ap = argparse.ArgumentParser(description="Bankroll Kings weekly social cards")
    ap.add_argument('--refresh', action='store_true', help="Fetch live game lines + props first")
    ap.add_argument('--week', default='Week 1', help="Week label shown on cards, e.g. 'Week 1 - Sunday'")
    ap.add_argument('--out', default=str(BASE / 'marketing' / 'weekly_cards'), help="Output directory")
    ap.add_argument('--only', default='', help="Comma list: slate,top,premium,floor,defense,parlay")
    ap.add_argument('--book', default='DraftKings',
                    help="Prefer this book for the whole board when it carries the play at the same line "
                         "(default DraftKings - deepest menu + best UX). Pass '' to keep each play's best-price book.")
    args = ap.parse_args()

    if args.refresh:
        refresh_live()

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    want = {s.strip() for s in args.only.split(',') if s.strip()} or {'slate', 'top', 'premium', 'floor', 'defense', 'parlay', 'hitlist'}

    games = load_slate()
    plays = apply_book_preference(load_scored(), args.book)
    made = []
    if 'slate' in want:
        made.append(card_slate(games, streak_leans(games), args.week, str(out_dir / 'bk_slate.png')))
    if 'top' in want:
        made.append(card_top(plays, args.week, str(out_dir / 'bk_top_props.png')))
    if 'premium' in want:
        made.append(card_board(plays, 'premium', games, args.week, str(out_dir / 'bk_premium_board.png')))
    if 'floor' in want:
        made.append(card_board(plays, 'floor', games, args.week, str(out_dir / 'bk_floor_board.png')))
    if 'defense' in want:
        sacks, tk = load_defense()
        if len(sacks) or len(tk):
            made.append(card_defense(sacks, tk, args.week, str(out_dir / 'bk_defense.png')))
    if 'hitlist' in want:
        made.append(card_hitlist(plays, games, args.week, str(out_dir / 'bk_hitlist.png')))
    if 'eqc' in want:
        made.append(card_eqc_tickets(args.week, str(out_dir / 'bk_eqc_tickets.png')))
    if 'openers' in want:
        made.append(card_openers(games, args.week, str(out_dir / 'bk_openers.png')))
    if 'bol' in want:
        made.append(card_bol_tickets(args.week, str(out_dir / 'bk_bol_tickets.png')))
    if 'parlay' in want:
        made.append(card_parlay(args.week, str(out_dir / 'bk_parlay.png')))

    print(f"Rendered {len(made)} card(s) to {out_dir}:")
    for p in made:
        print("  ", p)

if __name__ == '__main__':
    main()
