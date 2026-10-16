# Active ATS Wave — Admission Contract (CFB + NFL), FROZEN

**Status: FROZEN RULE (design). Membership is factual, not a model.** Amends the CFB/NFL ATS Wave
contract and the forthcoming Model Registry (`docs/model_registry_spec.md`). Captures the real
"ride the wave" principle: **the system detects when the wave starts, regardless of what happened
earlier in the season.** Date: 2026-10-16.

## The rule — Active ATS Wave
Wave Watch membership is driven by a team's **current consecutive graded ATS-cover streak**, **not** an
undefeated season start and **not** overall cover percentage. A team **qualifies** when:

- Its latest **three or more graded ATS decisions are consecutive covers**.
- **Earlier losses do not disqualify it** (a 3–3 team on a 3-cover run qualifies).
- A **bye does not interrupt** the streak.
- A game with **no closing line or no grade is ignored** (does not interrupt, does not count).
- A **push does not count as a cover**: it **pauses** the sequence rather than being presented as part
  of "three consecutive covers," and the page **shows the push separately**.
- The streak **ends when the team records an ATS loss**.

### Truth table (frozen)
| Season ATS record | Recent ATS results (old→new) | Qualifies? | Reason |
|---|---|---:|---|
| 3–3 | L, L, L, W, W, W | **Yes** | active 3-cover streak |
| 5–1 | W, W, L, W, W, W | **Yes** | active 3-cover streak |
| 5–0 | W, W, W, W, W | **Yes** | active 5-cover streak |
| 4–2 | W, W, W, L, W, W | **No** | current streak is 2 |
| 3–2–1 | W, W, P, W | **No** | not three uninterrupted covers (push pauses) |

## Factual labels — kept separate (a team may carry several)
- **Active Cover Streak** — consecutive recent ATS covers. **This is the principal Wave Watch admission
  rule.**
- **Season ATS Record** — total season performance (**context only**).
- **Strong Season Record** — ≤ 1 ATS loss with ≥ 3 decisions.
- **Perfect Start** — no ATS losses.

These are **independent** factual labels; the board shows them side by side. Only **Active Cover Streak
≥ 3** governs admission.

## Membership vs model (the firewall)
- **Membership is factual** — every team with an active streak of ≥ 3 covers is **included**. A model
  may **never suppress** a qualifying team.
- **Within the factual Wave board, objective sorting by current streak length is permitted** and must
  be **labeled as such** (e.g., "sorted by active cover streak").
- **Model reads appear beside every row as an overlay** (the neutral tier labels already shipped in the
  Gate-1 wave work) and **never control membership or ordering** beyond the factual streak sort.

## Data requirements
- A **chronological, per-game graded ATS sequence** per team (the `cfb_ats_streaks` /
  `NCAAF_GameLineResults.csv` lineage already computes active streaks this way), **not** the aggregate
  `cover%`/`ats`/`n` currently used by `build_cfb_wave_context` admission.
- Each decision carries: graded result (**cover / loss / push**), whether it had a **closing line +
  grade** (else ignored), and order. Byes are absent rows (ignored, not interrupting).
- Same lineage for NFL (the "Riding the Wave" ATS surface).

## Required fixtures (tests)
Add fixtures proving admission + streak computation on:
1. **Midseason 3–3 team on a three-cover run** → qualifies (streak = 3).
2. **A bye** in the recent window → does not interrupt the streak.
3. **A push** inside the run → pauses the sequence (not counted as a cover), shown separately; a
   `W,W,P,W` tail does **not** qualify.
4. **An ungraded / no-closing-line game** → ignored (neither interrupts nor counts).
5. **An ATS loss** → resets the streak (a team that just lost does not qualify; `4–2` with `…L,W,W`
   has streak 2 → no).
Plus the five truth-table rows as direct cases.

## Current state & implementation note (not yet implemented)
`build_cfb_wave_context` (app.py) currently admits on `cover% ≥ 60` + `n ≥ 3` (aggregate) — this
**contradicts** the frozen rule (it would include a high-cover%% team with no active streak and could
exclude a 3–3 team actively riding a 3-cover run). **Implementation** (to be approved separately):
replace the admission metric with the active-cover-streak computation above (wiring the per-game graded
ATS sequence, as `cfb_ats_streaks` does), keep the model tier labels as an overlay, add the fixtures,
and apply the same rule to the NFL ATS wave surface. No membership/selection code is changed by this
contract.
