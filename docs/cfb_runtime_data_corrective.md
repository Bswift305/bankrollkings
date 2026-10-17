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

## Approval asked for
Steps 2–5 (the resolver + the `cfb_line_moves` migration + the deploy-script change). Step 1 is done;
Steps 6–7 are prod/SSM verification. I will not touch `bk-auto-deploy.sh` or move files without a go.
