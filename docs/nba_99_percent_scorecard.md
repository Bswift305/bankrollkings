# NBA 99% Scorecard

This is the NBA-only readiness scorecard for Bankroll Kings.

The goal is simple:

- not “is the app usable?”
- not “did the route load?”
- but “is the NBA engine trustworthy enough that it feels 99% ready?”

Use this as the focused standard for the flagship sport.

---

## Scoring Rule

Each section gets one status:

- `PASS`
- `WATCH`
- `FAIL`

### Decision Rule

- `NBA 99% READY`
  - no `FAIL`
  - no more than `2` `WATCH`
- `NOT 99% YET`
  - any `FAIL`
  - or `3+` `WATCH`

---

## 1. Refresh Reliability

### Question
- Does the NBA refresh chain run end to end without manual rescue?

### Must Include
- playoff results
- playoff player logs
- game lines
- player props
- injuries
- featured snapshot
- source QC
- contradiction QC
- board QC

### PASS
- full daily NBA refresh runs clean for multiple cycles
- no silent stale feeds
- no broken step in the chain

### WATCH
- refresh usually works, but still needs occasional manual intervention

### FAIL
- any core NBA refresh step is unreliable or silently stale

---

## 2. Source Truth Accuracy

### Question
- Is the NBA site using the correct source for the correct context every time?

### Must Be True
- postseason cards use postseason-only truth
- no regular-season fallback into playoff series state
- current series mapping is correct
- injuries and return impacts reflect current reality

### PASS
- source audit is clean
- postseason context is correct
- no known source-mixing bugs remain

### WATCH
- source QC is clean, but edge-case manual override dependence still exists

### FAIL
- any live NBA page can show the wrong series state, wrong source, or stale context without flagging it

---

## 3. Suggestion Integrity

### Question
- Are displayed NBA suggestions internally consistent and honest?

### Must Be True
- no contradiction failures
- no duplicate stat rows
- no broken streak direction
- no `CONFLICTED` or `PASS` rows being promoted as real plays
- zero-required fragile props visibly flagged
- expensive low-edge plays visibly downgraded

### PASS
- `qc_nba_contradictions.py` returns `0 failures`
- promoted surfaces only show rows that clear contradiction gating

### WATCH
- `0 failures`, but persistent warnings remain

### FAIL
- any contradiction failure
- or any promoted play that is visibly misleading

---

## 4. Injury And Return Context

### Question
- Does the NBA board correctly express GTD, OUT, DOUBTFUL, and return-risk situations?

### Must Be True
- GTD players show medical warning badges
- OUT/DOUBTFUL players are downgraded
- return squeezes affect support-role props
- name matching works across feed formats

### PASS
- no known injured/GTD player can appear unflagged
- return-impact suppressions are flowing

### WATCH
- the system is structurally correct, but still relies on some manual return overrides

### FAIL
- a real NBA injury/return state is present in data but not surfaced on the board

---

## 5. Visual Trust

### Question
- Could a smart user misunderstand the NBA board even if the underlying logic is correct?

### Must Be True
- `PLAY / CONFLICTED / PASS` are visually obvious
- market range context is visible
- injury flags are visible
- warning language is readable before a user leaves for a sportsbook
- no stat card overstates certainty

### PASS
- visual pass completed and no trust-breaking presentation issues remain

### WATCH
- logic is good, but visual trust pass is not fully complete

### FAIL
- any row still looks stronger/cleaner than it really is

---

## 6. Archive And Replay Completeness

### Question
- If someone challenges an NBA suggestion tomorrow, can we reconstruct what the model showed?

### Must Be True
- featured suggestions are saved
- market edge suggestions are saved
- floor suggestions are saved
- matchup top props are saved
- archived rows contain enough context to replay and grade

### PASS
- major NBA suggestion surfaces are archived and replayable

### WATCH
- archive exists, but one meaningful surface is still incomplete or lightly captured

### FAIL
- any important NBA suggestion surface is still display-only

---

## 7. Calibration Maturity

### Question
- Do we have enough resolved NBA suggestion volume to trust model tuning?

### Thresholds
- under `50` resolved rows = `NOT YET MEANINGFUL`
- `50+` resolved rows = first usable signal
- `100+` resolved rows = much stronger confidence

### PASS
- `50+` resolved NBA rows
- calibration report identifies real strong/weak buckets
- at least one formula change has been made from real calibration evidence

### WATCH
- calibration loop is operational, but resolved row count is still under `50`

### FAIL
- no grading loop
- or no calibration report

---

## 8. Repeatability

### Question
- Has NBA stayed clean over repeated cycles, not just one good run?

### PASS
- multiple refresh/QC cycles stay clean
- no resurfacing of recently fixed issue classes

### WATCH
- current cycle is clean, but recent fixes have not yet proven durable over time

### FAIL
- recently fixed issue classes are already resurfacing

---

## 9. Formula Learning

### Question
- Is the NBA model actually learning, or only logging?

### PASS
- calibration outputs have already informed:
  - confidence caps
  - boosted buckets
  - contradiction rules
  - downgraded weak buckets

### WATCH
- logging and reporting are in place, but resolved volume is not large enough yet to justify real tuning

### FAIL
- results are being captured but never used to inform the formula

---

## Current Practical Standard

To call NBA “99%”:

- refresh chain must be boringly reliable
- source truth must stay clean
- contradiction QC must stay at `0 failures`
- injury/return context must be visible and trustworthy
- all important suggestion surfaces must be archived
- calibration must be real, not theoretical
- visual trust must be strong enough that the board does not accidentally mislead

---

## What Usually Keeps NBA Below 99%

Historically, these are the last blockers:

- too little resolved calibration volume
- visual trust still needing one more pass
- return/injury edge cases
- repeated warnings not yet aged into rule changes
- a system that logs outcomes but has not yet learned from them

---

## Operator Summary

If you want the shortest possible read:

- `Infrastructure` gets NBA close
- `Repetition` proves it
- `Calibration` finishes it

That is the path from “strong” to “99%”.
