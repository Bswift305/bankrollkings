# Model Registry Inventory and Roadmap

**Date:** 2026-10-18  
**Status:** read-only authority inventory; no mechanism is promoted by this document.

This inventory answers one question: **what currently influences visibility, membership, ordering,
scores, or betting-language authority, and has it earned that job?** It applies the contract in
`docs/model_registry_spec.md`: facts may create visibility; only a Qualified Sport × Market × Angle
entry with historical, holdout, and prospective validation may affect ordering or selection.

## 1. Classification

- **Factual rule:** deterministic display/membership from observed facts. Not a predictive model.
- **Generic shortcut:** shared score/adjustment used across materially different markets.
- **Disconnected context:** useful evidence displayed or computed without decision authority.
- **Candidate model:** angle-specific mechanism worth validating independently.
- **Contained/failed:** preserved for research but barred from live authority.
- **Missing:** an important angle has no governed mechanism.

`Authority today` describes actual code behavior, not what the label claims.

## 2. Cross-sport mechanisms

| Mechanism | Evidence | Classification | Authority today | Registry ruling |
|---|---|---|---|---|
| Live calibration adjustments | `app.py:12334` mutates `method_score` and sometimes `market_confidence` by up to ±8 using matching historical buckets | Generic shortcut | **Changes live scores** in NBA/WNBA/MLB paths | **Not Qualified. Priority containment:** stop score mutation; retain the bucket result as labeled context until each sport × market entry validates it. |
| Promotion signals | `app.py:26636` maps PROMOTE/HOLD labels to +4.5/+2.5/+1/−8 and mutates several score fields; called by NFL/WNBA/MLB boards | Generic shortcut | **Changes live scores and ordering** across unrelated markets | **Not Qualified. Priority containment:** expose the historical profile beside the row, but no score mutation or promotion ordering. |
| Market-implied probability / lean gap | football board `app.py:9464`; NBA/WNBA/MLB board builders | Factual market transformation | Visibility and often base ordering | Allowed only when labeled as market price/lean, never BK probability, confidence, or edge. |
| `play_verdict` guardrails | sport registry plus per-board deterministic checks | Factual/rules engine | Can remove or demote rows | Keep only where every rule is documented, source-cleared, and described as a rule—not a validated model. Audit independently by sport. |

The first two rows are the largest remaining governance mismatch: they apply historical shortcuts to
live scores without a Qualified registry entry. They should be contained before adding more models.

## 3. NFL

| Market / mechanism | Evidence | Classification | Authority today | Status / next action |
|---|---|---|---|---|
| Player-prop market lean + `method_score` | `build_football_live_prop_board`, `app.py:9464`; market lean, book count, line range, environment, NGS deltas combine into a 50–99 score and sorting | Generic shortcut | Orders the football prop board | Under Review at best; split into market facts and independent market-specific entries. No cross-market score should survive as authority. |
| Longshot-Over guardrail | same builder; explicit sub-25% implied Over demotion with graded-record rationale | Candidate guardrail | Demotes longshot Overs | Keep as a separately governed loss-avoidance rule only after its sample, price assumptions, holdout and prospective record are registered. Not a universal prop model. |
| Green Light configured-lens count | `build_green_light`, `app.py:31266`; Opportunity, Matchup, Game Identity, Coaching, Concentration | Context assembly | Orders by factual configured-lens count; code says lenses Under Review | Keep visible as labeled convergence/context; never translate count into confidence or “best.” Each lens needs its own entry and validation before authority. |
| Floor Board historical threshold | `build_nfl_floor_board`, `app.py:30237`; recent outcomes vs current line with minimum sample/hit threshold | Factual historical rule | Membership in Floor Board | Keep if labeled historical hit record and exact window/n; it is not a forecast. Price and line remain separate. |
| Opportunity/usage board | `build_nfl_usage_board`, `app.py:30880` | Factual role context | Visibility/order by observed workload | Keep as context; no claim that opportunity guarantees a cover. |
| Defense vs Channel | `build_nfl_dvp`, `app.py:31070` | Disconnected context / candidate input | Context only | Preserve. Map outputs to the relevant angle entry; never use generic RB run defense for QB rushing. |
| QB rushing × opponent QB allowance | `services/model_registry.py`, `nfl_qb_rushing_yards` | Candidate model | Research display only | **Discovery.** Build the canonical validation dataset; no boost until holdout + prospective pass. |
| PropScore v1 | containment comments near `app.py:33359`, `45719`, `47460` | Contained/failed | Removed from live ordering/sections | Keep quarantined for research only. Never revive without a new version and full validation. |
| Wind-under evidence | weather/context paths and governance reviews | Candidate angle | Context/guardrail varies by surface | Inventory source licensing, freeze eligible market/weather thresholds, reproduce historical result, then prospective-track as its own entry. |

## 4. CFB

| Mechanism | Classification | Authority today | Status / next action |
|---|---|---|---|
| Active ATS Wave | Factual rule | Membership = current consecutive graded covers ≥3; objective streak sort | **Keep.** It is not a model. Every qualifier remains visible; model overlays may not suppress membership. |
| Season ATS / one-loss labels | Factual descriptive cohorts | Context | Keep with n, record and assumed-price disclosure where return is shown. |
| Matchup signal context | Disconnected context / candidate inputs | Explanatory overlay | Split into angle entries (spread, total, pace/explosiveness, coaching) before any scoring authority. |
| Generic CFB “edge/best” hierarchy | Generic shortcut / legacy language | Some legacy surfaces imply authority | Continue neutral-language remediation; no CFB mechanism is documented Qualified. |

## 5. NBA / WNBA

| Mechanism | Classification | Authority today | Status / next action |
|---|---|---|---|
| NBA.com-derived game-log/tracking/boost context | Data-gated | Suppressed while `BK_NBA_STATS_ENABLED=0` | Remains unavailable until lineage/licensing clears; no registry work can bypass the legal gate. |
| De-vigged market price / lean gap | Factual market transformation | Display/context; residual copy remediated on NBA | Keep with market labels only. Do not call confidence, edge, fair BK price, or prediction. |
| Simulation/model estimates | Legacy model output | NBA residual remediation labels it Legacy and removes selection authority | Keep only in the Legacy disclosure until a new governed entry validates. |
| WNBA `method_score` + calibration/promotion | Generic shortcut | Alters score/order | Contain score mutation. Rebuild per market after cleared data and validation exist. |
| NBA assists, rebounds, usage/injury angles | Missing/data-gated candidates | None | Design only after cleared inputs exist; each market gets its own entry. |

## 6. MLB

| Mechanism | Classification | Authority today | Status / next action |
|---|---|---|---|
| Market confidence + Statcast delta | Generic shortcut / candidate inputs | Produces and orders a 50–99 score | Split market fact from batter/pitcher/park/weather angle models. No universal MLB prop score. |
| Method-board score thresholds | Generic shortcut | Filters rows (for example `method_score >= 64`) | Not Qualified; containment required before calling the result a best-play set. |
| Ballpark/weather/handedness context | Disconnected context / candidate inputs | Context and sometimes score adjustment | Preserve facts with licensed lineage; validate separately by prop market. |
| Promotion/calibration adjustments | Generic shortcut | Mutates live score/order | Same cross-sport containment priority as §2. |

## 7. Missing high-value entries

Priority is based on usable licensed evidence, user value, and whether the angle is distinct from a
price the market already supplies.

1. **NFL QB rushing yards** — current first entry. Build the validation dataset: QB identity/archetype,
   designed runs/scrambles/attempts, opponent QB-rushing allowance, real captured line/price, result,
   timestamp and push. Historical → time-based holdout → prospective.
2. **NFL WR receiving yards / receptions** — target role × coverage/channel allowance × game script;
   separately validate yards and receptions.
3. **NFL RB rushing yards / attempts** — workload × opponent RB-rushing allowance × script; explicitly
   separate from QB rushing.
4. **NFL passing yards / attempts** — dropback role × opponent passing channel × pressure/weather;
   missing/stale weather or pressure must cause abstention.
5. **CFB spread continuation** — factual active wave × current price movement × team/coaching context;
   wave membership remains independent and complete.
6. **MLB batter total bases / hits / home runs** — three separate entries; pitcher handedness,
   park/weather and lineup slot are inputs, not one shared score.
7. **NBA/WNBA assists / rebounds / points** — remain blocked by the data-rights gate until an authorized
   source can support prospective validation.

## 8. Execution order

1. **Contain unauthorized authority — implemented 2026-10-18:** cross-sport calibration and promotion
   retain their observed labels/gaps as `RESEARCH_ONLY` context, while their live score delta and sort
   boost are forced to zero. `qc_unqualified_authority_containment.py` proves scores and ordering keys
   remain unchanged. The underlying research record is preserved for later angle-specific validation.
2. **Complete the NFL QB-rushing observation table — storage foundation implemented:**
   `services/model_observations.py` freezes a pre-event decision snapshot with exact line, price,
   sportsbook, event/entity identity, model version/status, inputs, output and dataset lineage; grading
   later adds HIT/MISS/PUSH/VOID/DNP/UNGRADED without rewriting the snapshot. The default store is
   outside the checkout and no ingestion schedule or UI is enabled. The remaining work is the
   source adapter for the angle-specific inputs.
3. **Run historical and time-based holdout evaluation:** publish sample, calibration and return at real
   captured prices; failure remains a valid result.
4. **Prospective shadow mode:** predictions/alignments written before games, invisible to customers,
   then graded automatically.
5. **Governance review:** only a passing record can move Discovery → Under Review → Qualified.
6. **Repeat per market:** never copy weights or status across sport/market/angle boundaries.

## 9. Immediate acceptance rules

- No Discovery/Under Review/Failed/Retired entry changes a score, order, membership or recommendation.
- Market prices remain facts and are not relabeled as model probabilities.
- Factual cohort membership never depends on a model overlay.
- Every displayed research item states status, version, inputs, freshness, output and abstention.
- Every model observation is captured before the event and carries the real line and price.
- Restricted/unknown lineage causes abstention, not a fallback dataset.

