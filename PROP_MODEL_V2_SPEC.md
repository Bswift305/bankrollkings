# Prop Model V2 Spec

## Purpose

This document defines the `v2` prop-ranking model for Bankroll Kings.

The goal is to turn the current hand-tuned prop engine into a documented, stable, developer-friendly scoring system with:

- explicit input layers
- explicit priority rules
- explicit override rules
- tighter playoff handling
- less drift between pages

This is a rule-based scoring model, not a trained machine-learning model.

## High-Level Model Type

The current engine should be described as:

`a deterministic, feature-weighted prop scoring system`

It does **not** generate rankings from one closed-form academic betting formula.

It works by:

1. choosing the right sample
2. calculating exact-line over/under hit rates
3. stabilizing small samples
4. applying contextual boosts/penalties
5. choosing the better side
6. converting the adjusted rate into confidence
7. ranking and tiering the results

## Core Design Principle

The model should follow this rule:

`hard evidence beats soft signals`

That means:

- exact-line series results beat generic trend tags
- shot volume beats vibes
- minutes/role stability beats narrative
- opponent-specific failure at the line beats broad season averages

If a player has missed the same line 4 straight playoff games, the model should need a very strong reason to still rank the over.

## Model Pipeline

### 1. Sample Selection

Choose the correct source before calculating anything.

#### Regular season mode

- use current-team sample if the player has enough games with current team
- otherwise use full-season sample

#### Postseason mode

- use playoff logs first
- do not mix regular-season logs into playoff rankings unless explicitly building a fallback feature

#### Sample rules

- regular season minimum sample: `5`
- playoff minimum sample: `2`

If minimum sample is not met:

- do not create a ranked playable prop
- allow a watchlist state only if needed later

### 2. Raw Exact-Line Rates

For each `player + stat + line`:

- compute `over_rate`
- compute `under_rate`
- compute `push_rate`

This is always based on:

- exact stat
- exact line
- selected sample

This is the first real anchor of the model.

### 3. Sample Stabilization

Small playoff samples should not display fake certainty.

Rule:

- shrink raw rates back toward `50%` when sample is small
- target stabilization window: `6 games`

Examples:

- `3/3 over` should not read like a true `100% certainty`
- it should read like `strong lean, small sample`

This applies to displayed weighted O/U and to downstream confidence inputs.

### 4. Recency Weighting

Build weighted rates from:

- full selected sample
- last 10
- last 5

Current weighting structure:

- if sample >= 10:
  - full sample: `20%`
  - last 10: `30%`
  - last 5: `50%`
- if sample >= 5:
  - full sample: `35%`
  - last 5: `65%`
- if sample < 5:
  - stabilized full sample only

Important:

- recency is a secondary weighting layer
- recency is not allowed to erase a strong series miss pattern without support from minutes and volume

### 5. Primary Scoring Inputs

These should drive the side selection most heavily.

#### Primary inputs

1. exact-line weighted O/U rate
2. recent shot volume for scoring stats
3. projected minutes
4. role stability
5. direct series/opponent performance at the same line

#### Secondary inputs

1. hot/cold tags
2. pace/total
3. spread/blowout risk
4. generic trend labels
5. pressure/narrative tags

## Stat Family Rules

Different prop types should not be treated identically.

### Points

Points props should prioritize:

1. exact-line hit rate
2. FGA
3. FTA
4. projected minutes
5. current series scoring against same opponent
6. role/usage
7. environment

Points props should be hardest to force upward with soft tags.

#### Hard under trigger for points

If all are true:

- player has at least `3` current-series games
- player is `0-for-series` clearing the line
- recent FGA is weak relative to line

Then:

- apply a strong under penalty
- suppress `L5 SURGE` style over language unless separately justified

### Rebounds

Rebounds props should prioritize:

1. exact-line hit rate
2. projected minutes
3. rebound role
4. opponent rebound environment
5. blowout/game script effect

### Assists

Assists props should prioritize:

1. exact-line hit rate
2. touches
3. drives
4. usage/playmaking role
5. projected minutes
6. opponent assist suppression

### Threes

3PM props should prioritize:

1. exact-line hit rate
2. 3PA or proxy shot volume
3. projected minutes
4. role stability
5. opponent 3-point profile

### Stocks

`STL` and `BLK` should be treated as more volatile.

That means:

- lower confidence ceiling by default
- stronger downgrade when sample is tiny
- more caution in top-of-board ranking

## Context Modules

### Projection context

Projection context should contribute:

- projected minutes
- minutes delta
- usage rate
- TS%
- role label
- snapshot consistency
- snapshot trend

Projection context should help confirm a play, not invent one.

### Game environment

Game environment should contribute:

- total
- spread
- blowout risk
- pace tags

Environment should be a modifier, not a base driver.

Suggested philosophy:

- environment should rarely flip a side by itself
- environment should mostly separate close calls

### Situational context

Situational context includes:

- back-to-back
- elite defense
- hot/cold
- pressure tags

This should remain a lighter layer than:

- hit rate
- volume
- minutes
- direct opponent evidence

## Side Selection Logic

After all adjustments:

1. calculate adjusted over score
2. calculate adjusted under score
3. choose side with higher adjusted score
4. convert adjusted score into displayed confidence

Rule:

If the model chooses a side that directly contradicts:

- `0-for-3`
- `0-for-4`
- or similarly strong same-series evidence

then at least one of these must also be true:

- minutes projection has materially increased
- shot volume has materially increased
- role changed upward
- line moved materially downward

If not, the contradiction should be treated as model failure.

## Confidence Philosophy

Displayed confidence is a presentation layer, not raw probability.

That means:

- confidence is derived from adjusted rates
- confidence is normalized to keep the board readable

But it should remain bounded by reality.

### Confidence targets

- `50-64`: weak lean / watchlist
- `65-74`: playable
- `75-84`: strong
- `85-94`: elite board play
- `95-99`: reserved for truly exceptional profile alignment

### Important rule

`95-99` should be rare.

If too many props are landing at `99%`, the confidence layer is overstating certainty and flattening the board.

## Ranking Rules

After confidence is generated, the board ranks should be sorted by:

1. confidence
2. build quality / strategy score
3. edge / EV
4. minutes / stability

Not every high-confidence prop should be top-tier parlay material.

The board should separate:

- best raw side
- best betting price
- best floor-play leg
- best parlay leg

## Override Rules

These rules are critical.

### Rule 1: Series miss override

For postseason `PTS` props:

If:

- series games >= 3
- player is under the line in every game
- FGA is not rising materially

Then:

- under gets strong priority
- over cannot be top-ranked unless role/minutes increased enough to justify a new projection regime

### Rule 2: Volume override

For `PTS` and `3PM`:

- weak shot volume limits over confidence
- strong shot volume can rescue an over even if raw hit rate is mixed

### Rule 3: Minutes override

If projected minutes are unstable or falling:

- do not allow soft trend tags to manufacture aggressive overs

### Rule 4: Volatility cap

For `STL`, `BLK`, and other volatile props:

- cap confidence more aggressively
- require stronger evidence to place them at top of board

## Page Consistency Rule

All prop surfaces must use the same logic inputs in the same mode.

That includes:

- Props
- Smart Picks
- Parlay Builder
- Series page
- Matchup page
- Player page

If postseason mode is on, all of these must use the same playoff sample path.

No page should rank a player over while another page ranks the same stat/line under unless:

- the lines differ
- the sample differs by design and is clearly labeled

## What Drifted In V1

These are the main problems we are correcting.

1. Too many soft tags could overpower direct line evidence.
2. Postseason pages were not always using the same sample source.
3. Small playoff samples were displayed as false certainties.
4. Points props were not strict enough about shot volume and repeated series misses.
5. Confidence distribution became too compressed near the top.

## Recommended Refactor Structure

Developers should think of the engine as these modules:

1. `sample selection`
2. `base rates`
3. `stabilization`
4. `stat-family adjustment`
5. `projection adjustment`
6. `game environment adjustment`
7. `side selection`
8. `confidence normalization`
9. `ranking and tiering`

Suggested future implementation shape:

```text
score_prop(player, stat, line, mode):
    logs = select_logs(player, mode)
    base = calculate_exact_line_rates(logs, stat, line)
    base = stabilize_small_sample(base, len(logs))
    stat_adjusted = apply_stat_family_rules(base, logs, stat, line)
    projection_adjusted = apply_projection_rules(stat_adjusted, projection_context)
    environment_adjusted = apply_environment_rules(projection_adjusted, market_context)
    side = choose_side(environment_adjusted)
    confidence = normalize_confidence(side.adjusted_rate)
    return build_ranked_prop(side, confidence, metadata)
```

## What A Developer Should Be Told

Use this summary:

> The Bankroll Kings prop model is a rule-based scoring engine, not a black-box ML model. It starts from exact-line over/under hit rates, stabilizes small samples, then layers in recency, playoff series evidence, role/minutes projection, volume, opponent context, and game environment. The v2 spec tightens the hierarchy so hard evidence like series misses and shot volume can override softer trend tags.

## Immediate V2 Priorities

1. Separate hard signals from soft signals in code.
2. Reweight `PTS` props so shot volume and same-series results dominate.
3. Enforce the same playoff sample path on every page.
4. Reduce fake `99%` saturation.
5. Add automated tests for contradiction cases like:
   - series page says under
   - parlay page says over

## First Test Cases To Lock In

These should become regression tests:

1. A player under the same `PTS` line in 4 straight playoff games should not rank as a featured over without major role/volume change.
2. A player with `3/3` playoff overs should not display as `100% certainty`; small-sample stabilization should pull that down.
3. Postseason `Props`, `Smart Picks`, `Parlay`, and `Series` should agree on direction for the same player/stat/line.
4. Low-minute, low-volume bench players should not dominate the top of series prop boards from tiny samples alone.

