# Bankroll Kings — Master Program Ledger

One place for active work, blockers, deferred work, acceptance evidence and the **next authorized action**.
Nothing is "done" without an evidence-backed receipt. Partial checks are recorded as partial.
Branch: `program/ledger` (docs only; **not merged to master** while an exact-HEAD validation is pending).

_Last updated: 2026-11-01 (UTC 16:xx)._

## Standing rules
- **Master freeze until the 11-02 receipt is read:** the RC one-shot job aborts unless prod HEAD == `63060a9`.
  Any push to master before 2026-11-02 12:30 UTC — even docs — voids that validation.
- Overall `bk-daily` result is always reported **separately** from step results. It has exited 1 every day
  in the window (10-25 → 11-01); never record it as success.
- During owner ticket windows: pause build work, support the live decision workflow, log product gaps here.
- Production changes need explicit owner approval per action. Capture stays OFF until Phase 2 acceptance.

## Phase 1 — Restore production health  _(ACTIVE)_

| Item | State | Evidence | Next authorized action |
|---|---|---|---|
| 1.1 RC 2D1 producer corrections deployed | **DONE** | Gate v3 PASS `5983b6fb` (HEAD `63060a9`, 7 files, 36/36 single-writer); master FF `628657b..63060a9`; deploy check `49144d1f` (HEAD OK, active 15:12 UTC, 200, flags 0/0/0, artifacts == backup) | — |
| 1.2 Pre-deploy backup | **DONE** | `3a4d0fe0`: `/home/ubuntu/bk-backups/rc-scheduled-20261101T150655Z/` 5 files, SHA256SUMS verified, baseline roster null_governed=8, props SourceUpdatedAtUTC_nonblank=0 | — |
| 1.3 Scheduled-run validation of the producer fix | **SCHEDULED** | transient `rc-sched-validate-20261102.timer` @ 2026-11-02 12:30 UTC, job sha `acc7e371…` (`b1a92edb`) | After ~13:30 UTC 11-02: read `receipt-20261102.txt`; validate; report ACCEPTED / RESTORED / missing (reboot? abort? job failure?) — **no prod change** |
| 1.4 RCA: overall `bk-daily` failure | **DIAGNOSED (read-only)** | `docs/bk_daily_rca_2026-11-01.md` — 7 recurring/structural causes, classified | Owner review of F1–F5 |
| 1.5 Fix `bk-daily` (F1 QC drift, F2 season gate, F3 NBA playoff QC, F5 NCAAF slate-aware) | **PROPOSED** | RCA §3 | After 1.3 closes: implement as separate reviewed commits + QCs; deploy; verify |
| 1.6 CFBD latch (F4, config) | **BLOCKER (owner decision)** | Probe `4f282454` (approved; ONE CFBD `/conferences` call, 2026-11-01 16:03 UTC): **HTTP 200 — quota has reset.** Latch `5cb540b5`: `/opt/bankrollkings-runtime/cfbd_quota_state.json` `exhausted:true, reset_at:null` since 2026-10-24 13:04; no `BK_CFBD_RESET_AT`/`BK_CFBD_FORCE` in `.env`. ⚠️ The 10-24 exhaustion means daily CFB usage consumed a full month's quota in ~24 days — clearing alone likely re-exhausts ~late Nov | Owner: (a) when to clear the latch (after the 11-02 receipt recommended), (b) CFBD budget: reduce daily CFB call volume or upgrade the plan, (c) set `BK_CFBD_RESET_AT` to the next monthly reset |
| 1.7 Production-health acceptance | OPEN | — | One full scheduled run: `Result=success`, exit 0, zero `[FAIL]`, freshness within contract — receipt |
| 1.8 Known out-of-scope finding | RECORDED | Six nflverse builders re-download the same feed daily (efficiency) | Deferred |

## Phase 2 — Research Candidate operational  _(BLOCKED on Phase 1)_
2.1 validate corrected roster + authoritative source timestamps (from 1.3) · 2.2 provision governed store
securely · 2.3 owner-only capture behind the flag · 2.4 one genuine pre-event observation · 2.5 idempotent
retry, provenance, backup, restore, sanitized logs, rollback · 2.6 dark bake before any wider exposure.
Design refs: `docs/research_candidate_contract.md`, `docs/research_candidate_2d1_*`.

## Phase 3 — Green Light rebuilt around the owner's process  _(QUEUED)_
Workshop first: how the owner actually decides; **UCLA −23 vs Nevada** as reconstruction case #1; required /
optional factors, contradictions, disqualifiers; convergence across trends, matchup, market behavior,
injuries, line movement, context; missing/stale evidence shown honestly; account-level preferences; final
decision stays with the owner — **no manufactured confidence score**. Implement in reversible slices.

## Phase 4 — Ticket workflow  _(QUEUED)_
Research → proposed ticket without losing rationale, line, timestamp, evidence; connect Green Light,
Research Candidates, Decision Journal, editable tickets; measure what happened afterward.

## Phase 5 — Legal and launch readiness  _(QUEUED — not skippable)_
Audit every customer-facing claim; disclaimers, terms, privacy, data rights, subscriptions, auth, retention;
desktop + mobile; full production acceptance; written go/no-go record.

## Deferred / parked (explicit, not lost)
- Single-writer proposal doc (`docs/research_candidate_2d1_roster_single_writer_proposal.md`) — implemented as
  `63060a9`; kept for the record.
- Local `master` in the main checkout carries one unpushed commit `3098325` (streak explainer correction 4) —
  needs its own review/push decision; not part of any phase above yet.

## Ticket-window observations (product gaps found while deciding)
_(none recorded yet)_
