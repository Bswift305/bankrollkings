# CFB ATS Wave Audit #3 — Source→Render evidence (build_cfb_wave_context)

Read-only audit (prod `diag_cfb_ats_wave_audit.py`, HEAD `57a70ef`; `READ-ONLY PROOF … ALL UNCHANGED`,
exit 0; **no CFBD request/refresh**). Governing contract: `docs/ats_wave_contract.md` (FROZEN). Uses the
RUNTIME artifacts consumed in production; authoritative identity `(GameID, TeamSide)`, names presentation
only. Shaped for later Evidence-Ledger migration; no receipts implemented.

## Verdict: CLEAN — contract satisfied, board synchronized, no remediation.

## Runtime lineage / freshness (no provider call)
- manifest `cfb_line_moves.json` → `/opt/bankrollkings-runtime/scenarios/…` (**BK_RUNTIME_DIR**), sha
  `359914e1…`, season 2026, `updated 2026-10-21 13:06 UTC`, 954 games.
- graded `NCAAF_GameLineResults.csv` → `/opt/bankrollkings/data/tracking/…` (gitignored repo tree,
  grader-regenerated), sha `7a54014a…`, mtime 2026-10-24 13:11 UTC.
- `cfb_2026_results.json` / `cfb_2026_ats.json` under BK_RUNTIME_DIR.
- **Provider-outage separation:** no CFBD call was made; artifact validity is judged by manifest
  lineage + completeness, not provider availability. The manifest being 3 days older than the graded file
  is acceptable — CFB sync is lineage+completeness, not a time budget (unlike NFL's 48h sidecar).

## Real evidence (prod, 2026-10-25)
- **Sync:** `synchronized=True`, `read_error=None`, manifest_season 2026, `completed_week=7`,
  `wave_week=8`, `wave_through_week=7`.
- **`(GameID,TeamSide)` conservation (all clean):** expected_decisions 898 (FBS sides of completed
  line-bearing games) ⊆ graded_decisions 1732; **missing 0, overdue 0, ineligible 0, malformed 0,
  conflicts 0, manifest_missing_gameid 0, unknown_conference 0, manifest_dup_gameid 0**; exclusions 828
  (non-FBS sides + no-line/cancelled — legitimate).
- **Membership:** 15 FBS members (`cover_streak ≥ 3`); hash `e8492e82a812a93c`; ordering
  `(cover_streak desc, team asc)` monotonic; `overlay_misattributions=0`. 9 fades (`loss_streak ≥ 3`).
  Live examples prove *earlier losses don't disqualify*: Kentucky 6-1 (`L,W,W,W,W,W`) → cover_streak 5;
  Okla St, Wake Forest likewise; BYU/UCLA 6-0 → 6.
- **FBS gate proven live:** graded index 266 teams = 138 FBS + 128 NON_FBS; cover_streak distribution
  `{0:136,1:73,2:31,3:14,4:6,5:4,6:2}` (max 6) → 26 teams at ≥3, of which only **15 FBS are admitted**;
  the 11 non-FBS ≥3 streaks are correctly excluded by the conference gate. `unknown_conference=0`.

## Frozen-contract invariants (synthetic, pure core `_cfb_cover_streaks_from_df`) — all pass
Earlier loss + prior-season excluded → cover_streak 3; push interrupts → 1; loss resets → 0;
`(GameID,TeamSide)` conflict detected (fail closed); missing-GameID row ineligible; conference tri-state
SEC→FBS / Big Sky→NON_FBS / misspelled→UNKNOWN (fails sync closed, never silently non-FBS).

## Conservation reconciliation (required before closure) — PROVEN
`diag_cfb_ats_conservation.py` (prod `553d014`, `ALL UNCHANGED`) partitions all 1,732 graded
`(GameID,TeamSide)` decisions into exactly one disjoint terminal disposition:

```
expected_FBS 898 + known_non_FBS 828 + no_line 0 + future_week 6 + not_completed 0
+ outside_manifest 0 + unknown_conference 0  =  1732  (== graded_keys)     conservation: True
```

The earlier "graded ⊇ expected" framing was loose and is **withdrawn**: `graded = expected + exclusions`
left 6 unexplained; they are now classified. The **6 remainder rows are all `future_week`** — three
early-Week-8 games (played 2026-10-20), each × 2 sides, all `manifest completed=True`, `week=8` (beyond
`completed_week=7`), valid lines, known FBS conferences:
`401871055` MTSU/FIU (Conference USA), `401871092` Marshall/South Alabama (Sun Belt),
`401871069` Delaware/Missouri State (Conference USA). They are real completed games counted by the
game-completeness model but correctly outside the "expected through Week 7" set — a legitimate terminal
category, **no residual, no overlap, no hidden defect** (0 unknown_conference / malformed / outside_manifest /
not_completed).

## Presentation-pending (owner visual, not calc failures)
- **Rendered-membership / hash reconciliation** — confirm the rows the page renders match the
  `membership_hash` (same as recorded for NFL ATS).
- **Empty-state / visual** — board is non-empty (15 members, 9 fades); confirm rows + fades render and the
  "sorted by active cover streak" label shows.

## Status
Audit #3 **CLOSED — contract satisfied, conservation proven, no remediation**. All three streak audits are
done: Hot Hand (#1, F5+F2 shipped + verified), NFL ATS (#2, clean), CFB ATS (#3, clean + conserved).
Per direction, **F3 is recorded for the future exclusion-receipt work** (not a separate ad-hoc disclosure
now), and the shared streak explainer is **deferred** until the Decision Integrity Architecture Constitution
defines the receipt contract (with NFL ATS as the enforcement pilot). Independent gates still open: Hot Hand
/ NFL ATS owner visuals; the NBA scheduled-acceptance receipt.

## Ordered next steps (per direction, 2026-10-25)
1. **Finish the already-authorized entity-link + minimal-destination P0:** WNBA player-link batch;
   `football_method_board` destination defect; schedule team links; minimal MLB/WNBA team destinations;
   client-rendered resolver payloads, beginning with SGP Workbench.
2. Owner visuals for Hot Hand + ATS.
3. **Decision Integrity Architecture Constitution** — design-only.
4. **NFL ATS as the receipt/enforcement pilot.**
5. **Shared streak explainer** built from the approved receipt contract.
