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

---

## Interpretation (authorized; held to the frozen scope)

**What the result means (within §8 scope — Team Form v1, H=3 only).** Reweighting the SRS
toward recent games at a 3-week half-life does not merely fail to help — on the 850 games
where it *overturned* the cumulative rating's side, following it was **anti-predictive**
(48.1% vs the 51.9% the benchmark would have had). So the recency tilt is not neutral noise;
at this specification it actively discards useful signal. The margin-error ranking says the
same thing in a second, independent way: spread (12.18) < cumulative SRS (13.31) < Team Form
(13.52).

**A mechanistic reading (hypothesis, not proven by this test).** A 3-week half-life throws
away most of a ~12-game season — by week 10 more than half the season's evidence is
down-weighted toward zero. What remains is dominated by *small-sample recent margins and
the luck in them*, which cumulative opponent-adjustment already handles better. In other
words, at H=3 "recent form" is mostly measuring variance, not a real change in team quality.
This is the same lesson Audit #1 and the NFL record keep returning: the obvious signal is
already in the price (and even in plain cumulative strength), and chasing recency adds
variance without edge.

**What it does NOT mean (§8).** This is not a verdict on recency in general. Untested and
genuinely separate: a *longer* half-life; a "form **delta**" used as a *flag* (recent minus
cumulative) rather than as a replacement rating; or *cause-specific* form (a QB change, a
coaching change) rather than blind reweighting. Each is its own candidate with its own
pre-registration. But the burden is now higher — Team Form v1 failed, and a bare
half-life sweep is exactly the window-shopping the freeze process forbids.

**Implication for the queue.** Recency-as-reweighting is disfavored as a direction; the
higher-value Audit #3 is a **different mechanism**, not a Team Form variant. Candidates (for
Director selection — not selected or frozen here):
1. **Coaching Continuity** — the next in the frozen queue and a genuinely distinct mechanism
   (coordinator/scheme/regime change creating or destroying team identity). *Gated:* it needs
   a **feasibility/reconstructability check first** — can regime/coordinator history be
   rebuilt point-in-time from `build_cfb_coaches.py` + the coaches data? — exactly as the
   evidence-base audit preceded the mechanism audits.
2. **Situational (rest / travel / short week)** — testable on the same game-line base, no new
   data.
3. **Line value (open→close move)** — data-gated (open spread exists for only ~52% of games).

The benchmark every one of these must beat on the same paired population remains **Audit #1
cumulative SRS**.

See `docs/cfb_mechanism_audit_02_preregistration.md` (the frozen test),
`docs/cfb_mechanism_audit_01_opponent_adjusted_strength.md` (the benchmark), and
`research/cfb_mechanism/audit2_frozen_population.json`.
