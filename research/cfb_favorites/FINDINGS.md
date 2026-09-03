# CFB Big-Favorite Trend — by team AND coach (2026-09-03)

**Data:** CFBD games + lines + coaches, **2016–2025** (10 seasons), all joined on CFBD
IDs/names — no fuzzy matching. `research/cfb_favorites/fetch_cfbd_favorite_history.py`
pulled it: 23,810 games, **10,533 lined games**, 1,438 coach-seasons →
`data/historical/CFBD_{Games,Lines,Coaches}_2016_2025.csv`. Cover = favorite wins by
MORE than the consensus (median-across-books) number; push if exactly equal.

## Headline: heavy early favorites are a coin flip — the market prices them right
Early season (weeks 1–4), FBS teams favored by:
- **30+**: 642 games, favorites cover **48%** (302–328) → *losing* at −110.
- **40+**: 243 games, favorites cover **47%** (110–125) → *losing*.

Blindly backing big favorites to cover does not work. The value is in the **spread** between
teams/coaches — and the coach is the sharper signal.

## Georgia / Kirby Smart — the poster child (validated at scale)
Darrel's read was right. As an early-season favorite, **Kirby Smart is the worst in the country:**
- **30+ favorite: 3–12 ATS (20%)** — every game his (2016–2025).
- **40+ favorite: 0–9 ATS (0%).** He has **never** covered a 40+ early spread in nine tries.
Textbook misses: Kent State −45 won by 17; UAB −41 by 28; Austin Peay −46.8 by 22; Nicholls
−49.5 by only 2. Smart empties the bench and manages blowouts — provably, not anecdotally.

## Slow starters (don't cover big) — by COACH
Kirby Smart (0–9 at 40+; 20% at 30+), Dabo Swinney (27–29%), Mario Cristobal (29–30%),
Jim Harbaugh (36%), Ryan Day (40–50%). By team: Georgia 20%, TCU 25%, Clemson 27%, LSU 27%,
Baylor/Michigan/Oregon ~33%.

## Fast starters (cover big) — by COACH
Lane Kiffin (75%), Neal Brown (75%), Josh Heupel (70%), Nick Saban (62–64%, 9–5 at 40+).
By team: West Virginia 75%, Texas/Ole Miss/Missouri/Texas Tech 67%, Alabama 65% (11–6),
Miami 64–67%, Tennessee 62%.

## The coach follows the coach, not the school
The by-coach table aggregates across job changes, and the tendency travels:
- **Mario Cristobal 3–7** spans Oregon (2018–21) **and** Miami (2022+) — slow at both.
- **Lane Kiffin 6–2** spans FAU **and** Ole Miss — fast at both.
This is why coach is the better key than team: when a program changes coaches, its
big-favorite cover profile changes with the new coach's DNA (tempo, starter usage, whether
they run it up). Aggressive up-tempo offenses (Kiffin, Heupel) cover; ball-control
"sportsmanlike" blowout managers (Smart) don't.

## Engine
`research/cfb_favorites/cfb_favorite_trends.py`:
`--min-line 30|40  --weeks 1-4  --min-games N  --team Georgia`. Filters FBS favorites,
grades covers, ranks by team and by head coach; `--team` prints a clean game-by-game log.

## Honest caveats
- Per-team/coach samples are 8–16 games over 10 years — a real *tell*, not a lock; Kirby's
  0–9 at 40+ is the strongest signal because it's perfect and directional.
- Consensus line = median across books; a bettor shops for a better number.
- 2020 (COVID) had fewer games; included. Weeks 1–4 = the early-season window big favorites cluster in.
- This is honest CONTEXT for a side, not a promised ROI edge — but the coach split is a genuine,
  repeatable angle worth a live board, and it's forward-testable this season.
