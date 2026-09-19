# NFL Product Spec — the three surfaces

Turns the validated angles (see FINDINGS.md) into weekly product + content. All three
read the **same scored-props data your model already produces** — this is *surfacing an
edge you already compute*, not building new models. The engine (`nfl_edge_board.py`)
already generates each list.

---

## 1. 🏆 Kings' Top Plays  (the flagship — everyday product)
- **What it is:** the model's highest-conviction leans, ranked by `BK_NFL_PropScore`.
- **Filter:** model lean (`Confidence > 50`), `PropScore ≥ 10` (standard) / `≥ 20` (premium).
- **Shows:** Player · Prop · line · the model's side · PropScore · a confidence chip.
- **Proven:** +9→+16% ROI, replicated OOS, ~60–200 plays/week (a full board).
- **Tiering:** show the **count + a couple teasers free**; the full ranked board is **All Access**. This is your paid core for NFL.
- **Content:** "This week's Top Plays" graphic (Sunday AM), and a weekly **graded recap** ("last week's Top Plays went X-Y") — honest receipts, on-brand.

## 2. 📈 Usage / Volume  (the weekly hook — replaces the "hot streak")
- **What it is:** players with locked-in, high, stable usage the market underprices.
- **Filter:** model lean, top-quartile `UsageStability`.
- **Shows:** Player · Prop · line · "Volume: High" tag.
- **Proven:** +12% ROI both seasons.
- **Angle:** *"Volume is king."* Intuitive, sticky, weekly. The NFL equivalent of the NBA
  opportunity idea — bet the guys who get the ball, not the guys who got hot.
- **Content:** "Volume Report" cards; pairs with injury news ("starter out → who eats").

## 3. 🌬️ Wind Report  (the specialist conviction play)
- **What it is:** passing/receiving **unders** when wind ≥ 15 mph.
- **Filter:** `Stat ∈ passing/receiving`, `WindMph ≥ 15`, side = UNDER.
- **Proven:** +10→+22% ROI; the over side is a −22%/−32% disaster (clean direction).
- **Cadence:** rare (~40–50 spots/season) → **high-conviction alert**, not a daily board.
  "🌬️ Windy today — passing unders are live." Ties to the wind cards you already made.

---

## Rollout
1. **Now (off-season):** engine + memo done; wire nothing live yet (no games).
2. **Preseason → Week 1:** point `nfl_edge_board.py` INPUT at the live weekly scored-props
   file; add a `/nfl/top-plays`, `/nfl/usage`, and wind-alert surface that call
   `top_plays()`/`usage_plays()`/`wind_report()`. (Model already computes the inputs.)
3. **Forward-capture (recommended):** log each board's plays with the CLOSING line+price
   and grade weekly — same pattern as the NBA sleeper harness — so the live record is
   public and honest ("Top Plays: 34-21, +8% ROI this season").

## Honest framing (every surface)
- "For entertainment & informational purposes." Show the model's number vs the market,
  and the real running record — wins and losses. No "locks."
