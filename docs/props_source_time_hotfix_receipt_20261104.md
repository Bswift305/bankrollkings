# Hotfix production receipt — NFL prop quote time = `SourceUpdatedAtUTC` (`17b5e69`, 2026-11-04)

**Status: DEPLOYED and ACCEPTED in production at exact `17b5e6979098096c10d38ed3a5d1c27e77c3610e`.**
The deploy was conditionally owner-authorized ("if every gate passes"). Every gate passed. No revert, purge,
regeneration or paid call.

## Cause

Defect found during `4afcab9` acceptance; see `docs/integrity_d4_production_receipt_20261104.md`.

- `fetch_player_props` writes `LastUpdated` as its own zone-less fetch time on the UTC box.
- The executable-quote contract added in `f642091` read that stamp as Eastern, putting every 13:00Z quote at 18:00Z.
- **Effect if left:**
  - blocked as `QUOTE_FROM_FUTURE` until ~17:45Z;
  - then executable until 24:00Z;
  - from 19:00Z, past the real 6h rule, with a false "updated 13:00 ET" label.

## Change — one commit on `4afcab9`, no rewrite (8 files, +385/−38)

- **Quote authority:**
  - `_quote_from_row` and the newest-row choice read `SourceUpdatedAtUTC` only, which must be present, parseable
    and timezone-aware.
  - Missing, blank or zone-less → no quote.
  - `LastUpdated` never authorizes.
- **Freshness** (`_quote_clock_status`):
  - zone-less source time → `MISSING_UPDATE_TIME`;
  - 0–5 min ahead → fresh with internal `CLOCK_SKEW_TOLERATED`, age clamped to 0;
  - more than 5 min ahead → `QUOTE_FROM_FUTURE`;
  - over 6h real age → `STALE_QUOTE`.
- **Display:** explicit `America/New_York`, DST-aware, independent of the process zone. No source time →
  "Update time not recorded".
- **SGP Workbench:** prop legs carry `source_updated_utc` for authority and current terms; display is ET "provider
  source time".
- **Customer-facing NFL-prop times now from `SourceUpdatedAtUTC`:**
  - Player Check (per book plus "latest quote updated");
  - Best Lines offer times;
  - the props-feed "last updated" panel (`get_props_refresh_meta`) for any feed with that column.
- **Reviewed and left unchanged:** internal derivative metadata, feed validation and NBA market-reference sorting.
  None of them render or authorize anything.
- **Caches (no purge):**
  - floor-board disk key `q1k2` → `q1k2s3`;
  - NFL dashboard bundle version `+ ('srcutc1',)`.
- **QC:**
  - new `qc_props_quote_source_time.py`, 158 checks under UTC, New York and Los Angeles process zones;
  - it fails on `4afcab9` with the production symptoms;
  - fixtures updated in `qc_unpriced_line_legs`, `qc_sgp_workbench`, `qc_ticket_submission_atomic` and
    `qc_ticket_quote_change`;
  - registered additively in `run_all_scorecards.py`.

## Gates

| Gate | Result |
|---|---|
| Offline (Windows, `qc_offline.py`) | 46/46 rc 0; `qc_odds_feed` exit 3; 5 blocked connections, all in `unpriced_line_legs` self-tests |
| Linux, exact SHA | AWS CloudShell, fresh anonymous clone, work dir `/tmp/hotgate`. Script sha256 `3bbd9dd1…853d8fe3b03`; log sha256 `0819e320…a73f97307f1df86b`; 14:04:55Z → 14:08:36Z |
| Linux identity and scope | `IDENTITY_OK`; `ORIGIN_MASTER_IS_BASE_OK` (`4afcab9`); `BASE_ANCESTOR_OK`; 1 commit; `SCOPE_8_OK`; the 8 D1 files identical to `6bdb73f`; `run_all_scorecards` `removed_lines=0` |
| Linux tree | 0 / 0 / 0 entries before, after install and after QCs; HEAD unchanged |
| Linux isolation | `unshare --net`, loopback up, no routes: `NO_NETWORK_CONFIRMED gaierror`, `curl_http=000`, curl rc 6 |
| Linux results | `py_compile` 46 files rc 0. **`QC_TOTAL=46 QC_FAIL=0`**, incl. `props_quote_source_time` 158/158, `unpriced_line_legs` 174/174, `ticket_quote_change` 114/114, `ticket_submission_atomic` 68/68, `parlay_save_exact` 117/117, `ticket_kickoff_gate` 119/119, `sgp_kickoff_gate` 53/53, `matchup_center_cache_version` 16/16, D1 275/275. `qc_odds_feed` rc 3 |

## Deploy

- **Pre-push recheck 14:09:31Z** (SSM `cf6f8d22-7b96-4f11-8dc8-90b4db1f1507`):
  - HEAD `4afcab9`, `tracked_dirty=0`;
  - no active `bk-*` (`bk-nfl-postweek`'s 14:00 tick had finished);
  - capture 0;
  - health 200.
- **Push 14:09:56Z:** fast-forward `4afcab9..17b5e69`, no force.

## Post-deploy (SSM `5bd2569b-…` and the preceding run)

- **Version and restart:** HEAD exact `17b5e69`, tracked tree clean. Restart at 14:11:27Z, `NRestarts=0`, workers
  booted.
- **Health:**
  - 0 error lines;
  - 0 earlyoom kills;
  - health 200;
  - 4967 MB available.
- **Capture:** OFF in `.env`, the unit, MainPID and workers.
- **Cache:**
  - `nfl_floor_board_q1k2s3_{20,24,60,90}_*.pkl` written 14:11–14:15Z;
  - old `q1k2` (13:37/13:39) and pre-`q1k2` files left untouched and unread;
  - `nfl_dashboard_runtime.pkl` rebuilt 14:14Z.

## Signed-in production acceptance (14:12–14:20Z)

| Check | Result |
|---|---|
| Today's Cards | 3 cards built from real single-book quotes; 0 "quote from future"; 0 `-110`; leg times "updated 2026-11-04 07:59/08:00 ET" (provider 12:59:40Z–13:00:37Z), never 13:00 ET |
| Server ticket gate (`POST /tools/daily-card.png`) | exact terms → 200 PNG; worse price and **better** price → 409 `PRICE_CHANGED`; line +1 → 409 `LINE_CHANGED`; book → 409 `BOOK_CHANGED`; terms missing → 409 `QUOTE_UNCONFIRMED`; selection Over→Under and a different event → 409 `QUOTE_MISMATCH`; formatting-only (`-114.0`, `5.50`, upper-case book) → 200; 1 leg → 422 `wrong_leg_count` (minimum message); 9 legs → 422 `wrong_leg_count` ("nothing was trimmed"). Every rejection was JSON with current safe terms and no image |
| Editor confirm-and-resubmit (real UI) | 409 → leg marked, "You confirmed: FanDuel · 5.5 · -120 → Now: FanDuel · 5.5 · -114 (updated 2026-11-04 07:59 ET)", **Confirm current terms**, no download. After confirming, resubmission → 200 PNG, one download (intercepted; no file saved) |
| `/parlay/save` | 0 picks → 422 `TOO_FEW_PICKS`; 21 → 422 `TOO_MANY_PICKS`; an invalid pick → 422 `INVALID_PICKS` `[{index:1, INVALID_DIRECTION}]`; duplicate → 422 `DUPLICATE_PICK`; all `saved:false`; `/parlay/tickets` byte-identical before and after (54,992 chars). **No accepted save was made in production**, so no test record was left in the owner's account. Exact storage of 1–20 accepted picks is covered by `qc_parlay_save_exact` 117/117 |
| Player Check (Dak Prescott) | "latest quote updated 2026-11-04 07:59 ET"; per-book times 07:59 ET |
| Best Lines (NFL) | offer times 07:59/08:00 ET; "Update time not recorded" where absent; `-110`s are real DraftKings offers with their provider time |
| NFL props page | "REFRESHED 2026-11-04 08:00 ET · 1619 live prop rows" |
| SGP Workbench (DAL@IND) | legs "2026-11-04 07:59 ET (provider source time)"; its `-110` is a real DraftKings price |
| King's Tickets, Menu, Green Light, NFL hub, Featured, Floor, NFL totals, Matchup Center | 200; 0 "quote from future"; 0 started-leg text; 0 invented `-110`; Matchup Center shows no substituted DraftKings attribution |
| D1 weather | "Weather unavailable / No forecast available" shown honestly; 0 "0 mph"; 0 calm/indoor/dome |
| Browser health | every page-load resource 200; no page-script error. Console 409×8, 422×6 and 404×6 are exactly my probe requests and mistyped URLs. One 401 predates the hotfix probes and is unexplained; noted, not a page fault |

## Known, non-blocking (owner-classified)

- **Editor wording.**
  - The UI caps building at 5 legs (King's Tickets shows "2–5"); the server contract is 2–8.
  - The tooltip "A ticket holds at most 5 legs" is inaccurate.
  - Future copy: `This editor builds up to 5 legs`, bundled with the next ticket-editor/UI release.

## Standing (not this deployment)

`bk-daily` ended 13:29:04Z with exit 1 (`Result=exit-code`). This is the standing daily failure since 2026-10-27,
recorded before either push.

## Follow-ups (not done here)

- **Upstream root:** `fetch_player_props` still writes `LastUpdated` as a zone-less fetch time in the process zone.
  It no longer authorizes or displays anything for NFL props; correct it in a future fetcher change.
- **Other sports:** feeds without a `SourceUpdatedAtUTC` column keep their legacy `last updated` label.
