# NFL ATS Wave Audit #2 — Source→Render evidence (build_nfl_ats_wave)

Read-only audit (prod `diag_nfl_ats_wave_audit.py`, HEAD `488c236`; `READ-ONLY PROOF … ALL UNCHANGED`,
exit 0). **No membership, ordering, template, or data-source change made.** Governing contract:
`docs/ats_wave_contract.md` (FROZEN). Shaped for later Evidence-Ledger migration; no receipts implemented.

## Verdict: CLEAN — contract satisfied, no remediation required.

Unlike Hot Hand (Audit #1, which had the F5 active-board defect), the NFL ATS Wave is **correct by
construction** and the audit confirms it on real data.

## Chain + real evidence (prod, 2026-10-25)
`Source (nflverse games parquet, sha-verified sidecar) → canonical game_id / reciprocal TeamSide →
eligibility (resolver season, event-level completeness) → ATS grading (result − spread) → trailing
cover streak → membership (cover_streak ≥ 3) → ordering (streak desc, team asc) → render`

- **Source / freshness:** `nflverse games (recorded spread)`, season 2026, sidecar basis (no mtime
  fallback), age 4.6h < 48h budget, sha `27465dcd…`, bootstrap False. `synchronized=True`.
- **Eligibility / completeness:** `season_rows=272`, unique `game_id`=272, **graded_games=94**,
  overdue 0, malformed 0, excluded(no-spread) 0, conflicts 0, exact-duplicates-collapsed 0. Conservation
  holds: `272 = 94 graded + 178 future/within-grace` (residual ≥ 0).
- **Grading / streaks:** `cover_streak` distribution `{0:16, 1:9, 2:7}`, **max 2**; loss-streak
  `{0:18, 1:6, 2:8}`; teams by last graded week `{5:4, 6:26, 7:2}`. Sample (old→new, 1=cover/−1=loss/0=push)
  manually verified: CAR `[-1,1,-1,1,1]`→2, HOU `[-1,-1,-1,-1,1,1]`→2, NYJ `[1,1,0,-1,1,1]`→2 (push+loss
  break earlier), GB `[-1,-1,-1,0,1,1]`→2.
- **Membership / ordering:** `members (cover_streak≥3) = 0` — **factual** (max trailing cover run is 2),
  not a calc bug. Ordering (streak desc, team asc) monotonic. No builder-level display limit (any cap is
  view-level).
- **`graded_through_week=7`** while the resolver completed week is 6 — **correct by contract**: the ATS
  Wave is a *game-completeness* model ("a completed Thursday game counts immediately"), deliberately NOT
  Hot Hand's week boundary; the 2 finished Week-7 games count, the rest of Week 7 is future/ignored.

## Frozen-contract invariants (synthetic, pure core `_nfl_ats_decisions_from_games`) — all pass
Earlier(-season) losses do not disqualify a trailing 3-cover run; **push interrupts**; **loss resets**;
reciprocity (cover/loss mirror or two pushes); **prior-season rows excluded**; **overdue past-grace game →
fail closed**; future/within-grace ignored. These match the contract truth table + required fixtures.

## Notes (not defects)
1. **Intentional game-vs-week completeness difference from Hot Hand.** Hot Hand caps at the resolver
   completed week (F5); the ATS Wave counts every *completed game* immediately (incl. finished Week-7
   games). Both are correct for their respective contracts — do NOT "fix" the ATS Wave by analogy to Hot
   Hand's week cap; the ATS contract explicitly chose game-completeness.
2. **Empty-state presentation (view-level, owner visual).** With 0 qualifying members the surface should
   render an honest "no active 3+ ATS cover streaks" state (not a blank/broken-looking board). This is a
   presentation acceptance item for the owner visual, not a builder correctness defect.

## Status
Audit #2 complete, **no remediation**. F3 (identity disclosure, Hot Hand) and the shared streak explainer
remain queued per direction. Next independent audit in the work order: **CFB ATS (Audit #3)** — which the
contract notes shares this frozen rule (`qc_cfb_ats_wave_admission.py`) but reads a different source
(CFBD / `cfb_line_moves.json` manifest) with its own identity grain.
