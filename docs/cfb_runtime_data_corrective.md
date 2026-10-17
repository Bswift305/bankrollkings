# CFB Runtime-Data / Deploy Corrective — Inventory + Plan (design; approval before implementation)

**Status: STEP 1 (inventory) complete + staged plan for Steps 2–6. No files moved, no deploy-script
change yet — returns for approval.** Root cause (confirmed on prod, 2026-10-16): `cfb_line_moves.json`
is git-tracked; `bk-auto-deploy.sh:49` runs `git checkout -- .` before every pull, reverting prod's
freshly-refreshed copy to the committed **Sept-27** snapshot (`b413ac5`). The CFB ATS wave then reads a
3-week-stale manifest and correctly fails closed. Date: 2026-10-16.

## Step 1 — Inventory of tracked `data/scenarios/*.json` (36 files)
Axis that matters: **written by the prod daily-refresh lane** (clobbered by the deploy revert → must
move) vs **offline research/seed export** (intentionally committed → keep tracked).

### A. RUNTIME-AUTHORITATIVE — CFB daily lane (`refresh_cfb_data.py`) — 9 (+1 to confirm)
| File | Writer (daily lane) | Runtime consumers |
|---|---|---|
| `cfb_line_moves.json` | `fetch_cfb_line_moves.py` | `app._cfb_line_move`, `build_cfb_wave_context`, `build_cfb_board_context`, `report_cfb_wave_sync.py` |
| `cfb_2026_results.json` | `build_cfb_2026_results.py` | `cfb_current_form`, `build_cfb_wave_context`, board |
| `cfb_2026_ats.json` | `build_cfb_2026_ats.py` | wave (optional season context) |
| `cfb_ats_streaks.json` | `build_cfb_ats_streaks.py` | ATS Streaks board |
| `cfb_rankings.json` | `build_cfb_rankings.py` | wave / matchup |
| `cfb_coaches_2026.json` | `build_cfb_coaches.py` | coach/favorite trend |
| `cfb_key_numbers.json` | `build_cfb_key_numbers.py` | Key Numbers board |
| `cfb_pace.json` | `build_cfb_pace.py` | Totals/Pace board |
| `cfb_weather.json` | `fetch_cfb_weather.py` | matchup weather context |
| `cfb_ats_streak_forward_rates.json` | *(confirm: `build_cfb_ats_streaks.py`?)* | streak context |

### B. RUNTIME-AUTHORITATIVE — NFL daily lane (`run_daily.py`) — ~10 (same class; same bug)
`nfl_scores.json`, `nfl_2026_form.json`, `nfl_2026_defense.json`, `nfl_channel_dependency.json`,
`nfl_coaching.json`, `nfl_concentration.json`, `nfl_officiating.json`, `nfl_qb_profiles.json`,
`nfl_regression.json`, `nfl_role_stability.json`. *(Out of the immediate CFB scope, but identical
risk — the runtime-dir resolver + deploy fix below cover them too; migrate after CFB.)*

### C. SEED / RESEARCH — offline `research/.../build_*_export.py` — keep tracked — 16
`bk_power_players`, `cfb_ats`, `cfb_ats_games`, `cfb_bigfav_records`, `cfb_favorites`, `cfb_matchup`,
`cfb_power`¹, `cfb_regression`, `cfb_situational`, `cfb_talent`, `cfb_team_log`, `cfb_totals`,
`mlb_nrfi`, `mlb_situational`, `nfl_scenarios`, `nfl_usage_by_state`². These are built by one-off research
exporters, **not** by `refresh_cfb_data.py`/`run_daily.py`, and are the intentional committed artifacts.
¹ `cfb_power.json` also has `cfb_current_form.py` in its writer set — **confirm** it is not rewritten
during a live request (a runtime write to a tracked file would be the same bug). ² `nfl_usage_by_state`
has a top-level `build_nfl_usage_by_state.py` — **confirm** whether `run_daily` invokes it.

## Step 2–4 — Move runtime outputs outside the checkout (recommended design)
- **Runtime dir via env:** add `BK_RUNTIME_DIR` (set in `/opt/bankrollkings/.env` to a path **outside**
  the repo, e.g. `/opt/bankrollkings-runtime/scenarios`). A single resolver
  `runtime_scenarios_path(name)` returns `$BK_RUNTIME_DIR/name` when set, else the repo
  `data/scenarios/name` (so **local dev is unchanged** — it never runs bk-deploy, so nothing clobbers it).
- **Read precedence (seed/bootstrap, Step 3):** the resolver reads the **runtime copy if present**, else
  falls back to the **committed seed** in `data/scenarios/` (read-only). Fresh host → renders the seed
  until the first refresh writes the runtime copy; for a pure live feed like `cfb_line_moves.json` the
  wave's lineage/freshness check simply keeps it **fail-closed** until the refresh runs (consistent with
  the NFL approach — honest, not a stale board).
- **Writers:** the daily-lane writers write to `runtime_scenarios_path(...)` (the runtime dir on prod).
- **Consumers:** `build_cfb_wave_context`, `build_cfb_board_context`, `app._cfb_line_move`,
  `report_cfb_wave_sync.py`, `cfb_current_form`, the ATS Streaks/Key-Numbers/Pace/matchup readers all go
  through the resolver. **Migrate `cfb_line_moves.json` first** (the active blocker), then the other CFB
  files, then NFL — each a small reversible commit.
- **Tracking:** once a file's runtime copy is authoritative, keep the committed copy only as a **seed**
  (or `git rm --cached` + add a bootstrap exporter) so the deploy revert can't un-fresh prod. Decide
  per file; `cfb_line_moves` can drop its committed copy (fail-closed is the correct fresh-host state).

## Step 5 — Make the deploy stop DELETING uncommitted tracked changes (sensitive)
Replace the blanket `git checkout -- .` (bk-auto-deploy.sh:49). Two-stage, **sequenced after** the
runtime move so the tree is already clean of generated churn:
- **New behavior:** if the tree has unexpected dirty **tracked** files, **do not delete them** — log
  `git status --porcelain` and **hold the deploy** (exit 1, service stays on current code), so a genuine
  uncommitted change on the box is surfaced, never silently discarded.
- Runtime outputs no longer live in the checkout, so the normal case is a **clean** tree and the pull
  proceeds. Untracked regenerable data under gitignored dirs is unaffected.
- **Install note:** the live copy is `/usr/local/bin/bk-auto-deploy.sh` (outside the repo); reinstall via
  SSM after editing `ops/bk-auto-deploy.sh` — it is **not** auto-updated by a pull (deliberately).

## Step 6 — Verify the daily refresh independently
Confirm `refresh_cfb_data.py` actually runs on prod (its timer/cron) and writes the runtime copies —
git-clean alone never proved the refresh ran, only that the revert won. Check the CFB refresh unit's
last run + exit, and that `BK_RUNTIME_DIR/cfb_line_moves.json` advances.

## Step 7 — Re-run `report_cfb_wave_sync.py`; close CFB only at `synchronized: True`
With `missing decisions: 0`, `conflicts: 0`, no lineage problem, and a current `manifest updated`.

## Rollback
Each step is a separate reversible commit; unset `BK_RUNTIME_DIR` to revert consumers to the committed
`data/scenarios/` copies; restore the prior `bk-auto-deploy.sh` from git + reinstall. No data loss (the
runtime dir and the committed seeds are independent).

## Implementation status (approved; built)
- **Classification finalized (exact 9):** `cfb_line_moves`, `cfb_2026_results`, `cfb_2026_ats`,
  `cfb_ats_streaks`, `cfb_rankings`, `cfb_coaches_2026`, `cfb_key_numbers`, `cfb_pace`, `cfb_weather`.
  Resolved as NOT runtime (stay tracked seeds/research): `cfb_ats_streak_forward_rates` (offline
  backtest), `cfb_power` (read-only in cfb_current_form; written only by the offline ratings export),
  `nfl_usage_by_state` (NFL, offline). NFL daily-lane files are a SEPARATE later migration.
- **Resolver:** `bk_runtime.py` — `BK_RUNTIME_DIR` (prod) / gitignored `.runtime/generated/` (local);
  runtime copy wins; a live CFB file with no runtime copy returns a non-existent path → consumer fails
  closed (never a stale seed); atomic `publish_json`.
- **Writers (9) → `bk_runtime.publish_json` (atomic).** **Readers → `bk_runtime.scenario_read_path`**
  (`app.py`, `cfb_current_form`, `cfb_coach_trends`, `report_cfb_wave_sync`). `build_nfl_team_form` only
  names the file in a docstring — untouched.
- **Deploy hardening:** `bk-auto-deploy.sh` no longer runs `git checkout -- .`; it HOLDS the deploy and
  prints offending paths if any TRACKED file is modified (untracked excluded), deleting nothing.
- **Tests:** `qc_cfb_runtime_data.py` (precedence, live fail-closed, atomic preserve-prior, deploy
  dirty-guard, fresh-checkout safe) + updated `qc_cfb_ats_wave_admission`/`qc_cfb_wave_wording`.

## Safe production rollout (SSM; in this order)
1. **Deploy the migration commit** (resolver + writers + readers). Prod now writes runtime outputs; with
   `BK_RUNTIME_DIR` unset they go to the gitignored in-repo `.runtime/generated/` (already deploy-safe),
   but set it outside the checkout for cleanliness:
   - add `BK_RUNTIME_DIR=/opt/bankrollkings-runtime` to `/opt/bankrollkings/.env`;
   - `sudo -u ubuntu mkdir -p /opt/bankrollkings-runtime/scenarios` (owned by `ubuntu`);
   - `sudo systemctl restart bankrollkings`.
2. **Regenerate CFB outputs into the runtime dir + verify:** `sudo -u ubuntu … python refresh_cfb_data.py`
   then confirm `/opt/bankrollkings-runtime/scenarios/cfb_line_moves.json` has a current `updated`; run
   `report_cfb_wave_sync.py`.
3. **Deploy the untrack commit** (git rm --cached + ignore the exact 9) — lands under the OLD deploy
   script, which cleans the now-unwritten tracked copies and pulls the removal cleanly; runtime copies
   already exist, so no gap.
4. **Reinstall the hardened deploy script — BLOCKED until the NFL scenario migration.**
   `sudo install -m 755 ops/bk-auto-deploy.sh /usr/local/bin/bk-auto-deploy.sh` **must NOT run yet.** The
   hardened script holds on any dirty tracked file, but the ~10 NFL daily-lane `data/scenarios/nfl_*.json`
   are still tracked and still written by the prod NFL refresh, so the tree is NOT clean. Reinstalling now
   would hold every deploy. Keep the old `git checkout -- .` script (now CFB-safe — CFB data lives outside
   the checkout) until the separate NFL runtime migration untracks the NFL files; reinstall then.
5. **Verify the daily refresh timer** runs independently, and **re-run `report_cfb_wave_sync.py`** — close
   CFB only at `synchronized: True`.

The untrack commit (step 3) is held until step 2's runtime copies are verified present (so pulling a
removal of locally-modified tracked files can't fail and prod never loses fresh data).

## Post-corrective: the CFB "missing decisions" gap (separate diagnosis, read-only)
After the runtime fix the manifest is fresh, but the wave still fail-closes on ~67 "missing decisions":
completed, line-bearing FBS-team games in the manifest that are ungraded. Read-only code findings:
- **Same endpoint, same universe (code fact).** Both feeds call `GET /lines?year=&seasonType=regular`
  (one call, no pagination). The manifest (`fetch_cfb_line_moves.py`) keeps a game by the **median spread
  across all books**; the history (`fetch_cfbd_game_lines_history.py`) keeps `_first_line` = **`lines[0]`
  only**. `normalize_ncaaf_team_name` does **not** blank unknown (FCS) teams (returns the cleaned name).
- **No root cause asserted yet.** The earlier "the loss is purely normalization" claim is **RETRACTED as
  an unconfirmed hypothesis** — `lines[0]`-vs-median and a name/date join divergence are *candidates*, but
  which stage actually drops each game is only established by the four-stage reconciliation below.
- **Reconciliation tool (read-only, no pipeline change):** `diagnose_cfb_line_coverage.py` loads **all
  four artifacts** — runtime manifest (with `updated`/season/source-path provenance), fresh raw `/lines`,
  stored `NCAAF_GameLines_History.csv`, graded `NCAAF_GameLineResults.csv` — and walks each expected
  manifest decision through **manifest → raw → normalized replay → stored history → graded**, charging it
  to the FIRST failing stage. Mutually-exclusive buckets: `graded_ok`, `absent_from_current_raw`,
  `absent_from_runtime_manifest` (cross-check), `dropped_in_normalize:name_blanked`,
  `first_book_no_spread`, `dropped_in_normalize:other`, `in_replay_absent_from_stored_history`,
  `in_history_but_ungraded`, `ambiguous_legacy_join`. Anchored on the CFBD game `id`; since the manifest/
  history/results carry no id, the join is a disclosed legacy bridge `(season, week, resolved home,
  resolved away)` + kickoff date, and **any ambiguous join makes the tool exit nonzero**. Missing/
  unreadable inputs also exit nonzero. Targeted checks: FBS-FCS, the named FBS-FBS games, week-0,
  neutral-site, date-vs-numbered-week drift, pagination/response-size.
- **Recommended correction (not applied):** add a `GameID` column to future `NCAAF_GameLines_History` +
  `NCAAF_GameLineResults` rows so this reconciles on the stable id, not a legacy name/date join.
- **Governance (provisional, Darrel):** any completed game with a valid market line belongs in the FBS
  team's ATS record, FCS opponent included — do NOT narrow the expected universe to obtain sync; exclude
  only no-line / cancelled / ungradeable games. Board stays fail-closed until a corrective is approved.

### Root cause (CONFIRMED by the four-stage reconciliation) + Option-1 fix
The 67 are neither a coverage gap nor a normalization drop: the games ARE in raw + history. They fail to
match because the two sides of the sync canonicalize names with **two different canonicalizers that
disagree** for ~a dozen teams — the manifest/expected side resolved the raw CFBD name
(`cff._resolve("App State")="app state"`), while the graded side resolved the history's
`normalize_ncaaf_team_name`-expanded name (`cff._resolve("Appalachian State")="appalachian state"`).
Confirmed diverging teams include App State, Southern Miss, UConn, UL Monroe, UT Martin, Miami (OH).

**Option 1 (wave-local, shipped):** one helper `_cfb_wave_team_key(name) =
cff._resolve(normalize_ncaaf_team_name(name))` applied to EVERY wave identity — manifest home/away,
graded team/opponent, active-streak sequences, expected-decision keys, and the FBS-membership set
(re-keyed). Display names stay original; `cff._resolve`, stored history, and other CFB surfaces are
untouched. **Collision guard:** proven pre-ship by `qc_cfb_wave_canon.py` (aliases merge; idempotent;
distinct teams incl. Miami FL/OH, USC/South Carolina, the Louisiana schools, Washington/Washington
State and FCS lookalikes never collapse; FBS-FCS side retained), and the raw-universe
`diagnose_cfb_line_coverage.py --collision-audit`; the wave also runs a per-feed collision check at build
time and **fails closed** if any manifest key would merge two distinct teams. QC: the admission QC now
asserts short(manifest)↔long(graded) reconciliation, no double-count, and FBS-FCS retention. The
diagnostic was corrected (both-orientation raw index so a road team isn't a false "absent from raw";
distinct game ids reported separately from team-side decisions; genuine absent-from-raw / ambiguity /
collision all exit nonzero). **Recommended follow-up (not applied): a `GameID` column** on future
history + results rows to reconcile on the stable id instead of the legacy name/date bridge.

### SUPERSEDED — Option 1 (wave-local name canonicalization) was unviable on prod
The prod collision audit proved the two-step name helper merges distinct teams (`Miami`/`Miami (OH)`,
`Tennessee`/`UT Martin`, `Louisiana`/`UL Monroe`, `Southern`/`Southern Miss`) because prod's `cff._resolve`
is **data-dependent** (prefix matching keyed off `_cfbd_names()`), so names cannot be an authoritative
identity. All fail-closed guards fired correctly; no corruption reached the board. Option 1 is replaced by:

### Game-ID reconciliation (SHIPPED)
**Authoritative identity = `(GameID, TeamSide)`**, `TeamSide in {HOME, AWAY}`; `GameID` alone identifies the
game, its two ATS decisions are the two sides. **Authoritative records are never joined on normalized
names again.** FBS eligibility is decided by the **provider conference** captured with the game
(`CFB_FBS_CONFERENCES`), never fuzzy names. Name normalization is **presentation-only** (the model/ranking
overlay, which cannot change membership or ordering).

Persisted through the pipeline (all from the one CFBD `/lines` call both feeds already share):
- `fetch_cfb_line_moves.py` (manifest): adds `game_id`, `home_conf`, `away_conf`, exact `home`/`away`.
- `fetch_cfbd_game_lines_history.py`: adds `GameID`, `HomeTeamRaw`/`AwayTeamRaw`, `HomeConf`/`AwayConf`
  (new columns; the normalized Home/Away stay for other presentation consumers).
- `build_ncaaf_game_line_backfill.py`: emits **two records per game** with `GameID` + `TeamSide` + exact
  provider `Team`/`Opponent` + `Conf`/`OppConf` + selected `Line` + grade.
- Wave (`_cfb_cover_streaks_from_df` / `_cfb_ats_sync` / `build_cfb_wave_context`): decisions keyed on
  `(GameID, TeamSide)`; streaks grouped by the **exact provider team name** (stable across both feeds);
  FBS gate from conference. `_cfb_wave_team_key` removed from all authoritative paths (kept only for the
  non-authoritative overlay + diagnostics). A missing/null `GameID` is **ineligible** and fails the board
  closed; identical `(GameID, TeamSide)` rows collapse, conflicting ones (or a `GameID` with inconsistent
  teams/kickoff) fail closed.

Tests (`qc_cfb_ats_wave_admission.py`, game-id model): Miami/Miami (OH), Tennessee/UT Martin,
Louisiana/UL Monroe, Southern/Southern Miss stay distinct; App State/Appalachian State presentation
aliases don't affect identity; exactly two decisions per FBS-FBS game; exactly one for an FBS-FCS game;
same-week doubleheaders distinct; duplicate collapse vs conflict; missing/null GameID fails closed;
inconsistent-GameID fails closed; push/loss/bye unchanged; overlay cannot change membership/order.

**Migration (prod, SSM):** re-run `refresh_cfb_data.py` (regenerates the manifest, the history with
`GameID`+conf+raw names, and the graded results with `GameID`+`TeamSide` in one pass), then
`report_cfb_wave_sync.py` and `diagnose_cfb_line_coverage.py --completed-week 6`. Old rows lacking
`GameID` are ineligible and keep the board fail-closed — no fabricated IDs. Follow-up: a stable provider
team ID for streak grouping if CFBD exposes one.

**Close CFB only when:** `synchronized: True` with zero missing, conflicts, ineligible (GameID-less /
missing side / missing names), `manifest_missing_gameid`, `manifest_dup_gameid`, `unknown_conference`,
`overlay_misattributions`, duplicates, malformed, and overdue; the full reconciliation exits 0. Overlay
name-collisions are non-authoritative and do not gate closure.

### Implementation blockers resolved (pre-regeneration pass)
1. **Tri-state conference** (`_cfb_conf_class` → FBS / NON_FBS / UNKNOWN). An UNKNOWN side (missing,
   misspelled, renamed) in a completed line-bearing game increments `unknown_conference` and FAILS sync
   — never a silent non-FBS exclusion. `diagnose_cfb_line_coverage.py` audits every distinct 2026
   conference value and flags UNKNOWN ones to extend `CFB_FBS_CONFERENCES` / `CFB_NON_FBS_CONFERENCES`.
2. **Overlays exact-provider-name match only** (AP ranking). No `cff._resolve`; no exact key → the
   overlay is omitted (unavailable), never fuzzy-matched. SoS/divergence overlays are omitted (their
   sources key off the data-dependent resolver). `overlay_misattributions` is 0 by construction.
3. **Atomic writes + ordered refresh.** History and results publish via `bk_runtime.write_csv_atomic`
   (temp + fsync + os.replace) with pre-publish validation; `refresh_cfb_data.py` SKIPS grading if the
   history step fails (never grades stale history) and runs the verifier after successful grading. (Not
   a single atomic generation across all three outputs — each is written atomically on its own.)
4. **Canonical GameID** (`bk_runtime.cfb_game_id`): one parser for manifest/history/grader/sync/
   diagnostics; accepts integral numeric/string (incl. a float-typed CSV `12345.0`), rejects
   null/fractional/scientific/malformed; CSV round-trip proven.
Fail-closed validation added for: missing provider team names, missing TeamSide, inconsistent
teams/date for one GameID, duplicate manifest GameIDs with different identities, UNKNOWN conference,
history-failure-before-grading, and overlay abstention (never misattribution). Tests:
`qc_cfb_ats_wave_admission.py` (15 checks).
