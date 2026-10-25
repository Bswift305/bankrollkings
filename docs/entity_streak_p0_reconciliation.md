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
- **Fix — IMPLEMENTED (single-writer-per-file, authorized 2026-10-24).** See the ownership contract and
  reader/writer inventory below. The live streak + Heating-Up boards already want live-only, so they heal
  automatically once the backfill stops clobbering the live file. (Alternatives rejected: reorder the
  pipelines, or merge-on-write keyed by `IsBackfill` — both leave two writers on one file and stay
  race-prone.)
This precedes Audit #1.

**Out of scope / untouched:** NBA surface migration (owned by NBA Season Readiness); MLB/WNBA team pages
(product decision); the scheduled **NBA props** acceptance run.

## Item-5 fix: NFL result-artifact ownership contract (implemented)

**Contract** (`services/nfl_result_artifacts.py` — single source of paths, union loader, ownership
registry):

| Authoritative artifact | Sole writer | Population |
|---|---|---|
| `NFL_AllPropResults.csv` | `refresh_all_prop_results` (`app.replace_all_prop_results_snapshot_for_sport`) | LIVE / current-season grades |
| `NFL_AllPropResults_Backfill.csv` | `build_nfl_historical_calibration` | historical calibration only |

No job read-modify-writes another job's file. Consumers needing both populations use
`load_combined()` (an explicitly owned **read-time union**, backfill + live, live wins dedup).

**Reader/writer inventory (consumers reclassified):**

| Consumer | Before | After |
|---|---|---|
| Wave `build_nfl_prop_streaks`, Heating-Up `build_nfl_prop_hot_start`, `build_floor_play_index` | read raw (polluted by backfill) | read raw = **live-only** (unchanged code; heals) |
| `calculate_nfl_edge_score` (→ `NFL_AllPropResults_Scored.csv`) | read raw | **`load_combined`** (live + backfill) + atomic write |
| `calibrate_nfl_model` → `services/model_calibration.run_calibration` | read raw via `results_path` | passes **`results_frame=load_combined(...)`** (new optional field; MLB/WNBA/NBA/CFB untouched) |
| `build_nfl_hit_profile_linemeta` | read raw | **`load_combined`** |
| `build_nfl_historical_calibration` (writer) | wrote `NFL_AllPropResults.csv` (replace) | writes **`NFL_AllPropResults_Backfill.csv`** atomically |
| `normalize_result_metadata` (NFL raw target) | stamped `NFL_AllPropResults.csv` | stamps **`NFL_AllPropResults_Backfill.csv`** atomically |
| freshness/review (`build_phase2_dashboard_context`, `_build_live_promotion_signal_context`, `candidate_review`, `missed_opportunities`, `qc_odds_feed`) | metadata/mtime | unchanged (correctly track the live file) |

**Safeguards:** atomic publication (`write_atomic` = tmp + `os.replace`) for both artifacts and the
normalize/edge-score rewrites; Edge Engine can no longer overwrite the live artifact and the daily grader
can no longer overwrite the historical artifact (distinct paths), so **job order no longer affects either
result**; a failed write preserves each artifact's prior valid file; live-board cache keys already key on
`NFL_AllPropResults.csv` mtime (the live file) — correct without change.

**QCs (both green locally):** `qc_writer_ownership.py` (fails if two pipelines target one authoritative
path, or if the backfill writer / normalize target drifts back to the live file) and
`qc_nfl_result_artifact_isolation.py` (runs the real live + backfill writers against temp paths in both
orders; proves population isolation, independent hashes, `load_combined` union, and atomic
failure-preservation).

**Clobber fix VERIFIED on prod 2026-10-24 (HEAD `dc9bdb6`):** both contract QCs exit 0; the backfill now
writes `NFL_AllPropResults_Backfill.csv`; and the clobber-proof (re-run the Edge Engine, compare the live
file sha) shows the live artifact **byte-unchanged** — the Edge Engine can no longer touch it.

**86-vs-16,753 RECONCILED — a second defect (#2) is confirmed: the candidate archive is transient
(no retention of completed weeks), so the live grader cannot build a season's graded record.**
`diag_nfl_grading_completeness.py` on prod: the gamelog reaches 2026-10-16 (Week 6 complete), yet the
archive's current-season NFL candidates are **1,072 and ALL future** (`completed(<= data-through)=0`),
SnapshotDate spread only Oct 16–24 (9 days), 990/1072 duplicates; dry-run **0 resolved, 0
completed-but-unresolved** (correct — nothing to grade). Decisively, between the 13:25 input probe (13,386
NFL rows, 86 resolvable) and the 20:00 completeness probe (~1,072 current-season, 0 resolvable) the archive
**shrank and discarded the Week-6 resolvable candidates** — so it is rebuilt/pruned to the rolling
upcoming slate. `archive_method_candidates` (app.py:11890-11910) appends + dedupes on a key that *includes*
`SnapshotDate` with **no** date prune, so the pruning is elsewhere (a rebuild/reset of the archive file, or
a regeneration under `BK_RUNTIME_DIR`), not in that merge. Because `refresh_all_prop_results` *rebuilds*
`NFL_AllPropResults.csv` from this transient archive by replace, no season history can accumulate. **The
16,753-through-Week-6 figure therefore cannot have come from this live lane** — it was a different grain
(the historical backfill, or a persistent graded store that no longer feeds the live record).

**Defect #2 ROOT-CAUSE RESOLVED (read-only forensics, prod `diag_nfl_graded_lineage.py`, HEAD `8efd9a9`):
a source-selection mismatch, not a prune.** The Wave (`build_nfl_prop_streaks`) + Heating-Up
(`build_nfl_prop_hot_start`) read **Lane 1** (`NFL_AllPropResults.csv`, the transient candidate-pool grade —
currently backfill residue, 34,788 rows 2024/25 only), while the **persistent, run_daily-designated streak
record is Lane 2**: `capture_nfl_prop_lines` → append-only `NFL_PropLines_Archive.csv` (10,980 rows, all
2026, Sep 30–Oct 24) → `grade_nfl_prop_lines` → `NFL_PropLines_Graded.csv` (**10,980 rows, all 2026, Weeks
3–7** [3:876 4:2695 5:2915 6:2670 7:1746], Result UNDER 4960 / OVER 4094 / PENDING 1902 / PUSH 24, ~9,078
graded). No code prunes the archive (both `replace_candidate_archive` callers + `archive_daily_candidates`
append+dedupe only) — Lane 1's thinness is inherent to a current-slate pool. **Earlier "shrank 13,386→1,072"
claim retracted** (apples-to-oranges: total-by-SnapshotDate vs current-season-by-GameDay).

**16,753 lineage:** no current store holds 16,753 rows of 2026-through-Week-6. The persistent 2026 graded
record is Lane 2 at **10,980 (Wks 3–7)**; `NFL_Props_History.csv` is 17,394 but **2024/25** (the backfill
input, not 2026). So **no persistent population was lost** — 16,753 was most plausibly a prior-day count of
a time-varying store (the rolling candidate pool, or a transient `NFL_AllPropResults` state pre-clobber).
Not forced to a match it does not have.

**Your 4-role durable architecture already exists:** (1) replaceable current-slate pool = candidate
archive; (2) append-only observation history = `NFL_PropLines_Archive.csv`; (3) grader-owned persistent
graded history = `NFL_PropLines_Graded.csv`; (4) separate historical calibration backfill =
`NFL_AllPropResults_Backfill.csv`. No new store needed.

**Recommended correction (one reversible commit, AWAITING AUTHORIZATION):** repoint `build_nfl_prop_streaks`
+ `build_nfl_prop_hot_start` to `NFL_PropLines_Graded.csv` via a thin schema adapter (`Result` →
direction/outcome, `Actual` → ResultValue; one canonical observation per player·stat·week; drop
PENDING/PUSH from streaks), **keeping** the freshness/through-week gates + fail-closed. Lane 1 stays for the
current-slate candidate boards + the Edge-Engine Scored chain. Weeks 1–2 are genuinely absent (capture
began Sep 30) and not recoverable from this lane — board discloses "graded from Week 3". Recovery needs no
provider/network. Rollback = revert the source constant. **QCs before any write:** real-schema streak
integration (Result/Actual map, week dedup, PENDING excluded); through-week freshness gate off Lane 2;
fail-closed when Lane 2 absent/empty.

**Item 5 remains OPEN** pending that repoint. Close criteria: the streak boards serve from the **persistent
graded record** (Lane 2), the historical/backfill file is separate (done), and the Edge Engine cannot
clobber the live artifact (done). Audit #1 stays held.
