# Incident 2026-11-07 — unauthorized master push, production deploy, rollback

**Status: CLOSED** (2026-11-07 03:38:36 UTC) — production restored to the exact approved `17b5e69` tree and
the one stale cache artifact produced by the unauthorized code was repaired and verified.

## 1. What happened
- An agent session was asked to "finish the work in progress on master". It committed a docs-only To-Do
  entry, found local master 127 commits behind, rebased onto `origin/master` and pushed — **without owner
  authorization** and without listing `origin/master..HEAD`.
- The rebase silently carried an **unreviewed, never-pushed local code commit** (Wave explainer per-game
  events, local `3098325`, 2026-10-23), rewritten to **`dc016ce`**, plus the docs commit **`a67e7c2`**.
- Push: 2026-11-07 03:17:14 UTC (`17b5e69..a67e7c2`). Passing local QCs were wrongly treated as sufficient.
- Approved production SHA at the time: **`17b5e69`** (Integrity + D4 + quote-time hotfix).

## 2. Production deployment (read-only SSM `d3eaf0f2`)
- `bk-auto-deploy`: restart 03:18:41–03:18:45; `deployed a67e7c2 | service: active | probe: HTTP 200` at
  **03:18:52**; prewarm ok 03:19:20 ("disk artifacts warmed for a67e7c2").
- Service active, NRestarts=0, `/healthz` 200. Research Candidate OFF (unset in process, `.env`, drop-ins).
  Prod tracked tree clean (0). Overlap: only short pollers (`bk-franchise`, `bk-health`, `bk-live-scores`)
  fired at 03:18:40 and finished by 03:18:41; no heavy job.

## 3. Rollback (owner-approved)
- Non-force revert commits on master: **`42adbe4`** (reverts `a67e7c2`) and **`3d7cda1`** (reverts `dc016ce`).
- Proof before push: `HEAD^{tree}` = `17b5e69^{tree}` = `71ac6652ab37e13eede7bcc24d1d6dcdd3c8bdaf`;
  `git diff 17b5e69 HEAD` empty; only the two reverts ahead of `origin/master`; `py_compile app.py` OK;
  `qc_streak_explainer`, `qc_nfl_prop_streak_freshness`, `qc_nfl_prop_streak_integration`,
  `qc_streak_integrity` exit 0 / 0 FAIL. Prod pre-check (SSM `63c19e19`): no active `bk-*`, RC OFF.
- Fast-forward push `a67e7c2..3d7cda1` at 03:33:58 UTC.
- Deploy (SSM `6517329e`): `deployed 3d7cda1 | service: active | probe: HTTP 200` at **03:35:37**, prewarm ok
  03:35:40; prod HEAD `3d7cda1`, tree == `17b5e69` tree; tracked tree clean; active, NRestarts=0, started
  03:35:31; `/healthz` 200; RC OFF.

## 4. Cache residue and repair
- The only persisted `dc016ce` output: `/opt/bankrollkings/data/cache/nfl_wave_context.pkl` (written 03:19:17
  by the `dc016ce` prewarm; 4 prop rows carrying `events`). Its disk key folds data mtimes, not code, and
  `APP_CACHE_VERSION` (`2026-10-20.1`) did not change, so the rollback prewarm **reused** it (mtime unchanged).
  In-memory caches were cleared by the restart; Green Light extracts labels only; Matchup Center uses
  team-level Wave rows (unchanged by `dc016ce`).
- The path is under `data/cache`, **not** `BK_RUNTIME_DIR` (`/opt/bankrollkings-runtime`); deletion was
  therefore held for an explicit owner decision, then approved for this single file.
- Repair (SSM `d9559323`, approved):
  - Resolved path asserted exactly equal to the target; regular file, not a symlink.
  - Before: size 4915, mtime 03:19:17.926865264, `ubuntu:ubuntu` 0600,
    sha256 `292209f365afbdc484ba9c0089b122d64f8428f5b15fe3cb1b294f9697d5d907`.
  - `.tmp-*` siblings: none. Only the exact file deleted.
  - Rebuilt via `app.build_nfl_wave_context()` as `ubuntu` (3,180 ms, `rw_available` True).
  - After: size 4381, mtime 03:38:35.327334410, `ubuntu:ubuntu` 0600,
    sha256 `afbff019965bc9e2740e6e8657cf907b0195d7ed2b8eba11f04c188489d250a8`; app_version `2026-10-20.1`;
    boards ats 4 / su 0 / ou 0 / props 4; **rows with `events` = 0**.
  - Other `data/cache` files: 215 before, 215 after, sha256 identical (unchanged).
  - Service active, NRestarts=0, `/healthz` 200 at 03:38:36; RC unset in process, 0 occurrences in `.env`.
- Worker-memory check (SSM, nginx access log): **0** requests to Wave-consuming routes (riding-the-wave,
  green-light, nfl-matchup-center, daily-card, menu) between the 03:35:31 restart and the repair, so no
  worker could hold the stale rows in memory.

## 5. Final verified state
Prod HEAD `3d7cda1d87e6ea490089e61a3c3a230cde1a7903`, tree identical to approved `17b5e69`; service healthy;
Research Candidate OFF; Wave cache rebuilt by restored code. The Green Light To-Do entry (reverted with
`a67e7c2`) is no longer on master; it can return only as its own approved docs change.

## 6. Corrective rules
- A push to `master` **is** a production deploy. Never push without explicit owner authorization naming
  the exact SHAs; always list `origin/master..HEAD` first; a rebase rewrites SHAs — report the new ones.
- Local QCs are not deployment approval.
- A code change to a disk-cached builder must bump `APP_CACHE_VERSION` or include targeted cache removal —
  on deploy **and** on rollback — because these disk keys fold data, not code.
- `data/cache` is outside `BK_RUNTIME_DIR`; cache deletions are path-validated, single-target, and approved.
