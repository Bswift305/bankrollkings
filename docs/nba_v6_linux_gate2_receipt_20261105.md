# NBA v6 Linux gate #2 receipt — exact `28187ad` (2026-11-05) — **FAIL on one assertion (#14, latent fail-open); every other assertion PASS**

**Verdict.** Not deployable as-is under the owner's "never `OK`" rule. Fix with a one-line classifier change, then rerun
the full gate on the new SHA. Every other assertion passes, including **4×50 Linux loops with zero flakes**.

## Context
- **Authorization:** owner, 2026-11-04 — fresh gate for exact `28187ad`, with a 63-file scope.
- **Nothing changed in production:** no deploy, no timers, no paid calls, no capture changes, no merge.
- **Environment:** AWS CloudShell us-east-1, kernel 6.1, Python 3.13, fresh anonymous clones.
- **Gate script:** sha256 `61457bb9…cca6360f`, identical on both sides.

**Two runs:**
1. **Run 1** (`/tmp/nbagate2`, 02:05Z): identity, scope, compile, the 63 QCs, probes and audit.
   - Its 4×50 loops were killed when CloudShell timed out. They are not evidence either way.
2. **Run 2** (`/tmp/nbagate3`, 18:10Z): the same script with the QC list replaced by the 2 omitted QCs, plus the full
   4×50 loops.
   - It was derived on CloudShell by `sed` from the verified script. Only two lines differ: the work dir and the QC
     list.

## Results against the owner's assertions
| # | Assertion | Result |
|---|---|---|
| 1 | Exact base `17b5e69` | `IDENTITY_OK` (HEAD `28187ad0051f…`), `ORIGIN_MASTER_IS_BASE_OK`, `BASE_ANCESTOR_OK`, 40 commits |
| 2 | Exact 63-file scope | `SCOPE_63_OK` (+11,391 / −382) |
| 3 | Compile clean | `py_compile` on 86 changed `.py` files (vs D1 base): rc 0 |
| 4 | All 63 QCs exit 0 | **`QC_TOTAL=63 QC_FAIL=0`**, 0 network-blocked outside the self-tests |
| 4b | QCs changed in scope but missing from the 63-list | `qc_recover_odds_wrapper` rc 0; `qc_sport_registry` rc 0 (run 2) |
| 5 | `qc_odds_feed` refused | via `qc_offline.py`: **rc 3** (NOT RUN, `REQUIRES_NETWORK`) |
| 6 | Clean tree before/after | 0 / 0 / 0 entries; HEAD unchanged |
| 7 | No network routes | `unshare --net`: only `lo` is present (UNKNOWN), 0 routes, gaierror, curl rc 6 |
| 8 | No QC resolves, creates or writes beneath `/opt/bankrollkings-runtime` | See **Runtime containment** below — PASS |
| 9 | Every publisher-reaching QC uses a unique private runtime | 20 `qc_runtime_*` dirs in run 1: **20 unique, all mode 0o700**, 0 left over. All 17 reach-set QCs in the 63-list plus `line_movement_receipt_identity` were ISOLATED; `recover_odds_wrapper` and `sport_registry` were ISOLATED in run 2 |
| 10 | POSIX modes execute, not skip | lines lock **59/0/0**, props lock **41/0/0**, receipt contract **37/0/0** — all "0 skipped (platform: linux)" |
| 11 | Line-movement receipts accepted only by matching token | `qc_line_movement_receipt_identity` 17/0. Probe: other token → `RUN_RECEIPT_MISMATCH`; identical-mtime A→B sequence classified by token only |
| 12 | Missing / mismatched / tokenless receipt fails | Probe: missing, torn and non-object → `RUN_RECEIPT_MISSING`; other token, tokenless and runner-without-token → `RUN_RECEIPT_MISMATCH` |
| 13 | No mtime-based classification remains | `refresh_line_movement_snapshots.py`: **`NO_MTIME_REFS`** (no `st_mtime` / `getmtime` / `_mtime(` / `mtime_before`) |
| 14 | Production line-movement failures can never report `OK` | **FAIL (latent)** — see **Finding** below. 18/19 probe cases pass |
| 15 | Four 50-run suites, zero flakes | Run 2, 18:10:07→18:41:39Z, in parallel: **orchestrator 50/0, lines lock 50/0, props lock 50/0, credit attribution 50/0**, `LOOPFAIL_FILES=0`. During the loops: 200 `qc_runtime_*` dirs, 200 unique, all 0o700, 0 left over. 50 audit events, all `os.putenv` from `qc_nba_lines_lock`'s guard-refusal test (one per run); canary untouched. Log sha256 run 2 `c009f0bda79af19a…`, run 1 `03d106c8a0ff4476…` |
| 16 | D1, D4, ticket-integrity and source-time production markers unchanged | 8 D1 files identical to base; `run_all_scorecards.py` removed_lines=0; all `app.py` markers SAME except `SourceUpdatedAtUTC` **18 → 19** — see **Marker note** |

**Other QC counts (Linux):**

| QC | Result |
|---|---|
| orchestrator | 52/0/0 |
| credit attribution | 57 |
| no-game governance | 41/0 |
| game-lines event slate | 59/0 |
| `nba_wnba_props_stale` | 157/0 |
| `elite_live_labels` | 108/0 |
| `elite_alert_history` | 25/0 |
| `odds_age_timezone` | 19/0 |
| D14 retired scan | 22/0 |
| `runtime_isolation` | 14/0 |
| `ncaaf_odds_single_writer` | second-writer mutations caught |

## Runtime containment (assertion 8)
**Canary.** Before the QCs ran, the gate created `/opt/bankrollkings-runtime` itself: empty, 0700, owned by the gate
user, so any write would have **succeeded and been visible**.
- After run 1's QCs, its mtime, ctime, mode, owner and entry count (0) were identical; the comparison line matched.
- It was removed afterwards; the 18:10Z environment shows no `/opt/bankrollkings-runtime`.

**Audit hook.** A gate-only `sys.addaudithook`, installed into the venv via `.pth` and never in the repo, logged every
`open` / `os.*` / `shutil.*` / `pathlib.*` event whose path is under that root.
- **Positive control:** the hook fired on a deliberate `os.listdir` of the canary and on a `mkdtemp`.
- **What it recorded:** only 2 events across all 63 QCs, both `os.putenv` from `qc_nba_lines_lock` (one in its `-c`
  child). These are the guard-refusal tests: they set `BK_RUNTIME_DIR` to the production path and assert
  `runtime_root()` **refuses** it.
- **Zero filesystem events** (no open / list / mkdir / write) touched the path.
- The pure-rule check uses the guard-free `_resolve_runtime_root("")`, which does no I/O.

## Finding — assertion 14 (latent fail-open)
`refresh_line_movement_snapshots.classify_step` treats any **token-matched receipt on exit 0 whose `outcome` is absent
or `None`** as `OK`:

```python
if returncode == 0:
    if receipt.get("outcome") not in (None, "UPDATED"):
        return "FAILED", ...
    return "OK", "published"
```

- **Not reachable today:** the only writer, `fetch_game_lines._write_lines_receipt`, is called from one `finish()`, and
  every call passes an explicit outcome string.
- **Still a violation:** a malformed or partial receipt carrying this run's token would report `OK`, contrary to "never
  OK without proof".
- **Fix (one line):** accept `OK` only when `outcome == "UPDATED"` and `exit_code == 0`; otherwise `FAILED`. Add a QC
  case for the missing-outcome receipt.
- **Consequence:** this changes the SHA, so the gate reruns in full.

## Marker note (assertion 16)
- `SourceUpdatedAtUTC` in `app.py`: base 18, head 19.
- All 18 base lines are present byte-for-byte; 0 removed lines mention it.
- The one addition is a new **reader**: `'quote_updated_utc': _elite_live_text(row.get('SourceUpdatedAtUTC'))` in the
  Elite live-label payload. It follows the frozen source-time direction.
- **Correction:** this addition was already in `479e8c4`. The gate #1 receipt's "all SAME" was wrong for this one
  marker.

## Safeguard A overlap (recorded as instructed; not merged)
- `fix/fetch-output-path-guard` (Safeguard A) also edits `refresh_line_movement_snapshots.py` (exit semantics: 0 / 1
  benign-only / ≥2 hard failure). This branch edits the same file's receipt classification (token instead of mtime).
- On this branch the runner still returns **1** for any failure. Production `bk-linemove` has `SuccessExitStatus=1`, so
  systemd records such a failure as **success** until Safeguard A's exit semantics land.
- **Additional overlap** reported by the Safeguard A builder (`31d09dd`): `services/run_outcomes.py` conflicts. This
  branch still treats `NO_ACTIVE_EVENTS` as benign for game lines (`BENIGN_LINES_NONPUBLISH`), contrary to the owner's
  governed-only rule.
  - The NBA schedule authority must be registered in `GOVERNED_SCHEDULE_CONTRACTS` before any `NO_GAMES_SCHEDULED` can
    count.
- **Before integration:** a reviewed conflict resolution of that file, then the full offline gate again. Whichever of
  NBA v6 or L1 deploys second is rebuilt and re-gated on the new master.

## Retired-phrase positions
Unchanged from gate #1. The two rendered disclaimers are reworded on `fix/market-movement-neutral-language` (`b2ec094`),
per the owner ruling; that branch conflicts with this one in `app.py` and `elite_dashboard.html` (take the D14 side).
