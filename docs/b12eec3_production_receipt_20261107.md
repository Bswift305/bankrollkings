# `b12eec3` production acceptance receipt — PART 1 of 2 (deploy + first `bk-linemove`)

**Status: OPEN.** Part 2 (first post-deploy `bk-daily`, 2026-11-08 13:00 UTC) pending. Read-only evidence via AWS SSM.

## Deploy (owner-approved 2026-11-07, exact SHA)
- Preflight: prod HEAD = `origin/master` = `3d7cda1`; tracked tree clean; `bankrollkings` active, NRestarts 0, `/healthz`
  200; Research Candidate unset in the running process, 0 occurrences in `.env`; no `bk-*` unit active;
  `bankrollkings` / `bk-linemove` / `bk-daily` all `User=ubuntu`; `/opt/bankrollkings-runtime` `ubuntu:ubuntu`.
  No legacy `data/tracking/Last_LineMovement_Summary.json` existed on prod.
- Push: plain fast-forward `3d7cda1..b12eec3` (51 commits) at 14:51:31 UTC; `bk-auto-deploy.sh` logged
  `deploy: 3d7cda1 -> b12eec3`, prewarm ok. One transient `/healthz` 502 while the app was still starting.
- Post-deploy: HEAD = `origin/master` = `b12eec342a2637596ab4f01b6f3051f2fe21aed2`; tracked tree clean; service active
  since 14:51:36 UTC, NRestarts 0; `/healthz` 200; Research Candidate still OFF. No timer, env, cache, manual
  producer or paid-call change.
- Unit scope verified: `bk-linemove.timer` `OnCalendar=*-*-* 00,04,08,12,16,20:00:00 UTC`, no drop-ins;
  `bk-linemove.service` runs `refresh_line_movement_snapshots.py` (no args) as `ubuntu`, `SuccessExitStatus=1`
  (inert: the runner exits only 0 or 2). Deployed STEPS = MLB game lines (`--days 3`), WNBA game lines (`--days 5`).

## First ordinary `bk-linemove` under `b12eec3` — 2026-11-07 16:00 UTC — **overall FAILED (honest, per contract)**
| Check | Result |
|---|---|
| Unit | started 16:00:10, exited 16:00:12; `ExecMainStatus=2`; `Result=exit-code`; systemd "Failed" |
| Steps | MLB game lines **FAILED** (`exit 1, outcome=NO_ACTIVE_EVENTS`, `published=False`); WNBA game lines **FAILED** (same) — off-season zero-event answers now surface as failures (frozen semantics), files preserved |
| Provider cost | WNBA receipt `x-requests-last` 0, `COST RECEIPT: OK`, remaining 95,710 |
| Invocation marker | `invocation.json`: id `db6331ca8a304bf29af64a13ea3a72c4` (matches `^[0-9a-f]{32}$`), state `RUNNING`, pid 1690870, `started_at` 16:00:10Z (marker is the start record; it is not rewritten on success by design) |
| Final summary | `summary.json`: same id, `finished_at` 16:00:12Z, `exit_code` 2, both steps FAILED, `failed_steps` listed; journal: "Run summary published: summary.json (invocation db6331ca)" |
| Modes | `status/` 0755 (parent, pre-existing convention); `status/line_movement/` **0700**; both files **0600**, nlink 1, owner `ubuntu` |
| Run Status binding | `linemove_status.read_signals()` → DEGRADED reason "line-movement step(s) failed: MLB game lines=FAILED, WNBA game lines=FAILED", bound to invocation `db6331ca…`, exit 2, age 1.63 h |
| Legacy summary | `data/tracking/Last_LineMovement_Summary.json` still absent — neither read nor rewritten |
| App | HEAD `b12eec3`, tree clean, NRestarts 0, `/healthz` 200 |

**Post-release work list (authoritative, from this run):**
1. MLB game lines `NO_ACTIVE_EVENTS` every 4 h in the off-season → `bk-linemove` fails 6×/day until a governed
   off-season calendar or schedule contract exists (owner decision; do not weaken the contract).
2. WNBA game lines — same.

## Part 2 — pending
First post-deploy `bk-daily` (2026-11-08 13:00 UTC): overall result; NBA lines/props publication, freshness and
credit attribution; every newly surfaced failure (CFBD quota latch — `cfbd_quota_state.json` `"exhausted": true`
pre-deploy; missing keys; off-season zero-event answers). Pre-deploy baseline (2026-11-07 13:00 UTC run): DEGRADED —
CFB data refresh, MLB daily refresh, NBA daily refresh, WNBA game lines FAIL.
