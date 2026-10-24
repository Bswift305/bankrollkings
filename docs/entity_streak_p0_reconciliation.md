# Entity-link + streak-integrity P0 — shipped-state reconciliation matrix

Read-only inventory before resuming the P0 (do not redo prod-verified work). Grounded in
`docs/entity_streak_p0_closure.md` (authoritative, supersedes the premature `b080a3b`),
`docs/entity_link_migration.md`, `docs/entity_destination_matrix.md`, the QC suite (run status below),
and template/builder greps. "Verified" = compile + owner test-client + QC; the authed prod receipt +
owner visual pass are owner-run (this session has no SSM/authed-prod).

> **Status wording (required):** this matrix is **locally verified and committed**; its **production
> column is PENDING**. The P0 is NOT "production-verified" until the authenticated crawl, destination
> fetches, universe/membership/render hashes, and visual checks run on the DEPLOYED commits. Do not
> describe the whole P0 as production-verified before then.

## Matrix

| Dimension | Shipped / DONE | Remaining | Prod-verified? |
|---|---|---|---|
| **Entity-link conversions by sport × surface** | NFL: player→`/tools/player-check`, team→`/tools/nfl-team` (targetable) on injury_report, nfl_milestones, nfl_matchup_center. MLB: 13 player surfaces → `/player?sport=mlb` (fixed wrong-dest bug). CFB: team→`/tools/cfb-team`. NBA/WNBA: `/player`,`/team` sport-scoped (gated→plain) **+ Option A market-only `/tools/nba-player|wnba-player|nba-team`** (`6fbc4dc`). | WNBA player links batch (wnba_dashboard/matchup/method_board); `football_method_board.html:499` (NFL/CFB→NBA route bug); NFL row-anchor surfaces (nfl_hub/heatmap/matchup_edge/prop_floor — nested-anchor care); cross-sport dashboards; schedule team. **NBA surfaces DEFERRED to NBA Season Readiness.** | Server surfaces: ✅ local+QC; authed prod crawl owner-run |
| **Destination-page coverage** | NFL player+team ✅; CFB team ✅ (player plain-text by design); NBA player+team ✅ (gated) + market-only; MLB player ✅; WNBA player (gated) + market-only | **MLB team / WNBA team → minimal destination to BUILD** (NOT "blocked" — product requirement: names clickable where a valid destination exists). Minimal page = canonical identity + sport/team label + cleared schedule & licensed market facts where available + restricted-data abstention banner, NO fabricated stats, unknown/ambiguous → plain text, destination-fetch test asserts the rendered team. WNBA governed by the legal gate. Until built, resolver returns plain text (not a wrong link). Belongs in the destinations phase. | ✅ `qc_entity_links` fetch-tests each resolvable dest |
| **Prop-streak integrity** | `qc_streak_integrity` ✅, `qc_nfl_prop_streak_integration`/`_freshness` ✅; Riding-the-Wave current-season-bound, fail-closed | Full Source→Render evidence shaping (shared with Hot Hand audit) | ✅ local/QC. **Item 5 — RECONCILED 2026-10-24 (prod read-only receipt, `diag_nfl_grading_receipt.py`):** `NFL_AllPropResults.csv` is **FRESH by mtime** (09:12 ET, 3.6h ago, 34,788 rows, 22 MB) but holds **ZERO current-season (2026) rows — only 2024 (15,282) + 2025 (19,506)**. `resolver_current_season=2026`/`completed_week=6`; `board_available=False (current_season_ungraded)`. **Both prior claims were wrong:** not "stale Wk18" (the file is freshly rewritten), and not "fresh 2026 Wk6 / ~16,753" (there are **0** 2026 rows — that figure was a different source, the game-stat/nflverse record, not this graded CSV). **The board correctly fails closed** (do NOT infer health from mtime). **Not input-starved** (first-cut guess, corrected): a prod read of the candidate archive shows **13,386 NFL candidates, all current-season (2026)** — the input is healthy. The regression is DOWNSTREAM of the archive. Two corrections to the first probe: (a) a **time skew** — the on-disk output was written 09:12 while the archive was re-read at 13:25, so they reflect different moments and cannot be compared directly; (b) the on-disk `NFL_AllPropResults.csv` carries **one-off-backfill-only columns** (`IsBackfill`/`GameDate`/`WindMph`/`ModelVersion`) that `grade_candidate_archive_rows` + the `load_candidate_archive` projection **cannot emit** → the on-disk file is almost certainly the **untouched one-off 2024/25 backfill** (CLAUDE.md §13), not a dropped grade. → **ACTIVE P0 (ahead of Audit #1):** decide between **GRADER_RESOLUTION_GAP** (grader's exact full-name gamelog join `logs['Player']==player` fails against a short-form 2026 gamelog — the Nico Collins identity bug, but in the market-line grader) and **GRADER_OK_NOT_PUBLISHED** (grader resolves but its write never lands / backfill clobbers it). The skew-free decider is `diag_nfl_grading_input.py` **v2**: on-disk writer identity + last `all_prop_results` QC entry + a **read-only in-memory dry-run grade** of the current archive vs the current gamelog. |
| **Milestone integrity** | `qc_streak_integrity_milestone` ✅, `qc_nfl_milestone_streaks` ✅; `/tools/nfl-milestones`; explainer **wired** | — (complete) | ✅ local/QC; Nico Collins #1 prod-verified earlier |
| **Hot Hand integrity** | `qc_streak_integrity_hothand` ✅, `qc_nfl_heatmap_freshness` ✅ | **AUDIT #1**: emit full evidence (universe/counted/excluded/data-through/membership+render hash/fixtures/no prior-season leak/no identity suppression). Explainer not yet on Heat Map (row is a single `<a>` → needs **non-nested** disclosure restructure) | ✅ QC green; full audit + explainer pending |
| **NFL ATS integrity** | `qc_streak_integrity_ats` ✅, `qc_nfl_ats_wave` ✅ | **AUDIT #2**: on the **NFL ATS Wave** streak board (`build_nfl_ats_wave`) — `/tools/nfl-ats` is a cover-**rate** table, not a streak board (explainer does not belong there) | ✅ QC green; audit + explainer pending |
| **CFB ATS integrity** | `qc_cfb_ats_wave_admission` ✅ (authoritative `(GameID,TeamSide)`, FBS by conference) | **AUDIT #3**: FIRST audit the ACTUAL live CFB ATS Wave contract — only generalize the `ats` view-model for `kind∈{cover,total}` IF the existing in-scope live surface already emits both (do NOT create a new totals-streak product). If the live surface is cover-only, keep the explainer cover-only. Per-game opponents/weeks not on the row → carry where available, label rest `unavailable` unless the builder already emits them | ✅ QC green; audit + explainer pending |
| **Shared streak-explainer coverage** | `services/streak_explainer.py` + `templates/_streak_explainer.html` exist; `qc_streak_explainer` ✅. **Wired: nfl_milestones, riding_the_wave** | Heat Map, NFL ATS Wave, CFB ATS (after their audits) | ✅ wired surfaces local/QC |
| **Remaining client-rendered (JS) names/teams** | — | **Item 2**: King's Tickets, SGP Workbench, Daily Cards, Matchup Center, live Wave/Heat-Map tables print names as plain text in JS. Approach: **one** server-generated resolver payload (`{kind,sport,identity}→href\|null` via existing `player_url`/`team_url`) threaded into each client renderer; never build hrefs in JS. **Start SGP Workbench** (most self-contained) + QC, then replicate. Plus batch-6 JS boards (parlay/fantasy/green_light/data-boards) | N/A (not yet started) |
| **Production verification status** | Local compile + owner test-client (server-side gate bypass) + full QC suite green | Authed prod receipt + owner-session visual pass (desktop+375px); Item-5 prod grading-refresh investigation (SSM) | Owner-run; this session cannot reach authed prod/SSM |

## Standing constraints (held)
Feature/data gates OFF, `?view=classic` retained, `BK_NBA_STATS_ENABLED=0`, Decision Journal + King's
Tickets draft store disabled, no NBA.com/WNBA stats ingestion, no gate lifted. Names never cross-link;
unknown/ambiguous/gated → plain text; no nested anchors; sport-scoped resolution.

## Work order (separate reversible commits; shape audit outputs for later migration, but do NOT implement the constitutional Evidence Ledger during this P0)
**Gate before Audit #1 — RECONCILED, and it did NOT clear (Item 5 above):** the prod content receipt
showed the graded source is fresh-by-mtime but prior-season-only (zero 2026 rows), so the Wave stays
unavailable and the NFL prop-grading **input-starvation** is the **active P0**. Do NOT start Audit #1
(Hot Hand) until that P0 is isolated on prod with `diag_nfl_grading_input.py` and the upstream archiving
is understood — building an explainer on top of a known-broken grading lane is exactly what the gate
forbids. (Hot Hand reads the nflverse weekly parquet, a *different* source, so it is not itself blocked
by this data gap — but the gate is procedural: resolve the promoted P0 first.)
1. **Audits** (prove `Source → Canonical events → Identity resolution → Eligibility → Calculation →
   Membership → Ordering → Render` with the full evidence set): **Hot Hand → NFL ATS → CFB ATS.**
2. **Shared streak explainer** on those three (builder-emitted evidence; UI never recalculates membership
   or invents reasoning) — generalize the `ats` branch for `kind`, wire CFB ATS + NFL ATS Wave via the
   proven `<details>` pattern, restructure the Heat-Map row for a **non-nested** disclosure.
3. **Destinations + client conversions** — the already-scoped missing destinations (WNBA player batch,
   football_method_board, schedule team) and the JS resolver-payload surfaces (start SGP Workbench);
   preserve sport-scoping, plain-text for ambiguous/unknown, no nested anchors, row-click behavior, legal
   gates, and destination-fetch tests that assert the rendered entity.
4. Then the design-only **Decision Integrity Architecture Constitution** (returned for approval).

**Active P0 (promoted from Item 5) — ROOT CAUSE CONFIRMED on prod 2026-10-24 (`diag_nfl_grading_input.py`
v2, exit 3 = GRADER_OK_NOT_PUBLISHED):** a **shared-path write collision** between two independent prod
pipelines corrupts `data/tracking/NFL_AllPropResults.csv`.

- **Not input-starvation, not a resolver bug.** The archive is healthy (13,386 all-2026 NFL candidates);
  the gamelog reaches 2026 (2,090 players); the guard passes. The read-only **dry-run grade** of the
  current archive resolves **86 current-season (2026) rows** (Hit 43 / Miss 43) with the rest correctly
  *Pending* (future games). Every sampled "unresolved" player matches the gamelog **exactly** (`exact=True`,
  `shortform=False`) — so the earlier Nico-Collins short-form hypothesis is **ruled out**; those are
  future-week picks, not dropped rows.
- **The clobber.** `refresh_all_prop_results.py` (run_daily step "All prop results grading", ran 13:06:27,
  clean) grades the archive into `NFL_AllPropResults.csv`. ~55s later `build_nfl_historical_calibration.py`
  (whose `OUTPUT_PATH` **is** `NFL_AllPropResults.csv`, a plain `to_csv` replace) runs via
  `run_bk_edge_engine_pipeline.py` and overwrites it with 34,788 historical 2024/25 rows
  (`IsBackfill=True`, `Method='Historical Backfill'`, `ModelVersion='NFL_Backfill_v1'`, `SnapshotWrittenAt`
  13:07:22). Whichever pipeline runs last wins; the Edge-Engine backfill runs last → the published file has
  **zero** current-season rows → the Wave correctly fails closed.
- **Fix family (one reversible commit; AWAITING DIRECTION — a shared data-contract change):** give the
  historical calibration backfill its **own** file (e.g. `NFL_AllPropResults_Backfill.csv` /
  `NFL_HistoricalCalibration.csv`) so `refresh_all_prop_results.py` owns `NFL_AllPropResults.csv`
  exclusively. Repoint `build_nfl_historical_calibration.py:OUTPUT_PATH`, `normalize_result_metadata.py`'s
  NFL target, and every calibration consumer that currently reads the historical rows out of
  `NFL_AllPropResults.csv` (audit: `calibrate_nfl_model.py`, the calibration-note / drift-alert
  generators). The live streak + Heating-Up boards already want live-only, so they heal automatically.
  (Alternatives considered: reorder the pipelines, or merge-on-write keyed by `IsBackfill` — both leave two
  writers on one file and stay race-prone; single-writer-per-file is the durable fix.)
This precedes Audit #1.

**Out of scope / untouched:** NBA surface migration (owned by NBA Season Readiness); MLB/WNBA team pages
(product decision); the scheduled **NBA props** acceptance run.
