# Scorecard RCA + production `venv/` (read-only, 2026-11-05)

**Scope.** Read-only SSM between 18:4xZ and 18:5xZ, plus code at `17b5e69`. No code was changed, nothing was written
to prod, and no cache was touched.

## 1. NBA 99 Scorecard — `Source Truth Accuracy` = FAIL

**What the scorecard checks:**
- **Assertion:** `run_nba_99_scorecard.py:108` sets `source_status = "PASS" if source_report["failure_count"] == 0 else
  "FAIL"`. The `source_report` is `qc_nba_sources.run_source_audit()`.
- **Which branch fired:** `qc_nba_sources.py`, the `elif props_refresh_meta.get("is_stale")` branch, which appends
  `"Live props feed is stale at {age}h old during source audit."`
- **Stale threshold:** `get_props_refresh_meta(..., max_age_hours=LIVE_MARKET_MAX_AGE_HOURS)`, and
  `services/freshness_contract.py:35` sets `LIVE_MARKET_MAX_AGE_HOURS = 6.0`.

**Prod evidence (`data/tracking/QC_Run_Log.csv`, scope `nba_sources`):**

| Run | Clean | FailureCount | Notes |
|---|---|---|---|
| 11-04 13:23:50 | 1 | 0 | "Props status: live …" |
| 11-04 13:27:44 | 1 | 0 | "Props status: live …" |
| 11-05 13:21:53 | 0 | **1** | "Props status: **stale** \| Audited 0 playoff matchups, 0 player playoff samples, 0 player sample failures." |
| 11-05 13:25:47 | 0 | **1** | same |

**The single failure is the stale-props assertion:**
- 0 matchup failures, and 0 player failures.
- The regular-season playoff checks found nothing: 0 playoff matchups audited, so no series failures.

**Underlying artifact:** `data/props/NBA_Props.csv`.
- 1,678 rows, max `SourceUpdatedAtUTC` 2026-11-04T13:05:19Z, so about 24h old at audit time, against the 6h limit.
- It went stale because `refresh_nba_daily` stopped at its `game_lines` step. The validator refused "implausible
  row-count collapse: 6 rows < 50% of prior 42", so the props step never ran (see `bk_daily_checkpoint_20261105.md`).

**Is it fixed by an existing branch?**
- **Not directly by any scorecard/QC branch.** No branch modifies `qc_nba_sources.py` or `run_nba_99_scorecard.py`. F3
  (`fix/bk-daily-f3-nba-playoff-qc`) gates `qc_nba_board`, not this audit.
- **Indirectly by NBA v6.** It replaces the NBA lines/props path with the event-slate contract and separate lines/props
  locks, so props can refresh even when a lines slice is refused. This is expected to clear the assertion once NBA props
  are fresh within 6h.
- **Unproven until a post-deploy run shows it.** No code change to the assertion is warranted: it is correctly
  reporting a genuinely stale feed.

## 2. Prelaunch Scorecard — `Data Freshness And Source Truth` = FAIL

**What the scorecard checks:**
- **Assertion:** `run_prelaunch_scorecard.py:263-276` passes only when **all** of these are 0: `odds_feed.failure_count`,
  `nba_source_report.failure_count`, and the `failure_count` of every injury report (NBA, NFL, WNBA, MLB, CFB).

**Which inputs failed (row text, prod `Prelaunch_Scorecard.csv`):**

| Input | Status on 11-05 | Fails the section? |
|---|---|---|
| `odds_feed` | Per-family: NFL/NCAAF lines+props FRESH (0h); NBA lines+props FRESH (24h, by file age); **WNBA lines STALE 109h, WNBA props STALE 120h, MLB lines STALE 185h, MLB props STALE 192h**; Futures FRESH; NFL graded FRESH | **YES** — the `dc82c9d` per-family rule: lines STALE and props STALE ⇒ FAIL, for sports still counted "active" |
| `nba_source_report` | `failure_count` 1 (§1) | **YES** |
| Injury feeds | NBA f=0/w=1, NFL f=0/w=0, WNBA f=0/w=1, MLB f=0/w=0, CFB f=0/w=1 | no (warnings only) |

**Underlying artifacts:**
- **MLB/WNBA:** `data/odds/WNBA_Odds.csv` (11-01T00:00), the MLB odds file, `WNBA_Props.csv` (mtime 10-31) and
  `MLB_Props.csv` (mtime 10-28). These are off-season leagues whose files still count them "active", because
  `season_utils.active_sports()` treats a sport as active when its props file has rows. This is RCA item 6 (F6),
  downstream of F2.
- **NBA:** the same stale `NBA_Props.csv` as §1.

**Is it fixed by an existing branch?**
- **MLB/WNBA family half:** `fix/bk-daily-f6-odds-health-season` (`3fd0e40`) and `fix/bk-daily-f2v2-season-preexec`
  (`0ccf053`) change `qc_odds_feed.py`, `season_utils.py` and `run_prelaunch_scorecard.py` around an "audited,
  provenance-carrying season calendar". Neither is built on `17b5e69`, and both overlap Safeguard A (`31d09dd`), which
  also edits `season_utils.py` / `run_prelaunch_scorecard.py` semantics. Under the owner's rule, F2v2's calendar must be
  accepted as the **governed** season calendar before MLB/WNBA can be classified off-season. Until then the FAIL is the
  honest result.
- **NBA half:** NBA v6, as in §1.
- **Also noted by the Safeguard A builder:** `run_prelaunch_scorecard` still marks off-season *routes* N/A from props
  files. That affects `Platform Reliability` (PASS today), not this section.

**Other prelaunch sections on 11-05:**
- `Platform Reliability` PASS.
- `Suggestion Integrity` WATCH (0 plays evaluated).
- `Sport-Specific Launch Questions` WATCH (WNBA warnings=1, CFB warnings=2).

## 3. Production `venv/` (read-only; not modified)

| Question | Answer |
|---|---|
| Is `venv/` ignored? | **No.** `git check-ignore -v venv/ venv/bin/python` → rc 1; `.gitignore` has no venv line. `git status --porcelain` shows `?? venv/`; tracked dirty = 0 |
| Exact dirty-tree check in auto-deploy | `/usr/local/bin/bk-auto-deploy.sh:48` `DIRTY=$(git status --porcelain --untracked-files=no)`. The comment at :45–46 says it HOLDs only if a **tracked** file is modified (staged or unstaged); untracked files are excluded. The installed script is byte-identical to `ops/bk-auto-deploy.sh` (sha256 `4bbc5dce…2bfe44cf`) |
| Why prior deploys proceeded | The untracked `venv/` is excluded by `--untracked-files=no`, and `git pull --ff-only` is not blocked by an untracked directory that no incoming commit tracks. Last deploy 11-04 14:11Z prewarmed `17b5e69` OK |
| Checkout size / execution | 622 MB, created 2026-06-05, owned by ubuntu. **It is the production interpreter:** gunicorn `ExecStart` is `/opt/bankrollkings/venv/bin/gunicorn`, and `bk-daily` and `bk-linemove` run `/opt/bankrollkings/venv/bin/python`. It is not in git, so it adds nothing to clone or fetch size; it lives on the 50 GB data volume |

**Risk (no action taken).** Because `venv/` is not ignored, a `git add -A` on the box would try to stage 622 MB of
interpreter. A `git clean -fdx` / `-fd` would **delete the running interpreter** and take the site and every timer
down.

**Narrow follow-up for the owner to decide:**
1. Add `venv/` to `.gitignore`, as a reviewed repo change.
2. Optionally assert in the deploy script that the interpreter path exists.

Do not delete or move the folder.

**Incidental finding.** `bk-deploy` logged one `git fetch` failure on 11-05 (16:01:56Z, `git@github.com: Permission
denied (publickey)`).
- That tick held; it did not half-deploy.
- Count today = 1. The latest run succeeded (Result=success, exit 0, 18:45:56Z).
- It looks transient; recheck if it recurs.
