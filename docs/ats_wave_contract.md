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

## Current state & implementation note
**CFB and NFL are both implemented** to the frozen rule above, in separate reversible commits.

**NFL (`build_nfl_ats_wave` / `build_nfl_wave_context`, riding_the_wave.html):** the ATS wave reads the
current-season source `nflverse_games.parquet` (characterized in
`docs/nfl_ats_wave_source_characterization.md`), **not** a copy of CFB's mechanics. NFL uses a stable
`game_id` identity, two reciprocal team-side decisions per completed game, the nflverse **recorded
spread** (`spread_line > 0` ⇒ home favored ⇒ home ATS margin `= result − spread_line`), an **explicit
active-season gate** (`_nfl_expected_completed_week`, never `max(season)`), **event-level completeness**
(a completed Thursday game counts immediately; a scheduled game past an 8h settlement grace with no
usable result is overdue → fail closed; future/within-grace games ignored), duplicate collapse vs
conflict fail-closed, and a **48h source freshness budget**. SU and O/U on the same page are **failed
closed** (they previously read the 2011–2025 history and showed prior-season runs as active); they
return only once re-sourced and separately verified. Enforced by `qc_nfl_ats_wave.py`. **Open operator
task:** no prod job currently refreshes `nflverse_games.parquet` (verified: absent from `ops/`,
`deploy/`, `run_daily`) — until one is wired and verified, the NFL ATS wave correctly fails closed on
the freshness budget rather than showing a stale board.

**CFB (`build_cfb_wave_context`):** the prior aggregate admission (`cover% ≥ 60` + `n ≥ 3`) is gone;
membership now iterates the authoritative per-game streak index. Three integrity corrections are part
of the implementation and are enforced by `qc_cfb_ats_wave_admission.py`:

1. **Membership iterates the authoritative streak index**, never the season aggregate — the aggregate
   can never suppress a qualifying team; the displayed season record is derived from the per-game
   sequence.
2. **Canonical team-GAME identity** = `(season, resolved team, resolved opponent, GameDate/kickoff;
   stable event ID when available)`. **Week is an attribute, not an identifier** — using `(week, team)`
   wrongly collapsed two legitimate games a team plays under one numbered week (e.g. a Week-1 label
   spanning two Saturdays). Chronology is by actual `GameDate`. Duplicate handling: an **exact repeat**
   of the same canonical game + result is **collapsed once** (`duplicates_collapsed`); the **same
   canonical game with a conflicting result/line** is a **conflict** that **fails sync closed**; a
   **different opponent or kickoff** is a **separate legitimate game, never a duplicate**.
3. **Synchronization = completeness + manifest lineage**, not `max(Week)`. The expected-game manifest
   (`cfb_line_moves.json`) must **declare the requested season** and carry a games list, or the source
   **fails closed** (`manifest season/lineage invalid`); its `updated` timestamp is reported. Expected
   and graded identities are matched at `(week, resolved team, resolved opponent)` grain. The board is
   synchronized only when every expected completed-game FBS decision is graded and there are no
   conflicts; otherwise it shows an honest "not synchronized" state and **never** falls back to season
   cover %.

**Real-data status (2026-10-16, local):** at the corrected canonical grain the graded source has **0
exact duplicates and 0 conflicting identities** — the previously reported "54 duplicate conflicts" was
an artifact of the `(week, team)` collapse and is **withdrawn**. The local source is graded through
**Week 2** while the slate is at **Week 7**, so the board correctly **fails closed** (640 of 782
expected FBS decisions through completed week 6 are ungraded). **Production freshness is pending
verification** — the production sync report must prove the graded source is current before any claim
that it is kept current.
