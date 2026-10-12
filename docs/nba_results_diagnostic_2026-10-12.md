# NBA Results Diagnostic — read-only (2026-10-12)

**Status: READ-ONLY DIAGNOSTIC. No model tuned. No threshold added. No edge claimed. No code
changed.** Companion to the NBA readiness work (`docs/nba_season_readiness_review_2026-10-11.md`,
`docs/nba_p0_remediation_spec.md`). Purpose: run the disciplined evidence loop's **analysis**
steps (freeze → join → evaluate → diagnose) on the NBA data we actually have, and state plainly
what that data can and cannot support. It does **not** motivate a live change; it separates
*descriptive findings* from the (currently empty) set of *evidence eligible to justify a governed
experiment*.

**The one rule this honors:** analyze all results to learn — but never use the same results both
to invent a tweak and to claim the tweak works. Nothing here is used to tune the model.

---

## 1. Data-trustworthiness audit (do we have point-in-time predictions + prices?)

Inspected: `data/tracking/NBA_AllPropResults.csv` (5,290 rows) and
`data/tracking/NBA_Simulation_Results.csv` (5,150 rows).

**What exists (good):** a genuine point-in-time capture harness. Every row is
`IsBackfill = False` (not reconstructed), with `SnapshotDate` / `SavedAt` / `SnapshotWrittenAt` /
`ModelVersion`, the resolved outcome (`OutcomeState`, `ResultValue`, `ResultDate`), and — in the
simulation file — a frozen predicted probability (`SimHitProbability`,
`CalibratedSimHitProbability`, 0–100 scale).

**What's missing or limited (the blockers to honest validation):**

| Limitation | Evidence | Consequence |
|---|---|---|
| **Wrong season / window** | All rows `Season = 2025-26`; `SnapshotDate` spans **2026-05-28 → 2026-07-18** (last season's **playoffs/offseason**). | Cannot speak to the upcoming **regular season**; playoff props price and behave differently. |
| **Core model-prob columns empty** | In `NBA_AllPropResults`: `ModelProb`, `SimProb`, `MarketProb`, `PlayVerdict`, `ClvPricePct` are **0% populated**. Only `Confidence` (legacy composite) is 100%. | The main archive cannot calibrate the *model's* probability; only the legacy Confidence score and the separate sim file carry a usable probability. |
| **CLV effectively unavailable** | `ClvPricePct` 0%; `OpenPrice` 31%, `ClosePrice` 17% populated. | Closing-line value cannot be computed reliably. |
| **Heavy voids** | `OutcomeState`: Void **3,243 (61%)**, Hit 1,063, Miss 972, Push 12 → **~2,035 graded** win/loss. | Modest graded sample; selection of what voided is itself unaudited. |
| **Prices partial** | `MarketPrice` 33% overall, but **86% of graded rows** (1,755/2,035). | ROI computable on graded+priced only. |

**Verdict.** We possess enough for **descriptive tendencies** on last-season playoff props. We
**cannot** honestly validate the current model or claim an edge, because the data is the wrong
season, the main model-probability and CLV fields are unpopulated, and the graded sample is
modest with 61% voids. **Honest validation is blocked on a live, current-season point-in-time
capture** that records model prob, market prob, price, and closing line with `IsBackfill=False`
— which depends on the readiness refresh chain (P0-4) running this season.

---

## 2. Descriptive findings (last-season playoffs, graded Hit/Miss) — NOT edges

All figures below are **in-sample, single-window (2025-26 playoffs), descriptive**. They are
candidate *observations*, not validated performance. Hit rate is the hit rate of the side the
board surfaced; ROI is at the captured `MarketPrice`.

**Overall (n = 2,035 graded; priced subset n = 1,755):**
- Hit rate **52.2%**; ROI **−4.6%** at the available price — i.e. roughly the vig, consistent
  with the platform's standing "edge ≈ the vig" result on 171k+ graded MLB/WNBA props.

**By direction (priced, n = 1,755) — the clearest signal:**
| Side | Hit | ROI | n |
|---|---|---|---|
| OVER | 43.9% | **−13.5%** | 900 |
| UNDER | 58.4% | **+4.7%** | 855 |

Strong OVER/UNDER asymmetry, directionally consistent with the enforced **prefer-UNDER** and
**LONGSHOT-OVER** guardrails. **Caveat:** playoff totals are a regime where overs are often
systematically mispriced high; this is exactly the kind of in-sample result the platform has
watched reverse out-of-sample. Treat as a hypothesis, not an edge.

**By the legacy `Confidence` composite:**
| Confidence band | Hit | ROI | n |
|---|---|---|---|
| ≤60 | 47.2% | −4.7% | 1,343 |
| 60–70 | 59.7% | −5.6% | 330 |
| 70–80 | 70.2% | −0.3% | 57 |
| 80–90 | 83.3% | +3.3% | 12 |
| 90–100 | 100.0% | +8.2% | 13 |

Confidence **rank-orders hit rate monotonically** (a real descriptive property). But positive ROI
appears only in the top three bands, whose combined n ≈ 82 — far too thin to trust, and the kind
of small-sample "it works at the top" pattern that has reversed before. Not evidence of an edge.

**Sim-probability calibration (`CalibratedSimHitProbability`, graded, n = 1,898):**
| Predicted | Actual hit | n |
|---|---|---|
| 0–40% | 45.5% | 178 |
| 40–50% | 48.3% | 572 |
| 50–55% | 51.5% | 297 |
| 55–60% | 57.0% | 330 |
| 60–70% | 56.3% | 430 |
| **70–100%** | **44.0%** | 91 |

Well-calibrated through the middle (45–60%); **over-confident at the top (predicts ≥70%, hits
44%)**, and mean predicted 53.6% vs actual 51.6% (~2 pts hot overall). This **confirms the known,
still-open top-of-range overconfidence** documented in the platform's model-calibration work — now
seen in NBA sim probs on playoff data.

---

## 3. Strengths / weaknesses (of the measurement system, not the picks)

**Strengths**
- A real point-in-time capture harness exists with a rich schema (snapshot timestamps,
  `IsBackfill`, `ModelVersion`, outcomes), plus a separate sim file with a frozen, calibrated
  probability. The *plumbing* for an honest evidence loop is largely in place.
- Outcomes are joined to snapshots; prices are present for most graded rows.

**Weaknesses / gaps (what to fix before validation is possible)**
- The main archive's `ModelProb` / `MarketProb` / `PlayVerdict` / `ClvPricePct` are unpopulated —
  the model's own probability and CLV are not being stored where the results join expects them.
- No current-season (regular-season) capture yet; only last-season playoffs.
- 61% of rows void; the void-selection rule is unaudited (potential selection/exclusion bias).
- High-`Confidence` / high-sim-prob samples are tiny — any "it works at the top" read is
  premature.

---

## 4. Candidate hypotheses (evidence-eligible for a GOVERNED experiment — later, not now)

These are **logged, not acted on.** None may change the live model until preregistered and tested
once on untouched current-season point-in-time data (per the loop's steps 6–8).

1. **Directional asymmetry (prefer UNDER / fade OVER).** Preregister a test on current-season
   captured props at real prices; confirm or kill against the already-enforced guardrails.
2. **Top-of-range overconfidence in the sim probability.** Preregister a recalibration test:
   does shrinking ≥70% predictions improve calibration out-of-sample without harming the middle?
3. **Confidence monotonicity vs ROI.** Whether Confidence's hit-rate ordering ever survives as
   *ROI* at the price (so far it does not, except on ~82 rows).

Each requires: a frozen training window, a single untouched holdout, then shadow mode — and
promotion only if the frozen criteria improve without damaging other segments.

---

## 5. Descriptive vs evidence-eligible — the explicit line

- **Descriptive (§2):** everything measured here. In-sample, one window (last-season playoffs),
  Confidence/sim-prob (not the empty ModelProb), modest n, 61% void. Useful for learning *where to
  look*; **not** proof of anything.
- **Evidence-eligible to motivate a governed experiment (§4):** the three hypotheses, each to be
  **preregistered** and tested on **current-season point-in-time** data that does not yet exist.
- **Eligible to change the live model today:** **nothing.** No tune, no new threshold, no edge
  claim follows from this diagnostic.

---

## 6. The one prerequisite that unblocks everything

Honest NBA model validation is impossible until a **live current-season point-in-time capture**
runs and records, per prop, at decision time: model probability, market probability, the price,
and the closing line (so CLV computes), with `IsBackfill=False`. That capture rides on the P0-4
refresh chain. **Recommended sequence:** finish NBA P0 readiness → ensure the capture populates
the model-prob + price + close fields this regular season → let it accrue → *then* run this
diagnostic on real current-season data and, only then, consider a preregistered experiment.

*End of read-only diagnostic. No model, threshold, ranking, or claim was changed or made.*
