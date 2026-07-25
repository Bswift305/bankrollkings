# Best Lines Quick Tool — Developer Handoff

**Status:** Product recommendation approved for developer review  
**Audience:** Bankroll Kings developer  
**Scope:** Cross-sport, factual player-prop line comparison  
**Target route:** `/tools/best-lines`

---

## 1. Product objective

Give multi-sport bettors one fast answer:

> Which available sportsbook currently has the most favorable listed number or price for this player prop?

This tool is a line-shopping surface, not a betting recommendation engine. It should display observable sportsbook offers across supported sports without claiming that an offer has positive expected value.

Supported feeds:

- NBA
- WNBA
- MLB
- NFL
- NCAAF, when player props are actually available

The tool should remain useful when only one sport is active. Inactive or unavailable sport feeds must be labeled honestly rather than treated as application failures.

---

## 2. Product rules

### Best Number

The easiest listed threshold for the selected direction:

- **OVER:** the lowest available line
- **UNDER:** the highest available line

If multiple books share that number, use the best available price among those books as the displayed offer.

### Best Price

The highest available American price for the selected direction.

The line belonging to that exact price must always be displayed. A favorable price at a worse number must not be presented as though it applies to the Best Number offer.

### Keep the two concepts separate

Best Number and Best Price can come from different sportsbooks. The interface must not collapse them into a single “best bet,” “edge,” or “value” score.

Example:

| Direction | Best Number | Best Price |
|---|---|---|
| Over | Over 6.5 at Book A, -120 | Over 7.5 at Book B, +105 |

The user can see the tradeoff; the product should not decide it for them.

---

## 3. Required source data

Use the existing per-sport prop loaders and their normalized fields:

| Field | Purpose |
|---|---|
| `Player` | Player identity |
| `Stat` | Prop market |
| `Game` | Matchup identity |
| `Book` | Sportsbook |
| `CurrentLine` | Preferred current threshold |
| `Line` | Fallback threshold when `CurrentLine` is absent |
| `OverOdds` | Current American price for the over |
| `UnderOdds` | Current American price for the under |
| `LastUpdated` | Offer timestamp |

Existing loaders identified for the tool:

- `load_props()` — NBA
- `load_wnba_props()`
- `load_mlb_props()`
- `load_nfl_props()`
- `load_ncaaf_props()`

Use `get_props_refresh_meta(..., max_age_hours=6)` for feed row count, book coverage, freshness, and stale-state labeling.

Do not infer missing prices, manufacture consensus lines, or substitute model projections for sportsbook offers.

---

## 4. Required interface

### Summary

Show:

- Total directional offers
- Multi-book comparisons
- Offers with a meaningful line range
- Available leagues and feed state

### Filters

Provide server-side filters for:

- League
- Direction: Over or Under
- Stat/market
- Player or game search
- Multi-book offers only

### Results table

Each row should contain:

- League
- Player
- Stat and game
- Direction
- Best Number, sportsbook, and price
- Best Price, sportsbook, and attached line
- Number of books
- Available line range
- Last updated time
- Stale or thin-market indicator when applicable

### Pagination

Do not render the complete cross-sport dataset in one response. Use server-side pagination, with approximately 200 rows per page.

### Empty states

Differentiate between:

1. **No live props exist:** books have not posted supported player props.
2. **No filter matches:** offers exist, but none match the selected filters.
3. **Sport is off-slate:** the absence is expected and not a feed error.

---

## 5. Required language and disclaimers

Recommended page description:

> Compare currently listed player-prop numbers and prices across available sportsbooks.

Required disclosure:

> Best Number identifies the easiest listed threshold for the selected direction. Best Price identifies the highest listed American price and includes the line attached to that offer. Neither label represents expected value, a prediction, or a betting recommendation.

Avoid unsupported labels such as:

- Best bet
- Positive EV
- Sharp side
- Lock
- Guaranteed value
- Market consensus, unless the calculation and minimum book depth are explicitly defined

---

## 6. Current local prototype

A local, uncommitted prototype currently exists in:

- `app.py`
- `templates/best_lines.html`

The prototype includes:

- `/tools/best-lines`
- Placement in the workflow navigation as **Best Lines**
- All Access gating
- Cross-sport aggregation
- Separate Best Number and Best Price calculations
- League, direction, stat, search, and multi-book filters
- Server-side pagination
- Feed freshness and availability states
- A 60-second in-process snapshot cache

This prototype has **not** been committed or deployed. It should be reviewed by the developer rather than treated as production-ready merely because it exists.

---

## 7. Prototype validation results

Authenticated local route checks passed for:

- Default results
- MLB + Over + multi-book filtering
- Second-page pagination
- No-match empty state
- Python compilation
- Whitespace/error checks with `git diff --check`

Observed local performance during validation:

| Request | Approximate result |
|---|---|
| Cold cross-sport snapshot | 10–17 seconds |
| Cached filter or page request | 0.05–0.08 seconds |
| Default rendered response | About 303 KB |
| Default page size | 200 rows |

The cold build requires attention before production approval. Production currently runs a memory-constrained single Gunicorn worker, so the developer should profile CPU time, peak memory, and first-request behavior using production-sized data.

`pytest` was not available in the local Python environment, so no repository test suite was executed.

---

## 8. Developer review checklist

- [ ] Review the uncommitted prototype diff before keeping any code.
- [ ] Confirm each loader uses equivalent current-line and price semantics.
- [ ] Verify duplicate book offers are resolved deterministically.
- [ ] Confirm American odds parsing handles blanks, malformed values, and non-American formats.
- [ ] Confirm stale timestamps are parsed consistently across sports.
- [ ] Profile cold aggregation memory and duration with production data.
- [ ] Decide whether the 60-second process-local cache is sufficient for Gunicorn.
- [ ] Consider cache invalidation based on source-file modification times.
- [ ] Add unit tests for Over/Under Best Number selection.
- [ ] Add unit tests proving Best Price retains its exact attached line.
- [ ] Add route tests for filters, pagination, empty feeds, and stale feeds.
- [ ] Test desktop and mobile table behavior.
- [ ] Confirm sportsbook naming is normalized across feeds.
- [ ] Confirm licensing and display permissions for every sportsbook source.
- [ ] Update `docs/PROJECT_MAP.md` only after the feature is approved and shipped.
- [ ] Commit and deploy through the normal Bankroll Kings release process.

---

## 9. Acceptance criteria

The feature is ready when:

1. Every displayed value can be traced to a current sportsbook-feed row.
2. Best Number follows the correct directional rule.
3. Best Price always includes the line belonging to that price.
4. Stale, single-book, missing, and off-slate data are clearly distinguished.
5. Filters and pagination preserve all query parameters.
6. The page makes no EV or predictive claim.
7. Cold and warm performance are acceptable on the production EC2 instance.
8. Automated calculation and route tests pass.
9. The developer has reviewed and intentionally accepted or replaced the local prototype.

---

## 10. Deferred related tool: Market Movers

Do not ship Market Movers from the current data.

The existing line-movement files do not yet contain enough temporal snapshot depth:

- Current files largely show Open equal to Current.
- Historical files generally contain only one or two snapshots per game.
- Book-to-book disagreement must not be mislabeled as temporal line movement.

Revisit Market Movers only after the capture pipeline reliably stores multiple timestamped observations throughout each market’s life.

