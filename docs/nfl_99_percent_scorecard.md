# NFL 99% Scorecard

Use this scorecard to judge whether NFL is operating at the same trust standard as the governed basketball and baseball boards.

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

- `PASS`: the section is structurally sound and currently clean.
- `WATCH`: the section is operational, but still building evidence or repeated clean cycles.
- `FAIL`: the section has an active integrity problem or is missing a required artifact.

## Decision Rule

- `NFL 99% READY`
  - no `FAIL`
  - `2` or fewer `WATCH`
- `NOT 99% YET`
  - any `FAIL`
  - or more than `2` `WATCH`

## NFL-Specific Note

NFL props are a support layer, not the first read. The board should always prove:

- sides and totals still lead the script
- prop support buckets are historically trustworthy
- tight-support yardage plays do not survive as clean premium plays
- fade or weak governance buckets do not get dressed up as confidence
