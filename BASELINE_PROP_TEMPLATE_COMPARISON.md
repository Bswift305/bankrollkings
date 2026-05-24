# Baseline Prop Template Comparison

## Purpose

This document compares the current Bankroll Kings prop engine against a few public NBA prop-model templates so we can:

- identify the conventional baseline
- identify where our system is stronger
- identify where our system drifted
- decide what the `v2` model should keep or remove

## Short Answer

Bankroll Kings is **more advanced than a basic average-based prop tool**, but it is **less disciplined than a clean conventional projection model**.

That means:

- we are ahead on context richness
- we are behind on formal structure and consistency

## Comparison Targets

### 1. Simple Heuristic Baseline

Repo:

- [parlayparlor/nba-prop-prediction-model](https://github.com/parlayparlor/nba-prop-prediction-model)

What it does:

- pulls player logs with `nba_api`
- calculates recent averages
- adds simple matchup analysis
- exports projected stats

Why it matters:

- this is the easiest version of a player-prop template
- it is useful as a "minimum viable" baseline

What it is missing:

- no deep confidence logic
- no robust market comparison
- no formal probability calibration
- limited playoff logic

### 2. Conventional Projection + Market Template

Repo:

- [chevyphillip/plus-ev-model](https://github.com/chevyphillip/plus-ev-model)

What it does:

- builds player prop predictions with engineered features
- uses rolling windows
- uses home/away splits
- uses opponent strength metrics
- uses a ridge regression model
- compares model output to sportsbook lines
- calculates edge and Kelly sizing

Why it matters:

- this is much closer to a conventional "serious" prop pipeline
- it has a clear structure:
  - data
  - features
  - model
  - probability
  - edge
  - bet sizing

What it is missing relative to us:

- less obvious playoff-series nuance
- less visible role/tag language for a bettor-facing UI
- likely less explainable at the page level unless extra UI is added

### 3. Regression Research Baseline

Repo:

- [VinceDiR/Prop_Betting_Regression_Project](https://github.com/VinceDiR/Prop_Betting_Regression_Project)

What it does:

- uses linear regression to model NBA prop outcomes
- merges player stats, team stats, and betting data
- evaluates whether predictions would have beaten the market

Why it matters:

- this is a useful baseline for "projection-first" modeling
- it is closer to a research workflow than a live app

What it is missing:

- not a polished product engine
- limited live-site decision logic
- less operational than our current tool

### 4. Prop Analysis UI Baseline

Repo:

- [matthew-hoty/nba-player-prop-analysis-shiny](https://github.com/matthew-hoty/nba-player-prop-analysis-shiny)

What it does:

- creates a UI around prop evaluation
- compares predicted probability to implied sportsbook probability
- helps rank edges in a bettor-facing app

Why it matters:

- useful for interface and workflow comparison
- reinforces that a prop engine should separate:
  - prediction
  - market comparison
  - decision support

## Our Current Model

Our current engine is best described as:

`a rule-based, feature-weighted prop ranking engine`

It currently does:

- exact-line over/under rates
- current-team vs full-sample selection
- playoff sample switching
- small-sample stabilization
- postseason/series adjustments
- role/minutes projection
- tracking/usage context
- game environment adjustments
- confidence normalization
- board ranking
- tiering
- parlay/floor-play overlays

This is more complete than the simple baseline repos.

## Side-by-Side Comparison

### A. Core modeling style

#### Simple baseline

- recent averages
- basic matchup adjustments

#### Conventional regression template

- engineered features
- trained projection model
- market edge calculation

#### Bankroll Kings

- hit-rate-first
- layered rule adjustments
- projection-aware
- market-aware
- heavy context overlay

### B. Strengths of Bankroll Kings

1. Better bettor-facing UX than research repos
2. Better playoff/series awareness than generic models
3. Better role/minutes language
4. Better integration with props, parlays, review, and glossary systems
5. Better practical explainability than black-box style templates

### C. Weaknesses of Bankroll Kings

1. No single governing mathematical template
2. Too many hand-tuned modifiers
3. Hard evidence and soft tags were not clearly separated
4. Page-to-page logic drift happened
5. Confidence can overstate certainty
6. No formal regression test suite around contradiction cases

## Where We Are Better

We are better than the basic average-based repos at:

- integrating minutes/role/context
- surfacing bettor-readable signals
- handling postseason narratives and series state
- turning research into a usable product

## Where Conventional Templates Are Better

The regression/probability-first repos are better at:

- architectural discipline
- projection-first thinking
- cleaner feature hierarchy
- market comparison structure
- evaluation framing

In other words:

- they are weaker products
- but often cleaner modeling templates

## The Main Architectural Difference

### Conventional baseline

```text
project stat
-> convert projection to probability
-> compare against market line/price
-> rank by edge
```

### Bankroll Kings today

```text
measure hit rate at line
-> reweight with recency and context
-> add role/matchup/playoff modifiers
-> choose side
-> normalize confidence
-> rank and tier
```

That is the biggest conceptual difference.

## Is Our Model Top Notch?

Not yet.

### Honest grade right now

- product thinking: strong
- betting workflow design: strong
- model structure: promising but not elite
- modeling discipline: needs tightening
- consistency/guardrails: not strong enough yet

### Better wording

The current system is:

- creative
- useful
- more advanced than beginner templates
- but not yet top-tier because it is still too heuristic and too loosely governed

## What "Top Notch" Would Mean

To be called top notch, the model should have:

1. explicit formula hierarchy
2. stat-family rules
3. contradiction protection
4. calibrated confidence
5. page-to-page consistency
6. regression tests
7. clear separation between:
   - projection
   - probability
   - edge
   - presentation

## Recommended Baseline To Use

Use these as our comparison set:

### Primary baseline

- `chevyphillip/plus-ev-model`

Why:

- closest to a serious player-prop template
- has clear prediction-to-edge structure

### Secondary baseline

- `parlayparlor/nba-prop-prediction-model`

Why:

- useful "simple version" benchmark
- keeps us honest about not overcomplicating basic projections

### Supporting reference

- `VinceDiR/Prop_Betting_Regression_Project`

Why:

- good for projection-first and evaluation framing

## Strategic Conclusion

We should not replace Bankroll Kings with one of these repos.

We should use them as:

- structural comparisons
- baseline templates
- discipline checks

The right goal is:

`keep our bettor-facing strengths, but rebuild the model around a cleaner conventional spine`

## Recommended V2 Direction

The `v2` model should become:

`projection + probability + market + context`

instead of:

`hit rate + many modifiers + confidence normalization`

More specifically:

1. project player output
2. estimate over/under probability at the line
3. compare against market implied probability
4. use context layers as controlled modifiers, not dominant drivers
5. use UI tags only as explanation, not as major ranking engines

## Immediate Next Step

Use this document with `PROP_MODEL_V2_SPEC.md` to guide the next implementation pass.

Suggested first implementation order:

1. define a projection-first baseline for `PTS`
2. compare its side output to current Bankroll Kings `PTS` logic
3. tighten conflict cases like Dyson
4. expand to `REB`, `AST`, `3PM`

