# CFB Game Lines (Spreads & Totals): Findings

**Date:** 2026-08-22 · **Data:** `NCAAF_OddsAPI_GameLines_History.csv` (935 games, full 2025 season, real spread/total/ML prices) joined to `NCAAF_CFBD_Games_2025.csv` (final scores + conference + neutral site). CFB **player props don't exist** locally (`NCAAF_AllPropResults.csv` = 2 bytes) — CFB is a **game-line** story.

## TL;DR
On one season, **there is no strong, provable CFB game-line niche.** Totals show no edge. The only signal positive in **both** halves of the season is **home favorites covering the spread — and it's razor-thin (+1.8% ROI at −110, 53% cover).** Track it live; don't sell it yet.

## The honesty catch (why the first numbers were a lie)
The source `SpreadOdds` column is partly **contaminated with leaked spread values** (e.g. `−2.5` sitting where the price should be). Feeding that to a payout function pays **+40 units** on a win, which fabricated fake "+36% mismatch" and "+49% big-favorite" edges. Spreads are always ~−110, so the fix is a flat −110. **Every spread "edge" evaporated under the correct price** — exactly the trap this brand exists to avoid.

## True results (flat −110, split early ≤wk7 / late)
| Angle | All | Early | Late | Read |
|---|---|---|---|---|
| **Home favorites ATS** | +1.8% (53%) | +2.0% | +1.5% | thin but consistent — the one lead |
| Power-home vs G5 (mismatch) | −4.5% | −6.9% | — | was the fake +36%; **dead** |
| Totals OVER (all) | −6.6% | — | — | over-bias, no edge |
| Totals UNDER (all) | −2.5% | — | — | no edge |
| Blowout 21+ OVER | +9.1% | +14% | −4.6% | **early-season only**, fades |
| Moneyline dogs | −14% / −45% | — | — | dogs are priced; dead |

## What it means for the product
- **CFB player props: not a product** (no market/data).
- **CFB's edge, if any, is the game line in soft markets** — the honest version is *your model's projected spread/total vs. the market* (the Command Center "our number vs. theirs"), the same shape as NFL Top Plays. We can't test that here (the backfill carries no model edge score), so it must be proven live.
- The **home-favorite ATS lean** is a real, tiny thread worth tracking.

## Caveats
- **One season.** Early/late split is a weak out-of-sample proxy.
- **59% team-name match** on the join → a biased subset; a cleaner name map would firm the home-fav number.
- No weather joined (CFBD games file has none); wind-on-totals (proven in NFL) is worth adding when a weather source is wired.

## The move: capture forward (season starts this week)
`cfb_gameline_capture.py` logs the home-favorite ATS lead (and the mismatch, to watch it stay dead) with real closing lines each week and grades vs final scores → a hindsight-free 2026 record. Wire the model's projected lines in and it also tests the real product. `simulate` reproduces the numbers above.

---

## UPDATE — "The Reveal" edge (clean-slate in-season Elo) ✅
Reframed per the portal/NIL reality: **you can't predict CFB preseason — react to it.** Built a
clean-slate Elo (`cfb_reveal_elo.py`) that starts every team at 1500 with NO preseason prior and
learns game-by-game (HFA 65, K 42, 25 Elo/pt, MOV-aware). Tested its spread vs the market on 2025:
- **Tape ramp:** 1-2 games −6.4% · 3-4 −3.4% · **5-7 +6.6%** · 8+ +2.5%. Edge needs ~5 games of tape.
- **Sweet spot (tape≥4, model-vs-market edge 3-6 pts): 55.8% cover, +6.5% ROI (n=208).**
- **Weeks 5-9: +7.4%** ; weeks 10-15 flat (market catches up). Extreme gaps (10+ pts) LOSE (−14%) — fade our own model when it disagrees wildly.
The internal consistency (tape / week / edge-size curves all agree) makes it credible on one season.
**Product = "The Reveal" board** (live from ~Wk5: opponent-adjusted rating vs market, sweet-spot plays).
Still 1 season → forward-capture 2026 to confirm, but this is the real CFB view.

## THE REVEAL ENGINE — `cfb_reveal_engine.py` (built + verified)
Live weekly engine. Modes: `ratings` (clean FBS "who's for real" board — Indiana/Miami/Oregon
top in 2025, G5 risers like James Madison surfacing), `board [week]` (model vs market, sweet-spot
flagged), `capture`/`grade`/`report` (forward-capture record), `simulate` (reproduces the edge:
57.5% cover / +9.7%, weeks 5-9 63.6%/+21.5%). FBS-vs-FBS only (filters out FCS/D2/D3 pollution).
In-season: point ODDS at the live weekly odds feed; run `ratings`+`board` weekly, `capture` the
sweet-spot plays near lock, `grade`+`report` after games.
