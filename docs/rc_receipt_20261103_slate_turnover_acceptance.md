# Production acceptance receipt — slate-turnover correction @ `a5de400` (2026-11-03)

**Verdict: PRODUCTION ACCEPTED** for the standalone event-aware slate-turnover correction (NFL + NCAAF props).
The track is **closed**: no revert, no further paid validation fetch.

This receipt is **separate from and does not amend** the 2026-11-02 receipt (`docs/rc_receipt_20261102.md`),
which stays `RESTORED / INCONCLUSIVE` as recorded.

Scope of this acceptance: the props correction only. It does **not** accept the RC/production program:
`bk-daily` still exited 1 (7 failed steps, ledger 1.5x) and the remaining Research Candidate artifact checks
(roster identity, adapter dry-run, round-trip, no-DB) were not part of this read.

## Correction of a stale statement

A report claimed both "a5de400 was fast-forward deployed" and "master remains at 63060a9". The second is
**false** as of 2026-11-03 00:45:07 UTC. Read-only evidence:

| Check | Value |
|---|---|
| `origin/master` (`git ls-remote`, from dev box and from prod) | `a5de4003e6d6462e448bd1bcef8a965288ff2c05` |
| Prod HEAD `/opt/bankrollkings` | `a5de4003e6d6462e448bd1bcef8a965288ff2c05` |
| Prod tracking `origin/master` | `a5de4003e6d6…` — no drift |
| Prod history | `a5de400 ← f6b54e7 ← 63060a9 ← aee1fe2` |
| Deploy | `2026-11-03T00:45:07Z bk-auto-deploy.sh: deployed a5de400 \| service: active \| probe: HTTP 200`; prewarm ok |
| Worktree | no tracked modifications (only untracked `venv/`) |

## Flag / capture

`BK_RESEARCH_CANDIDATE_ENABLED` is **unset** in `/opt/bankrollkings/.env` (the unit's only `EnvironmentFile`;
0 matches), absent from the unit `Environment` and every file under `/etc/systemd/system`, and `<unset>` in the
live gunicorn master (pid 1605749, started 13:20:31Z) and both workers. Capture remained **OFF**.

## Acceptance cycle = the ordinary scheduled run

`bk-daily.service` 2026-11-03 13:00:00 → 13:20:30 UTC, log `logs/daily_operator_20261103_130000.log`.
No ad hoc run, no override, no `--allow-collapse`.

- **Overall `bk-daily` result: FAILED** (`status=1/FAILURE`, `Result=exit-code`). Reported separately.
- Step **Football player props: `[PASS]`** — `OUTCOME football_player_props: nfl_player_props=UPDATED,
  ncaaf_player_props=UPDATED`.

### Event-aware validation receipts (`---- VALIDATION RECEIPT (event-aware) ----`)

| Field | NFL | NCAAF |
|---|---|---|
| now_utc | 2026-11-03T13:00:31Z | 2026-11-03T13:00:36Z |
| provider_errors | 0 | 0 |
| Provider events found (next 7d) / events with rows | 15 / 13 | 63 / 19 |
| Raw candidate rows | 450 | 828 |
| Prior file rows | 2,831 | 2,552 |
| completed_events_removed (rows) | 13 (2,831) | 46 (2,552) |
| started_candidate_rows_removed | 0 | 0 |
| overlapping_events_retained / new_events_added / sparse_future_events | 0 / 13 / 10 | 0 / 19 / 0 |
| prior_active_events_absent / vanished_events / collapsed_events | 0 / [] / [] | 0 / [] / [] |
| rejected_malformed_rows (all four reasons) / identity_invalid_rows | 0 / 0 | 0 / 0 |
| **decision / reason_code** | **PUBLISH / CURRENT_SLATE_VALID** | **PUBLISH / CURRENT_SLATE_VALID** |
| final_published_rows / published events | 450 / 13 | 828 / 19 |
| Provider credits (`x-requests-last`, props step) | 34 | 79 |

The shape receipts (`data/tracking/_last_props_fetch_americanfootball_{nfl,ncaaf}.json`) carry a matching
`publish` block (`basis: filtered current-slate file (not-yet-started events only)`, `decision: PUBLISH`).

### Published files (read-only evidence; sha256 truncated to 16 hex)

| File | mtime UTC | Bytes | sha256 | Rows |
|---|---|---|---|---|
| `data/props/NFL_Props.csv` | 2026-11-03T13:00:31Z | 98,593 | `e607456b2f90cb6b` | 450 |
| `data/props/NCAAF_Props.csv` | 2026-11-03T13:00:36Z | 179,978 | `a49c6086dc15bf80` | 828 |
| `data/tracking/NFL_Props_MarketCoverage.csv` | 13:00:31Z | 1,512 | `4da3b845067052d7` | 12 |
| `data/tracking/NCAAF_Props_MarketCoverage.csv` | 13:00:36Z | 1,018 | `58b72887b9b28fcc` | 8 |

- **Completed Sunday events: none remain.** Started rows 0 in both files; earliest NFL kickoff
  2026-11-06 01:15Z (Thu Nov 5 ET), earliest NCAAF 2026-11-04 00:00Z.
- **Final writer:** `bk-daily.service` → `run_daily.py` step "Football player props" →
  `[STEP] nfl_player_props` / `ncaaf_player_props` → `fetch_player_props.py`. File mtimes equal the receipt
  times; no other systemd unit or `/usr/local/bin` script references `fetch_player_props`; no other journal
  writer today.
- Post-refresh odds-feed health: `[PASS]` — NFL props FRESH (0h), NCAAF props FRESH (0h). The pre-refresh
  "props STALE while lines FRESH" lines (log 14–15) describe the state *before* this step ran.
- Run credits observed across all receipts: 3 + 3 (football lines) + 34 + 79 (props) + 4 (futures) + 3 (a
  failed in-season step); remaining after run **98,571**.

### Source timestamps — provenance stated precisely

- `SourceUpdatedAtUTC` non-null and parseable on **450/450** (NFL) and **828/828** (NCAAF) rows; range
  12:58:19–13:00:32Z; 16 distinct values over 13 NFL events, 20 over 19 NCAAF events (≈1 per event) —
  varying, not one fetch-time stamp. A separate `LastUpdated` column exists and is unchanged.
- The deployed code path (`aee1fe2`, carried in `a5de400`) binds it to the market-level provider
  `last_update` and never substitutes fetch time.
- **This run did not inspect the raw provider payload.** The governed raw-capture evidence that the market-level
  field is the provider's authoritative update time is the 2026-10-31 diagnostic: SSM `330ddbaa-40ea-4a28-910e-11703e7bd958`,
  `docs/research_candidate_2d1_sourcetime_raw_diagnostic.md` (commit `9db4583`, branch
  `claude/jolly-ishizaka-c6519a`): market `last_update` present 23/23, parseable 23, distinct 3; bookmaker level 0/3.
- Label for this run: **code-path verified; raw payload not witnessed in this run** (raw evidence: 9db4583).

## Coverage gap (not a failed publication)

The props step logged `Missing required markets`: NFL — Tackles + Assists, Solo Tackles, Sacks, Def INT;
NCAAF — Pass Completions, Rush Att. Publication succeeded; these markets were simply not offered by the
configured books. Recorded as a **coverage gap** (ledger 1.5y), not a validation or publish failure.

## Commands (all read-only)

SSM `63d9f79e-e957-48dd-868b-80b59863186f` (git/flag/bk-daily), a second read of the operator log + artifacts,
and `8b4e55ba-505d-4ab9-8100-590d75a5641b` (step list); outputs read via CloudShell
`aws ssm get-command-invocation`. No deploy, push to master, data regeneration, paid call, cache purge or flag
change.
