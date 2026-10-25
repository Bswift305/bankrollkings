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

## Notes (not defects)
1. **`graded_decisions (1732) > expected_decisions (898)` is correct** — graded_keys is all 2026 SPREAD
   `(GameID,TeamSide)` decisions (FBS + non-FBS + both sides); the contract only requires every *expected
   FBS* decision to be graded (`missing=0`), i.e. expected ⊆ graded. Not a conservation breach.
2. **Empty-state / rendered-membership presentation** (owner visual) — same view-level acceptance item
   noted for the other boards; here the board is non-empty (15 members), so confirm the rows + fades
   render and the "sorted by active cover streak" label shows.

## Status
Audit #3 complete, **no remediation**. All three streak audits are now done: Hot Hand (#1, F5+F2 shipped),
NFL ATS (#2, clean), CFB ATS (#3, clean). Queued per direction: Hot Hand **F3** (identity/absence
disclosure) and the **shared streak explainer** (to wire onto the now-stable surfaces). Independent gates
still open: Hot Hand / NFL ATS owner visuals, and the NBA scheduled-acceptance receipt.
