# CFB Mechanism Audit #2 — RESULT (Team Form v1, H=3)

**Executed under the frozen pre-registration** (`docs/cfb_mechanism_audit_02_preregistration.md`),
`research/cfb_mechanism/audit_team_form_w1.py`, 2026-10-09. The fingerprint guard **passed**
(`n = 4,653`, `sha256 ffb7c73f…`), so the population is the frozen, paired universe and no
choice was altered at run time. This document reports the **result only**; interpretation
beyond the frozen boundaries is a separate, not-yet-authorized gate.

**Scope (frozen §8):** this result pertains **only** to Team Form v1 — opponent-adjusted
exponentially-weighted SRS, `H = 3`. It says nothing about momentum, recency generally,
"team form" generally, other half-lives, or other weighting schemes.

## Numbers

**Margin prediction error (paired, n = 4,653):**

| Predictor | MAE | RMSE |
|---|---|---|
| Market spread | **12.18** | **15.33** |
| A — cumulative SRS (Audit #1) | 13.31 | 16.78 |
| B — Team Form v1 (H=3) | 13.52 | 17.06 |

B does **not** reduce MAE vs A (13.52 > 13.31). Both trail the spread.

**ATS cover (context):** A = 51.8% [50.4, 53.3]; B = 51.1% [49.7, 52.6].

**Decisive paired test — disagreement subset** (games where Team Form flipped A's side),
n = 850:

- **B cover on the flips = 48.1% [44.8, 51.5]** — when recency overturns cumulative
  strength, the flip is wrong more often than right (A would have been 51.9% on those games).
- Per season (all ≥ 30, so all count): 2021 48.6% · 2022 49.7% · 2023 45.2% · 2024 49.8% ·
  2025 47.0%. **0 of 5 seasons** clear 50%.

## Frozen composite rule (Option A) — mechanical outcome

| Criterion | Result |
|---|---|
| Disagreement n ≥ 200 | ✅ (n = 850) — **not** underpowered |
| Informational: Wilson LB > 50% | ❌ (LB = 44.8) |
| Informational: ≥ 3/5 seasons > 50% | ❌ (0/5) |
| Informational: leave-one-season-out > 50% | ❌ (drop 2024 → 47.6%) |
| Betting-edge (52.4%) criteria | ❌ (all fail) |
| Margin MAE improved vs A | ❌ |

## Verdict (frozen decision rule)

> **No demonstrated incremental edge.** Team Form v1 (H=3) did not reduce margin error vs the
> cumulative SRS, did not beat 50% on the games where it disagreed with the benchmark, and
> cleared no season. **Audit #1 cumulative SRS remains the benchmark.** No build is authorized
> under any outcome.

This is a well-powered negative (n = 850 disagreements), not an "insufficient data" result —
so the frozen reading is "tested and not additive for this specification," not "inconclusive."
Per §8 that conclusion binds to Team Form v1 (H=3) only.

See `docs/cfb_mechanism_audit_02_preregistration.md` (the frozen test),
`docs/cfb_mechanism_audit_01_opponent_adjusted_strength.md` (the benchmark), and
`research/cfb_mechanism/audit2_frozen_population.json`.
