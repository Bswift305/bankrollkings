# RC 2D1 — Roster single-writer correction (PROPOSAL, for review)

Status: **design only. No code, no commit, no deploy, no regeneration.** Deployed master stays `628657b`;
approved producer commits `a93c022` → `aee1fe2` (Linux gate v2 PASS, command `ec430098-…`) are NOT yet on
master. Capture flag OFF. Green Light queued.

## 1. Defect (blocking)

The governed roster artifact `data/tracking/_nflverse_stats_<season>.parquet` has **three** writers on prod,
and only one of them goes through the corrected producer boundary (`a93c022`):

| # | Writer | Scheduled as | Sanitized? | Atomic? |
|---|---|---|---|---|
| W1 | `fetch_nfl_player_week.py` `main()` | `run_daily` step "NFL weekly player stats" (run_daily.py:124); `bk-nfl-postweek` Tue/Wed | **yes** (`sanitize_player_identities`) | yes (`mkstemp` in OUT_DIR + `os.replace`) |
| W2 | `grade_nfl_week.py` `_season_df()` (via `--resolve`, and `fetch_actuals` in manual mode) | `run_daily` step "NFL board grade (resolve)" (run_daily.py:78) | **no** | **no** — `urlretrieve` straight onto the live path |
| W3 | `refresh_nfl_featured_results.py` → `from grade_nfl_week import _season_df` | `run_daily` step "NFL featured results" (run_daily.py:173) | **no** | **no** |

Daily order is W2 (78) → W1 (124) → W3 (173). **Every `run_daily` therefore ENDS with the raw, unsanitized
file on disk** (the null-identity aggregate rows are back), and twice a day a reader can observe a
half-written parquet. A one-time controlled regeneration would be undone by the next daily run. The dark
adapter fails closed on it (`ROSTER_SCHEMA_INVALID`, "null roster identity value"), so it is harmless
while capture is OFF, but capture cannot be enabled on top of it.

No other code writes the governed path. The other nflverse downloaders
(`build_nfl_defense_form`, `build_nfl_team_form`, `build_nfl_qb_profiles`, `build_nfl_scores`,
`build_nfl_receiver_profile`, `build_nfl_prior_team_map`) download to private temp/scratch paths. Readers
(`app.py`, `build_nfl_gamelogs`, `capture_green_light`, `grade_lenses`, `build_nfl_role_stability`,
`build_nfl_channel_dependency`, the adapter) only read.

## 2. Correction — one writer, readers never publish

Principle: **W1 is the only publisher of the governed artifact.** Graders need fresh actuals, not the
artifact, so they must obtain the season frame **without writing it**.

Change `grade_nfl_week._season_df(season)` to download into a **private temp file** and return the frame,
by reusing the producer's existing download helper — no copy of download, sanitation or publish logic:

```python
from fetch_nfl_player_week import _fetch_frame   # existing helper: private mkstemp, removes its temp

def _season_df(season: int) -> pd.DataFrame:
    """Season weekly stats for GRADING. Never writes the governed roster artifact
    (fetch_nfl_player_week is its single publisher)."""
    df = _fetch_frame(season, None)
    if df is None:
        raise RuntimeError(f"nflverse weekly stats unavailable for {season}")
    return df
```

* W3 is fixed by the same edit (it imports `_season_df`); no change to `refresh_nfl_featured_results.py`.
* Callers keep today's contract: a failure still raises, and both callers already `try/except` it.
* Grading keeps using the raw frame. It filters by week and `player_display_name`; the all-null aggregate
  rows can never match a player, so results are unchanged. Sanitation stays where governance needs it — at
  the one publish boundary — instead of being duplicated into a reader.
* `fetch_nfl_player_week.py` is **not modified**, so the gated `aee1fe2` content and its 15/15 QC stand.

**Considered and rejected:** making `_season_df` read the governed artifact instead of downloading. That needs
no network, but W2 runs *before* W1 in `run_daily`, so grading would run a day stale unless the steps
were reordered. That's a larger behavioral change for no governance gain.

## 3. Affected files (2)

1. `grade_nfl_week.py` — `_season_df` body only (≈8 lines). `import urllib.request` stays (other uses);
   remove only if unused.
2. `qc_nfl_roster_single_writer.py` — new adversarial QC (§5).

Resulting release: base `628657b` + `a93c022` + `aee1fe2` + **c3** (this change) = 3 commits, **7-file scope**.

## 4. Scheduled-job ordering

No reorder. After c3, in one `run_daily`: W2 (78) downloads privately → W1 (124) publishes sanitized,
atomically → W3 (173) downloads privately. `bk-nfl-postweek` (Tue/Wed) still runs only W1. The final state
of every daily run is the sanitized artifact.

## 5. Adversarial QC — `qc_nfl_roster_single_writer.py` (synthetic, no network)

1. **Static single-writer scan:** every tracked `*.py` / `*.sh` that references `_nflverse_stats_` is
   classified. Any use of a write primitive on that path (`urlretrieve`, `to_parquet`, `os.replace`,
   `shutil.copy*`, `open(…, "wb")`) outside `fetch_nfl_player_week.py` fails. This catches a future fourth writer.
2. **W2 behavioral:** stub `urllib.request.urlretrieve` to drop a fixture parquet with all-null aggregate
   rows + valid rows; point `BASE_DIR` / `OUT_DIR` at a temp tree pre-seeded with a sanitized governed file.
   Call `grade_nfl_week._season_df(2026)`. Assert the governed file's SHA-256, inode and mtime are unchanged,
   that no file was created under `data/tracking/`, that the private temp file is removed, and that the
   returned frame equals the fixture (grading semantics preserved).
3. **W3 binding:** `refresh_nfl_featured_results._season_df is grade_nfl_week._season_df` (no shadow copy).
4. **Failure path:** the stub raises → `_season_df` raises; governed file untouched; no temp left behind.
5. **Absent artifact:** with no governed file present, `_season_df` must not create one.
6. **W1 regression:** `qc_nfl_roster_sanitize` stays 15/15. W1 still publishes atomically (new inode, no
   leftover `nflwk_out_*`).
7. **Mutation check:** temporarily restore the old `_season_df` body in-process. Checks 1, 2 and 5 must FAIL,
   which proves the QC detects the bypass.

## 6. Acceptance sequence (each step reviewed; prod mutations need explicit approval)

1. Review this proposal → implement c3 on `fix/rc-producer-corrections` (local QC: the new QC + the
   existing 10 gate suites).
2. Linux gate **v3** (read-only, disposable clone): HEAD == c3, ancestry `628657b → a93c022 → aee1fe2 → c3`,
   exactly 3 commits, **7-file** diff, clean checkout, same fixture containment, suites incl. the new QC,
   flag unset before/after → `PREPROD ACCEPTANCE: PASS`.
3. Prod preflight (read-only): master == `628657b`, timers / no producer running, gate verdict, artifact
   stat + SHA-256.
4. **[approval]** fast-forward master to c3 → controlled one-time regeneration with backups and validation
   (as previously specified).
5. **Persistence receipt (new):** after the next scheduled `run_daily` completes, re-run the read-only
   validation. Zero null governed identities, the artifact last written by W1, and no `nflwk_out_*` leftovers.
   Capture stays OFF until this receipt passes.

## 7. Rollback

* **Code:** `git revert c3` (no force-push) restores today's behavior. Safe only while capture is OFF (the
  adapter fails closed). Nothing else depends on the private-temp change.
* **Artifacts:** unchanged from the authorized plan — permission-preserving backups + SHA-256 receipts
  taken before regeneration, and restored (and hash-verified) on any regeneration or validation failure.
* **Grading:** if nflverse is unreachable, behavior is identical to today (the exception is caught by
  the callers). The governed file simply isn't touched any more.

## 8. Out of scope (noted, not changed)

* W1 publishes via `mkstemp`, so the file mode is 0600, owner `ubuntu` (same user as the app → readable).
  Regeneration validation will compare mode/owner before vs after rather than change it.
* The six private-temp builders download the same feed independently (≈6 extra downloads/day). That's an
  efficiency issue, not a governance one.
