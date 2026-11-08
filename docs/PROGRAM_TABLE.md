# Bankroll Kings — Authoritative Program Table (program reset 2026-11-07)

**Rules (owner, 2026-11-07).** One production release candidate at a time. No new implementation branch while a
candidate awaits a gate or receipt. Discovery/design only when it cannot change the active release. One state per
item: `DISCOVERY` · `DESIGN` · `BUILD` · `GATE` · `PRODUCTION ACCEPTANCE` · `CLOSED` (plus disposition `PAUSED` /
`SUPERSEDED`). Nothing is done without a production receipt. No opportunistic master pushes. No product-purpose
change under a legal/integrity/UX label. Owner workflow acceptance is mandatory alongside technical QC.
Paused branches are **not** deleted, merged, rebased or advanced.

**Production today:** `origin/master` = prod = **`b12eec3`** (owner-approved FF deploy 2026-11-07 14:51:31 UTC; previous `3d7cda1`). Capture/Research Candidate OFF.
**Active candidate:** `b12eec3` (row P1-1) — **PRODUCTION ACCEPTANCE**: awaiting the first ordinary `bk-linemove` (16:00 UTC 11-07) and `bk-daily` (13:00 UTC 11-08) receipts. Next candidate: P1-GL. Everything else waits.

## CONTROLLING PROGRAM ORDER — approved and frozen by owner 2026-11-07
This section governs. Rows below are the detailed ledger; where they differ, this section wins. Owner of every item
= Darrel Copper (owner); executor = CTP.

**Program invariant.** No implementation begins unless the item appears here with one owner, one stage, one ordered
position, explicit scope, explicit exclusions and acceptance criteria. A production incident may interrupt the order
only when recorded explicitly as an incident. No undocumented "while we are here" work. The roadmap is not reopened
unless production evidence reveals a genuine dependency.

| Pos | Item | Stage | Scope | Exclusions | Acceptance / exit |
|---|---|---|---|---|---|
| 1 ACTIVE | **`b12eec3` production acceptance** (P1-1) | PRODUCTION ACCEPTANCE (deployed 2026-11-07 14:51:31 UTC; `bk-linemove` 16:00 UTC observed — receipt part 1 `docs/b12eec3_production_receipt_20261107.md`) | Observe the normal 2026-11-08 13:00 UTC `bk-daily`; report separately: overall result; every failed/degraded step under frozen semantics; NBA lines + props publication, row/event counts, freshness, provider-credit attribution; CFBD quota result; missing-key and off-season outcomes; Run Status binding; site health, clean tree, Research Candidate OFF | No manual refresh, no other deploy; a defect found ⇒ remediate **only this release** | Receipt part 2 written; passes ⇒ CLOSED before any other implementation |
| 2 NEXT | **Green Light Release 1A — Repair** (P1-GL). Sole question: *can the owner safely use Classic Green Light the way it was originally used?* | DESIGN (authorized to BUILD only after pos 1 closes) | (1) exclude started events via governed kickoff eligibility; (2) one shared availability rule — OUT, IR, PUP, suspended, otherwise unavailable; (3) repair NFL injury join; (4) repair line-movement join, exclude completed/non-current events; (5) bind sportsbook, line, price, timestamps to the same offer; (6) display both **Book updated** and **Observed by BK**, never merged or substituted; (7) retain the currently deployed NFL-props eligibility clock (L3 separate); (8) **before implementation**, a read-only count of offers eligible under each clock; (9) suppress stale evidence; distinguish unavailable / missing / no-result honestly; (10) hide all unregistered model output from customer pages — models never select or order visible games; (11) every eligible game in kickoff order; (12) `Model %` → Market-implied probability, remove unsupported Confidence, correct AP-poll wording, remove unsupported "opponent-adjusted"; (13) existing all-overs warning on the Green Light ticket-building path; (14) retain all valid legal, licensing, provenance, freshness and ticket-safety protections. Classic stays explicitly accessible | No new scoring/confidence; no automatic picks; no new lenses; no game-centric redesign; no new cross-page navigation; no ticket-storage expansion; no CFB restoration; no Green Light Next; **no default-route switch** | Built from post-`b12eec3` master; full offline + exact-SHA Linux gates; deployed as the only candidate; signed-in production receipt proving the repaired Classic view has no started events or unavailable players, truthful same-offer pricing + timestamps, current eligible evidence, and the owner's convergence workflow intact. **Stop for owner acceptance** |
| 3 | **Green Light Release 1B — Activate** | DESIGN (authorized only after owner accepts 1A) | `/tools/green-light` renders repaired Classic; `?view=classic` compatible; `?view=workspace` keeps the workspace; navigation points to the supported default; bookmarks keep working; cache versioning prevents the old default persisting | Neither experience deleted; nothing else in the change | Exact activation change gated, deployed separately, final signed-in production verification. **Green Light Release 1 closes only after 1B passes** |
| ∥ G | **Decision Integrity Constitution** — final owner review, version, freeze | DESIGN → owner review (non-build; no release lane) | Prepare the final review package | No Phase 2 implementation | Owner approval ⇒ versioned + frozen |
| ∥ N | **NCAAB Foundation design + acceptance package** | DESIGN (non-build) | One implementation-ready package: registries, schedules, books, lines, prices, timestamps, forward capture, scores, per-book grading, movement, factual slate / matchup / team pages | No paid probe, no code branch, no models, predictions, confidence, simulations, props or Green Light integration | Package returned once for owner approval |
| 4 | **NCAAB Foundation (build)** | queued | per the approved package | per the package's exclusions | gates + production receipt |
| 5 | **Owner choice:** Green Light Release 2 **or** Decision Integrity Phase 2 | queued | — | — | owner decision after pos 4 |
| — | **Everything else** (Safeguard B, D11, L1/L2/L3, visuals/entity/disclosure, `bk-daily` fixes, Research Candidate, runtime pilot, market-movement language, Decision Journal, …) | PARKED | — | — | rebuilt on current master when scheduled here |

**Known dependency recorded for 1A item (6)/(8) — to be confirmed by the item-8 read-only count:** the prod
`NFL_Props.csv` schema observed on 2026-11-07 carries `SourceUpdatedAtUTC` (Book updated) and the zone-less
`LastUpdated` fetch stamp, but no explicit `FetchedAtUTC`. Under the quote-time authority rule (`17b5e69`)
`LastUpdated` cannot serve as "Observed by BK". If the count confirms the column is absent, 1A must either have the
props writer emit `FetchedAtUTC` (inside 1A scope as same-offer timestamp binding) or display "Observed by BK:
unavailable" — an owner decision before BUILD, not an assumption.

**RESOLVED by owner 2026-11-07 — Observed-by-BK contract (inside 1A scope: timestamp + same-offer binding; not a
separate release, not L3):**
- **Field name: `FetchedAtUTC`** — the repository's existing canonical name (already used by
  `fetch_ncaaf_slate_cfbd.py` and read at `app.py:18788`, and the name the approved L1 contract uses for "when BK
  observed the quote"). `ObservedAtUTC` is not introduced. Customer label: "Observed by BK".
- Value = timezone-aware UTC instant at which BK **successfully received the provider response containing that
  quote**; bound to the exact same row as sportsbook, market, line, price and `SourceUpdatedAtUTC`.
- **Granularity (owner clarification 2026-11-08): one value per successful provider response, not per quote.** Rows
  that arrived in the same response legitimately share the same `FetchedAtUTC`; the requirement is that every row
  stays bound to the response in which BK observed it. QCs must not demand per-row uniqueness — they check that a
  row's value is that of its own response, never another response's or a run-level stamp.
- **Never derived** from `LastUpdated`, file mtime, publish time, event time or `SourceUpdatedAtUTC`.
- Preserved through normalization and atomic publication.
- Every newly, successfully fetched props row must carry a valid value; existing rows without it display
  "Observed by BK: unavailable". **No backfill, no manufactured historical times.**
- 1A displays both clocks; **eligibility keeps the deployed `SourceUpdatedAtUTC` rule** — `FetchedAtUTC` is
  informational until L3 is separately approved.
- QCs: schema, provenance (not derived from any forbidden source), malformed / zone-less / future-time handling,
  same-offer binding (no cross-row or cross-book carry).
- Acceptance: synthetic fixtures + the **next normal scheduled fetch** on prod. No manual paid fetch to populate it.
- The item-8 read-only baseline count runs first and documents the current state.
- Note for BUILD: confirm the CFBD slate's existing `FetchedAtUTC` semantics match this definition (per-response
  vs per-run); any difference is recorded, not silently changed (CFB is outside 1A). **CFB implementation stays
  unchanged** unless the audit finds a direct shared-code conflict with the NFL props writer; a conflict is reported
  to the owner before anything CFB is touched.

## Phase 1 — Close production trust obligations (in order; one release at a time)
| # | Item (consolidated) | Branch @ exact SHA | Stage | Remaining acceptance condition | File overlap with active candidate `b12eec3` | Disposition |
|---|---|---|---|---|---|---|
| P1-1 | **NBA v6 + Safeguard A + governed line-movement status** (one release: NBA market v6, NBA validation issues, NBA acceptance receipt, Safeguard A off-season/exit rule, frozen exit semantics, line-movement status). Supersedes NBA v1–v5, v6 @ `28187ad`/`10aab11`, combined `d2187e5`, Safeguard A `31d09dd`/`287f99b` | `fix/nba-v6-sa-linemove-status-on-d2187e5` @ **`b12eec3`** | **GATE → awaiting owner review** (offline 79/79 + Linux gate #5 PASS, receipt `docs/nba_v6_sa_linemove_status_linux_gate5_receipt_20261107.md`) | Owner receipt review → single deploy decision → exact-SHA deploy (FF master) → read-only production acceptance receipt (HEAD, clean tree, units, first `bk-linemove` + `bk-daily` runs under frozen semantics, Run Status binding, RC OFF) | — (is the candidate) | **ACTIVE — next: owner review** |
| P1-GL | **Green Light Restoration P0** (owner 2026-11-07: existing-product regression on the site's central purpose; workspace-default switch `9057ba1` NOT owner-approved; intended GL = convergence board with contradictions + missing evidence visible). Plan: `docs/green_light_restoration_plan_20261107.md`; audit: `docs/green_light_play_finding_audit_20261107.md` | none yet (DESIGN; no branch) | DESIGN — plan reviewed; owner decisions recorded 2026-11-07 (Part 3: hide ungoverned models, kickoff-order visibility, FanDuel + best governed quote bound to one offer, renames) | **Two sequential candidates:** GL-R1 Truth & integrity (BUILD starts only after the P1-1 receipt closes) → gates → deploy → receipt; then GL-R2 Restoration & usability (ATS/Wave rebuild, convergence board default, connections) only after GL-R1's receipt | TBD at build (`app.py`, GL templates, adapters) | **NEXT after P1-1** (ahead of Safeguard B, D11, L1) |
| P1-2 | **Safeguard B** — NCAAB shell honesty (Season Markets lists CBB as Planned only; MLB visual-trust QC self-contained) | `fix/ncaab-shell-honesty` @ `0ad701e` (base `17b5e69`, 2 commits, 15 files) | BUILD (review package returned; not gated) | Rebuild on post-P1-1 master → offline gate → exact-SHA Linux gate → deploy → receipt | `app.py` | PAUSED until P1-1 receipt |
| P1-3 | **D11** — Run Status chooses the current run (operator lease, CAS lifecycle, persisted INCOMPLETE) | `fix/d11-run-status-current-run` @ `feca06f` (base `17b5e69`, 2 commits, 8 files) | GATE PASS on `17b5e69` (`docs/d11_linux_gate_receipt_20261104.md`) — **stale** vs. P1-1 | Heavy overlap ⇒ **rebuild on post-P1-1 master**, re-gate (offline + Linux), deploy, receipt | `app.py`, `generate_run_status.py`, `run_all_scorecards.py`, `run_bk_edge_engine_pipeline.py`, `run_daily.py`, `services/run_outcomes.py` | PAUSED |
| P1-4 | **L1** — game-lines truthful time + spread-side truth (CFB context; G1/G4). Same release covers F-T4 (5-hour staleness shift) and 1.5f/Q-A `LastUpdated` preserved | `fix/game-lines-l1-truthful-time` @ `6424f83` (base `17b5e69`, 1 commit, 11 files); related `fix/game-lines-lastupdated-preserved` @ `3e71f21` (base `63060a9`) | BUILD (approved branch-only; not gated) | Reconcile L1 + `LastUpdated`-preserved into one branch on post-P1-1 master → owner review → gates → deploy → receipt | L1: `app.py`, `fetch_game_lines.py`, `qc_ncaaf_odds_single_writer.py`; LastUpdated: `app.py`, `run_all_scorecards.py`, `services/timeutils.py` | PAUSED |
| P1-5 | **Owner visual checks + JS entity inventory + exclusion disclosures** (signed-in visual matrix; batch-1 JS entity fan-out reconcile incl. scenario_lab short-names; disclosure of excluded/abstained entities) | `claude/youthful-panini-fb6d0e` @ `4cf3f1e` (inventory docs, 32 commits on old base `ed0bf37`) | DISCOVERY (inventory returned) / owner visual checks OPEN | Owner signed-in visual acceptance; decide inventory batch; any code = its own release | n/a (docs) | PAUSED (owner checks can run read-only) |
| P1-6 | **`bk-daily` failures → final operational state** (consolidates 1.4 RCA, 1.5x seven defects, F2/F2v2/F6 season gate, F3 NBA playoff QC, F3b team mapping, F5 NCAAF slate-aware, NBA season-phase contract, 1.5k paid off-season calls, CFBD latch 1.6/1.6c, D12/D12b QC maintenance, QC flake isolation) | F2v2 `fix/bk-daily-f2v2-season-preexec` @ `0ccf053` → F6 `fix/bk-daily-f6-odds-health-season` @ `3fd0e40`; F3 `fix/bk-daily-f3-nba-playoff-qc` @ `5c889e5`; F3b `fix/f3b-nba-team-mapping-gated` @ `41a15ce`; F5 `fix/bk-daily-f5-ncaaf-slate-aware` @ `cea32ea`; phase `fix/nba-season-phase-contract` @ `26ecca2`; D12 `fix/d12-milestone-guard-fixture` @ `c62a381`; flake `fix/qc-ticket-quote-change-isolation` @ `1a580e4`; CFBD scaffold `feat/cfbd-budget-client-scaffold` @ `905cabe` (unwired) | BUILD (branches on `63060a9`/`17b5e69`; none gated) + CFBD = owner decision | Re-derive the current failure list from the post-P1-1 `bk-daily` run (frozen semantics change several outcomes: CFBD latch now FAIL, missing keys FAIL, off-season zero events FAIL); then one reconciled release per root cause, each gated + receipted; CFBD allowance/reset confirmed before wiring | F2v2/F6: `run_all_scorecards.py`, `run_bk_edge_engine_pipeline.py`, `run_daily.py`, `season_utils.py`, `services/timeutils.py`; F5: `fetch_game_lines.py`, `services/feed_validation.py`; F3b/phase: `app.py`; flake: `qc_ticket_quote_change.py`; F3/D12: none | PAUSED; F2 v1 `d2bf8b7` SUPERSEDED by F2v2 |
| P1-7 | **Green Light regression & restoration audit** (existing-product regression obligation, not a new initiative) | none (read-only) | DISCOVERY — **COMPLETE 2026-11-07** (findings → P1-GL); earlier note: paused at step 5; the read-only code/history pass (started before the reset) is parked at `docs/green_light_audit_code_history_20261107.md` — input only, prod data states unverified | Report items 1–7 (owner list); implementation only after owner review | n/a | PAUSED until P1-1…P1-6 |

## Phase 2 — Freeze governance
| # | Item | Branch / doc | Stage | Remaining acceptance condition | Disposition |
|---|---|---|---|---|---|
| G-1 | **Decision Integrity Constitution** (Rev 2.1 approved; Phase 2A Rev 2.2 design approved) | docs on `master`/ledger | DESIGN → final review | Owner final approval → version + freeze; reopen only for a documented contradiction/amendment | After Phase 1 |
| G-2 | Research Candidate Contract (Rev 2.1) + RC 2D1 production (capture OFF) | `claude/jolly-ishizaka-c6519a` @ `9db4583`; `release/research-candidate-2d1` @ `628657b` (in master) | DESIGN (stopped for review); 2D1 OFF in prod | Folded into G-1 review; **no Phase 2 implementation** | PAUSED |

## Phase 3 — NCAAB Foundation Release
| # | Item | Stage | Scope | Excluded | Disposition |
|---|---|---|---|---|---|
| N-1 | NCAAB Foundation design + acceptance plan (builds on `docs/ncaab_discovery_audit_20261104.md`, owner decisions 11-04, book policy, probe preconditions) | DESIGN (not started under reset) | canonical team / event / market registries; authoritative schedule ingestion; bookmaker-specific lines + prices; fetched/source timestamps; forward market capture; scores; per-book cover/fail/push grading; slate page; factual matchup + team pages; factual evidence notebook (supporting / contradictory / missing) | predictions, confidence scores, simulations, Green Light, props, unlicensed injuries, projections/power ratings, automatic picks, consensus grading | After G-1; **no implementation until design approved** |

## Other open items (recorded; not active — attach to the release that owns their files)
| Item | Stage | Attach to |
|---|---|---|
| Market-movement neutral language `fix/market-movement-neutral-language` @ `742ae90` (14 files; owner naming question open) | BUILD (branch-only) | Own UX/legal-language release after Phase 1; must not change product purpose. Overlap: `app.py`, `templates/elite_dashboard.html`, `templates/info.html` — PAUSED |
| F7 NCAAF odds single-writer `design/f7-ncaaf-odds-single-writer` @ `173efa4` | DESIGN | Phase 3 data foundation / P1-6 — PAUSED |
| Green Light workshop materials `design/green-light-workshop` @ `1730987` (UCLA case) | DESIGN | P1-7 outcome — PAUSED |
| F-T1/F-T2 timestamp producer + other-sport audit; F-T3 editor copy; L2 shared stale gate; L3 props freshness reconciliation | DISCOVERY/DESIGN | P1-4 (L1) family and next ticket-editor release — PAUSED |
| Decision Journal (dark), King's Tickets step 4 storage, SGP multi-leg handoff | DESIGN (held) | After Phase 3 — PAUSED |
| Readiness reconciliation / Decision Support Readiness Audit (owner request 11-07) | DISCOVERY (not started) | After P1-7 under the reset order — PAUSED |

## Superseded / already-in-master branches (no action; kept, not deleted)
In master (patch-equivalent): `fix/props-quote-source-utc` `17b5e69`, `integration/integrity-d4-6bdb73f` `4afcab9`,
`fix/d4-kickoff-gate-v2` `a086764`, `integration/integrity-group-a5de400` `672480d`, `integration/integrity-group`
`1482d65`, `fix/d1-weather-unavailable` `6bdb73f`, `fix/props-slate-turnover` `a5de400`, `fix/daily-card-no-fabricated-price`
`0f76289`, `fix/f7-cfbd-no-fabricated-prices` `4d7a60f`, `fix/qc-wnba-nba-self-contained` `ac55194`,
`fix/bk-daily-f1-heatmap-qc` `3564dc7`, `fix/rc-producer-corrections` `63060a9`, `release/research-candidate-2d1` `628657b`.
Superseded by P1-1: `fix/nba-game-lines-event-aware` v1–v5 (`c9bc374`, `f06e568`, `9ac078f`, `29acc81`, `84f1f0c`),
`fix/nba-market-v6-on-17b5e69` `28187ad`, `fix/nba-market-v6-on-3d7cda1` `10aab11`, `fix/nba-v6-safeguard-a-on-10aab11`
`d2187e5`, `fix/fetch-output-path-guard` `31d09dd`. Superseded otherwise: `fix/d4-kickoff-gate` `db84c1b` (by v2, in
master), `fix/bk-daily-f2-season-gate` `d2bf8b7` (by F2v2). Stale session branches: `claude/master-vs-main-branch-smh0bf`
`b722a91`, `claude/bankroll-kings-access-f5elr2` `6c52d00`.

## Execution order (owner directive)
1. ~~Finish and report the `b12eec3` gate~~ — **done, PASS** (receipt above).
2. **Await review and deployment decision on `b12eec3`** ← current.
3. If approved, deploy only `b12eec3` and obtain its production receipt.
**(Superseded by the CONTROLLING PROGRAM ORDER at the top of this file — kept for history.) Roadmap locked by owner 2026-11-07:**
- **ACTIVE:** `b12eec3` production acceptance — wait for the 2026-11-08 `bk-daily` receipt; close or remediate. Nothing else enters build.
- **NEXT:** **Green Light Release 1** — repair the classic convergence board (kickoff/started-event exclusion, OUT/IR/PUP
  availability, stale-evidence suppression, sportsbook + Book-updated/Observed-by-BK time attribution bound to one
  offer, injury and movement joins, model hiding, all-overs warning) → production acceptance → **then restore classic
  as the supported default** (`/tools/green-light`), workspace kept at an alternate entry (`?view=workspace`); nothing
  deleted. The default switch (plan U1) moves into Release 1, gated on its production acceptance.
- **PARALLEL GOVERNANCE (no release lane):** Decision Integrity Constitution — owner read → approve → version → freeze.
- **PARALLEL DESIGN (no implementation, no probes, no build):** NCAAB Foundation design package, returned once as
  one implementation-ready package.
- **FOLLOWING IMPLEMENTATION:** NCAAB Foundation (teams, events, books, lines, prices, scores, per-book grading,
  movement, slate/matchup/team pages).
- **OWNER DECISION after that:** Green Light Release 2 (ATS/Wave rebuild, connections, slate-by-game spec) **or**
  Decision Integrity Phase 2.
- **PARKED:** everything else (Safeguard B, D11, L1, visuals/entity/disclosure, `bk-daily` fixes, Research
  Candidate, runtime pilot, …) — each rebuilt on current master when its turn comes.
- **Rule:** an item not in this table does not enter implementation.
6. Decision Integrity Constitution final approval + freeze.
7. NCAAB Foundation Release design + acceptance plan (no NCAAB implementation until approved).
