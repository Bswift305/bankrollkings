# NBA Results Diagnostic — read-only, RETROSPECTIVE (rev 2 · 2026-10-12)

**Status: READ-ONLY DIAGNOSTIC. No model tuned. No threshold added. No edge claimed. No code
changed.** Companion to the NBA readiness work (`docs/nba_season_readiness_review_2026-10-11.md`,
`docs/nba_p0_remediation_spec.md`).

> **Rev-2 correction (important):** the prior draft called this archive "genuine point-in-time."
> That claim is **retracted.** A timestamp audit (§1) shows the archive was **batch-written in a
> single pass on 2026-08-15**, after the games it describes. Pre-event timing **cannot be
> established** for any row. Per the evidence-loop rule, these results are therefore labeled
> **RETROSPECTIVE / DESCRIPTIVE** and must **not** be characterized as point-in-time model
> performance. All tables below are recomputed at **one observation per unique market** (§2).

**The one rule this honors:** analyze all results to learn — but never use the same results both to
invent a tweak and to claim the tweak works, and never dress retrospective data as prospective.

---

## 1. Timestamp-integrity audit — why this is NOT point-in-time

Inspected: `data/tracking/NBA_AllPropResults.csv` (5,290 rows) and
`data/tracking/NBA_Simulation_Results.csv` (5,150 rows).

| Check | Finding | Implication |
|---|---|---|
| **Write time** | `SnapshotWrittenAt` is the **same value for all 5,290 rows: `2026-08-15 07:01:34`** | The entire archive was persisted in one batch on Aug 15 — **after** the season it covers. `IsBackfill=False` is therefore **not trustworthy** as a point-in-time guarantee. |
| **Snapshot vs result dates** | `SnapshotDate` spans **2026-05-28 → 07-18**; `ResultDate` spans **05-28 → 06-13** (playoffs ended mid-June). Snapshots run a **month past** the last result. | Many "snapshots" are dated after every game resolved. |
| **Saved after result** | **1,297** graded raw rows have `SavedAt` **after** `ResultDate`. At the unique-market grain (§2), **735 of 1,231** markets' earliest `SavedAt` is after the result, and **411** have their earliest `SnapshotDate` on/after the result. | A large share of the "predictions" were recorded after the outcome was known. |
| **Pre-event provability** | Only **820** unique markets even carry a `SnapshotDate` *earlier* than their `ResultDate`, and because of the uniform Aug-15 write, **none** can be *demonstrated* to have existed before the game. | **No documented decision-time cutoff exists**, so no row qualifies as demonstrably pre-event. |

**Verdict:** this is a **retrospective** dataset (last-season **playoffs**, 2025-26), useful for
**descriptive** study only. It cannot validate model performance, CLV, or an edge. Honest
validation requires a **live, current-season capture with a provable decision-time write** (a real
`SnapshotWrittenAt` at decision time, per prop), which does not yet exist — it rides on the P0-4
refresh chain.

---

## 2. Duplicate-snapshot audit + the frozen grain

The archive stores **repeated snapshots of the same market**, so raw row counts overstate the
evidence:

- **5,290 raw rows → 1,372 unique markets** (key: `Player · Stat · Direction · Line · ResultDate`).
- Graded (`OutcomeState ∈ {Hit, Miss}`): **2,047 raw rows → 1,231 unique markets.**

**Frozen grain for all tables below:** **one observation per unique market**, taken as the
**earliest `SnapshotDate`** for that market (ties broken by earliest `SavedAt`). This is the best
available single observation; it is **still retrospective** (§1), not a demonstrably pre-event
pick. No documented decision-time cutoff exists to prefer a different snapshot.

---

## 3. Retrospective descriptive findings (unique markets, last-season playoffs) — NOT edges

In-sample, single window (2025-26 playoffs), **retrospective**, Confidence/sim-prob (the main
archive's `ModelProb`/`MarketProb`/`PlayVerdict`/`ClvPricePct` are **0% populated**; CLV is
unavailable). ROI is at the captured `MarketPrice`.

**Overall (unique graded n = 1,231; priced n = 1,071):**
- Hit **51.7%**; ROI **−4.6%** at the available price — roughly the vig, consistent with the
  platform's "edge ≈ the vig" result on 171k+ graded MLB/WNBA props.

**By direction (unique priced, n = 1,071):**
| Side | Hit | ROI | n |
|---|---|---|---|
| OVER | 43.9% | **−12.9%** | 540 |
| UNDER | 57.6% | **+3.9%** | 531 |

(Unique graded, hit only: OVER 47.3% n=672 · UNDER 57.1% n=559.) A persistent OVER/UNDER asymmetry,
directionally consistent with the enforced prefer-UNDER / LONGSHOT-OVER guardrails. **Caveat:**
playoff totals are a regime where overs are often priced high; this is the kind of in-sample result
the platform has watched reverse out of sample. Hypothesis, not an edge.

**By the legacy `Confidence` composite (unique priced):**
| Confidence band | Hit | ROI | n |
|---|---|---|---|
| ≤60 | 47.6% | −4.1% | 841 |
| 60–70 | 57.4% | −9.4% | 188 |
| 70–80 | 77.8% | +8.8% | 27 |
| 80–90 | 87.5% | +5.2% | 8 |
| 90–100 | 100.0% | +8.2% | 7 |

Confidence rank-orders **hit rate** descriptively, but positive ROI appears only in the top three
bands, combined **n = 42** — far too thin to trust and the classic "it works at the top" pattern
that has reversed before. Not evidence of an edge.

**Sim-probability calibration (`CalibratedSimHitProbability`, unique markets, n = 1,139):**
| Predicted | Actual hit | n |
|---|---|---|
| 0–40% | 45.6% | 114 |
| 40–50% | 49.4% | 326 |
| 50–55% | 52.3% | 174 |
| 55–60% | 54.6% | 194 |
| 60–70% | 53.8% | 260 |
| **70–100%** | **46.5%** | 71 |

Well-calibrated through the middle (40–60%); **over-confident at the top (predicts ≥70%, hits
46.5%)**; mean predicted 54.0% vs actual 51.2% (~3 pts hot). This **matches the known, still-open
top-of-range overconfidence** documented in the platform's model-calibration work — now seen,
retrospectively, in NBA sim probs on playoff data.

---

## 4. Strengths / weaknesses (of the measurement system)

**Strengths**
- A capture *schema* exists (snapshot/result/`ModelVersion` fields, a sim probability, outcomes
  joined). The columns needed for a real evidence loop are defined.

**Weaknesses / gaps (fix before validation is possible)**
- **No provable decision-time write** — everything is a single Aug-15 batch, so nothing is
  demonstrably pre-event. This is the headline gap.
- The main archive's `ModelProb` / `MarketProb` / `PlayVerdict` / `ClvPricePct` are unpopulated;
  CLV cannot be computed.
- Duplicate snapshots inflate counts (5,290 rows → 1,231 graded markets).
- Only last-season **playoffs**; 61% of raw rows void; high-Confidence / high-sim-prob samples are
  tiny (n = 42 / n = 71).

---

## 5. Candidate hypotheses (evidence-eligible for a GOVERNED experiment — later, not now)

Logged, **not acted on.** None may change the live model until preregistered and tested once on
untouched, **provably decision-time** current-season data (loop steps 6–8).

1. **Directional asymmetry (prefer UNDER / fade OVER)** — preregister a test on captured
   current-season props at real prices; confirm or kill against the existing guardrails.
2. **Top-of-range overconfidence in the sim probability** — preregister a recalibration test:
   does shrinking ≥70% predictions improve calibration out of sample without harming the middle?
3. **Confidence monotonicity vs ROI** — whether Confidence's hit-rate ordering ever survives as
   *ROI* at the price (so far it does not, except on ~42 rows).

Each requires a frozen training window, a single untouched holdout, then shadow mode — promotion
only if the frozen criteria improve without damaging other segments.

---

## 6. Descriptive vs evidence-eligible — the explicit line

- **Descriptive (§3):** everything measured here. **Retrospective**, one window (last-season
  playoffs), deduped to unique markets, Confidence/sim-prob (not the empty `ModelProb`), modest n.
  Useful for learning *where to look*; **not** proof of anything, and **not** point-in-time
  performance.
- **Evidence-eligible to motivate a governed experiment (§5):** the three hypotheses, each to be
  **preregistered** and tested on **current-season, provably decision-time** data that does not yet
  exist.
- **Eligible to change the live model today:** **nothing.**

---

## 7. The one prerequisite that unblocks everything

Honest NBA validation is impossible until a **live current-season capture** records, per prop, **at
decision time** (with a provable write timestamp): model probability, market probability, the
price, and the closing line (so CLV computes) — one row per market, not a post-hoc batch.
**Recommended sequence:** finish NBA P0 readiness → make the capture write a true decision-time
snapshot that populates the model-prob + price + close fields this regular season → let it accrue →
*then* re-run this diagnostic on real current-season data and, only then, consider a preregistered
experiment.

*End of read-only diagnostic (rev 2 — point-in-time claim retracted; retrospective, unique-market
grain). No model, threshold, ranking, or claim was changed or made.*
