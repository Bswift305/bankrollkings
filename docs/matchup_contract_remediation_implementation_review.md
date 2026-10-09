# Remediation Implementation Review (Rev 3 Final)

Implementation of the approved spec `docs/matchup_contract_remediation_spec.md` (Rev 3 Final),
commit **60226f6**. Copy / labels / tooltips / framing only. 9 files, 25 insertions / 26 deletions.
Proving the ten required verification points.

## 1. Every replacement appears exactly as specified ✅

| Spec item | Surface | Verified change |
|---|---|---|
| P1.1 | matchup.html | key → "Market-implied probability" bands; badges → "{N}% market-implied" (all 3 branches); column "Verdict" → "Market-implied %"; 6th column "Play" → "Side" |
| P1.2 | mlb_matchup.html | "Best Anchor" → "Historical Hit-Rate Leader"; "Highest reliability prop…" → "Prop with the highest displayed historical hit rate…" |
| P2.1 | app.py + green_light.html | tiers → "4+/3/2/1 configured lenses" (both sides in sync) |
| P2.2 | green_light.html | intro "independent lenses" → "configured lenses"; Under-Review line added |
| P3.1 | daily_cards.html | subtitle → "assembled by rule… higher displayed historical hit rates at the current number… options, not a graded pick" |
| P3.2 | daily_cards.html | swap tooltip → "next alternate by the same rule" |
| P4.1 | app.py | free-tier → "by de-vigged market-implied probability, with displayed historical hit rates" |
| P4.2 | smart_picks_v2.html | sort label → "De-vigged market-implied probability" |
| P5.1/2/3 | cfb_board / nfl_board / nfl_game_board | headlines → "markets" / "market entries" / "largest model–market difference" / "displayed historical hit rate (default sort)" |

Old-string scan on the eight surfaces returns none of: Lock / Play / Pass / Highest conviction /
Strong context / Best Anchor / Highest reliability / best of the board / high-floor / next-best /
Highest Confidence / best plays / "the model's edge" (customer copy).

## 2. IDs unchanged ✅
No identity, join, or ID code was touched. Changes are text nodes in templates plus two string
literals in `app.py` (tier display names, free-tier copy). `git diff app.py` is exactly those two
edits.

## 3. Ordering unchanged ✅
No sort/order code touched. The NFL top board's default sort (`hit_pct`, in
`filter_and_sort_nfl_plays`) is unchanged; the `/market-edge` sort still passes
`('confidence','desc')` — only the button's visible label changed.

## 4. Thresholds unchanged ✅
`matchup.html` still branches on `prop.is_lock` and `prop.confidence >= 70` — only the badge **text**
changed to "{N}% market-implied" in each branch; the 70% boundary and the `is_lock` flag are intact.

## 5. Tier membership unchanged ✅
`build_green_light` still assigns tiers by `pl['convergence']` (≥4 / ==3 / ==2 / else) and the
template `ti` map was updated to the new names in lockstep. Smoke run: tiers rebuild as
`['4+ configured lenses','3 configured lenses', …]` with the same plays — only the display names
changed. Convergence counting and the market gate are untouched.

## 6. Daily Card legs unchanged ✅
`build_daily_cards` (selection/composition) was not touched; only `daily_cards.html` subtitle and the
swap-button tooltip changed. Same legs, same cards.

## 7. Swap order unchanged ✅
Only the swap button's `title` tooltip text changed; the swap/alternate logic is untouched.

## 8. No new authority language introduced ✅
Every replacement is observational/mechanical — "market-implied probability," "displayed historical
hit rate," "configured lenses," "largest model–market difference," "markets/market entries," "Side."
The only "edge" occurrences are **negations** ("not a validated edge," "not a graded edge").

## 9. Identified authority-language findings resolved ✅
All P1–P5 findings from the accepted conformance review are remediated (table in §1). The literal
"Lock" (do-not-build) is gone; Green Light no longer claims conviction or independence; Daily Card
no longer claims "best/strongest"; board headlines no longer claim "best/edge."

## 10. No claim of product-wide structural conformance ✅
This remediation addresses **only the identified authority-language findings**. It does **not**
assert product-wide conformance.

## Scope notes (transparency)

- **Extended (within the accepted correction):** the accepted independent→configured fix was applied
  to a **second** customer-facing instance on the same surface — `green_light.html:53`
  ("5 independent lenses can agree" → "5 configured lenses can point the same way") — so Green Light
  is internally consistent. Same word, same surface, same accepted correction.
- **Flagged, NOT changed (out of approved spec):** `nfl_board.html:64` ("…a **validated** PropScore
  play… because one is **proven**…") is a pre-existing overclaim relative to the frozen contract
  (nothing is documented Qualified). It was **outside the approved spec's lines**, so it was left
  untouched and is logged here for a future conformance pass. Route **docstrings** in `app.py`
  (e.g. "best plays, ranked by edge") are internal, not customer-facing, and were left as-is.

## Deploy
Pushed to `master` (60226f6); the `bk-deploy` timer pulls and `systemctl restart`s prod (~2 min),
which picks up template changes (preload_app needs a restart, which the timer performs).
