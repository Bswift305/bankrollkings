# Visual QA Checklist

Purpose:
- make sure no major windows or panels visually touch
- keep spacing consistent across cards, grids, and stacked sections
- reduce dead air without making pages feel cramped
- confirm actions, labels, and teaching copy are easy to scan

Completion rule:
- mark a page complete only when layout, spacing, copy clarity, and click paths all feel production-ready on desktop

Status legend:
- `[x]` complete
- `[ ]` still needs pass

## Global Rules

- [x] Panels should have visible separation from neighboring panels.
- [x] Section shells should not sit flush against the next shell.
- [x] Header style should feel consistent across all live pages.
- [ ] Empty or thin-data states should collapse gracefully.
- [ ] Action buttons should sit near the title area, not buried below long blocks.
- [ ] Teaching copy should clarify, not repeat what the card already says.

## Phase 1: Home Journey

Start at `/dashboard` and click every major route reachable from Home before moving into sport-specific passes.

Review focus:
- layout / spacing
- clarity
- navigation truth
- click paths
- empty states
- teaching copy

- [x] `/dashboard`
Notes:
- Home page passed after spacing cleanup on command cards and section shells.
- Header auth controls stay visible at `1440x900` after constraining the top nav to its own scroll lane.

- [x] `/tools/props`
- [x] `/tools/market-edge`
- [x] `/tools/matchup-lens`
- [x] `/tools/injuries`
- [x] `/tools/trends`
- [x] `/tools/parlay`
Notes:
- Universal tool hubs pass at `1440x900`: clear sport selectors, honest live/watch status, visible auth/account controls, no horizontal overflow.

## Phase 2: Sport Journeys

For each sport, start on the sport home, click through every major surface from that sport, and confirm the sport feels complete and self-consistent.

### NBA

- [x] `/sports/nba`
- [x] `/sports/nba/props`
- [x] `/sports/nba/market-edge`
- [x] `/sports/nba/matchup-lens`
- [x] `/matchup/<away>-<home>`
- [x] `/series/<series_id>`
- [x] `/player/<name>`
- [x] `/parlay`
- [x] `/parlay/tickets`
- [x] `/season-review`
Notes:
- NBA core journey passes at `1440x900`: sport home, props, market edge, matchup lens, representative matchup, player page, parlay builder, and saved tickets all load without horizontal overflow.
- Fixed dynamic postseason series navigation: generated `/series/nyk-sas?postseason=1` now resolves to the NBA Finals series page instead of `Series not found`.
- Fixed `/season-review?postseason=1` performance by caching the finished season review and bounding the on-page formula backtest to a recent-slate window. Browser verification now renders the page in about 1.2s from cache.

### WNBA

- [x] `/sports/wnba`
- [x] `/sports/wnba/props`
- [x] `/sports/wnba/market-edge`
- [x] `/wnba/matchup/<away>-<home>`
Notes:
- WNBA journey passes: home, props handoff, market edge, and representative matchup load without access gates or horizontal overflow.
- Fixed invalid `nan @ nan` matchup cards by hardening matchup slug generation, WNBA odds lookup, and stale WNBA snapshot handling.

### MLB

- [x] `/sports/mlb`
- [x] `/sports/mlb/props`
- [x] `/sports/mlb/market-edge`
- [x] `/mlb/matchup/<away>-<home>`
Notes:
- MLB journey passes in the app browser: home, props, market edge, and representative matchup load without access gates, error text, invalid `nan` content, or horizontal overflow.
- Fixed MLB cold-path interruptions by adding persistent caches for the shared prop board and enriched method board. After the one-time build writes cache, props and matchup surfaces return quickly across fresh app processes.

### NFL

- [x] `/sports/nfl`
- [x] `/sports/nfl/game-lines`
- [x] `/sports/nfl/totals`
- [x] `/sports/nfl/trends`
- [x] `/sports/nfl/props`
- [x] `/sports/nfl/matchup/<away>-<home>`
Notes:
- NFL journey passes in the app browser: home, game lines, totals, trends, props, and representative matchup `/sports/nfl/matchup/game/car-at-tb?postseason=1` load without gates, error text, invalid `nan` content, or horizontal overflow.
- Fixed NFL cold-path interruptions by caching the floor workbook, dashboard runtime bundle, football history lab, historical player trend rows, and NFL scored/simulation lookup tables.

### CFB

- [x] `/sports/ncaaf`
- [x] `/sports/ncaaf/game-lines`
- [x] `/sports/ncaaf/totals`
- [x] `/sports/ncaaf/trends`
- [x] `/sports/ncaaf/props`
Notes:
- CFB journey passes in the app browser: home, game lines, totals, trends, and props load without gates, error text, invalid `nan` content, or horizontal overflow.
- Fixed missing CFB conference values rendering as `nan` in current-season team signal rows.

### Men CBB

- [x] `/sports/ncaamb`
Notes:
- Men CBB page passes as an honest under-construction surface: route loads quickly, no access gate in the browser session, no invalid `nan`, no error text, and no horizontal overflow.

### Women CBB

- [x] `/sports/ncaawb`
Notes:
- Women CBB page passes as an honest under-construction surface: route loads quickly, no access gate in the browser session, no invalid `nan`, no error text, and no horizontal overflow.

## Phase 3: Specialist Pages

- [x] `/candidate-review`
- [x] `/bet-review`
- [x] `/missed-opportunities`
- [x] `/heat-map`
- [x] `/ops`
- [x] `/pricing`
- [x] `/account`
- [x] `/elite`
- [x] `/elite/matchup-builder`
- [x] `/elite/mlb-lab`
Notes:
- Specialist pages pass. `/ops` was verified with an owner session because the standard QA browser session is correctly permission-gated.
- Fixed Candidate Review missing-value display so review rows no longer render visible `nan` text.
- Heat Map now exposes a real page-level `h1` while preserving the existing compact dashboard layout.
- Elite MLB Lab loads cleanly after the MLB cache work, with no visible error, invalid `nan`, or horizontal overflow.
- Fixed Ops Dashboard QC note display so blank notes no longer render as visible `nan` text.

## Page Checks

Use these checks on every page before marking it complete:

- [ ] Header feels strong and intentional
- [ ] Main sections have enough breathing room
- [ ] No two windows visually touch
- [ ] No oversized dead zones
- [ ] Labels are understandable to a novice
- [ ] Key click targets are obvious
- [ ] Empty states feel honest, not broken
- [ ] Strong plays look strong, risky plays look risky

## Next Sweep Order

1. Finish Phase 1 Home Journey from `/dashboard`.
2. Complete Phase 2 sport-by-sport:
   - NBA
   - WNBA
   - MLB
   - NFL
   - CFB
   - Men CBB
   - Women CBB
3. Finish Phase 3 Specialist Pages.
