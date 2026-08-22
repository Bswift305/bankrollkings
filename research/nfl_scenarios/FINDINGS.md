# NFL Scenario Engine — the "information haven"

**Built:** 2026-08-22 · **Data:** `data/pbp/nfl_pbp_2019_2025_slim.parquet` (nflverse
play-by-play, 7 seasons 2019–2025, **344,622 plays**, 61 columns: real down / distance /
field position / pressure / drive-outcome / EPA on every snap). Consolidated from Darrel's
Downloads (zip 2019–2021, parquet 2022–2025) down to just the scenario fields (12 MB).

## The promise
Grade **any player or team, in any main situation**, with a number that traces to a real
graded snap. No projections, no invented data. Thin samples are labeled and held *below*
the boards, never sold as leaders.

## Full coverage (`research/nfl_scenarios/scenario_engine.py`)

### Player boards (leaderboards, any scenario)
- **`qb`** — conv%, EPA/dropback, success%, comp%, CPOE, sack%, INT%, aDOT. Scrambles credited to the QB.
- **`rb`** — carries, yds/carry, success%, EPA, move-chains%, stuff%, explosive (10+)%, TD%.
- **`wr`** — targets, catch%, yds/target, YAC, aDOT, EPA/target, move%, deep (20+)%, TD%.
- **`player "<name>"`** — auto-detects QB/RB/WR and prints that player's full situational card
  (3rd & short/med/long/10+, 1st down, 2nd & long, 4th, red zone, goal-to-go, two-minute,
  when leading, when trailing).

### Team profiles (one team, everything)
- **`team-off <TEAM>` / `team-def <TEAM>`** — EPA/play, success%, 3rd-down conv% (+ 3rd & long),
  red-zone TD%/trip, explosive pass/rush rate, early-down pass%, sack%/QB-hit% (allowed vs
  generated), per-drive TD%/score%/giveaway%/3-and-out%/plays, and EPA split by game state
  (leading vs trailing).

### Team leaderboards (league-wide)
- **`team-3rd`** — 3rd-down conv% by distance bucket (short/med/long/10+).
- **`team-redzone`** — red-zone TD% per trip, offense + defense.
- **`team-drive`** — per-drive TD%, score%, giveaway%, 3-and-out%, plays/drive.
- **`team-explosive`** — explosive pass (20+) & rush (10+) rate, for and against.
- **`team-pressure`** — sack% & QB-hit% per dropback: pass-pro (offense) and pass-rush (defense).
- **`team-early`** — early-down (1st/2nd) pass rate + EPA/play (tendency read).

Modifiers on every command: `--season YYYY`, `--min N`, `--down D`, `--dist BUCKET`.

## Sanity checks (all real, all reproduce known truth)
- QB 3rd & 10+: Allen 27.2% (n=342), Mahomes 26.6%, L.Jackson 26.5% — the true "move the
  chains when they know it's a pass" board.
- Deep-ball WR EPA 2024: **Jefferson #1** (1.37, 100% deep, 60% catch on 30.5 aDOT).
- Per-drive TD% 2024: **DET #1 (36.9%)**; pass-pro: **BUF best (2.8% sack)**; pass-rush:
  **DEN #1 (8.8% sack)** — matches the real 2024 leaders.
- CeeDee Lamb: strong everywhere but **goal-to-go collapses (34.5% catch, −0.72 EPA)**;
  Barkley: elite 3rd-&-short (61% move) but **1.2 yds/carry inside the 5** — real, useful splits.

## Why it matters for the product
This is the raw material for **matchup content and a props/totals angle** that is *provably*
true: "QB converts 21% on 3rd & long, opponent D is bottom-5 at getting off the field" →
context nobody else can back with numbers. It's also the honesty proof: our stats come from
real snaps, not vibes. Extensions when we productize: a weekly board pairing a player/team's
weak scenario against this week's opponent's matching defensive scenario; and it directly
feeds the **pick analyzer** (parked) — a bettor's picks checked against these real splits.

## Notes
- `qb_name` = passer, or the rushing QB on a scramble (dropbacks fully credited).
- 3rd/4th-down conversion uses nflverse's official `third_down_converted`/`fourth_down_converted`;
  other downs use "moved the chains" (first down OR TD).
- Drives grouped by `(game_id, fixed_drive)`; per-drive outcome from `fixed_drive_result`;
  3-and-out counts scrimmage snaps only (run/pass), so the punt down doesn't inflate the count.
- Add seasons: drop `play_by_play_<yr>.parquet|.zip` in Downloads, re-run the consolidation block.
