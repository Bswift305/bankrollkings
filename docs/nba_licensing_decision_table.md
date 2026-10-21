# NBA / WNBA licensing & substitute-source decision table — FOR COUNSEL & OWNERSHIP

**Prepared, not executed.** This is a decision aid for a legal/ownership review. It proposes nothing live:
**no provider switch, no new ingestion, no public exposure, and no change to `BK_NBA_STATS_ENABLED` (stays
`0`) occurs without a separate explicit approval.** It builds on `docs/nba_source_characterization.md`
(engineering inventory) and `docs/legal_ip_audit.md` / `docs/legal_register_v2.md` (legal register). All four
containment gaps that the characterization surfaced are already remediated and gated; this table is about the
*forward* question — for each restricted dataset, keep it gated, license it, substitute it, or drop it.

## How to read this
- **Disposition** is the engineering recommendation for the review to accept, modify, or reject.
- **Cleared substitute** is a *candidate* only; adopting one requires its own contract, attribution, and a
  separate build + review. BallDontLie (paid tier) and SportsDataIO appear in `DATA_REFRESH_README.md` as
  considered options; neither is wired in code today.
- Nothing here lifts the gate. Enabling any restricted dataset is a conscious, reviewed decision that would
  (a) secure a license, (b) wire the substitute/licensed source, (c) add attribution, (d) pass containment +
  QC, and only then (e) flip the gate.

## Decision table

| # | Dataset | Current source | Why restricted | Options (keep gated / license NBA / substitute / drop) | Candidate cleared substitute | Recommendation |
|---|---|---|---|---|---|---|
| 1 | NBA reg. gamelogs | stats.nba.com (`nba_api`) | NBA.com ToS §9(iv); bulk stat redistribution | license NBA data OR substitute OR keep gated | licensed stats provider (SportsDataIO / BallDontLie paid) | **Substitute** if the NBA model is a priority; else keep gated |
| 2 | NBA playoff logs + results | stats.nba.com + ESPN | same as #1; ESPN scrape for results | substitute / keep gated | licensed stats + a permitted results feed | Keep gated until #1 is resolved (shares lineage) |
| 3 | NBA schedule (start times) | nba.com (+Odds fallback) | NBA.com-derived facts | **already have a licensed path** | Odds-API schedule alias (in repo) | **Prefer the Odds-API schedule**; retire the NBA.com schedule read |
| 4-6 | NBA tracking / advanced / defense | stats.nba.com | granular NBA.com tracking IP | substitute / keep gated | licensed advanced-stats provider | Keep gated; substitute only if the model needs it |
| 7 | NBA injuries | official/cdn/stats.nba.com + ESPN | NBA.com injury report IP (spoof removed) | license / substitute / keep gated | licensed injury feed | **Substitute with a licensed injury feed**; do not re-enable the NBA.com scrape |
| 8 | NBA/WNBA officiating | official.nba.com | official.nba.com scrape | license / drop | licensed officiating data, or drop the lens | **Drop or license** — lowest value-to-risk |
| 11 | NBA roster | NBA.com / document | roster facts, NBA.com-labeled | license / substitute | licensed roster feed | Low priority; substitute with #1 |
| 12 | WNBA gamelogs | stats.nba.com (league_id 10) | same NBA.com lineage as #1 | substitute / keep gated | licensed WNBA stats | Keep gated until a WNBA stats license exists |
| 9,10,13,14 | NBA/WNBA props + lines | **The Odds API (licensed)** | — (permitted) | already cleared | — | **Keep as-is**; confirm key-in-URL log hygiene |
| 15 | WNBA injuries | ESPN (now gated) | gated with the family for consistency | license ESPN / keep gated | permitted ESPN/injury feed | Keep gated with the family, or clear ESPN terms separately |

## Cross-cutting items for the review
1. **The Odds API is the one live, licensed NBA/WNBA surface** (market-only board). It renders while the gate
   is off and is the safe baseline for any NBA product that ships before a stats license.
2. **A licensed stats provider decision (#1/#12)** unlocks the bulk of the gated model (gamelogs → projections,
   tracking, advanced). It is the highest-leverage single decision.
3. **Injuries (#7)** should move to a licensed feed, never back to the NBA.com scrape (the spoof is gone and
   must not return).
4. **Officiating (#8)** is the lowest value-to-risk; default to drop unless cheaply licensable.
5. **Attribution**: any licensed source adopted needs its required attribution wired into the UI.
6. **Historical restricted artifacts** (already-collected `data/gamelogs/`, `data/tracking/`, … — all
   gitignored, not committed) should be **quarantined, not deleted**, pending the decision, so a future
   licensed build can be validated against them in a test-only context.

## What a "yes" on any row requires before the gate moves (engineering gate)
- a signed license or confirmed-permitted source for that dataset;
- the substitute/licensed fetcher wired, with attribution;
- `qc_nba_containment.py` + `qc_legal_containment.py` still green (containment holds for everything not cleared);
- a both-flag QC proving the newly-cleared dataset renders ON and everything else stays contained;
- then, and only then, a scoped flip of `BK_NBA_STATS_ENABLED` (or a per-dataset successor flag).

**No action is taken on this table without that review and sign-off.**
