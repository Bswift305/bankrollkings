# CFB Point-in-Time Context — 2026-10-10

**Legacy analytical context. Ordered by displayed model–market difference. No validated betting
edge is claimed.** This is a bounded, reproducible snapshot — not picks, not an edge, not a best-bets
list, not King's View. Preserved because `cfb_2026_results.json` is overwritten season-to-date (no
point-in-time archive), so without this record the exact analysis could not be reconstructed later.

## Provenance (retrieval + input fingerprints)

- **Retrieval:** 2026-10-10 **17:55 UTC** (13:55 ET).
- **Included games:** only those whose kickoff (ET) was **after** the retrieval time (pre-kickoff).
- **Input fingerprints** (sha256, first 16):
  - `4e6189ae27cf08ab` — `data/scenarios/cfb_2026_results.json` (1,670 completed 2026 games)
  - `12bd74e9d8c10e6e` — `data/scenarios/cfb_power.json` — **Sep-3 preseason SP+ prior (STALE)**
  - `fa446ba5896dc521` — `data/scenarios/cfb_rankings.json`
  - `e33b78268cfd553a` — `data/odds/NCAAF_Odds.csv` (lines refreshed 2026-10-10 05:30)

## What this is / is not (honest bounds)

- **Legacy, not governed.** `cfb_current_form.py` is classified **Legacy** in the product contract;
  **no CFB mechanism is Qualified.** CFB is a Baseline program with **no demonstrated out-of-sample
  edge** (see `docs/cfb_research_audit.md`, Audit #1/#2).
- **Inputs are a blend, not pure current form.** The SRS rating (`_srs`) seeds each team with the
  **stale Sep-3 SP+ prior** as virtual games and fades it as real games accumulate; the totals read
  blends the same stale prior via offense/defense priors. So **both the sides and totals numbers mix
  current-season results with a fading September prior** — they are *not* a pure current-form read.
- **"Fresher" ≠ "better."** Current-season inputs are fresher than September, but this does **not**
  establish superior predictive performance. No claim of predictive value is made.
- **The column below is a mechanical difference**, computed as
  `model_home_margin − (−market_home_spread)`; the "side indicated" is simply the sign of that
  difference. It is **not** a recommendation.
- **Large differences are the least reliable**, not the strongest: a big number on a heavy
  underdog (e.g. +28.5 / +33.5 / +38.5) is where blowout / garbage-time / starters-pulled dynamics
  make an opponent-adjusted margin model least trustworthy. Mechanical artifact, not a signal.

## Screen (mechanical; HFA = 2.5; 32 games pre-kickoff, 2 FCS/unrated skipped)

| Kickoff ET | Game | Market (home spread) | Model (home margin) | Difference | Side indicated by the difference |
|---|---|---:|---:|---:|---|
| 18:00 | San Diego State @ Oregon State | −16.5 | +6.1 | −10.4 | San Diego State +16.5 |
| 19:00 | Nevada @ UTEP | +10.0 | −0.9 | +9.1 | UTEP +10 |
| 15:30 | Charlotte @ North Texas | −28.5 | +19.9 | −8.6 | Charlotte +28.5 |
| 15:30 | Stanford @ Notre Dame | −38.5 | +30.7 | −7.8 | Stanford +38.5 |
| 16:15 | Maryland @ Ohio State | −33.5 | +27.2 | −6.3 | Maryland +33.5 |
| 19:30 | Air Force @ Northern Illinois | +7.5 | −13.6 | −6.1 | Air Force −7.5 |
| 15:30 | Buffalo @ Toledo | −19.5 | +13.6 | −5.9 | Buffalo +19.5 |
| 15:30 | Virginia Tech @ California | +10.0 | −5.4 | +4.6 | California +10 |
| 15:30 | Ole Miss @ Vanderbilt | +9.5 | −5.6 | +3.9 | Vanderbilt +9.5 |
| 15:30 | Tulsa @ Navy | −1.5 | +4.9 | +3.4 | Navy −1.5 |
| 19:00 | North Dakota State @ UNLV | +2.5 | +0.3 | +2.8 | UNLV +2.5 |
| 19:00 | UAB @ Memphis | −14.5 | +17.2 | +2.7 | Memphis −14.5 |
| 22:30 | Boise State @ Fresno State | +6.5 | −3.9 | +2.6 | Fresno State +6.5 |
| 15:30 | Duke @ Georgia Tech | +6.5 | −3.9 | +2.6 | Georgia Tech +6.5 |
| 20:00 | Kansas @ Utah | −15.5 | +13.4 | −2.1 | Kansas +15.5 |
| 16:15 | Tennessee @ Arkansas | +13.5 | −11.5 | +2.0 | Arkansas +13.5 |
| 15:30 | Central Michigan @ Ohio | −2.5 | +4.4 | +1.9 | Ohio −2.5 |
| 15:30 | UCLA @ Oregon | −10.5 | +12.3 | +1.8 | Oregon −10.5 |
| 19:00 | LSU @ Kentucky | +8.5 | −10.0 | −1.5 | LSU −8.5 |
| 19:30 | USC @ Penn State | −1.5 | +0.1 | −1.4 | USC +1.5 |
| 15:45 | UConn @ Temple | −3.5 | +4.9 | +1.4 | Temple −3.5 |
| 15:30 | Eastern Michigan @ Akron | +5.5 | −4.3 | +1.2 | Akron +5.5 |
| 19:30 | James Madison @ Georgia Southern | +7.5 | −8.7 | −1.2 | James Madison −7.5 |
| 19:30 | Syracuse @ Virginia | −11.5 | +10.4 | −1.1 | Syracuse +11.5 |
| 15:30 | Illinois @ Michigan State | +2.5 | −1.6 | +0.9 | Michigan State +2.5 |
| 15:30 | Houston @ Kansas State | −2.5 | +1.6 | −0.9 | Houston +2.5 |
| 19:00 | Coastal Carolina @ Marshall | −4.0 | +3.4 | −0.6 | Coastal Carolina +4 |
| 15:30 | Texas @ Oklahoma | +7.5 | −6.9 | +0.6 | Oklahoma +7.5 |
| 20:00 | Minnesota @ Purdue | +2.5 | −1.9 | +0.6 | Purdue +2.5 |
| 15:30 | Kent State @ Western Michigan | −13.5 | +13.8 | +0.3 | Western Michigan −13.5 |
| 19:30 | Louisiana @ Louisiana Tech | −3.0 | +3.2 | +0.2 | Louisiana Tech −3 |
| 19:30 | Georgia @ Alabama | −1.5 | +1.3 | −0.2 | Georgia +1.5 |

*Record only. No row here is a pick, an edge, a best bet, or a governed conclusion.*
