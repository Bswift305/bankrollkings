# Arming the Kings Sleeper capture for the 2026-27 season

The harness (`nba_sleeper_capture.py`) is built and the pipeline is **verified**
(`simulate` reproduces the edge on real historical games: 2,296 candidates, 58% hit,
+10.7% at the proxy line, holding out-of-sample). To turn it into the **real-money
walk-forward test**, do these three things once games return.

## 1. Point it at the real props feed
In-season, the daily NBA player-prop file must exist at `data/props/NBA_Props.csv`
(or edit `PROPS` at the top of the script). The harness expects these columns
(rename your feed's columns to match, or add a small mapping):

    Player, Team, Opp, Stat, Direction, Line, Price   (Stat in PTS/REB/AST; Price American, e.g. -115)

Capture **near lock** so `Line`/`Price` is the closing number — that's what makes this a
true CLV/ROI test.

## 2. Wire "star teammate OUT" to TODAY's injury report  ← the one live integration point
`simulate` derives star-out from a game's actual absences (fine retrospectively). For
**live** capture, star-out must come from *today's* inactives, not yesterday's box score.
In `capture()`, replace the carry-in `star_out` proxy with a check against the live injury
feed (`data/injuries/…` / `load_injuries`): flag a candidate if a top-2-scoring rotation
teammate is ruled OUT today. (Streak and soft-matchup are already correct as-is.)

## 3. Schedule it (daily, in-season)
    # near lock:
    python nba_sleeper_capture.py capture              # logs today's candidates w/ real line+price
    # next morning:
    python nba_sleeper_capture.py grade                # grades resolved picks vs gamelogs
    python nba_sleeper_capture.py report               # walk-forward record + ROI

Add as a Windows Scheduled Task (or a prod systemd timer if you run it server-side).

## Reading the result
After ~4–6 weeks of games you'll have a real, hindsight-free record at **closing** prices.
- Clears 52.4% (−110 break-even) with positive ROI → **genuine, ownable edge.** Ship it as
  the "Kings Sleeper" feed and it's honest by construction ("we bet the opportunity").
- Lands at/below break-even → the market prices the opportunity too; demote to a context flag.
  Either way you get the truth — which is the whole point.

## Files
- `nba_sleeper_capture.py` — the harness (simulate / capture / grade / report)
- `sim_picks_2025_26.csv` — the historical picks the filter would have made (verification)
- `FINDINGS.md` — the backtest writeup
- `sleeper_capture_log.csv` — created in-season; the live record
