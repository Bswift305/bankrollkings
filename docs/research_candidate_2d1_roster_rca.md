# Research Candidate 2D1 — Roster Null-Identity Root-Cause Audit (READ-ONLY)

**Status: DIAGNOSIS + PROPOSED CORRECTION for review. Nothing changed on prod** — no artifact regenerated,
no code/env/dir/service/flag touched. All measurements read-only via SSM on `i-08d2fd818875381dd` (2026-10-31).
The only write was a `/tmp` throwaway corrected roster copy for a real-adapter dry-run, deleted immediately
(`throwaway_corrected_copy_removed = True`).

## Headline

- The 8 null-identity rows are **non-player aggregate/team rows** that should never enter a player roster —
  **not** real players missing IDs, **not** a join failure, **not** a producer schema defect.
- Dropping them is **lossless** for identity resolution (collision + board counts byte-identical).
- **The adapter's strict null rejection is correct and must stay unchanged.** The fix is at the **producer**.
- **⚠️ A SECOND, INDEPENDENT blocker surfaced** when the roster is corrected: the props board's
  `SourceUpdatedAtUTC` is **100% blank**, so capture stays blocked (`PROPS_SCHEMA_INVALID`) even with a clean
  roster. See §11. **Fixing the roster alone does NOT make the board capturable.**

## 1. The exact eight records (non-sensitive football fields only)

| row | player_id | player_name | player_display_name | season | week | season_type | team | position | position_group |
|---|---|---|---|---|---|---|---|---|---|
| 1117 | NaN | NaN | NaN | 2026 | 1 | REG | SEA | NaN | NaN |
| 2224 | NaN | NaN | NaN | 2026 | 2 | REG | BUF | NaN | NaN |
| 3338 | NaN | NaN | NaN | 2026 | 3 | REG | ATL | NaN | NaN |
| 4448 | NaN | NaN | NaN | 2026 | 4 | REG | CLE | NaN | NaN |
| 5505 | NaN | NaN | NaN | 2026 | 5 | REG | DAL | NaN | NaN |
| 6487 | NaN | NaN | NaN | 2026 | 6 | REG | SEA | NaN | NaN |
| 7446 | NaN | NaN | NaN | 2026 | 7 | REG | NE | NaN | NaN |
| 7520 | NaN | NaN | NaN | 2026 | 8 | REG | CAR | NaN | NaN |

Every identity column is null (`player_id`/`player_name`/`player_display_name` all 0/8 non-null) and
`position`/`position_group` are null (0/8), but each row carries a real `team`, `week` (1–8, one per
completed week), `season=2026`, `season_type=REG`. (Roster total 7521 rows.) No sensitive/unrelated data is
exposed — these are team/week football attributes only.

## 2. Trace through the producer and upstream

- **Producer:** `fetch_nfl_player_week.py` downloads
  `https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.parquet`
  and writes it **verbatim** to `data/tracking/_nflverse_stats_2026.parquet` — `df.to_parquet(tmp, index=False)`
  then atomic `os.replace` (lines ~34–35, ~82–92, ~211–215). **No filtering, no join, no transformation.**
- Therefore the 8 null-identity rows are **present in the upstream nflverse artifact itself** and pass through
  unchanged. This is a pass-through, not a local corruption.

## 3. Classification of each row

All 8 are the **same class: aggregate/team/placeholder rows that should never enter a player roster.**
- **Not real players missing an authoritative ID** — a real player row would carry a `player_name`/`position`;
  these have *no* name, display, or position at all.
- **Not a join failure** — the producer performs no join (verbatim pass-through).
- **Not a producer schema defect** — the schema is intact; these are legitimate nflverse **team-attributed**
  weekly rows (stats on plays not assignable to an individual player).

## 4. Exact producer code

`fetch_nfl_player_week.py`:
- `STATS_URL` (lines 34–35) — the nflverse `stats_player_week_{season}` release.
- `_fetch_frame()` (82–102) — download / `--source` read.
- write (211–221) — `tempfile.mkstemp(dir=OUT_DIR)` → `df.to_parquet(tmp2, index=False)` → `os.replace(tmp2, out)`.
- `out = data/tracking/_nflverse_stats_{season}.parquet`. `data/tracking` is gitignored (prod accumulates
  its own copy), wired into `run_daily.py` before the grader.

## 5. Upstream authoritative id?

**No.** For all 8 rows the upstream itself has **null `player_id` AND null `player_name` AND null
`player_display_name`** (0/8 non-null each). There is **no authoritative identity to recover**, and none can
be inferred. **Do not infer or backfill an ID** — confirmed impossible and prohibited.

## 6. Consumers of this artifact + effect of correcting

Consumers of `_nflverse_stats_2026.parquet` (grep): `build_nfl_gamelogs.py` (folds into `NFL_GameLogs.csv`),
`app.py` (`_nfl_player_week_data`, hot-hand board, prewarm), `build_nfl_channel_dependency.py`,
`build_nfl_role_stability.py`, `capture_green_light.py`, `grade_lenses.py`, `grade_nfl_week.py`, several
`diag_*`. **Effect of dropping the 8 null-identity rows: none harmful.** They carry no player identity, so
every player-keyed consumer already ignores or NaN-drops them (e.g. `build_nfl_prior_team_map.py` already
`.dropna(subset=["player_display_name","team"])`; graders/boards key on `player_id`/name). The collision
audit (§7) shows the resolvable identity population is **byte-identical** before/after — the drop is lossless.

## 7. Collision audit — current vs proposed-corrected population

| Population | rows | uniq identities | name→>1 id | id→>1 name | board names | resolvable | unresolved | ambiguous |
|---|---|---|---|---|---|---|---|---|
| CURRENT (dropna) | 7521 | 1694 | **3** | 0 | 429 | 343 | 85 | 1 |
| PROPOSED (drop 8 null rows) | 7513 | 1694 | **3** | 0 | 429 | 343 | 85 | 1 |

**Identical.** Removing the 8 rows introduces/removes no collision and changes no board-resolution count. (The
3 name→>1-id roster collisions and the 1 ambiguous board name are a *separate* known tail — unaffected by this
fix and handled by the adapter's existing abstain path.)

## 8. Narrowest producer-level correction + fail-closed QC

- **Correction (code, NOT done here):** in `fetch_nfl_player_week.py`, after fetching and **before** writing,
  drop only rows whose `player_id` is null/blank **or** `player_display_name` is null/blank — the exact
  identity completeness the adapter requires. It removes only player-less rows; it changes no identity, no
  stat, no other column. **The adapter's strict null rejection stays UNCHANGED.**
- **Fail-closed QC (code, NOT done here):** a `qc_*` asserting the written parquet has **zero** null/blank
  `player_id` and **zero** null/blank `player_display_name`, and that the drop removed **only** identity-null
  rows (row-count delta == measured null-identity count — so a real player can never be silently dropped), and
  season is the single expected int. Fails closed on any violation.

## 9. Exact regeneration + validation procedure (atomic + rollback)

For the later, separately-approved run (NOT executed here):
1. **Back up** the live artifact first: `cp -p _nflverse_stats_2026.parquet _nflverse_stats_2026.parquet.bak-<utc>`.
2. **Regenerate** with the corrected producer: `sudo -u ubuntu .../python fetch_nfl_player_week.py --season 2026`
   — it already writes **atomically** (`tempfile` in `OUT_DIR` → `os.replace`), so a concurrent web read never
   sees a half-written parquet.
3. **Validate:** run the new fail-closed QC (§8); then the adapter dry-run — it must report
   `RESOLVED_capturable ≥ 1` **(it will NOT until §11 is also fixed)**.
4. **Rollback:** `mv _nflverse_stats_2026.parquet.bak-<utc> _nflverse_stats_2026.parquet` (atomic; the old
   bytes are preserved).

## 10. No production mutation

Confirmed: only the live artifacts were **read**. The single write was a `/tmp` throwaway corrected copy used
for the real-adapter dry-run, **deleted immediately** (`throwaway_corrected_copy_removed = True`). No live
artifact regenerated, no code/env/dir/service/flag changed.

## 11. ⚠️ SECOND independent blocker (surfaced by the corrected dry-run)

Running the REAL adapter against the throwaway **corrected** roster:
`RESOLVED_capturable = 0 of 429`, all `PROPS_SCHEMA_INVALID` — the roster abstention cleared, exposing the
next gate (adapter step 5a: the bound row's `SourceUpdatedAtUTC` must be present + parseable).

Characterized read-only on `NFL_Props.csv` (2304 rows):

| Column | blank | unparseable(non-blank) | parseable | sample |
|---|---|---|---|---|
| `SourceUpdatedAtUTC` | **2304 (100%)** | 0 | **0** | — (all blank) |
| `EventCommenceAtUTC` | 0 | 0 | 2304 | `2026-11-01T18:00:00Z` |
| `LastUpdated` | 0 | 0 | 2304 | `2026-10-31 13:00` |

So the board's `SourceUpdatedAtUTC` column **exists but is entirely empty**; the provider-update timestamp is
actually carried in **`LastUpdated`** (fully populated, parseable). The adapter requires a parseable
`SourceUpdatedAtUTC` per bound row, so **every** resolve abstains `PROPS_SCHEMA_INVALID` even with a clean
roster.

**Implication:** the roster fix (§8) is **necessary but not sufficient**. A second, independent
producer/contract issue blocks capture: either the props producer must populate `SourceUpdatedAtUTC`, or the
adapter's declared freshness column must be reconciled with what the board actually carries (`LastUpdated`).
That is a **separate design decision + scoped props-producer RCA** — NOT decided here. I recommend it as the
next diagnostic, before any producer change or enablement.

---

**Bottom line:** two independent, data/producer-level blockers (roster null-identity rows; props
`SourceUpdatedAtUTC` empty). Both are fixable at the producer/contract layer without weakening the adapter.
Neither is fixed here — diagnosis + proposed corrections returned for review. The `0700` state-dir
provisioning stays parked until a corrected dry-run is capturable.
