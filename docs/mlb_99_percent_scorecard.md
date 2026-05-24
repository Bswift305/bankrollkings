# MLB 99% Scorecard

Use this scorecard to judge whether the MLB side is operating at the same trust standard as NBA and WNBA.

## Sections

- `Refresh Reliability`
- `Source Truth Accuracy`
- `Suggestion Integrity`
- `Injury And Return Context`
- `Visual Trust`
- `Archive And Replay Completeness`
- `Calibration Maturity`
- `Repeatability`
- `Formula Learning`

## Status Rules

- `PASS`: the section is operating cleanly with no active integrity problem.
- `WATCH`: the structure is in place, but the evidence or maturity is still building.
- `FAIL`: the section is missing a required artifact, has an active QC failure, or is not trustworthy enough to lean on.

## Decision Rule

- `MLB 99% READY`
  - no `FAIL` sections
  - `2` or fewer `WATCH` sections
- `NOT 99% YET`
  - any `FAIL`
  - or more than `2` `WATCH` sections

## What Counts As 99%

- refresh runs are reliable
- feeds are fresh and loaded
- contradiction QC is clean
- injury context is visible and governed
- the board is hard to misread
- suggestion surfaces are archived and replayable
- resolved results are accumulating into calibration
- repeated QC cycles stay clean

## Honest Constraint

Calibration and formula learning may stay `WATCH` until enough resolved MLB featured rows accumulate. That is expected. The goal is to make every other section strong enough that the remaining watches are only evidence-volume watches, not governance failures.
