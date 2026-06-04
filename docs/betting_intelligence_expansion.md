# Bankroll Kings Betting Intelligence Expansion

Source note: distilled from `C:/Users/Decatur/OneDrive/Documents/More Upgrades.docx`.

## Core Shift

Bankroll Kings should not stay positioned as only a player props screener. The product direction is a complete betting intelligence platform:

> Game lines, first-half analysis, player props, season win totals, futures, award races, and player milestones with tracking data, market movement, and calibrated hit rates.

The existing prop engine remains the strongest base layer, but the next expansion should add bet types that serious bettors already evaluate alongside props.

## Current Coverage

| Bet Category | Current State | Notes |
| --- | --- | --- |
| Player props | Built | Full board, market edge, calibration, tracking, and sport-specific context exist. |
| Moneyline / spread / game total | Partial | Game lines exist, and football line movement tracking now captures opener/current movement. |
| First half spread / total / moneyline | Not built | Closest new surface to existing game-log logic. Needs half-level splits. |
| Quarter lines | Not built | Lower priority than first halves. |
| Live betting | Not built | Should wait until watchlists, movement alerts, and refresh cadence are production-safe. |
| Season win totals | Not built | Fastest futures win once odds source is added. |
| Player season props / milestones | Not built | Can reuse player reliability and per-game pace calculations. |
| Awards / futures | Ingestion started | Championship/outrights odds and movement tracking now exist. Award odds and probability models are not built yet. |
| MLB F5 | Not built as a page | Existing pitcher/Statcast context is a strong foundation. |
| First TD / anytime TD | Not built | Should follow NFL red-zone and usage modeling. |

## Build Priority

### 1. Season Win Totals

This is the cleanest first futures page.

Data needed:
- Futures odds source for preseason/current season win totals.
- Team actual record.
- Remaining schedule.
- Schedule strength estimate.
- Injury-adjusted projection.
- Opening line vs current line movement.

Initial page:
- Team
- Opening win total
- Current win total
- Actual record
- Current pace
- Projected wins
- Pace delta vs line
- Injury/schedule notes
- Movement since open

Why first:
- High traffic before NFL Week 1 and before NBA season.
- Simple table model.
- Uses data structures the app already understands: teams, schedules, records, odds, movement.

### 2. First Half Analysis

This should appear first on matchup pages, then graduate to its own board if usage is strong.

Data needed:
- First-half scores from historical game logs or box scores.
- Team first-half offensive and defensive ratings.
- First-half pace vs full-game pace.
- Start-fast / start-slow team tendencies.
- Halftime adjustment profile where available.

Initial signals:
- First-half spread lean.
- First-half total lean.
- Team first-half scoring pace.
- First-half vs full-game mismatch.

### 3. Player Season Prop Pace Tracker

This should start on player pages and later become a standalone season props board.

Data needed:
- Current player season totals.
- Per-game pace.
- Games remaining.
- Remaining opponent difficulty.
- Injury risk / missed-game adjustment.
- Book season prop line.

Initial signals:
- Current pace vs season line.
- Schedule-adjusted pace.
- Variance warning.
- Injury-risk warning.

### 4. Awards and Futures

Championship/outrights ingestion is now in place through `fetch_futures_odds.py` and `refresh_futures_odds.py`.

Data needed:
- Current award odds.
- Historical award-winning statistical thresholds.
- Current leaderboards.
- Team success context where relevant.
- Injury and games-played risk.
- Opening odds vs current odds.

Current data foundation:
- `data/futures/Futures_Sports.csv`
- `data/futures/Futures_Odds.csv`
- `data/tracking/Futures_LineMovementHistory.csv`
- `data/tracking/Futures_LineMovementCurrent.csv`

Current coverage from The Odds API:
- NFL Super Bowl winner.
- NCAAF championship winner.
- MLB World Series winner.
- NBA championship winner.

Season win totals are still separate from this foundation unless a feed exposes them as a supported market.

Initial awards:
- NFL MVP, OPOY, DPOY, OROY, DROY.
- NBA MVP, DPOY, ROY, MIP, Sixth Man.
- MLB MVP, Cy Young, ROY.

### 5. MLB First 5 Innings

MLB F5 is a natural extension of existing pitcher and game environment work.

Data needed:
- Starting pitcher first-through-fifth inning splits.
- Team early-inning scoring rates.
- Starter matchup vs projected lineup.
- Manager starter pull tendencies.
- Bullpen exclusion logic.

Initial page:
- F5 moneyline.
- F5 spread / run line where available.
- F5 total.
- Pitcher fade / hold profile.
- Early scoring environment.

## Tier Mapping

| Bet Category | Free | Pro | Sharp | Elite |
| --- | --- | --- | --- | --- |
| Player props | Teaser | Full board | Market edge | Tracking data |
| Game lines | Teaser | Full | Movement | Sharp signals |
| First half lines | None | Basic board | H1 trends | H1 models |
| Season win totals | None | Basic table | Pace analysis | Injury-adjusted projection |
| Futures / awards | None | Leaderboards | Probability model | Opening vs current edge |
| Player season props | None | Pace view | Schedule-adjusted | Variance model |
| MLB F5 | None | Basic board | Statcast F5 splits | Full F5 model |
| Quarter lines | None | None | Basic board | Deep model |
| First TD scorer | None | None | Basic board | Red-zone model |
| Live betting signals | None | None | None | Full alerts |

## Implementation Notes

- Do not build new futures pages with fake or static data. Add the odds/data source first, then the page.
- Line movement should reuse the existing snapshot pattern: append-only history plus current open-vs-current summary.
- New bet types must preserve the product philosophy: explain when to play, when to pass, and why the line is risky.
- First release can be table-driven. Deeper models can follow after tracking history accumulates.
- AWS refresh jobs should keep futures and season-long calculations separate from live prop refreshes so archive-style work cannot block live boards.
