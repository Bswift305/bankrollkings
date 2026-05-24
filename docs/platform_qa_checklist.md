# Bankroll Kings QA Checklist

Use this before calling a sport, board, or major refresh cycle "done."

## Closeout Standard

A surface is only considered closed out when all 4 layers are clean:

1. `Data refresh`
2. `Logic sanity`
3. `Route smoke test`
4. `Visual / UX spot check`

Do not skip a layer just because the page loads.

---

## 1. Data Refresh

Run the refresh commands for the sport first.

### NBA closeout refresh

```powershell
cd "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls"
py -X utf8 refresh_playoff_results.py
py -X utf8 refresh_playoff_player_logs.py
py fetch_game_lines.py --bookmakers draftkings,caesars,fanduel,betmgm --days 5 --api-key 51234f049c2e262e299d9a78d1c0a829
py fetch_player_props.py --bookmakers draftkings,caesars,fanduel,betmgm --days 5 --api-key 51234f049c2e262e299d9a78d1c0a829
```

### Football closeout refresh

Use the current football refresh path for the sport being tested.

Examples:

```powershell
cd "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls"
py fetch_espn_current_roster.py
py fetch_cfbd_transfer_portal.py --year 2026 --api-key <KEY>
py fetch_cfbd_returning_production.py --year 2025 --api-key <KEY>
```

If a refresh fails, the QA pass is not complete.

---

## 2. Logic Sanity

Check whether the page is making the right decisions, not just rendering.

### NBA logic questions

- Is today’s schedule correct?
- Are active playoff series correct?
- Are obviously stale series removed?
- Are top props aligned with the actual recent streak?
- Are high-confidence plays being trimmed when there is:
  - a run conflict
  - a line-history conflict
  - a shallow sample
- Are later playoff rounds using playoff data first?
- Are round 1 reads using regular-season baseline?

### Football logic questions

- Are current roster / returning-production reads plausible?
- Are portal churn tags showing up on the right teams?
- Are team signals speaking plain English?
- Are matchup reads consistent with the actual board identity:
  - NFL = lines/totals first
  - CFB = lines/totals/matchups first

### Rule

If one obvious contradiction shows up, stop and fix it before calling the board clean.

---

## 3. Route Smoke Test

Test the important routes, not every single link.

### One-command smoke test

```powershell
cd "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls"
py qc_platform_routes.py
```

Or use:

- [C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\batch\QC_PLATFORM.bat](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\batch\QC_PLATFORM.bat)

### Core platform routes

- `/`
- `/dashboard?postseason=1`
- `/info`
- `/glossary`

### NBA routes

- `/sports/nba?postseason=1`
- `/schedule?postseason=1`
- `/game-lines?postseason=1`
- `/props?postseason=1&sample=current&date=today`
- `/market-edge?postseason=1&sample=current&date=today`
- `/matchup-lens?postseason=1`
- one active `/matchup/...`
- one active `/series/...`
- `/trend-board?postseason=1`
- `/bet-review?postseason=1`
- `/candidate-review?postseason=1`

### Football routes

- `/sports/nfl?postseason=1`
- `/sports/nfl/game-lines?postseason=1`
- `/sports/ncaaf?postseason=1`
- `/sports/ncaaf/game-lines?postseason=1`
- `/sports/ncaaf/totals?postseason=1`
- one football method board

### Smoke-test rule

Every route should:

- return `200`
- show the expected board title
- load the expected current-sport framing

If a core route returns `500`, the sport is not closed out.

---

## 4. Visual / UX Spot Check

Check the page like a user, not like a developer.

### Layout checks

- No text overlap
- No clipped badges
- No broken logos
- No giant empty dead zones where more context should exist
- Wide tables scroll left-right cleanly
- Top horizontal slider appears on wide widgets
- Scroll hints appear on dense boards where needed

### Content clarity checks

- Section titles explain themselves
- Picks have a short `why` line when they are featured
- Snapshot metrics are clearly labeled
- Sample type is visible when it matters:
  - `Regular-season baseline`
  - `Playoff sample`

### Trust checks

- If a board says `CLE offense leans live`, the explanation should make sense
- If a row is elite, it should not contradict the current run without warning
- If a metric looks strange, rename or clarify it before shipping

---

## NBA Final QC Command

This is the hard NBA board validator.

```powershell
cd "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls"
py qc_nba_board.py
```

Expected result:

- `Issues found: 0`
- `No blocking NBA QC issues detected.`

If this script fails, NBA is not done.

---

## Closeout Decision

You can check a sport off only when:

- refresh commands completed
- data looks current
- no obvious logic contradictions remain
- core routes passed
- visual spot-check passed
- sport-specific QC script passed if one exists

---

## Recommended Workflow

1. Refresh data
2. Run sport-specific QC script if available
3. Smoke test key routes
4. Open the 5-10 most important pages
5. Fix any contradiction immediately
6. Re-run the QC script
7. Only then call the sport done

---

## Notes

- Do not trust one page alone.
- Do not trust one data source alone.
- Do not call a board done just because it "looks good."
- The standard is: `fresh, sane, loads clean, and explains itself`.
