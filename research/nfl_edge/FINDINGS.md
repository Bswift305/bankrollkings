# NFL Props: Niche Hunt Findings

**Date:** 2026-08-22 · **Data:** `data/tracking/NFL_AllPropResults_Scored.csv` — 16,490 unique graded props, seasons **2024 (scout) + 2025 (out-of-sample)**, with REAL lines, bet prices, outcomes, and pre-game features (WindMph, Temperature, Roof, RestDays, UsageStability, GameScript, BK_NFL_PropScore). Unlike NBA (signal-only, no local lines), NFL let us measure **real ROI**.

## TL;DR
- **Hot streaks do NOT work in NFL** — betting overs after a 2-week over-streak lost −8.8% (2024) / −13.0% (2025), *worse* than baseline. Killed.
- **Three angles held up across both seasons, on real money:**
  1. **Top Plays** — `BK_NFL_PropScore ≥ 10` → **+9.2% / +11.3%**; `≥ 20` → **+13.3% / +16.1%** (63–66% hit).
  2. **Usage / Volume** — top-quartile `UsageStability` → **+12.1% / +11.8%**.
  3. **Wind Report** — passing/rec **UNDERS** at 15+ mph → **+10.4% / +21.9%** (the mirror, overs, = −22%/−32%).

Method (no tautology): one bet per prop = the model's **lean** side (`Confidence > 50`); ROI at `BetPrice`; 2024 to find, 2025 to confirm.

## Results
| Angle (bet the model's lean / value side) | 2024 | 2025 (OOS) | Volume |
|---|---|---|---|
| Top Plays `PropScore ≥ 10` | +9.2% (63%) | +11.3% (63%) | ~120–200/wk |
| Top Plays `PropScore ≥ 20` (premium) | +13.3% (66%) | +16.1% (66%) | ~60–90/wk |
| Usage top quartile | +12.1% (64%) | +11.8% (63%) | ~70–120/wk |
| Wind 15+ passing UNDER | +10.4% (59%) | +21.9% (64%) | ~40–50/season |
| *baseline: all overs* | −8.2% | −9.9% | — |

## What did NOT hold (cut, don't oversell)
- Hot streaks (negative, worse OOS).
- Raw `BK_NFL_EdgeScore` (noisy ramp; `PropScore` is the clean one).
- Situational tags alone: `LOW_TOTAL`, `DIVISION_GAME`, `PROJECTED_TIGHT_GAME` — inconsistent across seasons.
- Cold-alone, rushing-in-wind, dome overs, rest — none replicated.

## Caveats
- Props are **historical backfill** (reconstructed bet prices), so live execution needs line-shopping and the absolute ROI may trim — **but every angle replicated out-of-sample and the PropScore ramp is monotonic (higher score → higher ROI both years).** That's the real signal.
- 2 seasons; wind is low-volume (offset by a large, mechanistic effect).

## Engine
`nfl_edge_board.py` produces all three boards from the scored schema (`verify` reproduces the ROI above; `board <season>` prints sample plays). In-season, point it at the live scored props for that week's slate. Scripts: `nfl_niche_hunt.py`, `nfl_model_edge.py`.
