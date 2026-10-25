# Research Candidate — `PLAYER_MILESTONE_USAGE`

**Status: RESEARCH CANDIDATE — hypothesis family, not a proven edge, not a recommendation.**
Design-only artifact. No production store, job, or UI. No betting guidance is issued here.
Consistent with the betting guardrails (CLAUDE.md §10): a factor only becomes an edge claim after
out-of-sample measurement, and "every predictive factor tested so far is already in the price."

---

## 1. What this family is

A labeled family of hypotheses that a **personal milestone or narrative event** attached to a specific
player on a specific date might cause **intentional extra involvement** (usage), beyond what the player's
role, matchup, game script, and team pass volume would otherwise predict.

We do **not** hard-code any one narrative (e.g. birthdays) as an assumed edge. Each narrative is a
separately labeled, separately testable sub-hypothesis inside the family:

| Sub-label | Trigger |
|---|---|
| `BIRTHDAY` | the game falls on the player's birthday |
| `REVENGE_GAME` | player faces a former team |
| `RECORD_CHASE` | player is within reach of a career/franchise/league record |
| `HOMECOMING` | game is in the player's home city / college market |
| `CONTRACT_INCENTIVE` | a known contract incentive is in live reach |

Adding a sub-label is a data-labeling decision, never a scoring change.

## 2. Primary endpoint (what we actually measure)

**Target-share lift**, within-player, matched. **Not** touchdowns, **not** whether a prop went over,
**not** whether a bet won. The question is narrow and causal:

> Did the player's **opportunity** increase beyond what their role, matchup, game script, and team pass
> volume would normally predict?

### Measured variables (per milestone game)
- Targets and **target share**
- Routes run and **targets per route run** (TPRR)
- First-half targets
- Third-down targets and red-zone targets
- **Actual usage vs. pregame expected usage** (the key comparison)
- Posted receptions / yards lines and prices **at observation time** (context, not the endpoint)
- Team pass volume, snap participation, competing-receiver availability

### Eventual league-wide test (not built; stated so the case data is collected the right way)
Within-player matched comparison of milestone games vs. that same player's non-milestone games,
controlling for **routes, snaps, quarterback, opponent, injuries, and team pass volume**. One game can
never prove a milestone effect; single cases are recorded only to accrue a matched sample honestly.

## 3. Why this is recorded as a receipt, not a pick

This is the worked example behind the Phase 2A decision-receipt pattern:

```
user observation → timestamped thesis → measurable variables → decision-time receipt
                 → expected vs. actual → research candidate
```

The value is the **pre-event timestamp**: the thesis and its invalidation conditions are frozen before
kickoff, so the after-the-fact grade cannot be rationalized. Missing variables are recorded as
**pending**, never zero-filled.

---

## 4. Case #1 — Pat Freiermuth, 2026-10-25 (`BIRTHDAY`)

### Decision-time receipt (frozen pre-kickoff)

| Field | Value |
|---|---|
| `observation_id` | `PMU-BIRTHDAY-FREIERMUTH-2026-10-25` |
| `sub_label` | `BIRTHDAY` |
| `observed_by` | user |
| `captured_at` (ET) | **2026-10-25 08:51 EDT** — before kickoff |
| `captured_at` (UTC) | `2026-10-25T12:51:21Z` |
| `subject` | Pat Freiermuth (TE, Pittsburgh Steelers) |
| `event` | Steelers vs. New Orleans Saints, Paris (international game) |
| `birthday` | October 25, 1998 (per user-supplied Steelers bio) |
| `quarterback_assumption` | Aaron Rodgers starts |

### Thesis (user)
Aaron Rodgers may involve Freiermuth more than his normal role **because it is Freiermuth's birthday.**

### Assumptions (must hold for the test to be valid)
- Freiermuth active
- Normal snap role
- Rodgers starts

### Invalidation conditions (frozen before kickoff)
- Reduced snaps
- Injury limitation
- Unexpected quarterback change
- Game script that eliminates pass volume

If any invalidation condition fires, the case is marked **INVALIDATED** and excluded from the matched
sample (it is not graded as a miss — the thesis was never fairly testable).

### Variables to capture at observation time (pending — not yet recorded)
- [ ] Posted receptions line + price @ observation time
- [ ] Posted receiving-yards line + price @ observation time
- [ ] Pregame **expected** usage (role/matchup/script/pass-volume baseline)

### Result block (to be filled after the game)
- [ ] Targets / target share — actual
- [ ] Routes run / TPRR — actual
- [ ] First-half targets — actual
- [ ] Third-down + red-zone targets — actual
- [ ] Team pass volume, snaps, competing-receiver availability — actual
- [ ] **Expected vs. actual usage** — the grade
- [ ] Case disposition: `CONFIRMED_LIFT` / `NO_LIFT` / `INVALIDATED`

### Honesty note
One game cannot prove a "birthday effect." This case is the **first recorded observation** in the family,
collected to seed a matched sample — not a recommendation and not evidence of an edge. The endpoint is
usage lift, not the prop result.

### Source (user-supplied)
- Steelers player bio (birthdate): https://www.steelers.com/team/players-roster/pat-freiermuth/
- Steelers 2026 schedule (today's game): https://www.steelers.com/news/steelers-release-2026-schedule
