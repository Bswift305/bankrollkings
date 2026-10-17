# NFL scenario-file runtime migration

Companion to `docs/cfb_runtime_data_corrective.md`. Same class of bug (a prod refresh job writing a
git-TRACKED file -> dirty tree -> `git pull --ff-only` blocked), scoped to NFL and kept reversible.

## The trap

Six NFL scenario files are regenerated on prod by `run_daily.py`, but the builders wrote them straight
into the tracked tree (`data/scenarios/*.json`). Every prod rebuild left the working tree dirty, which is
what `git status` showed for `data/scenarios/nfl_2026_form.json`. That is the same failure the CFB
`cfb_line_moves.json` regression came from.

## Classification (read-only characterization)

**Group A — prod-regenerated (migrated), 6 files.** Wired into `run_daily.py`:

| File | Builder | Readers |
|---|---|---|
| `nfl_2026_form.json` | `build_nfl_team_form.py` | app.py, `nfl_current_form.py`, `build_nfl_regression.py` |
| `nfl_2026_defense.json` | `build_nfl_defense_form.py` | app.py, `nfl_defense_form.py` |
| `nfl_regression.json` | `build_nfl_regression.py` | app.py |
| `nfl_scores.json` | `build_nfl_scores.py` | app.py (×6 sites), `nfl_totals.py` |
| `nfl_officiating.json` | `build_nfl_officiating.py` | app.py |
| `nfl_qb_profiles.json` | `build_nfl_qb_profiles.py` | `nfl_backup.py` |

**Group B — static seeds, 6 files** (`nfl_coaching`, `nfl_concentration`, `nfl_channel_dependency`,
`nfl_role_stability`, `nfl_usage_by_state`, `nfl_scenarios`). NOT in `run_daily` or any prod timer —
built locally/one-time and shipped committed, read-only on prod (exactly like the `cfb_*.json` research
seeds). No trap; left unchanged and tracked.

## Design: committed-seed fallback (NOT fail-closed)

Chosen deliberately (contrast the CFB live-wave files, which fail closed). For these slowly-changing
context files feeding user-facing NFL lenses, a brief "unavailable" window after each deploy is worse UX
than serving a cold-start copy. So:

- **Builders write ONLY to the runtime dir, atomically** (`bk_runtime.publish_json` -> temp+fsync+
  os.replace under `BK_RUNTIME_DIR`, else the gitignored `.runtime/generated/`). They never touch the
  tracked tree, so prod stops dirtying it.
- **Consumers read via `bk_runtime.scenario_read_path(name)`**, resolved at READ time (never frozen at
  import — the long-lived gunicorn process must pick up a fresh runtime write after its lru_cache clears).
  These names are deliberately NOT in `CFB_RUNTIME_FILES`, so the resolver's DEFAULT branch applies:
  runtime copy if present, else the committed `data/scenarios/` seed.
- The committed copies STAY tracked as cold-start seeds (no `git rm`). `run_daily` keeps the runtime copy
  fresh daily; the seed is only read when the runtime copy is absent (fresh box / pre-first-rebuild).
- `bk_runtime.NFL_RUNTIME_FILES` lists the six for documentation; no code branch keys on it.

App-side cache **watch-lists** were repointed to the resolver too (via `_nfl_scenario_path`), so the board
caches invalidate when the runtime copy updates (not just when the frozen tracked path changes).

Verified locally: builder write path is under the runtime dir (not the tracked tree); `publish_json`
leaves the committed seed byte-unchanged; seed-fallback returns the committed data when the runtime copy
is absent; the runtime copy takes precedence when present. `qc_nfl_board.py`'s 6 pre-existing issues are
identical with and without this change (non-regressive).

## Production bootstrap (operator, via SSM — after the deploy lands)

The migration deploys like any commit. The currently-running deploy script reverts the dirty tracked
`nfl_2026_form.json` and pulls; from then on the builders write the runtime dir, so the tracked tree
stays clean. No `git rm` and no pre-seed are required — seed-fallback covers the gap until the next
`run_daily` writes the runtime copies.

1. Confirm the deploy landed (`git log --oneline -1`).
2. Let the daily `run_daily` tick run (or trigger the NFL builders), then confirm the runtime copies exist:
   `ls -1 "$BK_RUNTIME_DIR"/scenarios/nfl_*.json` (expect the 6 Group-A files).
3. Confirm the tracked tree no longer goes dirty from NFL jobs:
   `sudo -u ubuntu git -C /opt/bankrollkings status --porcelain data/scenarios/nfl_*.json` (expect EMPTY).

Optional housekeeping (separate): refresh the committed seeds occasionally by copying the current runtime
copies into `data/scenarios/` and committing, so a cold start begins from recent data.

## Gate: hardened deploy-script reinstall

Only AFTER the bootstrap verification above shows the tracked tree stays clean do we reinstall the
HOLD-on-dirty `ops/bk-auto-deploy.sh` (currently held). Then prove, on the box:
- a clean tree deploys;
- ignored/untracked runtime data does not block deployment;
- any tracked modification blocks deployment WITHOUT deleting it;
- the running service stays on the previous commit after a blocked pull.
