# RCA — recurring overall `bk-daily` failure (2026-10-25 → 2026-11-01)

Status: **diagnosis only (read-only). No fix applied, nothing pushed to master.** Separate from the RC 2D1
producer corrections (`63060a9`), whose acceptance keys on four specific steps and is being validated by the
one-shot scheduled job on 2026-11-02 (receipt pending). This document is about why the *job as a whole* is red.

Evidence (SSM, read-only, from CloudShell): `1c8f13bc` (`diag_refresh_incident.py --history 8`, no `--probe`),
`ecf34191` (per-day FAIL labels + context), `rca3`/`rca4` (scorecard log). Log files on prod:
`logs/daily_operator_2026MMDD_130000.log`, `logs/all_scorecards_20261101_131247.log`.

## 1. Run history

| Run (13:00 UTC) | Steps | PASS | FAIL | Overall exit |
|---|---|---|---|---|
| 10-25 | 187 | 178 | 7 | (in window; first degraded run per diag) |
| 10-26 | 188 | 176 | 10 | — |
| 10-27 | 190 | 176 | 12 | 1 (`systemd`: exit-code) |
| 10-28 | 190 | 176 | 12 | 1 |
| 10-29 | 162 | 152 | 8 | 1 |
| 10-30 | 172 | 163 | 7 | 1 |
| 10-31 | 172 | 163 | 7 | 1 |
| 11-01 | 172 | 159 | 11 | 1 |

`diag`: **no fully-successful run in the window**; first degraded run 10-25. Prod runs `run_daily.py
--continue-on-error`, so FAILs are **independent** — there is no abort cascade; every step after a FAIL still
ran. (FAIL counts include nested sub-step `[FAIL]` lines.) The 10-27/10-28 extra failures were only partially
listed (screen-limited); the persistent set below is complete.

## 2. Failures, classified

| # | Failing step (nested cause) | Days | Class | Root cause | Artifact impact |
|---|---|---|---|---|---|
| 1 | **CFB data refresh** | every day since 10-24 | provider + configuration | CFBD monthly quota 429 on 2026-10-24 → `refresh_cfb_data.py` persisted `cfbd_quota_state.json` (`exhausted`). By design it blocks until `BK_CFBD_RESET_AT` passes or an operator override (`BK_CFBD_FORCE=1` / clear the file). **No reset time was configured, so it blocks forever.** CFBD quotas reset monthly; it is now 11-01. | CFB artifacts frozen at last-known-good since 10-24 (fail-closed, not corrupted) — **CFB surfaces are 8 days stale.** |
| 2 | **MLB daily refresh** (`game_lines` exit 1: "empty/too-small current slice: 0 rows") | every day | configuration (season gate) | Off-season: Odds API returns 0 MLB rows. The strong validator correctly refuses to publish an empty slice. MLB still runs because `bk-daily.service` passes `--sports nba,wnba,mlb` and `season_utils.active_sports()` calls a sport active when its props file **has any row** — stale rows never expire. Prod: `active_sports = {MLB, WNBA, NFL, NCAAF, NBA}`. | None (last-known-good preserved; MLB is out of season). |
| 3 | **WNBA game lines / WNBA player props** (same validator message) | 11-01 | configuration (season gate) | Same as #2 for WNBA (season over). | None. |
| 4 | **NBA daily refresh** (`board_qc` exit 1) | every day | code (QC policy) | `board_qc` raises HIGH on "Playoff player logs are missing" and "Playoff results are missing" in the **regular season**; prod has never had postseason files. A QC demanding data that cannot exist yet. (Plus a MEDIUM: 530 resolved prop rows lack team mapping — not failing.) | QC only. To confirm: whether `refresh_nba_daily` stops later NBA sub-steps after `board_qc` fails. |
| 5 | **NFL Heat-Map Freshness QC** → **All scorecards** (Decision NO-GO) | since 10-25 | code (QC drift) | Commit `8a3ff74` (2026-10-25, "appearance-truthful label") changed `weeks_label` to `Appearances: Wks 1–4`; `qc_nfl_heatmap_freshness.py:127` still expects `Wks 1–4`. Product change is intended; the QC was not updated. Matches the 10-25 onset. | None (QC only). |
| 6 | **Odds feed health (post-refresh)** (scorecard) | recurring | downstream of #2/#3 (to confirm) | Per-family freshness reads MLB/WNBA lines+props as STALE (89–96 h) while they are still "active". Expected to clear when #2/#3 are fixed — must be re-verified, not assumed. | None. |
| 7 | **Football line movement** (`ncaaf_game_lines` exit 1: "implausible row-count collapse: 68 rows < 50% of prior 164") | 11-01 (weekly pattern) | validation policy | Sunday after the Saturday CFB slate: the forward window legitimately shrinks. The absolute collapse test compares against a stale, larger prior — the exact failure the NBA slate-aware validator was built to fix (incident 2026-10-24); NCAAF game lines never got it. | NCAAF lines held at last-known-good (AGING ~24 h) until a later run passes. **Will recur every Sunday.** |
| 8 | 10-28/10-29 one-offs: Football player props; "NBA/NCAAF/NFL props STALE while lines FRESH" | 10-28, 10-29 | provider / transient | Not present after 10-29 (consistent with NO_MARKETS_POSTED windows). | None observed now. |

**Not related to RC 2D1:** none of #1–#8 is in `Football player props`, `NFL board grade (resolve)`,
`NFL weekly player stats` or `NFL featured results`, which all PASSed on 11-01.

## 3. Narrowest reversible corrections (proposal — each needs review; none applied)

Order = cheapest/safest first. All code fixes land as separate commits **after** the 11-02 receipt is read
(any master push before 12:30 UTC 11-02 voids the RC validation's exact-HEAD precondition).

| Fix | Scope | Test | Rollback | Acceptance |
|---|---|---|---|---|
| F1 heat-map QC | `qc_nfl_heatmap_freshness.py:127-128` expect `Appearances: Wks 1–4` (fix the message's hyphen too) | QC passes locally; mutation: old label fails | `git revert` | Scorecard section PASS on next run |
| F2 season gate | `season_utils.active_sports()`: a sport is active only if its props file has rows **and** its schedule has events in the next 7 days (Eastern), reusing the logic `report_feed_availability.py` already has; never weaken the empty-slice validator | `qc_daily_operator_season_gate.py` + new cases (stale rows + no events ⇒ inactive; events ⇒ active) | `git revert` | MLB/WNBA steps SKIP (visible), no FAIL; NBA/NFL/NCAAF unchanged |
| F3 NBA playoff QC | gate the two playoff-freshness HIGH checks to the postseason phase (existing phase helper — see `qc_nba_postseason_phase.py`) | regular-season fixture ⇒ no HIGH; postseason fixture ⇒ HIGH still fires | `git revert` | `board_qc` PASS in regular season |
| F4 CFBD latch | **operator/config, not code**: one secret-safe probe (`diag_refresh_incident.py --probe`) to see whether CFBD has reset; if yes, clear the latch for one run (`BK_CFBD_FORCE=1` or remove `cfbd_quota_state.json`) and set `BK_CFBD_RESET_AT` going forward | probe 200 + CFB refresh PASS | latch re-arms itself on the next 429 | CFB artifacts fresh; CFB refresh PASS |
| F5 NCAAF slate-aware | extend the NBA slate-aware validation (independent manifest denominator) to NCAAF (and NFL) game lines | `qc_slate_validation.py` + NCAAF rollover fixture (68 vs 164 with matching manifest ⇒ publish) | `git revert` | Sunday run publishes NCAAF lines |
| F6 Odds feed health | none expected — re-verify after F2 | — | — | section PASS |

**Program acceptance for "production health green":** one complete scheduled `bk-daily` run with
`Result=success`, `ExecMainStatus=0`, zero `[FAIL]` (top-level and nested), scorecards GO-or-explained, and
artifact freshness within contract — recorded as a receipt, not inferred.
