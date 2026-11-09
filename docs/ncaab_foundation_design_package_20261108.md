# NCAAB Foundation — implementation-ready design package (consolidation, 2026-11-08) — UNCOMMITTED DRAFT

**Design only.** No probe, API request, branch, code, commit, push or program-table change. This package introduces
**no new product concept**: it consolidates the approved inputs into one index, records what changed in the
prerequisites since 11-04, and lists every decision that is still open. Where text below and the source design
disagree, the source design (with its binding amendment C1–C10) governs.

**Binding sources**
- `docs/ncaab_first_slice_design_20261104.md` — first-slice contract + **Amendment 2026-11-04 (C1–C10)**; the
  operative specification (§0 binding owner decisions 1–11, §1–§19).
- `docs/ncaab_discovery_audit_20261104.md` — read-only discovery, readiness matrix, credit model.
- `docs/PROGRAM_TABLE.md` row **N-1** (scope / exclusions); owner decisions 2026-11-04 (ledger).
- Cross-sport findings recorded 2026-11-08 in `docs/nov7_cross_sport_landing_audit_20261108.md` (used here only as
  evidence for prerequisites and acceptance, not as new scope).

## A. Required items → where they are specified

| # | Required item | Specified in (source design) | Status |
|---|---|---|---|
| 1 | Canonical team registry, permanent team IDs | §3.1–§3.3, §3.6 (opaque `ncaam_t_` / shared `ncaa_s_`, never name-derived; C1); exact fail-closed resolver; blocked bare names | Complete |
| 2 | Canonical event IDs + identity fields | §5.1–§5.2 (`EventId` = provider id; `NCAAMB_Events.csv`); §3.4 `IdentityStatus`; §5.5 duplicates | Complete |
| 3 | Actual venue + neutral-site | §9.3 (decision 6): `NeutralSite=UNKNOWN` in release 1; `Home (as listed)`; no splits/evidence from "home"; only `FALSE` rows may ever enter splits | Complete for release 1 (see D-3) |
| 4 | Governed schedule + final-score sources | §5 (provider `/events` only; no completeness claim); §8 Odds API `/scores?daysFrom=3` (decision 4; no ESPN) | Complete; cost unverified (probe) |
| 5 | Book-specific ML / spread / total offers | §4 book policy (C10, allowlist gates publication, no default book); §6 long form one row per (EventId, BookKey, MarketKey, Side) | Complete; allowlist content open (Q1) |
| 6 | Explicit side identity for every line and price | §6.3 side by construction (outcome name → HOME/AWAY/OVER/UNDER; point and price from the same outcome; no first-outcome, no negation); §6.4 `COMPLETE/ONE_SIDED/INCONSISTENT` incl. totals `Point_OVER == Point_UNDER` | Complete — explicitly avoids the shared writer's spread-price and totals-point defects found 2026-11-08 |
| 7 | `SourceUpdatedAtUTC` + `FetchedAtUTC` | §6.2, §10 (C5: availability = `FetchedAtUTC` ≤ 6h; movement/`Book updated` = `SourceUpdatedAtUTC`; no `LastUpdated` column); R9 source-after-fetch reject | Complete (see D-1, D-2) |
| 8 | Forward-only market capture | §7 append-only snapshots; first/last/pre-tip captured labels (never "open"/"closing"); decision 7 no historical purchase | Complete |
| 9 | Per-book cover/fail/push grading | §8.3 (C2–C4): each book graded at its own pre-tip point/price; distributions, per-book records; no consensus | Complete |
| 10 | Completed-event eligibility + live-surface removal | §5.3 `ListingStatus` (`COMPLETED`→`Final`, `NO_RESULT`); executability via the shared kickoff gate (strict `kickoff > now`); §6.4 D3 drops started rows; `qc_ncaamb_ticket_handoff.py` | Complete for NCAAMB pages; see D-4 for cross-site counters |
| 11 | Factual slate, matchup, team pages | §11.1–§11.4 (slate ordered by commence; matchup; team context from our finals only — decision 5; best available without consensus) | Complete; access tier open (Q9) |
| 12 | Supporting / contradicting / missing notebook | §11.5 evidence panel (counts by type, no numeric total) | Complete |
| 13 | Freshness + unavailable-state contracts | §10 `ncaamb_fact_state` (`AVAILABLE/STALE/UNAVAILABLE/PENDING`, reason codes, never zero-filled); decision 11 injuries "Unavailable" | Complete |
| 14 | Data-rights + provider-cost matrix | Discovery §1.x + §3 readiness matrix (ESPN unlicensed, KenPom not licensed, CBBD terms TBD, no CBB injury feed); design §14 per-call formulas, provisional **7,500 credits/month** cap, budget guard; §14.5 probe (A+B only, ≤5 credits, `us` only) | Complete as documented; costs [I] until the probe |
| 15 | Offline, Linux, production acceptance | §16 QC set (offline, socket-blocked, three process TZs, mutation-checked); §19 step 9 (offline gate → scoped Linux gate → owner approval → one governed manual prod run → receipt → timer + run_daily → `live=True` → monitored day → production receipt) | Complete |

**Explicit exclusions (unchanged, N-1 + §17):** Green Light; models; predictions; confidence; simulations; props;
power ratings; automatic picks; consensus grading; unlicensed injuries. Pace/efficiency stays `Unavailable — not
licensed`.

## B. Prerequisite status (§1) as of 2026-11-08

| ID | Prerequisite | 11-04 state | 2026-11-08 state (evidence) |
|---|---|---|---|
| PRE-1 | Safeguard A (fetch output-path guard) | built, not deployed | **In production** as part of `b12eec3` (acceptance pending) |
| PRE-2 | Safeguard B `fix/ncaab-shell-honesty` | built, not deployed | Branch only; PAUSED under the program reset |
| PRE-3 | Game-lines consolidated correction | pending surface map | Still pending. 2026-11-08 evidence sharpens it: spread price has no side identity; totals under-point unbound; `LastUpdated` dropped by the formatter (6h gate dead for NFL/NCAAF/MLB/WNBA lines); recorded as obligations O-3 / spread-writer requirements. NCAAMB does not inherit them (own long-form writer) but shares helpers and the site |
| PRE-4 | Run-receipt contract (NBA v6) | branch only | **In production** in `b12eec3` (acceptance pending); generalization for a second stage family still a reviewed change |
| PRE-5 | Cost probe | not run | Not run. Preconditions: Safeguard A passes (deployed), 11-05 checkpoint reviewed (status to confirm), probe proven unable to write NBA/WNBA paths |

## C. Implementation order
Unchanged from source §19 (each step its own reviewed branch; none authorized by this package): prerequisites →
probe → registries (+ reference review gate C8) → contract + market writer → scores + grading → sport registry →
pages/evidence/handoff → orchestrator/locks/receipts/budget/units (uninstalled) → release gate.

## D. Reconciliation notes from 2026-11-08 evidence (no new scope)
- **D-1 `FetchedAtUTC` granularity.** Source §6.2 defines it as "the run's single fetch instant". The owner
  clarified on 2026-11-08 (for NFL props) that `FetchedAtUTC` is **per successful provider response**. For NCAAMB
  the lines come from one `/odds` response per run, so the two coincide for quotes; `/events` and `/scores` are
  separate responses and carry their own fetch instants. Needs an explicit owner confirmation that the NCAAMB
  definition is per-response (see E-8).
- **D-2 Freshness clock across sports.** NCAAMB availability uses `FetchedAtUTC` (C5); NFL Green Light 1A keeps the
  deployed `SourceUpdatedAtUTC` eligibility rule until L3. Divergent by owner decision, not by defect; recorded so
  shared helpers are not "harmonized" by accident (E-9).
- **D-3 Neutral site.** The 2026-11-08 NFL venue finding (venue from the nominal home team, no abstention) is the
  failure mode §9.3 already prevents. The cross-sport acceptance contract recorded today (venue from `EventId`;
  neutral flag suppresses home assumptions; roof from actual venue; unavailable venue → abstain) is consistent with
  §9.3 and adds nothing NCAAMB release 1 must build.
- **D-4 Completed events on cross-site surfaces.** NCAAMB pages remove/label completed events (§5.3). Site-wide
  counters (Slate Pulse, Best Lines) count rows unfiltered today (O-3). Acceptance should include that NCAAMB rows
  never inflate those counters (fixture check in `qc_ncaamb_pages.py` scope), or that NCAAMB is excluded from them
  until O-3 lands (E-10).
- **D-5 Refresh cadence vs freshness.** Source §13.4 designs a 4h cadence with a 6h `FetchedAtUTC` rule, so every
  listed game stays observable; the NFL finding (one daily refresh cannot cover late games) does not apply.
- **D-6 Canonical record retention.** NCAAMB grades only against its own retained pre-tip snapshots (§7–§8), so the
  NFL ATS replay gap (non-retained nflverse source) does not arise.

## E. Unresolved owner / legal / provider decisions (not resolved here)
1. **Provider-book allowlist content** (Q1) — policy decided (C10); the list is open; needs the probe's observed keys.
2. **Pre-tip capture cadence** (Q4) — hourly O2 not approved; release 1 accepts up to 4h capture lead.
3. **Season window source** (Q6) — verified first/last dates vs schedule evidence.
4. **Access tier** (Q9) — slate and matchup free or `all_access`.
5. **Duplicate window** (Q10) — 12 hours acceptable?
6. **Budget policy month** (Q11) — UTC calendar month vs provider billing reset; plus whether the provisional 7,500
   credits/month cap stands after the probe.
7. **Reference-data sign-off** (Q12) — owner sign-off of the §15 schema/content review before the `.gitignore` commit.
8. **`FetchedAtUTC` definition for NCAAMB** (D-1) — confirm per successful provider response.
9. **Cross-sport freshness clock** (D-2) — confirm NCAAMB stays on `FetchedAtUTC` while NFL 1A stays on
   `SourceUpdatedAtUTC` until L3.
10. **Site-wide counters** (D-4) — exclude NCAAMB until O-3, or require NCAAMB-safe counting.
11. **Probe execution approval and timing** — conditionally approved 11-04 (≤5 credits, `us`, A+B); when it may run
    under the one-release-at-a-time rule; confirm the 11-05 checkpoint precondition is satisfied.
12. **PRE-2 / PRE-3 sequencing** — Safeguard B deployment and the consolidated game-lines correction relative to
    Green Light 1A and N-1.
13. **Legal/provider (open by design, no assumption made):** CBB scores licence = Odds API `/scores` only (ESPN
    rejected); CBBD terms, KenPom licence and barttorvik ToS — pace/efficiency excluded until decided; CBB injuries
    unavailable (no licensed feed); women's (`basketball_wncaab`) deferred and unverified.

## F. What "implementation-ready" means here
Every component has a contract, file/column spec, fail-closed rule and named offline QC in the source design. The
blocking unknowns are provider facts (per-call cost, observed book keys, team strings) that only the approved probe
can supply, plus the owner decisions in §E. No build step starts until N-1 is approved and appears in the program
table with owner, stage, position, scope, exclusions and acceptance criteria.
