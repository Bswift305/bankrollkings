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

# 15-leg teaser-style floor longshot: conservative OVER floors (take the lowest alt rung
# on the book). Derived from main lines - match each to the book's alt ladder + real price.
FLOOR_LONGSHOT = [
    ("Joe Burrow", "OVER 225 Pass Yds", "TB@CIN"),
    ("Dak Prescott", "OVER 210 Pass Yds", "DAL@NYG"),
    ("Jared Goff", "OVER 210 Pass Yds", "NO@DET"),
    ("Justin Herbert", "OVER 190 Pass Yds", "ARI@LAC"),
    ("Trevor Lawrence", "OVER 185 Pass Yds", "CLE@JAX"),
    ("Caleb Williams", "OVER 180 Pass Yds", "CHI@CAR"),
    ("Patrick Mahomes", "OVER 180 Pass Yds", "DEN@KC"),
    ("Josh Allen", "OVER 175 Pass Yds", "BUF@HOU"),
    ("Derrick Henry", "OVER 55 Rush Yds", "BAL@IND"),
    ("Saquon Barkley", "OVER 50 Rush Yds", "WAS@PHI"),
    ("Bijan Robinson", "OVER 50 Rush Yds", "ATL@PIT"),
    ("De'Von Achane", "OVER 45 Rush Yds", "MIA@LV"),
    ("Breece Hall", "OVER 45 Rush Yds", "NYJ@TEN"),
    ("Justin Jefferson", "OVER 50 Rec Yds", "GB@MIN"),
    ("Ja'Marr Chase", "OVER 55 Rec Yds", "TB@CIN"),
]

FLOOR_LONGSHOT_2 = [
    ("Baker Mayfield", "OVER 185 Pass Yds", "TB@CIN"),
    ("Bo Nix", "OVER 180 Pass Yds", "DEN@KC"),
    ("Jordan Love", "OVER 190 Pass Yds", "GB@MIN"),
    ("Aaron Rodgers", "OVER 170 Pass Yds", "ATL@PIT"),
    ("Jonathan Taylor", "OVER 50 Rush Yds", "BAL@IND"),
    ("James Cook", "OVER 50 Rush Yds", "BUF@HOU"),
    ("Javonte Williams", "OVER 50 Rush Yds", "DAL@NYG"),
    ("D'Andre Swift", "OVER 40 Rush Yds", "CHI@CAR"),
    ("Ashton Jeanty", "OVER 40 Rush Yds", "MIA@LV"),
    ("Quinshon Judkins", "OVER 38 Rush Yds", "CLE@JAX"),
    ("Amon-Ra St. Brown", "OVER 50 Rec Yds", "NO@DET"),
    ("Chris Olave", "OVER 48 Rec Yds", "NO@DET"),
    ("DeVonta Smith", "OVER 42 Rec Yds", "WAS@PHI"),
    ("Garrett Wilson", "OVER 40 Rec Yds", "NYJ@TEN"),
    ("Trey McBride", "OVER 38 Rec Yds", "ARI@LAC"),
]

# Single-game SGP tickets (a full book that allows same-game parlays). Edit per game.
SGP_GAME = "ATL @ GB  ·  TNF  ·  GB -4.5  ·  O/U 43  (thin props — injury-driven)"
SGP_TICKETS = [
    ("INJURY EDGE SGP", GOLD, "ATL down CB1 Terrell + edge Ebukam — GB airs it out, ATL chases", [
        ("Jordan Love", "OVER Pass TDs 1.5", "over"),
        ("Michael Penix Jr", "OVER Pass Comp 18.5", "over"),
    ]),
    ("GB CONTROL SGP", CY, "Love throws (not runs) with a lead; Bijan quiet as a receiver", [
        ("Jordan Love", "OVER Pass TDs 1.5", "over"),
        ("Jordan Love", "UNDER Rush Yds 8.5", "under"),
        ("Bijan Robinson", "UNDER Rec Yds 41.5", "under"),
    ]),
]

LONGSHOT_GAME = "DET @ BUF  ·  TNF  ·  BUF -5.5  ·  O/U 55"
LONGSHOT_TITLE = "SHOOTOUT LONGSHOT  ·  7-LEG SGP"
LONGSHOT_THESIS = "everything cashes if it's the high-scoring passing game the 55 total implies"
LONGSHOT_LEGS = [
    ("Game Total", "OVER 55", "line"),
    ("Jared Goff", "OVER Pass Yds 261.5", "over"),
    ("Josh Allen", "OVER Pass Yds 253.5", "over"),
    ("Jared Goff", "OVER Pass TDs 1.5", "over"),
    ("Josh Allen", "OVER Pass TDs 1.5", "over"),
    ("Jameson Williams", "OVER Rec Yds 57.5", "over"),
    ("Amon-Ra St. Brown", "OVER Rec Yds 79.5", "over"),
]


def card_game_longshot(week, out):
    """One big single-game shootout longshot SGP. Correlated legs -> the book prices
    it correlation-adjusted (a big number, but less than the same legs independent)."""
    kcol = {'over': GREEN, 'under': RED, 'line': GOLD}
    legs = LONGSHOT_LEGS
    top = 250; rh = 48
    H = top + 40 + len(legs) * rh + 150
    c = Card(H); d = c.d
    y = c.header("NFL - TONIGHT'S LONGSHOT", chip="SAME-GAME PARLAY")
    c.text(M, y, LONGSHOT_GAME, F['sub'], INK); y += 34
    c.text(M, y, LONGSHOT_TITLE, F['blk'], GOLD); y += 30
    c.text(M, y, f"({LONGSHOT_THESIS})", F['de'], DIM); y += 34
    d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 8
    for i, (subj, detail, kind) in enumerate(legs):
        d.rectangle([(M + 4, y + 6), (M + 24, y + 26)], outline=FAINT, width=2)
        c.text(M + 38, y + 4, f"{subj}", F['pl'], INK)
        c.text(M + 470, y + 4, detail, F['pl'], kcol.get(kind, INK))
        d.line([(M, y + rh), (W - M, y + rh)], fill=(20, 32, 38), width=1); y += rh
    y += 18
    c.text(M, y, f"Live board pulled {_stamp()}. 7 correlated legs — the book sets the SGP price (a big number,", F['ftb'], DIM); y += 30
    c.text(M, y, "but correlation-adjusted, not 7 independent legs). It's a lottery ticket: one quiet stat busts it. 21+", F['ft'], FAINT)
    return c.save(out)


CFB_READS_TITLE = "CFB SATURDAY — CURRENT-FORM READS"
CFB_READS = [
    ("Clemson @ Cal  (pick'em)", "Cal +1 / ML", "Clemson's underperforming badly (-6 avg margin); Cal +8. Fade the ranked name."),
    ("Ole Miss @ Florida  (-3)", "Florida -3", "Florida dominant early (+33/gm) at home; Ole Miss solid but a step back (+14)."),
    ("Iowa @ Michigan  (O/U 38.5)", "Iowa +5.5 + Under 38.5", "Iowa the better form team (+32.7); low-total Big Ten grind favors the under."),
    ("South Alabama @ Kentucky  (-20.5)", "South Alabama +20.5", "Kentucky winning by only ~5/gm — laying 20.5 is an overvalued-SEC fade."),
    ("Nebraska @ Michigan State  (+6)", "Nebraska +6", "Nebraska rolling (+34.7 margin) vs a middling MSU (+7)."),
]


SUNDAY_WEATHER = [
    ("LAR @ DEN", "UNDER 45", "19 mph"),
    ("TEN @ NYG", "UNDER 38.5", "15 mph"),
]
SUNDAY_CLEAN = [  # top PropScore plays with NO usage/archetype flag
    ("Dak Prescott", "OVER Pass TDs 1.5", "BAL@DAL", 35.3),
    ("C.J. Stroud", "UNDER Pass TDs 1.5", "HOU@IND", 35.0),
    ("Drake Maye", "OVER Pass Yds 218.5", "NE@JAX", 35.0),
    ("Lamar Jackson", "UNDER Rush Yds 38.5", "BAL@DAL", 33.5),
    ("Bryce Young", "UNDER Pass Yds 227.5", "CAR@CLE", 33.0),
    ("Patrick Mahomes", "OVER Pass Yds 234.5", "KC@MIA", 32.7),
    ("Ja'Marr Chase", "OVER Rec Yds 75.5", "CIN@PIT", 31.3),
]
SUNDAY_PARLAYS = [
    ("CLEAN 3-LEG · cross-game", CY, [
        ("Dak Prescott", "OVER Pass TDs 1.5", "over"),
        ("Ja'Marr Chase", "OVER Rec Yds 75.5", "over"),
        ("C.J. Stroud", "UNDER Pass TDs 1.5", "under"),
    ]),
    ("HOU@IND UNDER SGP", RED, [
        ("C.J. Stroud", "UNDER Pass TDs 1.5", "under"),
        ("Daniel Jones", "UNDER Rush Yds 11.5", "under"),
    ]),
]


def card_sunday_best(week, out):
    """Curated NFL Sunday card: weather-unders + the clean top PropScore plays (no
    usage/archetype flag) + two parlays."""
    kcol = {'over': GREEN, 'under': RED}
    top = 250
    H = (top + 46 + len(SUNDAY_WEATHER) * 40 + 60 + len(SUNDAY_CLEAN) * 44
         + sum(56 + len(l) * 40 + 16 for _, _, l in SUNDAY_PARLAYS) + 120)
    c = Card(H); d = c.d
    y = c.header(f"NFL {week.upper()} — SUNDAY BEST", chip="CLEAN PLAYS + WEATHER")

    # Weather
    d.rounded_rectangle([(M, y), (W - M, y + 42 + len(SUNDAY_WEATHER) * 40)], radius=12,
                        fill=(255//12, 176//12, 90//12), outline=(255, 176, 90), width=2)
    c.text(M + 16, y + 10, "WEATHER — WIND UNDERS", F['blk'], GOLD)
    yy = y + 46
    for mu, pick, wind in SUNDAY_WEATHER:
        c.text(M + 20, yy, mu, F['pl'], INK)
        c.text(M + 300, yy + 2, pick, F['pl'], RED)
        c.text(W - M - 20, yy + 2, wind, F['de'], FAINT, right=True)
        yy += 40
    y = yy + 18

    # Clean plays
    c.text(M, y, "CLEAN TOP PLAYS", F['col'], CY)
    c.text(W - M, y + 2, "no flags — trust these", F['de'], FAINT, right=True)
    y += 30; d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 8
    for i, (player, pick, mu, score) in enumerate(SUNDAY_CLEAN):
        c.text(M + 4, y + 6, f"{i+1}", F['rk'], FAINT)
        c.text(M + 34, y + 2, player, F['pl'], INK)
        c.text(M + 380, y + 4, pick, F['de'], GREEN if 'OVER' in pick else RED)
        c.text(M + 700, y + 6, mu, F['de'], FAINT)
        c.text(W - M, y + 2, f"{score}", F['sc'], CY, right=True)
        d.line([(M, y + 40), (W - M, y + 40)], fill=(20, 32, 38), width=1); y += 44
    y += 16

    # Parlays
    for title, accent, legs in SUNDAY_PARLAYS:
        bh = 50 + len(legs) * 40
        d.rounded_rectangle([(M, y), (W - M, y + bh)], radius=14, fill=PANEL, outline=LINE, width=2)
        d.rounded_rectangle([(M, y), (M + 10, y + bh)], radius=6, fill=accent)
        c.text(M + 30, y + 14, title, F['blk'], accent)
        ry = y + 50
        for subj, detail, kind in legs:
            c.text(M + 30, ry, subj, F['pl'], INK)
            c.text(M + 420, ry + 2, detail, F['pl'], kcol.get(kind, INK))
            ry += 40
        y += bh + 16
    y += 6
    c.text(M, y, f"Live board pulled {_stamp()}. Clean = no usage/archetype flag. Verify lines on Caesars.", F['ftb'], DIM); y += 30
    c.text(M, y, "Validated PropScore edge, not guarantees. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)


# ATL @ GB (Thu Week 3) — "The Good" tier: props where 2026 form + injuries stack the
# same way. Each: player, pick, kind, one-line why (grounded in usage + availability).
ATLGB_GAME = ("ATL @ GB", "Thu · GB -4.5 · O/U 42.5")
ATLGB_GOOD = [
    ("Christian Watson", "OVER 70.5 Rec Yds", "over",
     "94/gm pace · WR1 with Reed & S.Williams OUT · ATL's CB1 Terrell OUT"),
    ("Matthew Golden", "OVER 52.5 Rec Yds", "over",
     "76.5/gm pace · co-No.1 on the same target vacuum · Terrell OUT"),
    ("Bijan Robinson", "UNDER 39.5 Rec Yds", "under",
     "checkdown volume drops with Penix pushing the ball downfield"),
]
ATLGB_CTX = "Both run D's rank top-5 opponent-adjusted — ground games get stuffed, the total rides on passing."
# Game-level play: the same read expressed on the 1H total (median across books).
ATLGB_PERIOD = ("1st Half Team Total", "UNDER 20.5", "under",
                "both run D's top-5 adj — slow, run-stuffed start; the total needs passing, which takes time to warm up")


# CFB Wave Watch — Week 4. Full board of options. (team, pick, why)
# RIDES: ATS coverers the model also likes this week. WAVE: the undefeated (3-0 ATS)
# teams laying bigger numbers -- covering all year, but the model says the price is rich.
CFBWAVE_RIDES = [
    ("Penn State", "-10 vs Wisconsin", "2-1 ATS · rising · model +4"),
    ("New Mexico", "-11.2 vs NM State", "3-0 ATS · surging · model +3"),
    ("Michigan St", "+5.8 vs Nebraska", "surging home dog · model +4"),
    ("Oklahoma St", "+1.8 vs W. Virginia", "2-1 ATS · dog + points · model +5"),
    ("Colorado St", "+14 vs UTSA", "2-1 ATS · getting two scores · model +4"),
]
CFBWAVE_WAVE = [
    ("Georgia", "-13.5 vs Oklahoma", "3-0 ATS, +8 · OU collapsed but the number's rich"),
    ("Mississippi St", "-6 vs Missouri", "3-0 ATS, +18 · surging · both 3-0, coin flip"),
    ("Utah", "-7.5 @ Iowa State", "3-0 ATS · surging · road, near-fair number"),
    ("Louisville", "-12.5 vs Wake", "3-0 ATS · rising · the price has climbed"),
    ("Ohio State", "-26.5 vs Illinois", "3-0 ATS · Illinois regressed · big lay"),
]


# CFB Totals — Week 4. Only plays where the model AND the line move agree (the market
# isn't fighting it). Totals are the noisiest market, so confirmation matters most.
CFBTOT_OVERS = [
    ("Kansas St @ Cincinnati", "OVER 55.5", "model 60 · line rose to meet it · two soft D's"),
]
CFBTOT_UNDERS = [
    ("Oklahoma @ Georgia", "UNDER 43.8", "model 40 · OU offense broken (10 & 14 pts), two good D's"),
    ("Texas A&M @ LSU", "UNDER 51.8", "model 48 · line fell, market agrees"),
    ("Wisconsin @ Penn St", "UNDER 43.8", "model 40 · pairs with the PSU -10 ride"),
    ("Wake Forest @ Louisville", "UNDER 57.2", "model 54 · move agrees"),
]


# CFB Week 4 — five diversified 3-leg tickets ($5 each), built from the clean board.
CFB_PARLAYS = [
    ("1 · MODEL ATS RIDES", CY, [("Penn State", "-10"), ("Oklahoma St", "+1.8"), ("New Mexico", "-11.2")]),
    ("2 · UNDERS", RED, [("Okla @ Georgia", "U 43.8"), ("A&M @ LSU", "U 51.8"), ("Wake @ Louisville", "U 57.2")]),
    ("3 · DOGS + OVER", GREEN, [("Michigan St", "+5.8"), ("Colorado St", "+14"), ("KSU @ Cincy", "O 55.5")]),
    ("4 · THE 3-0 WAVE", GOLD, [("Georgia", "-13.5"), ("Utah", "-7.5"), ("Miss State", "-6")]),
    ("5 · PENN STATE STACK", CY, [("Penn State", "-10"), ("Wisc @ PSU", "U 43.8"), ("Michigan St", "+5.8")]),
]


def card_cfb_parlays(week, out):
    """Five diversified 3-leg CFB tickets ($5 each), casino-ready."""
    top = 250
    lh = 34
    bh_of = lambda legs: 46 + len(legs) * lh
    H = top + 44 + sum(bh_of(l) + 14 for _, _, l in CFB_PARLAYS) + 96
    c = Card(H); d = c.d
    y = c.header(f"CFB {week.upper()} — 5 TICKETS", chip="$5 EACH · 3-LEG")
    d.rounded_rectangle([(M, y), (W - M, y + 38)], radius=10, fill=PANEL, outline=LINE, width=1)
    c.text(M + 15, y + 8, "Diversified 3-leggers from the clean board · $25 total risk", F['de'], INK)
    y += 52
    for title, accent, legs in CFB_PARLAYS:
        bh = bh_of(legs)
        d.rounded_rectangle([(M, y), (W - M, y + bh)], radius=14, fill=PANEL, outline=LINE, width=2)
        d.rounded_rectangle([(M, y), (M + 10, y + bh)], radius=6, fill=accent)
        c.text(M + 28, y + 13, title, F['blk'], accent)
        ry = y + 48
        for team, pick in legs:
            c.text(M + 30, ry, team, F['pl'], INK)
            c.text(W - M - 20, ry + 2, pick, F['pl'], accent, right=True)
            ry += lh
        y += bh + 14
    c.text(M, y, f"Week 4 lines, {_stamp()}. Parlays compound the vig -- 3-leggers are lottery", F['ftb'], DIM); y += 28
    c.text(M, y, "tickets even off good legs. $5 fun money. Spots, not locks. 21+", F['ft'], FAINT)
    return c.save(out)


def card_cfb_totals(week, out):
    """CFB totals card: over/under plays where the opponent-adjusted total projection
    AND the line movement agree -- the market isn't fighting the model."""
    top = 250
    ph = 76

    def section(c, d, y, title, sub, rows, accent):
        c.text(M, y, title, F['col'], accent)
        c.text(W - M, y + 2, sub, F['de'], FAINT, right=True)
        y += 28; d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 10
        for game, pick, why in rows:
            d.rounded_rectangle([(M, y), (W - M, y + ph)], radius=12, fill=PANEL, outline=LINE, width=2)
            d.rounded_rectangle([(M, y), (M + 9, y + ph)], radius=5, fill=accent)
            c.text(M + 26, y + 11, game, F['blk'], INK)
            c.text(W - M - 18, y + 13, pick, F['pl'], accent, right=True)
            c.text(M + 26, y + 46, why, F['de'], FAINT)
            y += ph + 10
        return y + 8

    H = top + 44 + (28 + 10 + len(CFBTOT_OVERS) * (ph + 10) + 8) + (28 + 10 + len(CFBTOT_UNDERS) * (ph + 10) + 8) + 96
    c = Card(H); d = c.d
    y = c.header(f"CFB {week.upper()} — TOTALS", chip="O/U READS")
    d.rounded_rectangle([(M, y), (W - M, y + 38)], radius=10, fill=PANEL, outline=LINE, width=1)
    c.text(M + 15, y + 8, "Only where the model AND the line move agree (market not fighting it)", F['de'], INK)
    y += 52

    y = section(c, d, y, "OVERS", "offenses outrun the number", CFBTOT_OVERS, GREEN)
    y = section(c, d, y, "UNDERS", "defense / broken offense < the number", CFBTOT_UNDERS, RED)

    c.text(M, y, f"Week 4 lines, {_stamp()}. Totals are the noisiest market -- these have model +", F['ftb'], DIM); y += 28
    c.text(M, y, "line-move agreeing. Cross-check weather at kick. Spots, not locks. 21+", F['ft'], FAINT)
    return c.save(out)


def card_cfb_wave(week, out):
    """CFB Wave board: model-confirmed rides + the undefeated (3-0 ATS) wave laying
    bigger numbers, honestly tagged. A real menu of options, casino-ready."""
    top = 250
    ph = 76
    def section(c, d, y, title, sub, col, rows, accent):
        c.text(M, y, title, F['col'], col)
        c.text(W - M, y + 2, sub, F['de'], FAINT, right=True)
        y += 28; d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 10
        for team, pick, why in rows:
            d.rounded_rectangle([(M, y), (W - M, y + ph)], radius=12, fill=PANEL, outline=LINE, width=2)
            d.rounded_rectangle([(M, y), (M + 9, y + ph)], radius=5, fill=accent)
            c.text(M + 26, y + 11, team, F['blk'], INK)
            c.text(W - M - 18, y + 13, pick, F['pl'], accent, right=True)
            c.text(M + 26, y + 46, why, F['de'], FAINT)
            y += ph + 10
        return y + 8

    H = top + 44 + (28 + 10 + len(CFBWAVE_RIDES) * (ph + 10) + 8) + (28 + 10 + len(CFBWAVE_WAVE) * (ph + 10) + 8) + 96
    c = Card(H); d = c.d
    y = c.header(f"CFB {week.upper()} — WAVE BOARD", chip="ATS OPTIONS")
    d.rounded_rectangle([(M, y), (W - M, y + 38)], radius=10, fill=PANEL, outline=LINE, width=1)
    c.text(M + 15, y + 8, "The wave, sorted by whether the model likes THIS week's number", F['de'], INK)
    y += 52

    y = section(c, d, y, "MODEL RIDES", "wave + a number the model likes", CY, CFBWAVE_RIDES, GREEN)
    y = section(c, d, y, "THE 3-0 WAVE", "covering all year · number's rich (your read)", GOLD, CFBWAVE_WAVE, GOLD)

    c.text(M, y, f"Week 4 lines, {_stamp()}. RIDES = model-confirmed. 3-0 WAVE = still covering,", F['ftb'], DIM); y += 28
    c.text(M, y, "but laying a rich number -- your call. Spots, not locks. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)


def card_atlgb_good(week, out):
    """Single-game clean card: the ATL@GB 'Good' tier — props where current-season
    form and the injury report point the same direction, plus the 1H-under expression."""
    kcol = {'over': GREEN, 'under': RED}
    top = 250
    ph = 96  # per-play block height
    n_plays = len(ATLGB_GOOD) + 1  # + the 1H period play
    H = top + 54 + n_plays * (ph + 14) + 92 + 120
    c = Card(H); d = c.d
    y = c.header(f"NFL {week.upper()} — THE GOOD", chip=ATLGB_GAME[0])

    # Game context strip
    d.rounded_rectangle([(M, y), (W - M, y + 40)], radius=10, fill=PANEL, outline=LINE, width=1)
    c.text(M + 16, y + 9, ATLGB_GAME[1], F['pl'], INK)
    c.text(W - M - 16, y + 11, "form + injuries agree", F['de'], CY, right=True)
    y += 58

    c.text(M, y, "PLAYS WE TRUST", F['col'], CY)
    c.text(W - M, y + 2, f"{n_plays} clean", F['de'], FAINT, right=True)
    y += 32; d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 12

    # 1H period play first (game-level), with a period badge
    plabel, ppick, pkind, pwhy = ATLGB_PERIOD
    accent = kcol.get(pkind, INK)
    d.rounded_rectangle([(M, y), (W - M, y + ph)], radius=14, fill=PANEL, outline=LINE, width=2)
    d.rounded_rectangle([(M, y), (M + 10, y + ph)], radius=6, fill=accent)
    d.rounded_rectangle([(M + 30, y + 16), (M + 84, y + 40)], radius=6, fill=GOLD)
    c.text(M + 40, y + 19, "1H", F['blk'], (11, 18, 24))
    c.text(M + 100, y + 16, plabel, F['blk'], INK)
    c.text(W - M - 20, y + 18, ppick, F['pl'], accent, right=True)
    c.text(M + 30, y + 56, pwhy, F['de'], FAINT)
    y += ph + 14

    for player, pick, kind, why in ATLGB_GOOD:
        accent = kcol.get(kind, INK)
        d.rounded_rectangle([(M, y), (W - M, y + ph)], radius=14, fill=PANEL, outline=LINE, width=2)
        d.rounded_rectangle([(M, y), (M + 10, y + ph)], radius=6, fill=accent)
        c.text(M + 30, y + 16, player, F['blk'], INK)
        c.text(W - M - 20, y + 18, pick, F['pl'], accent, right=True)
        c.text(M + 30, y + 56, why, F['de'], FAINT)
        y += ph + 14

    y += 8
    d.rounded_rectangle([(M, y), (W - M, y + 56)], radius=12,
                        fill=(45//14, 212//14, 191//14), outline=(45, 212, 191), width=1)
    c.text(M + 16, y + 9, "WHY", F['col'], CY)
    c.text(M + 16, y + 30, ATLGB_CTX, F['de'], INK)
    y += 78

    c.text(M, y, f"Live board pulled {_stamp()}. 2-game sample — spots, not locks. Verify lines on Caesars.", F['ftb'], DIM); y += 30
    c.text(M, y, "Grounded in real 2026 usage + injury report. Not guarantees. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)


def card_cfb_reads(week, out):
    """CFB Saturday leans from the current-season form engine. Labeled trend/context --
    CFB has no validated edge like the NFL PropScore, and these are 3-game samples."""
    top = 250; rh = 92
    H = top + 40 + len(CFB_READS) * rh + 120
    c = Card(H); d = c.d
    y = c.header("CFB SATURDAY — FORM READS", chip="TREND / CONTEXT")
    c.text(M, y, "From this year's results + margins. NOT a validated edge — CFB has no proven niche, and it's early (3 games).", F['de'], DIM)
    y += 40
    for matchup, pick, thesis in CFB_READS:
        d.rounded_rectangle([(M, y), (W - M, y + rh - 12)], radius=14, fill=PANEL, outline=LINE, width=2)
        d.rounded_rectangle([(M, y), (M + 10, y + rh - 12)], radius=6, fill=CY)
        c.text(M + 30, y + 14, matchup, F['plr'], INK)
        c.text(W - M - 20, y + 16, pick, F['dir'], GOLD, right=True)
        c.text(M + 30, y + 50, thesis, F['de'], DIM)
        y += rh
    y += 8
    c.text(M, y, f"Live lines pulled {_stamp()}. Trend/context, not locks — CFB's honest read is 'lean and shop', not 'edge'.", F['ftb'], DIM); y += 30
    c.text(M, y, "Early-season form is inflated by opponent quality. Verify lines. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)


def card_game_sgp(week, out, stake=1.0):
    """Single-game SGP tickets for a full book. Correlated legs; the book sets the SGP
    price (correlation-adjusted, usually a bit under a straight parlay)."""
    kcol = {'over': GREEN, 'under': RED, 'line': GOLD}
    top = 250
    body = sum(56 + 18 + len(legs) * 42 + 16 + 22 for _, _, _, legs in SGP_TICKETS)
    H = top + body + 130
    c = Card(H); d = c.d
    y = c.header("NFL - TONIGHT'S SGPs", chip="SAME-GAME PARLAYS")
    c.text(M, y, SGP_GAME, F['sub'], INK); y += 34
    c.text(M, y, "Correlated $1 tickets off the PropScore board. Book sets the SGP price (usually a bit under a straight parlay).", F['de'], DIM)
    y += 40
    for title, accent, thesis, legs in SGP_TICKETS:
        bh = 56 + 18 + len(legs) * 42 + 16
        d.rounded_rectangle([(M, y), (W - M, y + bh)], radius=16, fill=PANEL, outline=LINE, width=2)
        d.rounded_rectangle([(M, y), (M + 10, y + bh)], radius=6, fill=accent)
        c.text(M + 30, y + 16, title, F['blk'], accent)
        c.text(M + 30, y + 50, f"({thesis})", F['mu'], FAINT)
        ry = y + 74
        for subj, detail, kind in legs:
            c.text(M + 30, ry, subj, F['pl'], INK)
            c.text(M + 420, ry + 2, detail, F['pl'], kcol.get(kind, INK))
            ry += 42
        y += bh + 22
    y += 6
    c.text(M, y, f"Live board pulled {_stamp()}. Verify lines on your book - SGP prices are correlation-adjusted.", F['ftb'], DIM); y += 30
    c.text(M, y, "Validated PropScore legs. SGPs are still longshots. Bet responsibly. 21+", F['ft'], FAINT)
    return c.save(out)

def card_floor_longshot(week, out, stake=1.0, avg_odds=-175, legs=None, corr_note=None):
    """One big teaser-style longshot: 15 conservative 'floor' overs (lowest alt rung),
    one per game. Payout illustrative at avg_odds/leg - the book prices your actual rungs."""
    if legs is None:
        legs = FLOOR_LONGSHOT
    if corr_note is None:
        corr_note = "Burrow + Chase are same-game (may need SGP). High-prob stack, still a longshot. 21+"
    dec_leg = 1 + (100 / abs(avg_odds) if avg_odds < 0 else avg_odds / 100)
    est = dec_leg ** len(legs) * stake
    top = 250; rh = 46
    H = top + len(legs) * rh + 200
    c = Card(H); d = c.d
    y = c.header(f"NFL {week.upper()} - FLOOR LONGSHOT", chip=f"{len(legs)}-LEG TEASER STYLE")
    c.text(M, y, "Floor numbers - take the LOWEST alt rung each guy clears most weeks. High-probability legs, lottery stack.", F['de'], DIM)
    y += 40; d.line([(M, y), (W - M, y)], fill=LINE, width=2); y += 6
    for i, (player, pick, mu) in enumerate(legs):
        d.rectangle([(M + 4, y + 8), (M + 24, y + 28)], outline=FAINT, width=2)
        c.text(M + 38, y + 6, player, F['pl'], INK)
        c.text(M + 470, y + 6, pick, F['pl'], GREEN)
        c.text(W - M, y + 6, mu, F['de'], FAINT, right=True)
        d.line([(M, y + rh), (W - M, y + rh)], fill=(20, 32, 38), width=1); y += rh
    y += 16
    box = f"$1 -> ~${est:,.0f}"
    bw = d.textlength(box, font=F['h1']) + 40
    d.rounded_rectangle([(M, y), (M + bw, y + 66)], radius=14, fill=(11, 30, 28), outline=CY, width=2)
    c.text(M + bw / 2, y + 8, box, F['h1'], CY, center=True)
    c.text(M + bw + 20, y + 12, "illustrative", F['de'], FAINT)
    c.text(M + bw + 20, y + 36, f"at ~{avg_odds}/leg", F['de'], FAINT)
    y += 86
    c.text(M, y, "Floors derived from main lines - the book's alt rungs & prices are the truth; payout will vary.", F['ftb'], DIM); y += 30
    c.text(M, y, corr_note, F['ft'], FAINT)
    return c.save(out)

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
    if 'floorshot' in want:
        made.append(card_floor_longshot(args.week, str(out_dir / 'bk_floor_longshot.png')))
    if 'sgp' in want:
        made.append(card_game_sgp(args.week, str(out_dir / 'bk_tonight_sgp.png')))
    if 'cfbreads' in want:
        made.append(card_cfb_reads(args.week, str(out_dir / 'bk_cfb_reads.png')))
    if 'sunday' in want:
        made.append(card_sunday_best(args.week, str(out_dir / 'bk_sunday_best.png')))
    if 'atlgb' in want:
        made.append(card_atlgb_good(args.week, str(out_dir / 'bk_atlgb_good.png')))
    if 'cfbwave' in want:
        made.append(card_cfb_wave(args.week, str(out_dir / 'bk_cfb_wave.png')))
    if 'cfbtotals' in want:
        made.append(card_cfb_totals(args.week, str(out_dir / 'bk_cfb_totals.png')))
    if 'cfbparlays' in want:
        made.append(card_cfb_parlays(args.week, str(out_dir / 'bk_cfb_parlays.png')))
    if 'sgplong' in want:
        made.append(card_game_longshot(args.week, str(out_dir / 'bk_tonight_longshot.png')))
    if 'floorshot2' in want:
        made.append(card_floor_longshot(args.week, str(out_dir / 'bk_floor_longshot2.png'),
                                        legs=FLOOR_LONGSHOT_2,
                                        corr_note="St. Brown + Olave share a game (different teams, low correlation). Still a longshot. 21+"))
    if 'parlay' in want:
        made.append(card_parlay(args.week, str(out_dir / 'bk_parlay.png')))

    print(f"Rendered {len(made)} card(s) to {out_dir}:")
    for p in made:
        print("  ", p)

if __name__ == '__main__':
    main()
