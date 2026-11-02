# RC scheduled-run receipt — 2026-11-02 (evidence record)

_Read 2026-11-02 ~22:01 UTC via SSM Run Command (read-only: cat/ls/stat/systemctl/journalctl/git rev-parse).
Source on prod: `/home/ubuntu/bk-backups/rc-scheduled-20261101T150655Z/receipt-20261102.txt` (7,964 B) +
`watch.log` (864 B). Both remain on the box, untouched. Nothing was written to production by this read._

## 1. RC verdict: **RESTORED**

`FINAL VERDICT: RESTORED -- artifacts returned to the verified backup; capture remains OFF` ·
`restore verified: artifacts == backup sha256` · `JOB EXIT 1 at 2026-11-02T13:24:56Z` · `VALIDATION: FAIL (5)`.

### The five failed assertions (exact text)

| # | Assertion | Observed |
|---|---|---|
| 1 | `VAL FAIL: at least one market-level SourceUpdatedAtUTC present` | `props_rows=2831 events=13 SourceUpdatedAtUTC nonblank=0 blank=2831` |
| 2 | `VAL FAIL: adapter dry-run RESOLVED_capturable >= 1` | `adapter_dry_run pairs=621 ROW_SOURCE_TIME_ABSENT=621` |
| 3 | `VAL FAIL: props published during this regeneration (fresh)` | `NFL_Props.csv` mtime `2026-11-01T13:00:28` (unchanged) |
| 4 | `VAL FAIL: props replaced atomically (new inode via os.replace)` | inode `1835034` before and after |
| 5 | `VAL FAIL: step 'Football player props' PASS (got FAIL)` | child outcome `football_props:nfl_player_props=VALIDATION_FAILED` (and `ncaaf_player_props=VALIDATION_FAILED`) |

**Single root:** the NFL props child returned `VALIDATION_FAILED`, so `NFL_Props.csv` was **not republished**
(`props_writes=0`). #1–#4 are consequences: the file checked is still the 2026-11-01 pre-change artifact, which
never carried `SourceUpdatedAtUTC`. The new source-time path was therefore **not exercised**, not disproven.
Why the props child failed validation is not in the journal summary (only the outcome line); it lives in the
sub-runner log — that is the next read-only diagnosis, not yet done.

### Why the props child failed (read-only, `logs/daily_operator_20261102_130000.log` lines 241–297, 446–451)

The fetch itself worked: 13 events in the 7-day window, 0 provider errors, **380 rows** fetched. The
publish guard then refused it:

```
Strong validation FAILED, preserving existing props CSV:
  - implausible row-count collapse: 380 rows < 50% of prior 2831 (pass an explicit override if intended)
[VALIDATION_FAILED] nfl_player_props seconds=2.5 exit=1 (ALERT): 380 rows fetched but the artifact did not advance
```

Per-event rows show why: on Monday morning only Monday night (CHI@SEA 221) and Thursday (JAX@BAL 123) are
fully posted; the seven Sunday games that had posted any props had 1–7 rows each and four had 0. The
"prior 2831" is Sunday's full slate. NCAAF hit the same guard (87 < 50% of 2,552).

**Reading:** the collapse guard behaved as designed (preserve last-known-good on a >50% drop), but the drop is
the normal post-Sunday slate turnover, not a bad fetch. A Monday 13:00 UTC run is therefore structurally
unable to publish NFL props, so this RC could not have exercised the source-time path on this day whatever the
code did. Side effect: the preserved `NFL_Props.csv` is Sunday's (now-played) slate. The RC code is neither
validated nor disproven. Choosing a re-run day or a governed rule for slate turnover is an owner decision.

## 2. Overall `bk-daily`: **FAILED (exit 1)** — reported separately

`Result=exit-code ExecMainStatus=1`, 13:00:00 → 13:24:16 UTC, `Overall: DEGRADED`. **8** failed steps (the
standing failure was 7): Football player props · CFB data refresh · MLB daily refresh · NBA daily refresh ·
WNBA game lines · WNBA player props · All scorecards · Odds feed health (post-refresh). Football player props is
the step that is new relative to the standing set, and it is the RC-relevant one.
Passed RC-relevant steps: NFL board grade (resolve), NFL weekly player stats, NFL featured results.

## 3. Artifact results

- **Roster sanitation: PASS.** `roster_rows=8355 null_governed_identity_rows=0`, season `{2026}`, weeks=8;
  written exactly once (13:04:31), atomic (new inode 1835056→1835055), mode/owner unchanged;
  `collision_audit name_to_multi_id=3 id_to_multi_name=0`.
- **Props source timestamps: FAIL (not exercised)** — see #1–#4. No substitution detected
  (`equals_event_time=0 equals_file_publish_minute=0`); board resolution 530/621 names, 89 unresolved, 2 ambiguous.
- **Writer attribution: PASS.** One roster writer, during `run_daily.py` (NGS fetch in flight);
  `fetch_nfl_player_week present=False`; no grader running at the write; `props_writes=0`.
- **Adapter dry-run: FAIL** — 0 capturable, 621/621 `ROW_SOURCE_TIME_ABSENT`; no artifact-level abstention.
- **Quota delta: OK.** NFL props credits by day: 10-28=74, 10-29=113, 10-30=105, 10-31=107, 11-01=141,
  **11-02=26** (within 1.5× prior max). Credits were spent today for a fetch whose output was not published.
- **Restoration: YES.** Restored to backup sha256. Consequence: today's fresh roster parquet (13:04, 486,210 B)
  and today's `_last_props_fetch_americanfootball_nfl.json` (13:00:32) were rolled back to the 2026-11-01
  versions (`at: 2026-11-01T13:00:27`). `Run_Status.json` carries today's 13:24:16 write.

## 4. Production state

- **HEAD:** `63060a944e0446ee3d3517ae32b5250b52200b09` (frozen value). Tree: only untracked `venv/`.
- **Capture flags:** OFF — `capture_flags env_file=0 unit=0 live_proc=0` before; `env_file=0` after; no
  `BK_RESEARCH_CANDIDATE_*` lines present in `.env`.
- **One-shot cleanup: CLEAN.** No `rc-sched*` units or timers loaded; `/run/rc-sched` absent.
- App `active`, probe 200 before and after.

## Held (unchanged)

No merge of `integration/integrity-group`, no Linux gate, no cache purge, no deploy. The ACCEPTED-branch gate
command is **not** prepared (verdict was RESTORED).
